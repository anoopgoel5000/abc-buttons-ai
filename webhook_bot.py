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

def extract_buyer_slots(text: str, session: dict = None) -> dict:
    """Intelligently extracts conversational slots for commercial sales qualification."""
    sess = session or {}
    lower = text.lower().strip()
    slots = {}

    # 1. AI Identity Query
    if re.search(r'\b(?:are you|aap)\s+(?:a\s+)?(?:bot|ai|robot)\b|\b(?:ai|bot|robot)\s+ho\b|\b(?:human|insaan)\s+ho\b|\bwho are you\b', lower):
        slots["is_identity_query"] = True

    # 2. Price Query
    if any(w in lower for w in ["rate kya", "price kya", "rate batao", "price batao", "kitne ka", "what is the price", "what is the rate", "cost kya", "per gross rate", "bhaav", "quotation chahiye", "quote bhejo", "price please", "rate please"]):
        slots["is_price_query"] = True

    # 3. Stock Query
    if any(w in lower for w in ["ready stock", "stock hai", "stock available", "godown me", "godown mein", "available hai kya", "stock me hai", "in stock"]) and not any(w in lower for w in ["aapne bola", "aapne kaha", "you mentioned"]):
        slots["is_stock_query"] = True

    # 4. Similar Samples Request
    if any(w in lower for w in ["similar sample", "milte julte", "similar button", "options dikhao", "swatch card", "sample card", "sample chahiye", "cutting sample", "similar options"]):
        slots["is_sample_request"] = True

    # 5. Custom Manufacturing
    if any(w in lower for w in ["custom banwana", "custom manufacture", "apna logo", "logo engraving", "custom design", "custom button", "custom dyeing", "dtm"]):
        slots["is_custom_mfg"] = True

    # 6. Urgency
    if any(w in lower for w in ["urgent", "urgently", "jaldi chahiye", "emergency", "asap", "immediate", "kal tak"]):
        slots["urgency"] = "URGENT"

    # 7. Quantity & Correction
    is_corr_phrase = any(k in lower for k in ["ki jagah", "badal", "change", "update", "kar do", "kar dena", "karo"]) or (lower.startswith("nahi") and any(ch.isdigit() for ch in lower))
    nums = re.findall(r'\b(\d+)\b', lower)
    if is_corr_phrase and sess.get("quantity") and nums:
        slots["is_qty_correction"] = True
        slots["quantity"] = int(nums[-1])
    else:
        m_gross = re.search(r'\b(\d+)\s*(?:gross|gr|gros)\b', lower)
        if m_gross:
            slots["quantity"] = int(m_gross.group(1))
            slots["is_qty_correction"] = False
        else:
            m_pcs = re.search(r'\b(\d+)\s*(?:pcs|pieces)\b', lower)
            if m_pcs:
                slots["quantity"] = max(1, round(int(m_pcs.group(1)) / 144))
                slots["is_qty_correction"] = False
            elif sess.get("waiting_for_detail") == "quantity" and nums:
                slots["quantity"] = int(nums[0])
                slots["is_qty_correction"] = False

    # 8. Category extraction
    cat_map = [
        (["agoya", "agora", "shirt pearl"], "Agoya Shell Button"),
        (["river shell", "river", "white river"], "River Shell Button"),
        (["trocas", "gunmetal"], "Trocas Shell Button"),
        (["mop", "mother of pearl", "caramel gold"], "MOP Shell Button"),
        (["polyester", "faux mop", "chalk", "resin"], "Polyester Button"),
        (["horn", "buffalo horn"], "Horn Button"),
        (["corozo", "tagua"], "Corozo Button"),
        (["coconut", "nariyal"], "Coconut Shell Button"),
        (["wood", "wooden"], "Wooden Button"),
        (["metal", "shank", "blazer"], "Metal Shank Button")
    ]
    for kws, cat_name in cat_map:
        if any(k in lower for k in kws):
            slots["product_category"] = cat_name
            break

    # 9. Size extraction
    sz_m = re.search(r'\b(\d{1,2})\s*[lL]\b', text)
    if sz_m:
        slots["size"] = f"{sz_m.group(1)}L"

    # 10. Multi-slot all-in-one check (e.g. "Hum Apex Fashions Surat se hain, 300 gross River Shell 18L chahiye urgent")
    m_allinone = re.search(r'(?:hum\s+)?([A-Za-z0-9\s]+?)\s+(?:from\s+|in\s+)?(Surat|Delhi|Mumbai|Ahmedabad|Jaipur|Bangalore|Kolkata|Noida|Gurgaon|Tirupur|Ludhiana|Chennai|Kanpur|Indore)\b', text, re.IGNORECASE)
    if m_allinone and not slots.get("is_qty_correction"):
        comp = re.sub(r'^(?:hum|we\s+are|hamara|from)\s+', '', m_allinone.group(1).strip(), flags=re.IGNORECASE).strip()
        cit = m_allinone.group(2).strip().title()
        if len(comp) >= 2 and not any(w in comp.lower() for w in ["gross", "button", "nahi"]):
            slots["company"] = comp
            slots["city"] = cit

    return slots

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
                crm_status="Image Download Failed - Needs Human Review",
                inquiry_status="PHOTO_DOWNLOAD_FAILED"
            )
            fallback_text = (
                f"Ji {salutation}, network connectivity ke kaaran button photo download nahi ho paayi. "
                f"Kripya photo dobara bhej dijiye taaki Sales Team ise verify kar sake."
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

        # ---------------- SIMPLIFIED 24x7 SALES INTAKE & HANDOFF FLOW ----------------
        # Determine IST time and office hours (Mon-Sat 9:30 AM to 7:00 PM IST)
        import datetime
        import random
        utc_now = datetime.datetime.now(datetime.timezone.utc)
        ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
        is_sunday = (ist_now.weekday() == 6)
        is_office_hours = (not is_sunday) and (datetime.time(9, 30) <= ist_now.time() <= datetime.time(19, 0))

        # Format: INQ-YYYYMMDD-XXXX (Unique internal inquiry ID, NOT a SKU)
        inq_id_prefix = f"INQ-{ist_now.strftime('%Y%m%d')}"
        active_inq_id = session.get("active_inquiry_id")
        if not active_inq_id or not str(active_inq_id).startswith(inq_id_prefix):
            inquiry_id = f"{inq_id_prefix}-{random.randint(1000, 9999)}"
            session["active_inquiry_id"] = inquiry_id
        else:
            inquiry_id = active_inq_id

        # Candidate SKU reference for internal sales team notes
        best_sku = res.get("best_match_sku")
        session["has_photo"] = True
        session["matched_sku"] = best_sku or "Custom / Non-Catalog"
        session["last_active_sku"] = best_sku

        # Parse quantity from caption if given
        caption_qty = None
        if caption:
            qm = re.search(r'(\d+)\s*(?:gross|gr|gros|pkt|packet|bag|box)?\b', caption.lower())
            if qm and int(qm.group(1)) > 0:
                caption_qty = int(qm.group(1))

        if caption_qty:
            session["quantity"] = caption_qty
        else:
            session["quantity"] = None  # Reset requirement quantity for new sample photograph

        # Reuse existing customer company & city from database if already known
        if not session.get("company") or not session.get("city"):
            with db.get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT company, city FROM live_inquiries WHERE phone = ? LIMIT 1", (db.normalize_phone(from_phone),))
                row = cur.fetchone()
                if row:
                    row_dict = dict(row)
                    if row_dict.get("company") and not session.get("company"):
                        session["company"] = row_dict["company"]
                    if row_dict.get("city") and not session.get("city"):
                        session["city"] = row_dict["city"]

        # Feature Extraction for Internal Sales Notes
        va = res.get("visual_analysis", {})
        mat_det = va.get("material_detected", "Shell")
        holes_det = va.get("holes_detected", "2/4 hole")
        finish_det = va.get("finish_detected", "Gloss")
        internal_cv_notes = f"Detected: {mat_det}, {holes_det}, {finish_det}. Reference: {best_sku or 'Custom Development'}"

        # Construct truthful acknowledgement
        if is_office_hours:
            ack_msg = (
                f"Ji {salutation}, aapka button sample photo humein prapt ho gaya hai.\n\n"
                f"📋 *Inquiry ID: {inquiry_id}*\n\n"
                f"Aapki requirement record kar li gayi hai aur hamari Sales Team ko forward kar di gayi hai. "
                f"Hamare sales executive physically sample aur warehouse stock verify karke aapse jaldi sampark karenge."
            )
        else:
            ack_msg = (
                f"Ji {salutation}, aapka button sample photo humein prapt ho gaya hai.\n\n"
                f"📋 *Inquiry ID: {inquiry_id}*\n\n"
                f"Abhi hamara office closed hai (Office Timing: Mon-Sat, 9:30 AM to 7:00 PM IST). "
                f"Aapki inquiry register kar li gayi hai. Kal subah office open hote hi hamari sales team physically stock verify karke aapse sampark karegi."
            )

        # Conversational missing details collection (One Question at a Time)
        has_qty = bool(session.get("quantity") and int(session.get("quantity") or 0) > 0)
        has_company = bool(session.get("company"))
        has_city = bool(session.get("city"))

        if not has_qty:
            ack_msg += "\n\n👉 Aapko is button ki lagbhag kitni quantity (Gross me) required hogi?"
            session["waiting_for_detail"] = "quantity"
            session["inquiry_status"] = "COLLECTING_DETAILS"
        elif not has_company or not has_city:
            ack_msg += "\n\n👉 Kripya apni Company / Firm ka naam aur City share kar dijiye taaki formal estimate taiyaar kiya ja sake."
            session["waiting_for_detail"] = "company_city"
            session["inquiry_status"] = "COLLECTING_DETAILS"
        else:
            ack_msg += f"\n\n✅ Details on Record: {session.get('quantity')} Gross | {session.get('company')}, {session.get('city')}."
            session["waiting_for_detail"] = None
            session["inquiry_status"] = "READY_FOR_SALES"

        # 8. Save the inquiry persistently BEFORE claiming it was forwarded
        full_notes = f"{caption or 'Buyer button sample'} | Internal CV: {internal_cv_notes}"
        db.save_inquiry_with_photo(
            inquiry_id=inquiry_id,
            phone=from_phone,
            buyer_name=contact_name,
            photo_b64=b64_img,
            notes=full_notes,
            crm_status="New Inquiry - Pending Sales Assignment",
            company=session.get("company", ""),
            city=session.get("city", ""),
            quantity=session.get("quantity") or 0,
            product_category=mat_det + " Button",
            urgency=session.get("urgency", "NORMAL"),
            inquiry_status=session.get("inquiry_status", "COLLECTING_DETAILS"),
            summary=f"Inquiry {inquiry_id} for {mat_det} button ({session.get('quantity') or 'Qty TBD'} Gross) - {session.get('company') or 'Customer'}",
            next_action="Collect missing details" if session.get("inquiry_status") == "COLLECTING_DETAILS" else "Warehouse stock check"
        )

        inq_entry = {
            "id": inquiry_id,
            "timestamp": ist_now.strftime("%Y-%m-%d %H:%M:%S"),
            "buyer_name": contact_name,
            "phone": from_phone,
            "photo_b64": b64_img,
            "matched_sku": best_sku or "Custom / Non-Catalog",
            "matched_name": (get_item_by_sku(best_sku) or {}).get("name", "Custom Button Development") if best_sku else "Custom Button Development",
            "matched_size": (get_item_by_sku(best_sku) or {}).get("size_ligne", "") if best_sku else "",
            "quantity": session.get("quantity") or 0,
            "company": session.get("company", ""),
            "city": session.get("city", ""),
            "status": "New Inquiry - Pending Sales Assignment",
            "crm_status": "New Inquiry - Pending Sales Assignment",
            "notes": full_notes,
            "human_takeover": session.get("human_takeover", 0),
            "assigned_salesman": session.get("assigned_salesman", "Unassigned")
        }
        existing_idx = next((i for i, x in enumerate(live_whatsapp_inquiries) if x.get("phone") == from_phone), None)
        if existing_idx is not None:
            live_whatsapp_inquiries.pop(existing_idx)
        live_whatsapp_inquiries.insert(0, inq_entry)
        save_live_inquiries()

        log_chat_event(from_phone, contact_name, "buyer", "image", caption or "📷 [Sample Button Photo Sent]", photo_b64=b64_img, sku=best_sku)

        # Send truthful acknowledgement (ZERO automatic catalog product photos sent)
        send_whatsapp_text(from_phone, ack_msg, contact_name)
        save_buyer_session(from_phone, session)
        db.update_inbound_message_status(msg_id, "COMPLETED")
        print(f"📤 Sent Sales Intake Acknowledgement ({inquiry_id}) to {from_phone}")
        return

    # ---------------- CASE 2: BUYER SENT A TEXT MESSAGE ----------------
    elif msg_type == "text":
        text_body = msg.get("text", {}).get("body", "").strip()
        lower_text = text_body.lower()
        print(f"💬 [INCOMING TEXT] From: {from_phone} | Message: '{text_body}'")
        log_chat_event(from_phone, contact_name, "buyer", "text", text_body)

        # ---------------- STEP 0: CONVERSATIONAL MISSING DETAILS HANDLER ----------------
        slots = extract_buyer_slots(text_body, session)

        # 0.1 AI IDENTITY TRANSPARENCY QUERY
        if slots.get("is_identity_query"):
            ident_reply = (
                f"Ji bilkul {salutation}, main ABC Buttons ka 24×7 AI Sales Assistant hoon. "
                f"Meri zimmedari aapki button requirements note karke hamari Sales Team ko connect karwana hai, "
                f"taaki aapko accurate stock availability aur best wholesale pricing mil sake.\n\n"
                f"Batayein sir, aaj aapko kis type ke buttons ki requirement hai?"
            )
            send_whatsapp_text(from_phone, ident_reply, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.2 IMMEDIATE PRICE INQUIRY HANDLING (Respectful Deferral to Sales Team)
        if slots.get("is_price_query") and not session.get("waiting_for_similar_approval") and not session.get("waiting_for_custom_mfg_qty"):
            session["inquiry_status"] = "QUOTATION_PENDING"
            has_qty = bool(session.get("quantity") and int(session.get("quantity") or 0) > 0)
            has_comp = bool(session.get("company"))
            has_city = bool(session.get("city"))
            
            price_deferral = (
                f"Ji bilkul {salutation}! ABC Buttons par hum wholesale volume pricing offer karte hain, "
                f"jo button ke material, size (Ligne) aur required quantity (Gross) par depend karti hai.\n\n"
                f"Hamare Sales Team physically sample verify karke sabse competitive best wholesale quote aapse share karenge."
            )
            if not session.get("has_photo") and not session.get("matched_sku"):
                price_deferral += "\n\n👉 Kya aapke paas sample button ki photo hai, ya aap required button ka naam share kar sakte hain?"
            elif not has_qty:
                price_deferral += "\n\n👉 Aapko is design mein lagbhag kitni Quantity (Gross mein) chahiye hogi?"
                session["waiting_for_detail"] = "quantity"
            elif not has_comp or not has_city:
                price_deferral += "\n\n👉 Kripya apni Company / Firm ka naam aur City bata dijiye taaki formal quote taiyaar kiya ja sake."
                session["waiting_for_detail"] = "company_city"
            else:
                price_deferral += f"\n\n📋 Inquiry ID: {session.get('active_inquiry_id') or 'INQ-PENDING'}\nSales Team aapse jald hi official quotation ke sath sampark karegi."
            
            send_whatsapp_text(from_phone, price_deferral, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.3 READY STOCK INQUIRY (Physical Godown Check Deferral)
        if slots.get("is_stock_query") and not session.get("waiting_for_similar_approval") and not session.get("waiting_for_custom_mfg_qty"):
            session["inquiry_status"] = "STOCK_CHECK_PENDING"
            has_qty = bool(session.get("quantity") and int(session.get("quantity") or 0) > 0)
            has_comp = bool(session.get("company"))
            
            stock_deferral = (
                f"Ji {salutation}, Central Godown (New Delhi) mein daily stock dispatch hota rehta hai, "
                f"isliye hamari Sales Team physically warehouse stock verify karke aapko accurate ready quantity confirm karegi."
            )
            if not session.get("has_photo") and not session.get("matched_sku"):
                stock_deferral += "\n\n👉 Aapko kis design ya material ke buttons ka stock check karwana hai? Sample photo yahan share kar dijiye."
            elif not has_qty:
                stock_deferral += "\n\n👉 Aapko lagbhag kitni quantity (Gross mein) ki zaroorat rahegi?"
                session["waiting_for_detail"] = "quantity"
            elif not has_comp:
                stock_deferral += "\n\n👉 Kripya apni Company aur City ka naam share kar dijiye."
                session["waiting_for_detail"] = "company_city"
            else:
                stock_deferral += f"\n\n📋 Inquiry ID: {session.get('active_inquiry_id') or 'INQ-PENDING'}\nSales Team live stock check karke aapko WhatsApp par update karegi."

            send_whatsapp_text(from_phone, stock_deferral, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.4 SIMILAR SAMPLES / SWATCH CARD REQUEST
        if slots.get("is_sample_request"):
            session["sample_required"] = 1
            session["inquiry_status"] = "SAMPLE_REVIEW"
            sample_reply = (
                f"Ji bilkul {salutation}, hamari Sales Team ke paas is design ke physical samples, running shade cards aur digital swatches uplabdh hain.\n\n"
                f"Humne sample request Sales Team ko mark kar di hai. Team aapse sample coordination aur dispatch ke liye sampark karegi."
            )
            if not session.get("company") or not session.get("city"):
                sample_reply += "\n\n👉 Kripya apna delivery City / Company details bata dijiye taaki sample dispatch plan kiya ja sake."
                session["waiting_for_detail"] = "company_city"
            send_whatsapp_text(from_phone, sample_reply, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.5 CUSTOM MANUFACTURING REQUEST
        if slots.get("is_custom_mfg") and not session.get("waiting_for_custom_mfg_qty"):
            session["inquiry_status"] = "SAMPLE_REVIEW"
            custom_reply = (
                f"Ji bilkul {salutation}! Hum custom button manufacturing, brand logo laser engraving aur custom dyeing (DTM) karte hain.\n\n"
                f"• Minimum Order Quantity (MOQ): Samanyatah 500 Gross rehti hai.\n"
                f"• Production Lead Time: 7-10 working days.\n\n"
                f"Sales Team aapke design ki factory feasibility confirm karegi. Aapko lagbhag kitni quantity required hogi?"
            )
            session["waiting_for_custom_mfg_qty"] = True
            send_whatsapp_text(from_phone, custom_reply, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.6 DYNAMIC QUANTITY CORRECTION & ACKNOWLEDGEMENT
        if slots.get("is_qty_correction") and slots.get("quantity"):
            old_qty = session.get("quantity")
            new_qty = slots["quantity"]
            session["quantity"] = new_qty
            session["customer_required_quantity"] = new_qty
            
            with db.get_db_connection() as conn:
                conn.execute("UPDATE live_inquiries SET quantity = ? WHERE phone = ?", (new_qty, db.normalize_phone(from_phone)))
            for item in live_whatsapp_inquiries:
                if item.get("phone") == from_phone:
                    item["quantity"] = new_qty
                    break
            save_live_inquiries()

            has_comp = bool(session.get("company"))
            has_city = bool(session.get("city"))
            
            corr_ack = f"Samajh gaya ji! {f'{old_qty} Gross ke bajaye ' if old_qty and old_qty != new_qty else ''}*{new_qty:,} Gross* update kar diya gaya hai."
            if not has_comp or not has_city:
                corr_ack += "\n\n👉 Kripya apni Company / Firm ka naam aur City bata dijiye taaki formal quote taiyaar kiya ja sake."
                session["waiting_for_detail"] = "company_city"
            else:
                corr_ack += f"\n\nUpdated requirement (*{new_qty:,} Gross* | {session.get('company')}, {session.get('city')}) Sales Team ko notify kar di gayi hai."
                session["waiting_for_detail"] = None
                session["inquiry_status"] = "READY_FOR_SALES"

            send_whatsapp_text(from_phone, corr_ack, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.7 MULTI-SLOT ALL-IN-ONE MESSAGE EXTRACTION
        if slots.get("company") and slots.get("city") and slots.get("quantity"):
            extracted_comp = slots["company"]
            extracted_city = slots["city"]
            extracted_qty = slots["quantity"]
            
            session["company"] = extracted_comp
            session["city"] = extracted_city
            session["quantity"] = extracted_qty
            session["customer_required_quantity"] = extracted_qty
            session["waiting_for_detail"] = None
            if slots.get("urgency"):
                session["urgency"] = slots["urgency"]
            if slots.get("product_category"):
                session["product_category"] = slots["product_category"]
            if slots.get("size"):
                session["matched_size"] = slots["size"]

            import datetime, random
            utc_now = datetime.datetime.now(datetime.timezone.utc)
            ist_now = utc_now + datetime.timedelta(hours=5, minutes=30)
            inq_id_prefix = f"INQ-{ist_now.strftime('%Y%m%d')}"
            active_inq_id = session.get("active_inquiry_id")
            if not active_inq_id or not str(active_inq_id).startswith(inq_id_prefix):
                inquiry_id = f"{inq_id_prefix}-{random.randint(1000, 9999)}"
                session["active_inquiry_id"] = inquiry_id
            else:
                inquiry_id = active_inq_id

            session["inquiry_status"] = "READY_FOR_SALES"
            summary_txt = f"{extracted_comp} ({extracted_city}) - {extracted_qty} Gross {session.get('product_category', 'Buttons')}"
            session["summary"] = summary_txt
            session["next_action"] = "Physically check warehouse godown stock & quote"

            db.save_inquiry_with_photo(
                inquiry_id=inquiry_id,
                phone=from_phone,
                buyer_name=contact_name,
                photo_b64="",
                notes=f"All-in-one inquiry: {text_body}",
                crm_status="Ready for Sales - Details Complete",
                company=extracted_comp,
                city=extracted_city,
                quantity=extracted_qty,
                product_category=session.get("product_category", ""),
                urgency=session.get("urgency", "NORMAL"),
                inquiry_status="READY_FOR_SALES",
                summary=summary_txt,
                next_action=session.get("next_action", "")
            )

            size_txt = f" ({session.get('matched_size')})" if session.get('matched_size') else ""
            cat_txt = session.get('product_category', 'Buttons')
            all_reply = (
                f"Ji bohot dhanyawad {salutation}! Aapki complete requirement note kar li gayi hai:\n\n"
                f"📋 *Inquiry ID: {inquiry_id}*\n"
                f"• Company: {extracted_comp}, {extracted_city}\n"
                f"• Item: {cat_txt}{size_txt} — *{extracted_qty:,} Gross*\n"
                f"• Priority: {session.get('urgency', 'NORMAL')}\n\n"
                f"Hamari Sales Team priority par warehouse stock verify karke jald hi aapse official quotation ke sath sampark karegi."
            )
            send_whatsapp_text(from_phone, all_reply, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.8 CATEGORY INQUIRY (e.g. "Agoya buttons", "River shell buttons")
        if not session.get("has_photo") and not session.get("quantity") and slots.get("product_category") and not any(w in lower_text for w in ["gross", "order", "dhanyawad", "ok"]):
            cat_name = slots["product_category"]
            session["product_category"] = cat_name
            sku_map = {
                "Agoya Shell Button": "ABC-136",
                "River Shell Button": "ABC-139",
                "Trocas Shell Button": "ABC-141",
                "MOP Shell Button": "ABC-137",
                "Polyester Button": "ABC-POLY-18L-10",
                "Horn Button": "ABC-HRN-24L-06"
            }
            if cat_name in sku_map and not session.get("matched_sku"):
                session["matched_sku"] = sku_map[cat_name]
                session["matched_name"] = cat_name
                session["last_active_sku"] = sku_map[cat_name]

            cat_prompt = (
                f"Ji bilkul {salutation}, {cat_name}s hamara regular running category hai.\n\n"
                f"👉 Kya aapke paas required button ka sample photo hai? Aap photo yahan share kar sakte hain, "
                f"ya agar aapko specific size (jaise 14L ya 18L) mein requirement hai toh batayein."
            )
            send_whatsapp_text(from_phone, cat_prompt, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 0.9 WARM INITIAL GREETING AS 24x7 AI SALES ASSISTANT
        is_greeting = lower_text in ["hi", "hello", "namaste", "hey", "hlo", "hi sir", "hello sir", "namaskar"]
        if is_greeting and not session.get("has_photo") and not session.get("quantity") and session.get("history_count", 0) <= 1:
            welcome_msg = (
                f"Namaste {salutation}! ABC Buttons mein aapka swagat hai. Main ABC Buttons ka 24×7 AI Sales Assistant hoon.\n\n"
                f"Garments ke liye kisi bhi type ke buttons (Agoya, River Shell, Trocas, MOP, Polyester, Horn) chahiye hon, "
                f"toh aap button ki photo ya requirements yahan share kar sakte hain.\n\n"
                f"Batayein sir, aaj aapko kis type ke buttons ki requirement hai?"
            )
            send_whatsapp_text(from_phone, welcome_msg, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

        # 1. Missing Quantity Handler (When bot prompted for missing quantity on sample intake)
        is_qty_reply = (session.get("waiting_for_detail") == "quantity" and bool(re.search(r'\b\d+\b', lower_text)))
        if is_qty_reply and not session.get("waiting_for_similar_approval") and not session.get("waiting_for_custom_mfg_qty") and not any(w in lower_text for w in ["ki jagah", "badal", "replace"]):
            num_m = re.search(r'\b(\d+)\b', lower_text)
            if num_m:
                qty_val = int(num_m.group(1))
                session["quantity"] = qty_val
                # Update DB and live feed
                with db.get_db_connection() as conn:
                    conn.execute("UPDATE live_inquiries SET quantity = ? WHERE phone = ?", (qty_val, db.normalize_phone(from_phone)))
                for item in live_whatsapp_inquiries:
                    if item.get("phone") == from_phone:
                        item["quantity"] = qty_val
                        break
                save_live_inquiries()

                has_comp = bool(session.get("company"))
                has_city = bool(session.get("city"))
                if not has_comp or not has_city:
                    session["waiting_for_detail"] = "company_city"
                    reply = (
                        f"Ji dhanyawad {salutation}! Aapki *{qty_val:,} Gross* requirement record ho gayi hai.\n\n"
                        f"👉 Kripya apni Company / Firm ka naam aur City bata dijiye taaki formal quote taiyaar kiya ja sake."
                    )
                else:
                    session["waiting_for_detail"] = None
                    session["inquiry_status"] = "READY_FOR_SALES"
                    summary_txt = f"Inquiry for {session.get('company')} ({session.get('city')}) - {qty_val} Gross"
                    session["summary"] = summary_txt
                    session["next_action"] = "Physically check warehouse godown stock & quote"
                    with db.get_db_connection() as conn:
                        conn.execute("UPDATE live_inquiries SET inquiry_status = 'READY_FOR_SALES', summary = ?, next_action = ? WHERE phone = ?", (summary_txt, session["next_action"], db.normalize_phone(from_phone)))
                    reply = (
                        f"Ji dhanyawad {salutation}! Aapki requirement (*{qty_val:,} Gross* | {session.get('company')}, {session.get('city')}) record ho chuki hai.\n\n"
                        f"Hamare sales executive physically warehouse stock verify karke jald hi aapse sampark karenge."
                    )
                send_whatsapp_text(from_phone, reply, contact_name)
                save_buyer_session(from_phone, session)
                db.update_inbound_message_status(msg_id, "COMPLETED")
                return

        # 2. Missing Company / City Handler
        if session.get("waiting_for_detail") == "company_city" and not any(w in lower_text for w in ["rate", "price", "catalog", "sample", "urgent", "kab", "kisko", "nahi"]):
            parts = [p.strip() for p in re.split(r'[,/-]|\bfrom\b|\bmein\b|\bse\b', text_body, flags=re.IGNORECASE) if p.strip()]
            company_str = parts[0] if parts else text_body.strip()
            city_str = parts[1] if len(parts) > 1 else ""
            session["company"] = company_str
            if city_str:
                session["city"] = city_str
            session["waiting_for_detail"] = None
            session["inquiry_status"] = "READY_FOR_SALES"
            summary_txt = f"Inquiry for {company_str} ({city_str}) - {session.get('quantity') or 'Qty TBD'} Gross"
            session["summary"] = summary_txt
            session["next_action"] = "Physically check warehouse godown stock & quote"

            with db.get_db_connection() as conn:
                conn.execute("UPDATE live_inquiries SET company = ?, city = ?, inquiry_status = 'READY_FOR_SALES', summary = ?, next_action = ? WHERE phone = ?", (company_str, city_str, summary_txt, session["next_action"], db.normalize_phone(from_phone)))
            for item in live_whatsapp_inquiries:
                if item.get("phone") == from_phone:
                    item["company"] = company_str
                    item["city"] = city_str
                    item["inquiry_status"] = "READY_FOR_SALES"
                    break
            save_live_inquiries()

            qty_part = f" for *{session.get('quantity'):,} Gross*" if session.get("quantity") else ""
            reply = (
                f"Ji bohot dhanyawad {salutation}! Aapki details (*{company_str}*{f', {city_str}' if city_str else ''}){qty_part} note kar li gayi hain.\n\n"
                f"Hamare sales executive physically warehouse stock & pricing check karke aapse isi WhatsApp number par sampark karenge."
            )
            send_whatsapp_text(from_phone, reply, contact_name)
            save_buyer_session(from_phone, session)
            db.update_inbound_message_status(msg_id, "COMPLETED")
            return

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
            
            # If quantity is not yet mentioned in this message, send conversational inquiry (NO catalog images auto-sent)
            if not has_qty_in_msg:
                reply_text = (
                    f"Ji {salutation}, {item['name']} hamara running catalog item hai.\n\n"
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

# ----------------- SALES TEAM ACTIONS (4 QUICK ACTIONS) -----------------

def send_verified_stock_and_photo(phone: str, sku: str, warehouse_stock: int = 0, salesperson_name: str = "Sales Team", custom_note: str = "") -> dict:
    """Action 1: Salesperson physically checks warehouse stock and sends verified photo + stock details to customer on WhatsApp."""
    cat_item = get_item_by_sku(sku) or {}
    p_img_path = os.path.join(CAT_DIR, f"{sku}.jpg")
    img_bytes = None
    if os.path.exists(p_img_path):
        with open(p_img_path, "rb") as fp:
            img_bytes = fp.read()
            
    item_name = cat_item.get("name", "Shell Button")
    size_str = cat_item.get("size_ligne", "")
    stock_to_show = warehouse_stock if warehouse_stock > 0 else cat_item.get("stock_gross", 0)
    
    caption = (
        f"🏆 *Verified Catalog Design: {item_name}*\n"
        f"• SKU: {sku}\n"
        f"• Size: {size_str} • Specification: {cat_item.get('holes', '2-Hole')}\n"
        f"• Warehouse Physical Stock: *{stock_to_show:,} Gross* (Physically Verified)\n\n"
        f"Ye sample hamare warehouse godown me ready available hai. "
        f"{custom_note if custom_note else 'Aapki required quantity dispatch ke liye confirm kar sakte hain.'}\n\n"
        f"— Verified by: {salesperson_name} (ABC Buttons)"
    )
    if img_bytes:
        res = send_whatsapp_image(phone, img_bytes, caption, sku=sku, product_name=item_name, size_opts=size_str)
    else:
        res = send_whatsapp_text(phone, caption)
        
    db.update_inquiry_crm_meta(phone, action_taken=f"Stock Check Verified ({sku}, {stock_to_show} Gr)", crm_status="Stock Confirmed - Ready to Quote")
    return res

def send_similar_options_pitch(phone: str, sku_list: list, salesperson_name: str = "Sales Team") -> dict:
    """Action 2: Salesperson offers similar options from ready stock with buyer permission request."""
    alts = [get_item_by_sku(s) for s in sku_list[:2]]
    alts = [a for a in alts if a] or SAMPLE_CATALOG[:2]
    
    intro_text = (
        f"Namaste sir, aapka sample dekh kar hamari Sales Team ({salesperson_name}) ne ready warehouse stock se "
        f"ye milte-julte (similar) running options select kiye hain:\n\n"
        f"Kya hum inke photos aur specifications aapse share karein?"
    )
    res = send_whatsapp_text(phone, intro_text)
    
    for idx, alt_item in enumerate(alts, 1):
        alt_path = os.path.join(CAT_DIR, f"{alt_item['sku']}.jpg")
        if os.path.exists(alt_path):
            with open(alt_path, "rb") as afp:
                alt_bytes = afp.read()
            alt_caption = (
                f"🔘 *Similar Option {idx}: {alt_item['name']}*\n"
                f"• SKU: {alt_item['sku']} • Size: {alt_item.get('size_ligne', '')}\n"
                f"• Ready Godown Stock: *{alt_item.get('stock_gross', 0):,} Gross*\n"
                f"• Recommended by: {salesperson_name}"
            )
            send_whatsapp_image(phone, alt_bytes, alt_caption, sku=alt_item["sku"], product_name=alt_item["name"])
            
    db.update_inquiry_crm_meta(phone, action_taken=f"Similar Options Sent ({', '.join([a['sku'] for a in alts])})", crm_status="Similar Options Offered")
    return res

def send_custom_mfg_feasibility(phone: str, moq: int = 500, lead_days: int = 10, salesperson_name: str = "Sales Team") -> dict:
    """Action 3: Salesperson sends factory custom manufacturing feasibility."""
    msg = (
        f"Namaste sir, hamari factory technical team ne aapka sample photo check kiya hai.\n\n"
        f"🏭 *Factory Custom Manufacturing Feasibility:*\n"
        f"• Exact Design & Finish: Possible (Same material & export polish)\n"
        f"• Minimum Order Quantity (MOQ): *{moq:,} Gross*\n"
        f"• Production & Delivery Time: *{lead_days}-12 Days*\n\n"
        f"Agar aap custom production proceed karna chahein, toh hum counter-sample taiyaar karwa sakte hain.\n\n"
        f"— {salesperson_name} (ABC Buttons Production Desk)"
    )
    res = send_whatsapp_text(phone, msg)
    db.update_inquiry_crm_meta(phone, action_taken=f"Factory Feasibility Sent (MOQ {moq} Gr)", crm_status="Custom Mfg Offered")
    return res

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
    """Synchronizes Human Takeover, Salesperson, Deal Stage, Company, City, and Actions from Streamlit Cloud to Render in real-time."""
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
            crm_status=body.get("crm_status"),
            action_taken=body.get("action_taken"),
            company=body.get("company"),
            city=body.get("city"),
            quantity=body.get("quantity")
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
