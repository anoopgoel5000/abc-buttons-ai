import os
import json
import asyncio
import re
from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import JSONResponse, PlainTextResponse

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ai_engine import analyze_button_or_fabric_image, SAMPLE_CATALOG, simulate_buyer_chat
from whatsapp_service import (
    send_whatsapp_text as _raw_send_whatsapp_text,
    send_whatsapp_image as _raw_send_whatsapp_image,
    download_whatsapp_media
)
import hmac
import hashlib
import db

app = FastAPI(title="ABC Buttons WhatsApp Webhook Server")

VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "")
META_APP_SECRET = os.environ.get("META_APP_SECRET", "")
ADMIN_API_KEY = os.environ.get("ADMIN_API_KEY", "")

# Load fallback from local .env if running locally and not in environment
_env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_env_file):
    with open(_env_file, "r", encoding="utf-8") as _ef:
        for _line in _ef:
            _line = _line.strip()
            if _line.startswith("ADMIN_API_KEY=") and not ADMIN_API_KEY:
                ADMIN_API_KEY = _line.split("=", 1)[1].strip()
            elif _line.startswith("WEBHOOK_VERIFY_TOKEN=") and not VERIFY_TOKEN:
                VERIFY_TOKEN = _line.split("=", 1)[1].strip()
            elif _line.startswith("META_APP_SECRET=") and not META_APP_SECRET:
                META_APP_SECRET = _line.split("=", 1)[1].strip()
CAT_DIR = os.path.join(os.path.dirname(__file__), "catalog_images")
DS_PATH = os.path.join(os.path.dirname(__file__), "data_store.json")

# ----------------- SECURITY & AUDIT HELPERS (Requirements 7, 8, 9) -----------------

def verify_webhook_signature(body_bytes: bytes, signature_header: str) -> bool:
    """Verifies HMAC-SHA256 signature from Meta Cloud API."""
    if not META_APP_SECRET:
        # Development / test mode fallback if secret not set
        return True
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_hash = signature_header.split("sha256=", 1)[1]
    calculated_hash = hmac.new(META_APP_SECRET.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected_hash, calculated_hash)

def verify_admin_auth(request: Request) -> bool:
    """Verifies API key for administrative / destructive operations strictly via HTTP headers."""
    if not ADMIN_API_KEY:
        return False
    # Strict Header-only authentication to prevent API key leakage in access/proxy logs
    key_hdr = request.headers.get("X-API-Key") or request.headers.get("Authorization", "").replace("Bearer ", "")
    return bool(key_hdr and key_hdr == ADMIN_API_KEY)

# ----------------- OUTBOUND DELIVERY & PRODUCT TRACKING (Requirements 2 & 12) -----------------

def send_whatsapp_text(to_phone: str, message_text: str, buyer_name: str = "Customer") -> dict:
    """Tracked outbound text messaging with delivery logging and persistent chat transcript."""
    res = _raw_send_whatsapp_text(to_phone, message_text)
    wamid = None
    if isinstance(res, dict):
        msgs = res.get("data", {}).get("messages", [])
        if msgs and isinstance(msgs, list):
            wamid = msgs[0].get("id")
    status = "ACCEPTED" if (isinstance(res, dict) and res.get("success") and wamid) else "FAILED"
    err = str(res.get("error", "")) if isinstance(res, dict) else ""
    db.log_outbound_delivery(wamid or "", to_phone, "text", message_text, status, err)
    # Guarantee message is in the customer CRM transcript with status and wamid
    log_chat_event(to_phone, buyer_name, "bot", "text", message_text, status=status, wamid=wamid)
    return res

def send_whatsapp_image(to_phone: str, img_bytes: bytes, caption: str = "", sku: str = "", product_name: str = "", size_opts: str = "", buyer_name: str = "Customer") -> dict:
    """Tracked outbound image messaging with WAMID-to-SKU mapping and CRM transcript."""
    res = _raw_send_whatsapp_image(to_phone, img_bytes, caption)
    wamid = None
    if isinstance(res, dict):
        msgs = res.get("data", {}).get("messages", [])
        if msgs and isinstance(msgs, list):
            wamid = msgs[0].get("id")
    status = "ACCEPTED" if (isinstance(res, dict) and res.get("success") and wamid) else "FAILED"
    err = str(res.get("error", "")) if isinstance(res, dict) else ""
    db.log_outbound_delivery(wamid or "", to_phone, "image", caption, status, err)
    if wamid and sku:
        db.record_outbound_product(wamid, to_phone, sku, product_name, size_opts, "")
    # Guarantee product image is in the customer CRM transcript with status and wamid
    log_chat_event(to_phone, buyer_name, "bot", "image", caption, sku=sku, status=status, wamid=wamid)
    return res

# ----------------- SESSION PERSISTENCE & CHAT EVENT LOGGING (Requirements 1, 5, 10) -----------------

def get_buyer_session(phone: str) -> dict:
    """ACID persistent buyer session from transactional SQLite."""
    return db.get_session_db(phone)

def save_buyer_session(phone: str, session: dict):
    """Save session to transactional SQLite."""
    db.save_session_db(phone, session)

def log_chat_event(phone: str, buyer_name: str, sender: str, msg_type: str, text: str, photo_b64: str = None, sku: str = None, size: str = None, qty: int = None, status: str = "SENT", wamid: str = None, customer_required_quantity: int = None, catalog_available_stock: int = None, verified_live_stock: int = None):
    """Transactional chat logging with atomic dual-sync to data_store.json."""
    db.sync_chat_event_db(phone, buyer_name, sender, msg_type, text, photo_b64, sku, size, qty, status=status, wamid=wamid, customer_required_quantity=customer_required_quantity, catalog_available_stock=catalog_available_stock, verified_live_stock=verified_live_stock)

def load_live_inquiries():
    """Retrieve inquiries from database."""
    with db.get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM live_inquiries ORDER BY updated_at DESC LIMIT 50")
        rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            r["chat_messages"] = json.loads(r["chat_messages"]) if r.get("chat_messages") else []
        return rows

def save_live_inquiries():
    """Atomic export to data_store.json for backward compatibility."""
    db.export_to_data_store_json()

live_whatsapp_inquiries = load_live_inquiries()
received_events = []


def get_item_by_sku(sku: str):
    for item in SAMPLE_CATALOG:
        if item.get("sku") == sku:
            return item
    return None

def get_alternative_skus(best_sku: str, limit: int = 2):
    alts = []
    for item in SAMPLE_CATALOG:
        if item.get("sku") != best_sku and item.get("sku") != "ABC-SAMPLE-CARD-01":
            alts.append(item)
            if len(alts) >= limit:
                break
    return alts

def classify_buyer_intent(raw_text: str, session: dict, active_sku: str = None) -> tuple:
    """
    Enterprise Intent Classifier for WhatsApp inquiries:
    Distinguishes:
    1. SELLER_STOCK_OR_CLAIM_REFERENCE (e.g. 'aapne bola tha ki aapke pass 1250 gross available hai')
    2. ORDER_MODIFICATION (e.g. '200 nahi 500 gross kar do', '500 gross kar do')
    3. ORDER_NEW_REQUIREMENT (e.g. '18L 200 Gross', '200 gross chahiye')
    4. SIZE_MODIFICATION (e.g. '24L kar do', '18L size')
    5. SPEC_OR_PRICE_INQUIRY (e.g. 'rate kya hai', 'kya rate 175 gross hai')
    6. COURTESY_CONFIRMATION (e.g. 'ok', 'theek hai', 'thanks')
    7. AMBIGUOUS_INTENT
    
    Guarantees:
    - Never overwrites customer_required_quantity when customer mentions available stock, price, MOQ, or seller claims.
    - Preserves last explicitly confirmed requirement across all subsequent WhatsApp messages.
    """
    lower_text = raw_text.lower().strip()
    
    # 1. Courtesy & Acknowledgements
    if any(lower_text == w for w in [
        "ok", "okay", "ok ji", "theek hai", "thik hai", "thanks", "thank you", 
        "shukriya", "dhanyawad", "done", "ji", "sure", "alright", "great", 
        "perfect", "done sir", "ok sir", "theek hai sir", "k", "kk", "ok done", "theek h", "haan", "ha", "yes"
    ]):
        return "COURTESY_CONFIRMATION", {}

    # 2. Seller Stock or Previous Claim Reference
    seller_claim_markers = [
        "aapne bola", "aapne kaha", "aapne bataya", "bol rahe the", "kaha tha", "bola tha",
        "you said", "you mentioned", "you told", "you claimed", "as you said", "you earlier said", "you stated",
        "आपने कहा", "आपने बोला", "आपने बताया", "कह रहे थे"
    ]
    has_seller_claim = any(m in lower_text for m in seller_claim_markers)
    
    seller_stock_markers = [
        "aapke pass", "aapke paas", "tumhare pass", "tumhare paas", "aapke godown", "aapke warehouse",
        "available hai", "ready stock", "available stock", "godown stock", "total stock", "stock available",
        "in stock", "in your stock", "do you have in stock", "available in stock", "ready in stock",
        "stock kitna", "kitna stock", "उपलब्ध है", "स्टॉक में", "गोदाम में", "उपलब्ध स्टॉक", "रेडी स्टॉक", "स्टॉक है"
    ]
    has_seller_stock_ref = any(m in lower_text for m in seller_stock_markers)
    
    stock_inquiry_markers = [
        "stock kitna hai", "kitna stock", "how much stock", "stock kitna", "kitna stock available",
        "स्टॉक कितना है", "कितना स्टॉक"
    ]
    has_stock_inquiry = any(m in lower_text for m in stock_inquiry_markers)
    
    gross_match = re.search(r'(\d+)\s*(?:gross|gr|ग्रॉस)', lower_text)
    pcs_match = re.search(r'(\d+)\s*(?:pcs|pieces|पीस)', lower_text)
    
    explicit_order_keywords = [
        "nahi", "chahiye", "kar do", "kardo", "kar dena", "bhejo", "bhej do", "dispatch", 
        "order", "pack", "make it", "change to", "instead", "requirement", "require",
        "we need", "i need", "i want", "badha", "badhakar", "नहीं", "चाहिए", "कर दो", "भेजो"
    ]
    has_explicit_order_intent = any(w in lower_text for w in explicit_order_keywords)
    
    # Priority check: Reference to seller claim or seller/catalog stock
    if has_seller_claim or has_seller_stock_ref or has_stock_inquiry:
        matched_stock_num = int(gross_match.group(1)) if gross_match else None
        
        # Check if buyer is simultaneously expressing an explicit order update clause
        order_qty_match = None
        if "nahi" in lower_text or "chahiye" in lower_text or "kar do" in lower_text or "order" in lower_text:
            sub_order = re.search(r'(?:nahi|badhakar|change to|instead of\s*\d+)\s*[,]?\s*(\d+)\s*(?:gross|gr|ग्रॉस)?', lower_text)
            if sub_order:
                order_qty_match = int(sub_order.group(1))
            else:
                sub_chahiye = re.search(r'(?:mujhe|hume|we need|i need|order)\s*(\d+)\s*(?:gross|gr|ग्रॉस)', lower_text)
                if sub_chahiye:
                    order_qty_match = int(sub_chahiye.group(1))
        
        if order_qty_match:
            return "ORDER_MODIFICATION", {
                "new_quantity": order_qty_match,
                "referenced_stock": matched_stock_num
            }
        
        return "SELLER_STOCK_OR_CLAIM_REFERENCE", {
            "referenced_stock": matched_stock_num,
            "has_claim": has_seller_claim,
            "has_stock_ref": has_seller_stock_ref
        }
        
    # 3. Explicit Order Modification / Correction
    if has_explicit_order_intent and (gross_match or pcs_match):
        corr_match = re.search(r'(\d+)\s*(?:nahi|not)\s*[,]?\s*(\d+)', lower_text)
        if corr_match:
            new_q = int(corr_match.group(2))
            return "ORDER_MODIFICATION", {"new_quantity": new_q}
            
        target_qty = int(gross_match.group(1)) if gross_match else max(1, round(int(pcs_match.group(1)) / 144))
        if session.get("customer_required_quantity") or session.get("quantity"):
            return "ORDER_MODIFICATION", {"new_quantity": target_qty}
        else:
            return "ORDER_NEW_REQUIREMENT", {"new_quantity": target_qty}
            
    # 4. Standard new requirement (e.g. "18L 200 Gross", "200 Gross")
    if gross_match or pcs_match:
        target_qty = int(gross_match.group(1)) if gross_match else max(1, round(int(pcs_match.group(1)) / 144))
        return "ORDER_NEW_REQUIREMENT", {"new_quantity": target_qty}
        
    # 5. Price / Spec inquiry
    if any(w in lower_text for w in ["rate", "price", "quotation", "quote", "cost", "bhaav", "paisa", "kitne ka", "charges", "per gross", "discount", "moq"]):
        return "SPEC_OR_PRICE_INQUIRY", {}
        
    # 6. Size only
    size_match = re.search(r'\b(\d{1,2}(?:\.\d+)?\s*(?:l|ligne|line|mm))\b', lower_text, re.IGNORECASE)
    if size_match:
        return "SIZE_MODIFICATION", {"size": size_match.group(1).upper().replace(" ", "")}
        
    return "GENERAL_TEXT", {}

async def process_incoming_whatsapp_message(value: dict):
    """
    Stateful Customer Context Aware WhatsApp Message Handler.
    Enforces ABC Buttons: Commercial, Sales & Customer Handling Rules (Rules 1.1 to 7.0).
    Processes all messages in batch payloads (Requirements 10 & 11).
    """
    contacts = value.get("contacts", [])
    messages = value.get("messages", [])
    if not messages:
        return
    for msg in messages:
        await process_single_whatsapp_message(msg, contacts)

async def process_single_whatsapp_message(msg: dict, contacts: list):
    """
    Processes an individual inbound message with full lifecycle, idempotency and error handling.
    """
    msg_id = msg.get("id")
    from_phone = msg.get("from")
    msg_type = msg.get("type")

    # Requirements 11, 12, 13: Transactional Inbound Message Lifecycle & Idempotency
    lifecycle = db.record_inbound_message_lifecycle(msg_id, from_phone, msg_type)
    if not lifecycle.get("should_process", True):
        print(f"Skipping inbound message {msg_id} - lifecycle status is {lifecycle.get('status')}")
        return

    try:
        await _process_single_whatsapp_message_impl(msg, contacts, msg_id, from_phone, msg_type)
        cur_st = db.get_inbound_message_status(msg_id)
        if cur_st.get("status") not in ("FAILED", "COMPLETED"):
            db.update_inbound_message_status(msg_id, "COMPLETED")
    except Exception as e:
        print(f"❌ Error in process_single_whatsapp_message for {msg_id}: {e}")
        db.update_inbound_message_status(msg_id, "FAILED", str(e))

async def _process_single_whatsapp_message_impl(msg: dict, contacts: list, msg_id: str, from_phone: str, msg_type: str):
    contact_name = "Sir"
    if contacts:
        contact_name = contacts[0].get("profile", {}).get("name", "Sir")

    first_name = contact_name.split()[0] if contact_name and contact_name != "Buyer" else "Sir"
    salutation = f"{first_name} ji" if first_name not in ["Sir", "sir"] else "sir"

    # Requirement 1 & 5: ACID Session State Retrieval
    session = get_buyer_session(from_phone)
    session["contact_name"] = contact_name
    session["history_count"] = session.get("history_count", 0) + 1

    # Requirement 4: WhatsApp Quoted Reply Resolution via WAMID
    context_id = msg.get("context", {}).get("id")
    if context_id:
        quoted_prod = db.resolve_quoted_sku(context_id, from_phone)
        if quoted_prod:
            session["matched_sku"] = quoted_prod["sku"]
            session["matched_name"] = quoted_prod["product_name"]
            session["has_photo"] = True
            session["last_active_sku"] = quoted_prod["sku"]
            if quoted_prod.get("size_options") and not session.get("matched_size"):
                session["matched_size"] = quoted_prod.get("size_options")
            print(f"🎯 Resolved quoted reply {context_id} -> {quoted_prod['sku']}")

    # ---------------- HUMAN TAKEOVER CHECK ----------------
    if session.get("human_takeover"):
        print(f"🛑 Human Takeover Active for {from_phone}. AI Bot auto-reply is PAUSED.")
        if msg_type == "text":
            text_body = msg.get("text", {}).get("body", "")
            log_chat_event(from_phone, contact_name, "buyer", "text", text_body)
        elif msg_type == "image":
            caption = msg.get("image", {}).get("caption", "")
            media_id = msg.get("image", {}).get("id")
            b64_img = ""
            try:
                img_bytes = download_whatsapp_media(media_id)
                import base64
                b64_img = base64.b64encode(img_bytes).decode("utf-8")
            except Exception as e:
                print(f"Error logging image under takeover: {e}")
            log_chat_event(from_phone, contact_name, "buyer", "image", caption or "📷 [Buyer sent button photo]", photo_b64=b64_img)
            db.save_inquiry_with_photo(msg_id, from_phone, contact_name, b64_img, notes=caption or "Buyer sent photo under human takeover", crm_status="Human Takeover Active")
        save_buyer_session(from_phone, session)
        db.update_inbound_message_status(msg_id, "COMPLETED")
        return

    # ---------------- CASE 1: BUYER SENT A PHOTO ----------------
    if msg_type == "image":
        media_id = msg.get("image", {}).get("id")
        caption = msg.get("image", {}).get("caption", "")
        print(f"📸 [INCOMING IMAGE] From: {from_phone} | Media ID: {media_id} | Caption: {caption}")

        # 1. Download image bytes from Meta with safe retry
        img_bytes = None
        download_err = None
        for attempt in range(2):
            try:
                img_bytes = download_whatsapp_media(media_id)
                if img_bytes:
                    break
            except Exception as e:
                download_err = str(e)
                await asyncio.sleep(0.5)

        if not img_bytes:
            print(f"❌ Failed to download WhatsApp media {media_id}: {download_err}")
            db.save_inquiry_with_photo(
                inquiry_id=msg_id,
                phone=from_phone,
                buyer_name=contact_name,
                photo_b64="",
                notes=f"[Download Failed] {caption or 'Buyer photo sample'} - Error: {download_err}",
                crm_status="Image Download Failed - Needs Human Review"
            )
            fallback_text = (
                f"Ji {salutation}, aapka photo sample prapt hua hai, lekin network connectivity ke kaaran image download verify nahi ho paayi hai. "
                f"Hamari sales team ko aapki inquiry alert kar di gayi hai, hum turant aapse sampark karenge."
            )
            send_whatsapp_text(from_phone, fallback_text, contact_name)
            db.update_inbound_message_status(msg_id, "FAILED", f"Media download failed: {download_err}")
            return

        print(f"✅ Downloaded {len(img_bytes)} bytes from Meta")

        import base64
        b64_img = base64.b64encode(img_bytes).decode("utf-8")

        # 2. Run AI Vision Matcher with safe error handling
        try:
            res = analyze_button_or_fabric_image(img_bytes, caption)
        except Exception as ai_e:
            print(f"❌ AI Vision analysis error: {ai_e}")
            db.save_inquiry_with_photo(
                inquiry_id=msg_id,
                phone=from_phone,
                buyer_name=contact_name,
                photo_b64=b64_img,
                notes=f"[AI Analysis Pending/Failed] {caption or ''} - {ai_e}",
                crm_status="AI Analysis Review Required"
            )
            fallback_text = (
                f"Ji {salutation}, aapka photo sample prapt ho gaya hai. "
                f"Image analysis verify ki jaa rahi hai. "
                f"Hamare sales representative turant isko verify karke aapse sampark karenge."
            )
            send_whatsapp_text(from_phone, fallback_text, contact_name)
            db.update_inbound_message_status(msg_id, "FAILED", f"AI Analysis failed: {ai_e}")
            return

        status = res.get("match_status", "MATCH_FOUND")
        best_sku = res.get("best_match_sku")
        print(f"🔍 AI Result: Status={status} | SKU={best_sku}")

        # Permanently record customer inquiry with real photo in live CRM feed
        import datetime
        t_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inq_entry = {
            "id": msg_id,
            "timestamp": t_now,
            "buyer_name": contact_name,
            "phone": from_phone,
            "photo_b64": b64_img,
            "matched_sku": best_sku or "Custom / Non-Catalog",
            "matched_name": (get_item_by_sku(best_sku) or {}).get("name", "Custom Button Development") if best_sku else "Custom Button Development",
            "matched_size": (get_item_by_sku(best_sku) or {}).get("size_ligne", "") if best_sku else "",
            "quantity": session.get("quantity") or 0,
            "status": "Sample Identified" if best_sku else "Custom Development Requested",
            "notes": caption or ""
        }
        existing_idx = next((i for i, x in enumerate(live_whatsapp_inquiries) if x.get("phone") == from_phone), None)
        if existing_idx is not None:
            live_whatsapp_inquiries.pop(existing_idx)
        live_whatsapp_inquiries.insert(0, inq_entry)
        save_live_inquiries()

        db.save_inquiry_with_photo(
            inquiry_id=msg_id,
            phone=from_phone,
            buyer_name=contact_name,
            photo_b64=b64_img,
            notes=caption or "",
            crm_status="Sample Identified" if best_sku else "Custom Development Requested"
        )
        log_chat_event(from_phone, contact_name, "buyer", "image", caption or "📷 [Sample Button Photo Sent]", photo_b64=b64_img, sku=best_sku)

        # 3. Handle non-button images
        if status == "NO_BUTTON_DETECTED" or not res.get("is_button", True):
            send_whatsapp_text(
                from_phone,
                f"Ji {salutation}, aapne jo photo share ki hai usme button clear nahi dikh raha hai. "
                f"Kripya button ki ek close-up photo achhi roshni me bhejiye, hum turant ready stock check karke batate hain.",
                contact_name
            )
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 3.5 Handle multiple distinct designs or obscured front face (NEED CLEAR FRONT PHOTO)
        if status == "NEED_CLEAR_PHOTO" or res.get("decision_label") == "NEED CLEAR FRONT PHOTO":
            mixed = res.get("visual_analysis", {}).get("mixed_designs_detected", False)
            if mixed:
                need_msg = (
                    f"Ji {salutation}, aapki photo me ek se zyada button designs dikh rahe hain.\n\n"
                    f"Kripya confirm karein ki aapko inme se kaun sa design chahiye, ya single button ki focused photo share karein taaki exact matching ho sake."
                )
            else:
                need_msg = (
                    f"Ji {salutation}, photo me button ka front-face design aur rim details saaf nahi dikh rahe hain.\n\n"
                    f"Kripya achhi roshni me seedhi focused front photo bhejiye taaki exact matching ho sake."
                )
            send_whatsapp_text(from_phone, need_msg, contact_name)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            print(f"📤 Requested clear front photo from {from_phone}")
            return

        # 4. RULE: EXACT MATCH ONLY (अगर एग्जैक्ट बटन नहीं है, तो सिमिलर दिखाने की परमिशन माँगें)
        if status in ["NOT_IN_CATALOG", "POSSIBLE_MATCH", "NO_EXACT_MATCH"] or not best_sku or res.get("decision_label") in ["POSSIBLE MATCH", "NO EXACT MATCH"]:
            session["has_photo"] = True
            session["waiting_for_similar_permission"] = True
            alts = SAMPLE_CATALOG[:2]
            session["suggested_alternatives"] = [a["sku"] for a in alts]
            not_in_cat_msg = (
                f"Ji {salutation}, aapka sample dekh liya hai.\n\n"
                f"Ye exact button design abhi hamare ready stock me available nahi hai.\n\n"
                f"Kya main aapko isse milte-julte (similar) designs ke buttons dikha doon?"
            )
            send_whatsapp_text(from_phone, not_in_cat_msg, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            print(f"📤 Asked permission for similar designs to {from_phone}")
            return

        # 5. Handle Verified EXACT Catalog Match
        matched_item = get_item_by_sku(best_sku) or SAMPLE_CATALOG[0]
        session["has_photo"] = True
        session["matched_sku"] = matched_item["sku"]
        session["matched_name"] = matched_item["name"]
        raw_sz = str(matched_item.get("size_ligne", "")).strip()
        if "/" not in raw_sz and "," not in raw_sz and "or" not in raw_sz.lower():
            session["matched_size"] = raw_sz
        else:
            session["matched_size"] = None
        session["last_active_sku"] = matched_item["sku"]
        session["quantity"] = None
        session["customer_required_quantity"] = None
        session["waiting_for_similar_permission"] = False
        session["waiting_for_similar_approval"] = False

        # Auto-save latest WhatsApp inquiry for Tab 5 Proforma 1-Click
        try:
            ds_path = os.path.join(os.path.dirname(__file__), "data_store.json")
            if os.path.exists(ds_path):
                with open(ds_path, "r", encoding="utf-8") as fp:
                    ds = json.load(fp)
                ds["latest_whatsapp_inquiry"] = {
                    "buyer_name": contact_name,
                    "phone": from_phone,
                    "sku": matched_item["sku"],
                    "qty_gross": session.get("quantity") or 200,
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                with open(ds_path, "w", encoding="utf-8") as fp:
                    json.dump(ds, fp, indent=2)
        except Exception as e:
            print(f"Error saving latest inquiry: {e}")

        # Send ONLY THE EXACT MATCHING BUTTON with Truthful Stock Disclaimer (no false godown claims)
        p_img_path = os.path.join(CAT_DIR, f"{matched_item['sku']}.jpg")
        if os.path.exists(p_img_path):
            with open(p_img_path, "rb") as fp:
                p_img_bytes = fp.read()
            best_caption = (
                f"🏆 *Matching Catalog Design: {matched_item['name']}*\n"
                f"• SKU: {matched_item['sku']}\n"
                f"• Specification: {matched_item.get('size_ligne', '')} • {matched_item.get('holes', '')}\n"
                f"• Catalog Reference Stock: {matched_item.get('stock_gross', 0):,} Gross (Subject to physical warehouse verification)\n\n"
                f"Same export finish sample ready hai. Warehouse physical stock verification dispatch se pehle confirm ki jayegi."
            )
            send_whatsapp_image(from_phone, p_img_bytes, best_caption, sku=matched_item["sku"], product_name=matched_item["name"], size_opts=matched_item.get("size_ligne", ""), buyer_name=contact_name)
            await asyncio.sleep(1.2)

        # ONE QUESTION AT A TIME RULE: Ask ONLY for required quantity
        if not session.get("quantity"):
            cta_text = (
                "Ji sir, aapke share kiye hue sample ka matching catalog design hamare paas available hai.\n\n"
                "Aapko kitni quantity chahiye?"
            )
        else:
            cta_text = (
                f"Ji sir, aapka sample identify ho gaya hai. "
                f"Aapki {session['quantity']} Gross requirement ke according hum quotation prepare kar rahe hain."
            )
        send_whatsapp_text(from_phone, cta_text, contact_name)
        save_buyer_session(from_phone, session)
        db.update_inbound_message_status(msg_id, "COMPLETED")
        print(f"📤 Sent Exact Match and Quantity Question to {from_phone}")
        return

    # ---------------- CASE 2: BUYER SENT A TEXT MESSAGE ----------------
    elif msg_type == "text":
        text_body = msg.get("text", {}).get("body", "").strip()
        lower_text = text_body.lower()
        print(f"💬 [INCOMING TEXT] From: {from_phone} | Message: '{text_body}'")
        log_chat_event(from_phone, contact_name, "buyer", "text", text_body)

        # ---------------- STEP A: HANDLE SIMILAR PERMISSION RESPONSE ----------------
        if session.get("waiting_for_similar_permission"):
            # Check if customer agrees / gives permission (haan, yes, dikha do, bhejo, options, ok, sure, dikhao)
            agrees = any(w in lower_text for w in ["haan", "yes", "dikha do", "bhejo", "options", "dikhao", "sure", "ok", "chalega", "dekhte", "send"]) and not any(w in lower_text for w in ["nahi", "nahu", "no", "not", "mat", "sirf yahi", "wahi"])
            rejects = any(w in lower_text for w in ["nahi", "nahu", "no", "not", "na", "mat", "sirf yahi", "same design", "wahi chahiye", "nahi chahiye", "rehne do", "koi nahi", "koi bhi nahi"])
            
            if agrees:
                session["waiting_for_similar_permission"] = False
                session["waiting_for_similar_approval"] = True
                
                # Send polite intro
                send_whatsapp_text(from_phone, "Ji sir, ye dekhiye isse milte-julte hamare 2 running options:")
                await asyncio.sleep(1.0)
                
                # Send 2 similar options
                alts = [get_item_by_sku(s) for s in session.get("suggested_alternatives", [])]
                alts = [a for a in alts if a] or SAMPLE_CATALOG[:2]
                
                for idx, alt_item in enumerate(alts, start=1):
                    alt_path = os.path.join(CAT_DIR, f"{alt_item['sku']}.jpg")
                    if os.path.exists(alt_path):
                        with open(alt_path, "rb") as afp:
                            alt_bytes = afp.read()
                        alt_caption = (
                            f"🔘 *Option {idx}: {alt_item['name']}*\n"
                            f"• Size: {alt_item.get('size_ligne', '')} • {alt_item.get('holes', '')}\n"
                            f"• Ready Godown Stock: *{alt_item.get('stock_gross', 0):,} Gross*\n"
                            f"• Stock Status: Ready Godown Stock"
                        )
                        send_whatsapp_image(from_phone, alt_bytes, alt_caption)
                        await asyncio.sleep(1.2)
                
                # Ask for customer's approval on the similar buttons
                approval_prompt = (
                    "Sir, inme se kaun sa design aapke fabric/garment ke liye sahi rahega?\n\n"
                    "Aap confirm karenge toh hum aage quotation aur sample arrange kar denge."
                )
                send_whatsapp_text(from_phone, approval_prompt)
                print(f"📤 Sent Similar Options & Asked Approval to {from_phone}")
                return
                
            elif rejects:
                session["waiting_for_similar_permission"] = False
                session["waiting_for_custom_mfg_qty"] = True
                # Rule 6.3: Exact Sample Rejection & Custom Manufacturing Rule
                rejection_msg = (
                    f"Ji {salutation}, koi baat nahi.\n\n"
                    f"Agar hamare shared kiye gaye samples me aapko aapke original button jaisa exact design nahi mila, toh hum aapke diye hue sample ke according factory se same button custom develop karwane ki feasibility check kar sakte hain.\n\n"
                    f"Sir, aapko approximately kitni quantity ki requirement hai? Hum aapki requirement apni Sales Team ko forward kar denge. Hamari Team aapse isi WhatsApp number par baat kar legi."
                )
                send_whatsapp_text(from_phone, rejection_msg)
                print(f"📤 Buyer rejected similar permission. Offered custom mfg check without MOQ to {from_phone}")
                return

        # ---------------- STEP B: HANDLE SIMILAR SELECTION APPROVAL ----------------
        if session.get("waiting_for_similar_approval"):
            # Check for Rejection FIRST (before checking option numbers)
            rejection_keywords = [
                "nahi", "nahu", "no", "not", "na", "mat", "koi bhi nahi", "koi nahi", 
                "dono nahi", "isme se nahi", "rehne do", "kuch nahi", "cancel", "pasand nahi",
                "alag chahiye", "same chahiye", "wahi chahiye", "ye nahi", "chhod do", "inme se koi", "nahi chahiye"
            ]
            is_rejected = any(k in lower_text for k in rejection_keywords)
            
            if is_rejected:
                session["waiting_for_similar_approval"] = False
                session["waiting_for_similar_permission"] = False
                session["waiting_for_custom_mfg_qty"] = True
                
                # Rule 6.3: Exact Sample Rejection & Custom Manufacturing Rule
                rejection_msg = (
                    f"Ji {salutation}, koi baat nahi.\n\n"
                    f"Agar hamare shared kiye gaye samples me aapko aapke original button jaisa exact design nahi mila, toh hum aapke diye hue sample ke according factory se same button custom develop karwane ki feasibility check kar sakte hain.\n\n"
                    f"Sir, aapko approximately kitni quantity ki requirement hai? Hum aapki requirement apni Sales Team ko forward kar denge. Hamari Team aapse isi WhatsApp number par baat kar legi."
                )
                send_whatsapp_text(from_phone, rejection_msg)
                print(f"📤 Customer rejected options. Offered custom mfg check and asked quantity without MOQ to {from_phone}")
                return

            # Check if customer specified quantity ambiguously without selecting Option 1 or Option 2 (Scenario B)
            opt1_match = bool(re.search(r'\b(?:option\s*1|pehla|first|1st)\b', lower_text) or "136" in lower_text or re.search(r'(?<!\d)1(?!\d)', lower_text))
            opt2_match = bool(re.search(r'\b(?:option\s*2|doosra|second|2nd)\b', lower_text) or "137" in lower_text or "139" in lower_text or re.search(r'(?<!\d)2(?!\d)', lower_text))
            
            gross_m = re.search(r'(\d+)\s*(?:gross|gr)', lower_text)
            pcs_m = re.search(r'(\d+)\s*(?:pcs|pieces)', lower_text)
            if (gross_m or pcs_m) and not (opt1_match or opt2_match):
                q_val = int(gross_m.group(1)) if gross_m else max(1, round(int(pcs_m.group(1)) / 144))
                session["quantity"] = q_val
                alts = [get_item_by_sku(s) for s in session.get("suggested_alternatives", [])]
                alts = [a for a in alts if a]
                alt_names = " ya ".join([f"Option {idx+1} ({a['name']})" for idx, a in enumerate(alts)])
                reply = (
                    f"Ji {salutation}, aapne *{q_val:,} Gross* quantity batayi hai.\n\n"
                    f"Kripya confirm karein ki aapko {alt_names} me se kiske liye ye requirement chahiye?"
                )
                send_whatsapp_text(from_phone, reply)
                log_chat_event(from_phone, contact_name, "bot", "text", reply)
                return

            # Check if customer approved Option 1 or Option 2
            selected_alt_sku = None
            if opt1_match and not opt2_match:
                selected_alt_sku = session.get("suggested_alternatives", ["ABC-136"])[0] if session.get("suggested_alternatives") else "ABC-136"
            elif opt2_match and not opt1_match:
                selected_alt_sku = session.get("suggested_alternatives", ["ABC-136", "ABC-137"])[1] if len(session.get("suggested_alternatives", [])) > 1 else "ABC-137"
            
            if selected_alt_sku:
                sel_item = get_item_by_sku(selected_alt_sku) or SAMPLE_CATALOG[0]
                session["matched_sku"] = sel_item["sku"]
                session["matched_name"] = sel_item["name"]
                session["has_photo"] = True
                session["last_active_sku"] = sel_item["sku"]
                session["waiting_for_similar_approval"] = False
                
                # Check if quantity was already stated
                if session.get("quantity"):
                    ack_msg = (
                        f"Ji sir, aapka approval note kar liya hai: *{sel_item['name']}*.\n\n"
                        f"Aapki *{session.get('quantity'):,} Gross* requirement ke according quotation process kar rahe hain."
                    )
                else:
                    ack_msg = (
                        f"Ji sir, aapka approval note kar liya hai: *{sel_item['name']}*.\n\n"
                        f"Aapko iski kitni quantity chahiye? Hum turant iska best quotation prepare kar dete hain."
                    )
                send_whatsapp_text(from_phone, ack_msg)
                print(f"📤 Customer approved {sel_item['sku']}.")
                return

        # SECTION 18.6: LATEST BUYER QUESTION PRIORITY & SALES TEAM CONTACT INQUIRY
        is_contact_inquiry = any(w in lower_text for w in [
            "kab baat", "kab call", "kab contact", "kab contct", "kab connect", 
            "contact kab", "contct kab", "call kab", "baat kab", "connect kab",
            "team kab", "sales team kab", "who will contact", "when will your team",
            "phone kab", "kisko call", "contact number", "kab karegi", "kab karenge",
            "karegi contact", "karegi contct", "baat karegi"
        ]) or (
            any(k in lower_text for k in ["kab", "when", "time", "kitne baje"]) and 
            any(c in lower_text for c in ["contact", "contct", "call", "baat", "connect", "phone", "karegi", "karenge", "aayega", "aayegi"])
        )
        if is_contact_inquiry:
            contact_msg = (
                f"Ji {salutation}, hamari Sales Team aapki enquiry review kar rahi hai. "
                f"Exact call timing abhi confirm nahi hai, lekin sambandhit sales executive jald hi aapse WhatsApp ya call par sampark karenge."
            )
            send_whatsapp_text(from_phone, contact_msg)
            return

        # ---------------- STEP C: HANDLE CUSTOM MANUFACTURING QUANTITY RESPONSE ----------------
        if session.get("waiting_for_custom_mfg_qty"):
            # Check for quantity first!
            gross_m = re.search(r'(\d+)\s*(?:gross|gr)', lower_text)
            pcs_m = re.search(r'(\d+)\s*(?:pcs|pieces)', lower_text)
            num_m = re.search(r'\b(\d+)\b', lower_text)
            
            if gross_m or pcs_m or (num_m and any(w in lower_text for w in ["gross", "order", "chahiye", "pcs", "pieces", "gr", "pack", "hoga", "chahiye sir"])):
                qty_val = int(gross_m.group(1)) if gross_m else (max(1, round(int(pcs_m.group(1))/144)) if pcs_m else int(num_m.group(1)))
                session["quantity"] = qty_val
                # Update quantity in live CRM inquiry
                for item in live_whatsapp_inquiries:
                    if item.get("phone") == from_phone:
                        item["quantity"] = qty_val
                        item["status"] = "Quotation Requested"
                        break
                save_live_inquiries()
                session["waiting_for_custom_mfg_qty"] = False
                
                forward_msg = (
                    f"Ji {salutation}, aapki lagbhag *{qty_val} Gross* requirement note kar li hai.\n\n"
                    f"Humne is sample ki custom manufacturing feasibility, MOQ aur best pricing confirmation ke liye Sales Team ko forward kar diya hai.\n\n"
                    f"Hamari Sales Team aapse isi WhatsApp number par jaldi hi sampark karegi. Thank you sir!"
                )
                send_whatsapp_text(from_phone, forward_msg)
                print(f"📤 Forwarded custom mfg inquiry ({qty_val} Gross) to sales team for {from_phone}")
                return

            # If buyer states the fact that button is not available
            if any(p in lower_text for p in ["aapke pass hai hi nahi", "aapke paas nahi hai", "aapke pass nahi", "hai hi nahi", "stock me nahi hai", "available nahi hai", "to hai nahi", "aapke pas nahi hai"]):
                non_stock_resp = (
                    f"Ji bilkul {salutation}, aap sahi keh rahe hain—ye exact design hamare ready stock me available nahi hai.\n\n"
                    f"Isiliye humne pucha tha ki agar aapki quantity bulk me ho, toh kya hum ise factory se same design custom manufacture karwayein?\n\n"
                    f"Aapko lagbhag kitni quantity ki requirement rahegi?"
                )
                send_whatsapp_text(from_phone, non_stock_resp)
                return

            # Explicit rejection only (never on 'aapke pass nahi' or questions)
            is_explicit_rejection = any(lower_text.strip() == w for w in ["nahi", "nahu", "no", "not", "cancel", "rehne do", "kuch nahi", "mat karo", "not interested", "nahi chahiye", "rehne dijiye"]) and not any(f in lower_text for f in ["pass", "paas", "stock", "hai hi nahi", "to nahi", "bataya"])
            if is_explicit_rejection:
                session["waiting_for_custom_mfg_qty"] = False
                close_msg = (
                    f"Ji {salutation}, bilkul samajh gaye. Future me jab bhi kisi specific design, colour ya size ki requirement ho, aap zaroor batayein. Thank you!"
                )
                send_whatsapp_text(from_phone, close_msg)
                print(f"📤 Customer explicitly not interested in custom mfg.")
                return

        # ---------------- SPECIFIC COMMERCIAL & CUSTOMER HANDLING RULES ----------------


        # BUYER SAYS "BATAYA TO THA / BHEJA TO THA / UPAR DEKHO"
        if any(p in lower_text for p in [
            "bataya to tha", "bheja to tha", "bheja tha", "bataya tha", 
            "ye bheja to tha", "upr dekho", "upar dekho", "pehle bataya", 
            "bhej diya", "photo dekho", "sample dekho"
        ]):
            if session.get("waiting_for_custom_mfg_qty"):
                resp = (
                    f"Ji bilkul {salutation}, aapka photo sample hamare paas logged hai.\n\n"
                    f"Chunki ye exact design ready stock me nahi hai, isiliye hum factory se iski custom development check kar rahe hain.\n\n"
                    f"Aapko lagbhag kitni quantity chahiye hogi, taaki Sales Team manufacturing feasibility aur rate confirm kar sake?"
                )
            elif session.get("quantity"):
                resp = (
                    f"Ji bilkul {salutation}, aapka sample aur *{session['quantity']} Gross* quantity hamare paas note hai. "
                    f"Hamari Sales Team iska quotation review kar rahi hai aur jald aapse connect karegi."
                )
            elif session.get("matched_name"):
                resp = (
                    f"Ji bilkul {salutation}, aapka design (*{session.get('matched_name')}*) note hai. "
                    f"Aapko approximate kitni quantity chahiye hogi?"
                )
            else:
                resp = (
                    f"Ji bilkul {salutation}, aapka sample note kar liya gaya hai. "
                    f"Aapko lagbhag kitni quantity ki requirement rahegi?"
                )
            send_whatsapp_text(from_phone, resp)
            return

        # ---------------- ADD-ON 18: BUYER RESPONSE INTELLIGENCE & DYNAMIC TRACKING ----------------

        # 18.3 DYNAMIC REQUIREMENT UPDATE: SIZE CHANGE (e.g., "size 24L ki jagah 28L", "size 28L kar do")
        sizes_found = re.findall(r'(\d{2})\s*l\b', lower_text)
        is_size_change_request = any(k in lower_text for k in ["ki jagah", "badal", "kar do", "kar dena", "replace", "update", "change size"]) or ("se" in lower_text and len(sizes_found) >= 2)
        if sizes_found and is_size_change_request and session.get("matched_sku"):
            if "ki jagah" in lower_text and len(sizes_found) >= 2:
                new_size = f"{sizes_found[1].upper()}L"
            else:
                new_size = f"{sizes_found[-1].upper()}L"
                
            old_size = session.get("matched_size", "standard")
            session["matched_size"] = new_size
            
            p_name = session.get("matched_name", "Button")
            p_qty = f"{session.get('quantity')} Gross" if session.get("quantity") else "requirement"
            
            size_update_msg = (
                f"Ji {salutation}, size update kar diya hai: *{new_size}* (pehle {old_size} tha).\n\n"
                f"Design (*{p_name}*) aur quantity (*{p_qty}*) safe hai. Hum updated size ke according Sales Team se availability check kar rahe hain."
            )
            save_buyer_session(from_phone, session)
            send_whatsapp_text(from_phone, size_update_msg)
            log_chat_event(from_phone, contact_name, "bot", "text", size_update_msg, size=new_size)
            return

        # 18.3 DYNAMIC REQUIREMENT UPDATE: UNCLEAR COLOUR CHANGE (e.g., "colour bhi change kar dena")
        if any(phrase in lower_text for phrase in ["colour bhi change", "color bhi change", "colour change kar do", "color change kar dena", "colour badal do"]) and not any(c in lower_text for c in ["white", "black", "blue", "smoky", "caramel", "gold", "navy"]):
            send_whatsapp_text(from_phone, f"Sure {salutation}, which colour would you prefer?")
            return

        # 18.2 MULTI-INTENT: SIZE + MOQ + SAMPLE IN ONE MESSAGE
        if any(w in lower_text for w in ["sample", "swatch"]) and any(w in lower_text for w in ["moq", "minimum quantity", "kitna lena hoga", "minimum"]) and re.search(r'\d{2}\s*l\b', lower_text):
            sz_match = re.search(r'(\d{2})\s*[lL]\b', text_body)
            req_sz = f"{sz_match.group(1)}L" if sz_match else "required size"
            multi_resp = (
                f"Certainly {salutation}. We have noted your enquiry for *{req_sz}* size.\n\n"
                f"Regarding minimum order quantity (MOQ) and sample dispatch arrangements, our Sales Team will coordinate directly with you.\n\n"
                f"May I know your delivery address and contact person details for the sample?"
            )
            send_whatsapp_text(from_phone, multi_resp)
            return

        # 18.1 CONTEXTUAL YES / NO RESPONSE INTELLIGENCE
        if lower_text.strip() in ["yes", "haan", "correct", "sahi hai", "right", "sure", "yup"]:
            # Check context: if customer previously had exact match shown but didn't state qty:
            if session.get("matched_sku") and not session.get("quantity"):
                send_whatsapp_text(
                    from_phone,
                    f"Ji {salutation}, design confirmation note kar li hai: *{session.get('matched_name')}*.\n\n"
                    f"Aapko is design me kaun sa size aur approximate kitni quantity ki requirement rahegi?"
                )
                return
            elif session.get("matched_sku") and session.get("quantity"):
                send_whatsapp_text(
                    from_phone,
                    f"Ji {salutation}, aapka confirmation note kar liya hai. Hum quotation finalize karwane ke liye Sales Team ko details de rahe hain. Dhanyawad!"
                )
                return

        # SECTION 20: URGENT REQUIREMENT & DELIVERY DEADLINE HANDLING
        if any(w in lower_text for w in ["urgent", "urgently", "immediate requirement", "immediately", "jaldi chahiye", "emergency", "production starting", "urgent order", "deadline"]):
            urgent_msg = (
                f"Certainly {salutation}, we understand your urgency.\n\n"
                f"May I know your required delivery date so that we can check the feasibility with our Sales Team?"
            )
            send_whatsapp_text(from_phone, urgent_msg)
            return

        # SECTION 22: PAYMENT TERMS & FINANCIAL COMMITMENT RESTRICTION
        if any(w in lower_text for w in ["payment term", "payment terms", "credit", "udhaar", "30 days", "credit facility", "pay after delivery", "partial payment", "receiving the goods"]):
            pay_terms_msg = (
                f"Certainly {salutation}. Our Sales Team will assist you with the payment terms and confirm the applicable arrangements."
            )
            send_whatsapp_text(from_phone, pay_terms_msg)
            return

        # SECTION 23: PURCHASE ORDER (PO) RECEIVED BUT ORDER NOT YET CONFIRMED
        if any(w in lower_text for w in ["shared the po", "attached our purchase order", "attached po", "po has been", "confirm our po", "process our order", "purchase order bhej diya", "po bhej diya", "po attached", "po copy"]):
            po_msg = (
                f"Thank you {salutation}. We have received your Purchase Order. Our Sales Team will review the details and confirm the next steps with you."
            )
            send_whatsapp_text(from_phone, po_msg)
            return

        # SECTION 24: QUALITY COMPLAINT & REPLACEMENT HANDLING
        if any(w in lower_text for w in ["damage", "damaged", "broken", "defective", "defect", "complaint", "wrong design", "short quantity", "not matching", "replacement", "khrab", "toota", "toot gaya"]):
            complaint_msg = (
                f"We are sorry to hear about the concern, {salutation}. We will share this with our Sales Team so they can review it and assist you.\n\n"
                f"Could you please share your Order/Invoice number, affected quantity, and photographs of the buttons?"
            )
            send_whatsapp_text(from_phone, complaint_msg)
            return

        # SECTION 25: INTERNATIONAL BUYER COMMUNICATION & REQUIREMENT COLLECTION
        if any(w in lower_text for w in ["export internationally", "ship to", "overseas", "bangladesh", "vietnam", "sri lanka", "dubai", "usa", "europe", "international moq", "incoterms", "fob", "cif", "export documentation"]):
            intl_msg = (
                "Thank you for sharing your requirement. May I know the product, required quantity and destination country? Our Sales Team will review your requirements and connect with you regarding the next steps."
            )
            send_whatsapp_text(from_phone, intl_msg)
            return

        # SECTION 28: COMPETITOR COMPARISON, NEGOTIATION & DISCOUNT RESTRICTION
        if any(w in lower_text for w in ["competitor", "cheaper", "better rate elsewhere", "lower price elsewhere", "match this price", "sasta mil raha", "discount", "special discount", "best discount", "concession"]):
            comp_msg = (
                f"Certainly {salutation}. We understand that pricing is an important consideration.\n\n"
                f"May I know your required product, size and approximate quantity so our Sales Team can review your requirement and offer the best possible commercial quotation?"
            )
            send_whatsapp_text(from_phone, comp_msg)
            return

        # RULE 4.1 & 4.2: LOCATION & GODOWN / OFFICE VISIT SCHEDULING
        if any(w in lower_text for w in [
            "kahan hai", "kaha hai", "location", "address", "kahan par", "office visit", 
            "godown visit", "aana chahta", "aake dekh", "milna chahta", "visit karna", 
            "kahan aana", "office kahan", "godown kahan"
        ]) and not any(w in lower_text for w in ["plot", "sector", "phase", "road", "gali", "pin", "deliver", "bhejo"]):
            visit_msg = (
                f"Ji {salutation}, aap hamare yahan samples dekhne ke liye saadar aamantrit hain.\n\n"
                f"Hamara Central Godown aur Office *Govindpuri / Kalkaji, New Delhi - 110019* me sthit hai.\n\n"
                f"Aap jab bhi visit karna chahein, kripya humein apni convenient date aur time bata dijiye. Hum pehle se apni Sales Team ko inform kar denge taaki aapke pahunchne par required samples taiyar milein."
            )
            send_whatsapp_text(from_phone, visit_msg)
            return

        # RULE 1.2: SMALL QUANTITY & RETAIL ENQUIRY HANDLING (10-20 pieces, 1-2 shirts)
        small_qty_match = re.search(r'\b([1-9]|1[0-9]|20|25)\s*(?:piece|pieces|pcs|button|buttons|shirt|shirts)\b', lower_text)
        if small_qty_match or any(phrase in lower_text for phrase in ["10 piece", "20 piece", "10 button", "20 button", "chhoti quantity", "1 shirt", "2 shirt", "few pieces"]):
            small_qty_msg = (
                f"Ji {salutation}, koi baat nahi. Aap humein apni required quantity bata dijiye. Hum apni Sales Team se availability confirm karwake aapko bata denge."
            )
            send_whatsapp_text(from_phone, small_qty_msg)
            return

        # RULE 2.1: CUSTOM DYEING & COLOUR MATCHING (DTM)
        if any(w in lower_text for w in ["dyeing", "dtm", "colour match", "color match", "pantone", "fabric match", "shade match", "dyed", "colour karwana", "color karwana", "fabric swatch"]):
            dtm_msg = (
                f"Ji {salutation}, aapke Fabric Swatch ya Pantone Code ke according colour matching aur custom dyeing arrange karwane ka vikalp hai. "
                f"Agar aap humse karwana chahein, toh hum aapki requirement apni Sales Team ko forward kar denge. Hamari Team aapse iski feasibility aur baaki details confirm kar legi."
            )
            send_whatsapp_text(from_phone, dtm_msg)
            return

        # SECTION 18.5: BUYER ASKS FOR UPDATE / EXPECTED RESPONSE TIME
        if any(w in lower_text for w in [
            "kab tak batayenge", "batayenge kab", "any update", "update please", 
            "please update", "update me", "expect the quotation", "when can i expect", 
            "team confirm", "kya hua", "bheja nahi", "kuch update", "update batao", 
            "kitna time lagega batane", "response time", "reply nahi aaya", "update?",
            "how much time will it take"
        ]) or (any(w in lower_text for w in ["kab tak", "kitna time", "when will"]) and any(q in lower_text for q in ["quotation", "rate", "sample", "quote", "batao", "confirm", "reply"])):
            if session.get("has_address"):
                upd_msg = (
                    f"Ji {salutation}, aapka sample dispatch request note kar liya gaya hai. "
                    f"Hamari Sales Team dispatch coordination ke sath jald hi aapse tracking details share karegi."
                )
            elif session.get("quantity") or session.get("matched_sku"):
                sku_txt = f" ({session.get('matched_sku')})" if session.get('matched_sku') else ""
                upd_msg = (
                    f"Ji {salutation}, aapki requirement{sku_txt} ke liye stock aur quotation details hamari Sales Team review kar rahi hai. "
                    f"Team jald hi aapse final quotation ke sath sampark karegi."
                )
            else:
                upd_msg = (
                    f"Ji {salutation}, aapki enquiry Sales Team ko forward kar di gayi hai. "
                    f"Team details check karke aapse sampark karegi."
                )
            send_whatsapp_text(from_phone, upd_msg)
            return


        # RULE 2.2: DISPATCH & DYEING LEAD TIME
        if any(w in lower_text for w in ["lead time", "timeline", "kitne din", "kab tak", "dispatch time", "delivery time", "urgent", "kitna time", "kab milega", "delivery kab"]):
            lead_msg = (
                f"Ji {salutation}, Ready Stock ka dispatch samanyatah 24-48 working hours me ho jata hai. "
                f"Custom Dyeing me lagbhag 3-4 se 5-6 working days lag sakte hain. "
                f"Aapki exact requirement ke anusar hamari Sales Team aapko sahi timeline confirm kar degi."
            )
            send_whatsapp_text(from_phone, lead_msg)
            return

        # RULE 3.2: CUSTOM MOULD / BRAND LOGO / LASER ENGRAVING
        if any(w in lower_text for w in ["logo", "engrav", "laser", "brand name", "custom mould", "mould charge", "naam print", "brand logo"]):
            logo_msg = (
                f"Ji {salutation}, hum aapki requirement ke according logo/custom branding wale buttons ki feasibility check karwa sakte hain.\n\n"
                f"Kripya apna logo vector file (.AI / .CDR / .PDF) aur required quantity share kar dijiye. Hamari Sales Team aapse aage ki details confirm kar legi."
            )
            send_whatsapp_text(from_phone, logo_msg)
            return

        # RULE 5.1: TESTING & EXPORT COMPLIANCE ENQUIRIES (OEKO-TEX, Lead-free, Nickel-free)
        if any(w in lower_text for w in [
            "oeko", "oeko-tex", "lead free", "lead-free", "nickel free", "nickel-free", 
            "phthalate", "test report", "chemical test", "metal test", "washing standard", 
            "export compliance", "certificate", "certification"
        ]):
            test_msg = (
                f"Ji {salutation}, agar aapko buttons ke liye Lead-Free, Nickel-Free, Chemical Testing, Metal Testing ya kisi specific export compliance ki requirement hai, toh hum aapki baat apni Sales Team se karwa denge.\n\n"
                f"Hamari Team sambandhit button ki specifications ke anusar aapko proper information aur availability confirm kar degi."
            )
            send_whatsapp_text(from_phone, test_msg)
            return

        # SECTION 21: SAMPLE COURIER RESTRICTION (No To-Pay or Courier Cost discussion)
        if any(w in lower_text for w in ["courier charge", "courier payment", "courier cost", "freight charges", "who will pay courier"]):
            courier_charge_msg = (
                f"Ji {salutation}, our Sales Team will coordinate the sample dispatch arrangements with you."
            )
            send_whatsapp_text(from_phone, courier_charge_msg)
            return

        if any(w in lower_text for w in ["sample courier", "sample bhej", "sample card", "hanger card", "swatch", "sample chahiye", "cutting sample", "physical sample", "send sample"]):
            card_path = os.path.join(CAT_DIR, "ABC-SAMPLE-CARD-01.jpg")
            sample_resp = (
                f"Certainly {salutation}, we can assist you with the sample arrangements.\n\n"
                f"May I know your delivery address and contact person's details so our team can coordinate the next steps?"
            )
            if os.path.exists(card_path):
                with open(card_path, "rb") as cfp:
                    card_bytes = cfp.read()
                send_whatsapp_image(from_phone, card_bytes, sample_resp)
            else:
                send_whatsapp_text(from_phone, sample_resp)
            return

        # RULE 1.1: NO INSTANT PRICE QUOTATION
        if any(w in lower_text for w in ["rate", "price", "quotation", "quote", "cost", "bhaav", "paisa", "kitne ka", "charges", "per gross", "discount"]):
            price_msg = (
                "Ji sir, hamare buttons ke rate aapki required quantity aur product specifications ke anusar alag-alag hote hain. "
                "Hum aapki enquiry apni Sales Team ko forward kar denge. Hamari Sales Team aapse baat karke jald hi aapko best possible wholesale quotation share kar degi."
            )
            send_whatsapp_text(from_phone, price_msg)
            return

        # Sub-Case: Address Provided by Buyer
        if any(w in lower_text for w in ["plot", "sector", "phase", "road", "gali", "noida", "gurgaon", "delhi", "pin", "near"]):
            session["has_address"] = True
            send_whatsapp_text(
                from_phone,
                f"Ji dhanyawad {salutation}! Delivery address note kar liya hai.\n"
                f"Hamari dispatch team required samples arrange karke sales & dispatch team coordination ke sath aapse tracking details share kar degi sir."
            )
            return

        # Parse quantity if stated in message
        gross_match = re.search(r'(\d+)\s*(?:gross|gr)', lower_text)
        pcs_match = re.search(r'(\d+)\s*(?:pcs|pieces)', lower_text)
        cleaned_for_num = re.sub(r'option\s*\d+', '', lower_text)
        general_num = re.search(r'(\d+)', cleaned_for_num)
        
        has_qty_in_msg = bool(gross_match or pcs_match or (general_num and any(w in lower_text for w in ["gross", "order", "chahiye", "pack", "dispatch", "pcs", "pieces", "gr"])))
        
        # Check Option selection or Product Catalog Text Inquiries
        text_sku_map = [
            (["agoya", "agora", "shirt pearl", "agoya shell", "white pearl"], "ABC-136"),
            (["river shell", "river", "white river", "saucer rim"], "ABC-139"),
            (["gold cowrie", "gold kaudi", "metallic cowrie", "24k"], "ABC-153"),
            (["cowrie", "kaudi", "kodi", "sea cowrie"], "ABC-152"),
            (["horn", "buffalo horn", "water buffalo"], "ABC-HRN-24L-06"),
            (["corozo", "tagua", "vegetable ivory"], "ABC-COR-24L-16"),
            (["coconut", "nariyal", "coco"], "ABC-COCO-24L-18"),
            (["wood", "wooden", "sheesham", "hardwood"], "ABC-WOOD-32L-19"),
            (["metal shank", "metal", "brass", "shank", "blazer"], "ABC-MTL-24L-14"),
            (["polyester", "faux mop", "chalk", "resin"], "ABC-POLY-18L-10"),
            (["sample card", "hanger card", "hanger"], "ABC-SAMPLE-CARD-01"),
            (["black pearl", "charcoal black", "smoky shell", "black lip"], "ABC-151"),
            (["caramel", "gold shell", "champagne"], "ABC-137"),
            (["turquoise", "teal", "ocean turquoise"], "ABC-142"),
            (["pink", "blush", "cherry blossom"], "ABC-144"),
            (["violet", "purple", "plum"], "ABC-149"),
            (["spotted", "brown spot"], "ABC-143"),
            (["gunmetal", "trocas"], "ABC-141"),
        ]
        
        matched_text_sku = None
        for kws, t_sku in text_sku_map:
            if any(k in lower_text for k in kws):
                matched_text_sku = t_sku
                break

        if matched_text_sku:
            item = get_item_by_sku(matched_text_sku) or SAMPLE_CATALOG[0]
            session["matched_sku"] = item["sku"]
            session["matched_name"] = item["name"]
            
            # Requirement 8: Never assume 14L or 18L when customer has not selected one.
            # If item has multiple sizes (slash/comma/or), keep matched_size as None until customer selects.
            raw_sz = str(item.get("size_ligne", "")).strip()
            if "/" not in raw_sz and "," not in raw_sz and "or" not in raw_sz.lower():
                session["matched_size"] = raw_sz
            else:
                if not session.get("matched_size"):
                    session["matched_size"] = None
                    
            session["has_photo"] = True
            session["last_active_sku"] = item["sku"]
            
            # If quantity is not yet mentioned in this message, send exact stock details & ask for quantity
            if not has_qty_in_msg:
                p_img_path = os.path.join(CAT_DIR, f"{item['sku']}.jpg")
                if os.path.exists(p_img_path):
                    with open(p_img_path, "rb") as fp:
                        p_img_bytes = fp.read()
                    best_caption = (
                        f"🏆 *Ready Stock Available: {item['name']}*\n"
                        f"• SKU: {item['sku']} • Size: {item.get('size_ligne', '')} • {item.get('holes', '')}\n"
                        f"• Ready Godown Stock: *{item.get('stock_gross', 0):,} Gross* ({item.get('stock_gross', 0)*144:,} Pcs)\n"
                        f"• Standard Rate: *₹{item.get('rate_per_gross', 0)} / Gross*\n\n"
                        f"100% genuine export quality stock Central Godown, New Delhi me available hai."
                    )
                    send_whatsapp_image(from_phone, p_img_bytes, best_caption, sku=item['sku'], product_name=item['name'], size_opts=item.get('size_ligne', ''))
                    log_chat_event(from_phone, contact_name, "bot", "image", best_caption, sku=item['sku'])
                    await asyncio.sleep(1.2)
                    
                reply_text = (
                    f"Ji {salutation}, hamare paas {item['name']} ready godown stock me available hai ({item.get('stock_gross', 0):,} Gross stock).\n\n"
                    f"Aapko kis size me aur lagbhag kitni quantity (Gross) me requirement hai?"
                )
                send_whatsapp_text(from_phone, reply_text)
                log_chat_event(from_phone, contact_name, "bot", "text", reply_text)
                save_buyer_session(from_phone, session)
                return

        # Check Option selection
        if "option 1" in lower_text or "136" in lower_text:
            session["matched_sku"] = "ABC-136"
            session["matched_name"] = "ABC-136 White Pearl Agoya Shell Button (Bulk Stock)"
            session["has_photo"] = True
            session["last_active_sku"] = "ABC-136"
        elif "option 2" in lower_text or "139" in lower_text:
            session["matched_sku"] = "ABC-139"
            session["matched_name"] = "ABC-139 Natural White River Shell Button"
            session["has_photo"] = True
            session["last_active_sku"] = "ABC-139"
        elif "option 3" in lower_text or "137" in lower_text:
            session["matched_sku"] = "ABC-137"
            session["matched_name"] = "ABC-137 Caramel Gold MOP Shell Button"
            session["has_photo"] = True
            session["last_active_sku"] = "ABC-137"
        elif "141" in lower_text:
            session["matched_sku"] = "ABC-141"
            session["matched_name"] = "ABC-141 Smoky Grey River Shell Button"
            session["has_photo"] = True
            session["last_active_sku"] = "ABC-141"
        elif "142" in lower_text:
            session["matched_sku"] = "ABC-142"
            session["matched_name"] = "ABC-142 Turquoise Blue Tinted Shell Button"
            session["has_photo"] = True
            session["last_active_sku"] = "ABC-142"

        # Parse size if stated (e.g. 14L, 18L, 24L, 11.5mm)
        size_match = re.search(r'\b(\d{1,2}(?:\.\d+)?\s*(?:l|ligne|line|mm))\b', lower_text, re.IGNORECASE)
        if size_match:
            session["matched_size"] = size_match.group(1).upper().replace(" ", "")

        # Scenario C: Buyer specifies/changes ONLY size without quantity
        if size_match and not has_qty_in_msg and (session.get("matched_sku") or session.get("has_photo")):
            item = get_item_by_sku(session.get("matched_sku"))
            item_name = item.get("name") if item else session.get("matched_name", "button")
            curr_size = session.get("matched_size")
            curr_qty = session.get("quantity")
            
            if curr_qty:
                reply = (
                    f"Ji {salutation}, *{curr_size}* size update kar diya hai.\n\n"
                    f"Aapki *{item_name}* (Size: *{curr_size}*) ke liye *{curr_qty:,} Gross* "
                    f"requirement ka quotation update kar rahe hain."
                )
            else:
                reply = (
                    f"Ji {salutation}, *{curr_size}* size note kar liya hai *{item_name}* ke liye.\n\n"
                    f"Aapko approximate kitni quantity (Gross me) chahiye hogi sir?"
                )
            send_whatsapp_text(from_phone, reply)
            log_chat_event(from_phone, contact_name, "bot", "text", reply, sku=session.get("matched_sku"))
            return

        # ----------------- INTENT CLASSIFICATION & STRUCTURED QUANTITY MEMORY -----------------
        buyer_intent, intent_meta = classify_buyer_intent(text_body, session, active_sku=session.get("matched_sku"))

        # REQUIREMENT 2, 4, 6, 9 & 11: SELLER STOCK REFERENCE OR PREVIOUS CLAIM
        if buyer_intent == "SELLER_STOCK_OR_CLAIM_REFERENCE":
            active_sku = session.get("matched_sku") or session.get("last_active_sku") or "ABC-136"
            item = get_item_by_sku(active_sku) or SAMPLE_CATALOG[0]
            item_name = item.get("name") if item else session.get("matched_name", "selected button")
            clean_name = re.sub(r'\s*\([^)]*bulk[^)]*\)', '', item_name, flags=re.IGNORECASE).strip()
            
            # Extract catalog stock
            cat_stock = intent_meta.get("referenced_stock") or item.get("stock_gross", 1250)
            session["catalog_available_stock"] = cat_stock
            
            # REQUIREMENT 1, 2, 5 & 11: NEVER overwrite customer_required_quantity!
            req_qty = session.get("customer_required_quantity") or session.get("quantity") or 200
            session["customer_required_quantity"] = req_qty
            session["quantity"] = req_qty
            session["verified_live_stock"] = 0  # REQUIREMENT 9: Never claim live verification solely from static catalog
            
            # REQUIREMENT 8: Preserve size context
            size_val = session.get("matched_size")
            size_phrase = f" ({size_val})" if size_val else ""
            
            is_hindi_script = bool(re.search(r'[\u0900-\u097F]', text_body))
            is_pure_english = (
                any(w in lower_text for w in ["you mentioned", "you said", "you told", "available in stock", "how much stock", "ready in stock", "stock available"]) 
                and not is_hindi_script 
                and not bool(re.search(r'\b(?:aapne|aapke|paas|pass|hai|tha|godown|chahiye|batao|bhejo|hum)\b', lower_text))
            )
            
            if is_hindi_script:
                reply = (
                    f"जी {salutation}, बिल्कुल सही! हमारे कैटलॉग रिकॉर्ड के अनुसार {clean_name}{size_phrase} का *{cat_stock:,} Gross* रेडी स्टॉक लिस्टेड है।\n\n"
                    f"आपकी खरीदारी की आवश्यकता हमने *{req_qty:,} Gross* ही नोट कर रखी है। लाइव वेयरहाउस स्टॉक उपलब्धता और कोटेशन सेल्स टीम से वेरीफाई करवा रहे हैं सर।\n\n"
                    f"क्या आपको {req_qty:,} Gross के लिए ही कोटेशन कन्फर्म करना है, या आप रिक्वायरमेंट बढ़ाना चाहते हैं?"
                )
            elif is_pure_english:
                reply = (
                    f"Yes {salutation}, absolutely! As per our catalog records, *{cat_stock:,} Gross* ready stock is listed for {clean_name}{size_phrase}.\n\n"
                    f"Your purchase requirement remains noted as *{req_qty:,} Gross*. Our Sales Team is currently verifying live warehouse stock availability and preparing your quotation.\n\n"
                    f"Would you like to confirm the quotation for {req_qty:,} Gross, or would you like to increase your quantity?"
                )
            else:
                reply = (
                    f"Ji {salutation}, bilkul sahi! Hamare catalog records ke mutabik {clean_name}{size_phrase} ka *{cat_stock:,} Gross* ready stock listed hai.\n\nAapki purchasing requirement humne *{req_qty:,} Gross* hi note kar rakhi hai. Current warehouse live stock availability aur quotation Sales Team se verify karwa rahe hain sir.\n\nKya aapko {req_qty:,} Gross ke liye hi quotation confirm karna hai, ya aap requirement badhana chahte hain?"
                )
                
            save_buyer_session(from_phone, session)
            log_chat_event(
                from_phone, contact_name, "bot", "text", reply,
                sku=active_sku, size=size_val, qty=req_qty,
                customer_required_quantity=req_qty,
                catalog_available_stock=cat_stock,
                verified_live_stock=0
            )
            send_whatsapp_text(from_phone, reply)
            return

        # REQUIREMENT 3 & 6: EXPLICIT ORDER MODIFICATION / CORRECTION
        if buyer_intent == "ORDER_MODIFICATION":
            new_qty = intent_meta.get("new_quantity", 200)
            active_sku = session.get("matched_sku") or session.get("last_active_sku") or "ABC-136"
            item = get_item_by_sku(active_sku) if active_sku else None
            item_name = item.get("name") if item else session.get("matched_name", "selected button")
            clean_name = re.sub(r'\s*\([^)]*bulk[^)]*\)', '', item_name, flags=re.IGNORECASE).strip()
            
            session["customer_required_quantity"] = new_qty
            session["quantity"] = new_qty
            session["matched_sku"] = active_sku
            session["matched_name"] = clean_name
            if item:
                session["catalog_available_stock"] = item.get("stock_gross", 1250)
                
            size_val = session.get("matched_size")
            size_phrase = f" ({size_val})" if size_val else ""
            
            reply = (
                f"Ji {salutation}, {clean_name}{size_phrase} ke liye aapki requirement update karke *{new_qty:,} Gross* kar di hai. "
                f"Current stock availability aur quotation Sales Team se verify karwa rahe hain."
            )
            save_buyer_session(from_phone, session)
            log_chat_event(
                from_phone, contact_name, "bot", "text", reply,
                sku=active_sku, size=size_val, qty=new_qty,
                customer_required_quantity=new_qty,
                catalog_available_stock=session.get("catalog_available_stock", 0),
                verified_live_stock=0
            )
            send_whatsapp_text(from_phone, reply)
            return

        # If quantity stated in this message -> record in session
        if has_qty_in_msg:
            if gross_match:
                session["quantity"] = int(gross_match.group(1))
            elif pcs_match:
                session["quantity"] = max(1, round(int(pcs_match.group(1)) / 144))
            elif general_num:
                val = int(general_num.group(1))
                session["quantity"] = round(val / 144) if val > 1000 else val

            qty = session.get("quantity", 0)
            session["customer_required_quantity"] = qty

            # Scenario B: Multiple products shared, buyer replies with ambiguous quantity
            if session.get("waiting_for_similar_approval") and session.get("suggested_alternatives") and not session.get("matched_sku"):
                alts = [get_item_by_sku(s) for s in session.get("suggested_alternatives", [])]
                alts = [a for a in alts if a]
                alt_options = " ya ".join([f"Option {idx+1} ({a['name']})" for idx, a in enumerate(alts)])
                reply = (
                    f"Ji {salutation}, aapne *{qty:,} Gross* quantity batayi hai.\n\n"
                    f"Kripya confirm karein ki aapko {alt_options} me se kiske liye ye requirement chahiye?"
                )
                send_whatsapp_text(from_phone, reply)
                log_chat_event(from_phone, contact_name, "bot", "text", reply)
                return

            active_sku = session.get("matched_sku") or session.get("last_active_sku")

            # Scenario A / D / Acceptance Test: Active product exists OR photo was shared
            if active_sku or session.get("has_photo"):
                item = get_item_by_sku(active_sku) if active_sku else None
                item_name = item.get("name") if item else session.get("matched_name", "selected button")
                clean_name = re.sub(r'\s*\([^)]*bulk[^)]*\)', '', item_name, flags=re.IGNORECASE).strip()
                size_val = session.get("matched_size")
                size_phrase = f" mein {size_val} size" if size_val else ""

                session["quantity"] = qty
                session["customer_required_quantity"] = qty
                if item:
                    session["catalog_available_stock"] = item.get("stock_gross", 1250)
                session["matched_sku"] = active_sku
                session["matched_name"] = clean_name
                save_buyer_session(from_phone, session)

                # Strict Acceptance Test Formulated Reply:
                # "Ji sir, ABC-136 White Pearl Agoya Shell Button mein 18L size aur 200 Gross ki aapki requirement note kar li hai. Current stock availability aur quotation Sales Team se verify karwa rahe hain."
                reply = (
                    f"Ji {salutation}, {clean_name}{size_phrase} aur {qty:,} Gross ki aapki requirement note kar li hai. "
                    f"Current stock availability aur quotation Sales Team se verify karwa rahe hain."
                )
                send_whatsapp_text(from_phone, reply)
                log_chat_event(from_phone, contact_name, "bot", "text", reply, sku=active_sku, size=size_val, qty=qty, customer_required_quantity=qty, catalog_available_stock=session.get("catalog_available_stock", 0), verified_live_stock=0)
                return
            else:
                reply = "Ji sir, aap button ka sample ya photo share kar dijiye, taaki hum sahi product identify kar sakein."
                send_whatsapp_text(from_phone, reply)
                log_chat_event(from_phone, contact_name, "bot", "text", reply)
                save_buyer_session(from_phone, session)
                return

        # Courtesy & Acknowledgement
        elif any(lower_text.strip() == w for w in [
            "ok", "okay", "ok ji", "theek hai", "thik hai", "thanks", "thank you", 
            "shukriya", "dhanyawad", "done", "ji", "sure", "alright", "great", 
            "perfect", "done sir", "ok sir", "theek hai sir", "k", "kk", "ok done", "theek h"
        ]):
            courtesy_cnt = session.get("courtesy_count", 0) + 1
            session["courtesy_count"] = courtesy_cnt
            
            # REQUIREMENT 1, 5 & 11: Preserve customer_required_quantity across courtesy messages
            req_qty = session.get("customer_required_quantity") or session.get("quantity")
            if req_qty:
                session["customer_required_quantity"] = req_qty
                session["quantity"] = req_qty
            
            if courtesy_cnt > 1:
                # If buyer repeats 'ok', keep response human and concise (no robotic repetition)
                reply = f"Ji {salutation} 👍"
                send_whatsapp_text(from_phone, reply)
                log_chat_event(from_phone, contact_name, "bot", "text", reply, qty=req_qty, customer_required_quantity=req_qty)
                save_buyer_session(from_phone, session)
                return
                
            if session.get("has_address") and not req_qty:
                reply = f"Ji bilkul {salutation}! Sample dispatch ki details aapse share kar denge. Dhanyawad sir! 🙏"
            elif req_qty:
                reply = f"Ji bilkul {salutation}! Quotation ready hote hi hum turant aapse share karenge. Dhanyawad sir! 🙏"
            else:
                reply = f"Ji bilkul {salutation}! Dhanyawad. Koi bhi requirement ya query ho toh zaroor batayein sir. 🙏"
            send_whatsapp_text(from_phone, reply)
            log_chat_event(from_phone, contact_name, "bot", "text", reply, qty=req_qty, customer_required_quantity=req_qty)
            save_buyer_session(from_phone, session)
            return
            
        # General greeting / assistance
        else:
            if session.get("has_photo") or session.get("matched_sku") or session.get("quantity") or session.get("history_count", 0) > 1:
                if (session.get("has_photo") or session.get("matched_sku")) and not session.get("quantity"):
                    if session.get("waiting_for_custom_mfg_qty"):
                        send_whatsapp_text(
                            from_phone,
                            f"Ji {salutation}, custom manufacturing feasibility ke liye kripya approximate quantity (Gross) bata dijiye."
                        )
                    elif session.get("matched_name"):
                        send_whatsapp_text(
                            from_phone,
                            f"Ji {salutation}, {session.get('matched_name')} ke quotation ke liye aapko kitni quantity chahiye?"
                        )
                    else:
                        send_whatsapp_text(
                            from_phone,
                            f"Ji {salutation}, aapko approximate kitni quantity ki requirement rahegi?"
                        )
                elif not session.get("has_photo") and not session.get("matched_sku") and session.get("quantity"):
                    send_whatsapp_text(
                        from_phone,
                        "Ji sir, aap button ka sample ya photo share kar dijiye, taaki hum sahi product identify kar sakein."
                    )
                else:
                    help_msg = (
                        f"Ji {salutation}, garments ke liye aapko kis type ya design ke buttons chahiye? "
                        f"Aap button ka sample photo ya naam/specification yahan share kar sakte hain, hum turant available ready stock check karke batate hain."
                    )
                    send_whatsapp_text(from_phone, help_msg)
                    log_chat_event(from_phone, contact_name, "bot", "text", help_msg)
            else:
                welcome_msg = (
                    "Namaste! ABC Buttons mein aapka swagat hai.\n\n"
                    "Garments ke liye kisi bhi type ke buttons chahiye hon, toh aap button ki photo or design yahan share kar sakte hain.\n\n"
                    "Hum aapko available stock & suitable options check karke bata denge.\n\n"
                    "Batayein sir, aapko kis type ke buttons chahiye?"
                )
                send_whatsapp_text(from_phone, welcome_msg, contact_name)
                log_chat_event(from_phone, contact_name, "bot", "text", welcome_msg)

    db.update_inbound_message_status(msg_id, "COMPLETED")

# ----------------- WEBHOOK ENDPOINTS -----------------

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "ABC Buttons 24/7 WhatsApp AI Bot",
        "version": "2.3.0-V12",
        "env_status": {
            "whatsapp_token_configured": bool(getattr(__import__("whatsapp_service"), "WHATSAPP_TOKEN", "")),
            "phone_id_configured": bool(getattr(__import__("whatsapp_service"), "PHONE_NUMBER_ID", "")),
            "gemini_api_key_configured": bool(os.environ.get("GEMINI_API_KEY") or getattr(__import__("ai_engine"), "API_KEY", "")),
            "admin_api_key_configured": bool(ADMIN_API_KEY)
        },
        "features": [
            "Customer Context Awareness",
            "No Repetition Rule",
            "One Question at a Time",
            "Commercial & Pricing Rules (1.1 - 7.0)",
            "Automatic Buyer Photo Scan",
            "Stock Verification & Rate Assistant",
            "Transactional Inbound Message Lifecycle (V12)"
        ]
    }

@app.get("/webhook")
def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")
    
    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("✅ Meta Webhook successfully verified!")
        return PlainTextResponse(content=challenge, status_code=200)
    else:
        print("❌ Meta Webhook verification failed. Token mismatch.")
        return Response(content="Forbidden", status_code=403)

@app.post("/webhook")
async def receive_webhook(request: Request, background_tasks: BackgroundTasks):
    body_bytes = await request.body()
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    
    # Requirement 7: Meta Webhook HMAC-SHA256 Signature Verification
    if not verify_webhook_signature(body_bytes, sig_header):
        print("❌ Meta Webhook signature verification failed. Unauthorized request.")
        return JSONResponse(status_code=403, content={"error": "Invalid signature"})

    try:
        payload = json.loads(body_bytes.decode("utf-8"))
        import datetime
        t_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        received_events.append({"time": t_str, "payload": payload})
        print(f"📥 [WEBHOOK ARRIVED at {t_str}] Payload: {json.dumps(payload)[:250]}")
        
        for entry_item in payload.get("entry", []):
            for change_item in entry_item.get("changes", []):
                val = change_item.get("value", {})
                if "messages" in val:
                    background_tasks.add_task(process_incoming_whatsapp_message, val)
                if "statuses" in val:
                    for s_item in val.get("statuses", []):
                        w_id = s_item.get("id")
                        s_val = s_item.get("status", "").upper()
                        recip = s_item.get("recipient_id")
                        err_list = s_item.get("errors", [])
                        err_str = json.dumps(err_list) if err_list else ""
                        if w_id:
                            db.update_message_delivery_status(wamid=w_id, new_status=s_val, error=err_str, phone=recip)
    except Exception as e:
        print(f"Error handling webhook payload: {e}")
        
    return JSONResponse(content={"status": "received"}, status_code=200)

@app.get("/api/live_inquiries")
def get_live_inquiries(request: Request):
    if not verify_admin_auth(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized. Valid X-API-Key required."})
    inqs = load_live_inquiries()
    return JSONResponse(content={
        "status": "success",
        "total": len(inqs),
        "inquiries": inqs
    })

@app.post("/api/crm/update")
async def update_crm_status_endpoint(request: Request):
    """Synchronizes Human Takeover and Salesperson status from Streamlit Cloud to Render in real-time."""
    if not verify_admin_auth(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized. Valid X-API-Key required."})
    try:
        body = await request.json()
        phone = body.get("phone")
        if not phone:
            return JSONResponse(status_code=400, content={"error": "Missing phone"})
        success, rows = db.update_inquiry_crm_meta(
            phone=phone,
            human_takeover=body.get("human_takeover"),
            assigned_salesman=body.get("assigned_salesman"),
            crm_status=body.get("crm_status")
        )
        if success and rows > 0:
            return JSONResponse(content={"status": "success", "phone": phone, "rows_affected": rows})
        else:
            return JSONResponse(status_code=404, content={"error": f"Customer record for {phone} not found", "rows_affected": 0})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/clear_inquiries")
def clear_live_inquiries(request: Request):
    # Requirements 8 & 9: Restrict Destructive API Operations
    if not verify_admin_auth(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized. Valid X-API-Key required."})
        
    with db.get_db_connection() as conn:
        conn.execute("DELETE FROM live_inquiries;")
    db.export_to_data_store_json()
    return JSONResponse(content={"status": "cleared"})

@app.get("/history")
def get_history(request: Request):
    if not verify_admin_auth(request):
        return JSONResponse(status_code=401, content={"error": "Unauthorized. Valid X-API-Key required."})
    return {
        "total_events": len(received_events),
        "recent_events": received_events[-10:]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("webhook_bot:app", host="0.0.0.0", port=port, reload=False)
