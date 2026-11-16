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
    send_whatsapp_text,
    send_whatsapp_image,
    download_whatsapp_media
)

app = FastAPI(title="ABC Buttons WhatsApp Webhook Server")

VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "abc_buttons_secret_2026")
CAT_DIR = os.path.join(os.path.dirname(__file__), "catalog_images")

# In-memory customer context session store
buyer_sessions = {}

def get_buyer_session(phone: str) -> dict:
    if phone not in buyer_sessions:
        buyer_sessions[phone] = {
            "has_photo": False,
            "matched_sku": None,
            "matched_name": None,
            "matched_size": None,
            "quantity": None,
            "has_address": False,
            "history_count": 0,
            "waiting_for_similar_permission": False,
            "waiting_for_similar_approval": False,
            "suggested_alternatives": [],
            "waiting_for_custom_mfg_qty": False
        }
    return buyer_sessions[phone]

# Message deduplication cache
processed_msg_ids = set()

# Real-time event log for debugging
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

async def process_incoming_whatsapp_message(value: dict):
    """
    Stateful Customer Context Aware WhatsApp Message Handler.
    Enforces ABC Buttons: Commercial, Sales & Customer Handling Rules (Rules 1.1 to 7.0).
    """
    contacts = value.get("contacts", [])
    contact_name = "Sir"
    if contacts:
        contact_name = contacts[0].get("profile", {}).get("name", "Sir")
        
    messages = value.get("messages", [])
    if not messages:
        return
        
    msg = messages[0]
    msg_id = msg.get("id")
    if msg_id in processed_msg_ids:
        return
    processed_msg_ids.add(msg_id)
    if len(processed_msg_ids) > 1000:
        processed_msg_ids.clear()
        
    from_phone = msg.get("from")
    msg_type = msg.get("type")
    first_name = contact_name.split()[0] if contact_name and contact_name != "Buyer" else "Sir"
    salutation = f"{first_name} ji" if first_name not in ["Sir"] else "Sir"
    
    session = get_buyer_session(from_phone)
    session["history_count"] += 1
    
    # ---------------- CASE 1: BUYER SENT A PHOTO ----------------
    if msg_type == "image":
        media_id = msg.get("image", {}).get("id")
        caption = msg.get("image", {}).get("caption", "")
        print(f"📸 [INCOMING IMAGE] From: {from_phone} | Media ID: {media_id} | Caption: {caption}")
        
        try:
            # 1. Download image bytes from Meta
            img_bytes = download_whatsapp_media(media_id)
            print(f"✅ Downloaded {len(img_bytes)} bytes from Meta")
            
            # 2. Run AI Vision Matcher
            res = analyze_button_or_fabric_image(img_bytes, caption)
            status = res.get("match_status", "MATCH_FOUND")
            best_sku = res.get("best_match_sku")
            print(f"🔍 AI Result: Status={status} | SKU={best_sku}")
            
            # 3. Handle non-button images
            if status == "NO_BUTTON_DETECTED" or not res.get("is_button", True):
                send_whatsapp_text(
                    from_phone,
                    f"Ji {salutation}, aapne jo photo share ki hai usme button clear nahi dikh raha hai. "
                    f"Kripya button ki ek close-up photo achhi roshni me bhejiye, hum turant ready stock check karke batate hain."
                )
                return
                
            # 4. RULE: EXACT MATCH ONLY (अगर एग्जैक्ट बटन नहीं है, तो सिमिलर दिखाने की परमिशन माँगें)
            if status == "NOT_IN_CATALOG" or not best_sku:
                session["has_photo"] = True
                session["waiting_for_similar_permission"] = True
                
                # Check closest similar running items in catalog
                alts = SAMPLE_CATALOG[:2]
                session["suggested_alternatives"] = [a["sku"] for a in alts]
                
                # Polite permission request
                not_in_cat_msg = (
                    f"Ji {salutation}, aapka sample dekh liya hai.\n\n"
                    f"Ye exact button design abhi hamare ready stock me available nahi hai.\n\n"
                    f"Kya main aapko isse milte-julte (similar) designs ke buttons dikha doon?"
                )
                send_whatsapp_text(from_phone, not_in_cat_msg)
                print(f"📤 Asked permission for similar designs to {from_phone}")
                return
                
            # 5. Handle Verified EXACT Catalog Match
            matched_item = get_item_by_sku(best_sku) or SAMPLE_CATALOG[0]
            session["has_photo"] = True
            session["matched_sku"] = matched_item["sku"]
            session["matched_name"] = matched_item["name"]
            session["matched_size"] = matched_item.get("size_ligne", "")
            session["waiting_for_similar_permission"] = False
            session["waiting_for_similar_approval"] = False
            
            # Auto-save latest WhatsApp inquiry for Tab 5 Proforma 1-Click
            try:
                import datetime
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
            
            # Send ONLY THE EXACT MATCHING BUTTON (No 3 options, Strictly exact match!)
            p_img_path = os.path.join(CAT_DIR, f"{matched_item['sku']}.jpg")
            if os.path.exists(p_img_path):
                with open(p_img_path, "rb") as fp:
                    p_img_bytes = fp.read()
                best_caption = (
                    f"🏆 *Exact Matching Stock: {matched_item['name']}*\n"
                    f"• Size: {matched_item.get('size_ligne', '')} • {matched_item.get('holes', '')}\n"
                    f"• Ready Godown Stock: *{matched_item.get('stock_gross', 0):,} Gross* ({matched_item.get('stock_gross', 0)*144:,} Pcs)\n"
                    f"• Stock Status: Available in Central Godown\n\n"
                    f"Same quality aur 100% genuine export finish ready mil jayegi."
                )
                send_whatsapp_image(from_phone, p_img_bytes, best_caption)
                await asyncio.sleep(1.2)
                
            # ONE QUESTION AT A TIME RULE: Ask ONLY for required quantity
            if not session.get("quantity"):
                cta_text = (
                    "Ji sir, aapke share kiye hue sample ka exact matching stock hamare paas available hai.\n\n"
                    "Aapko kitni quantity chahiye?"
                )
            else:
                cta_text = (
                    f"Ji sir, aapka sample identify ho gaya hai. "
                    f"Aapki {session['quantity']} Gross requirement ke according hum quotation prepare kar rahe hain."
                )
            send_whatsapp_text(from_phone, cta_text)
            print(f"📤 Sent Exact Match and Quantity Question to {from_phone}")
            
        except Exception as e:
            print(f"❌ Error processing image from {from_phone}: {e}")
            send_whatsapp_text(
                from_phone,
                f"Ji {salutation}, aapka photo sample prapt hua hai. Hamare sales representative turant isko verify karke aapse sampark karenge."
            )

    # ---------------- CASE 2: BUYER SENT A TEXT MESSAGE ----------------
    elif msg_type == "text":
        text_body = msg.get("text", {}).get("body", "").strip()
        lower_text = text_body.lower()
        print(f"💬 [INCOMING TEXT] From: {from_phone} | Message: '{text_body}'")

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

            # Check if customer approved Option 1 or Option 2
            selected_alt_sku = None
            if "option 1" in lower_text or "pehla" in lower_text or "136" in lower_text or ("1" in lower_text and "2" not in lower_text):
                selected_alt_sku = session.get("suggested_alternatives", ["ABC-136"])[0] if session.get("suggested_alternatives") else "ABC-136"
            elif "option 2" in lower_text or "doosra" in lower_text or "137" in lower_text or "139" in lower_text or ("2" in lower_text and "1" not in lower_text):
                selected_alt_sku = session.get("suggested_alternatives", ["ABC-136", "ABC-137"])[1] if len(session.get("suggested_alternatives", [])) > 1 else "ABC-137"
            
            if selected_alt_sku:
                sel_item = get_item_by_sku(selected_alt_sku) or SAMPLE_CATALOG[0]
                session["matched_sku"] = sel_item["sku"]
                session["matched_name"] = sel_item["name"]
                session["waiting_for_similar_approval"] = False
                
                ack_msg = (
                    f"Ji sir, aapka approval note kar liya hai: *{sel_item['name']}*.\n\n"
                    f"Aapko iski kitni quantity chahiye? Hum turant iska best quotation prepare kar dete hain."
                )
                send_whatsapp_text(from_phone, ack_msg)
                print(f"📤 Customer approved {sel_item['sku']}. Asked for quantity.")
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
            send_whatsapp_text(from_phone, size_update_msg)
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
        
        # Check Option selection
        if "option 1" in lower_text or "136" in lower_text or "agoya" in lower_text:
            session["matched_sku"] = "ABC-136"
            session["matched_name"] = "ABC-136 Agoya Shell Button"
        elif "option 2" in lower_text or "139" in lower_text or "river" in lower_text:
            session["matched_sku"] = "ABC-139"
            session["matched_name"] = "ABC-139 Natural White River Shell Button"
        elif "option 3" in lower_text or "137" in lower_text or "caramel" in lower_text or "gold" in lower_text:
            session["matched_sku"] = "ABC-137"
            session["matched_name"] = "ABC-137 Caramel Gold MOP Shell Button"
        elif "141" in lower_text or "smoky" in lower_text:
            session["matched_sku"] = "ABC-141"
            session["matched_name"] = "ABC-141 Smoky Grey River Shell Button"
        elif "142" in lower_text or "turquoise" in lower_text or "teal" in lower_text:
            session["matched_sku"] = "ABC-142"
            session["matched_name"] = "ABC-142 Turquoise Blue Tinted Shell Button"

        # If quantity stated in this message -> record in session
        if has_qty_in_msg:
            if gross_match:
                session["quantity"] = int(gross_match.group(1))
            elif pcs_match:
                session["quantity"] = max(1, round(int(pcs_match.group(1)) / 144))
            elif general_num:
                val = int(general_num.group(1))
                session["quantity"] = round(val / 144) if val > 1000 else val

            try:
                import datetime
                ds_path = os.path.join(os.path.dirname(__file__), "data_store.json")
                if os.path.exists(ds_path):
                    with open(ds_path, "r", encoding="utf-8") as fp:
                        ds = json.load(fp)
                    ds["latest_whatsapp_inquiry"] = {
                        "buyer_name": contact_name,
                        "phone": from_phone,
                        "sku": session.get("matched_sku", "ABC-137"),
                        "qty_gross": session["quantity"],
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    with open(ds_path, "w", encoding="utf-8") as fp:
                        json.dump(ds, fp, indent=2)
            except Exception as e:
                print(f"Error saving latest inquiry: {e}")

            if session.get("has_photo"):
                reply = "Ji sir, aapki requirement samajh aa gayi hai. Hum iske according quotation check karte hain."
                send_whatsapp_text(from_phone, reply)
                return
            else:
                reply = "Ji sir, aap button ka sample ya photo share kar dijiye, taaki hum sahi product identify kar sakein."
                send_whatsapp_text(from_phone, reply)
                return

        # Courtesy & Acknowledgement
        elif any(lower_text.strip() == w for w in [
            "ok", "okay", "ok ji", "theek hai", "thik hai", "thanks", "thank you", 
            "shukriya", "dhanyawad", "done", "ji", "sure", "alright", "great", 
            "perfect", "done sir", "ok sir", "theek hai sir", "k", "kk", "ok done", "theek h"
        ]):
            if session.get("has_address") and not session.get("quantity"):
                send_whatsapp_text(
                    from_phone,
                    f"Ji bilkul {salutation}! Sample dispatch ki details aapse share kar denge. Dhanyawad sir! 🙏"
                )
            elif session.get("quantity"):
                send_whatsapp_text(
                    from_phone,
                    f"Ji bilkul {salutation}! Quotation ready hote hi hum turant aapse share karenge. Dhanyawad sir! 🙏"
                )
            else:
                send_whatsapp_text(
                    from_phone,
                    f"Ji bilkul {salutation}! Dhanyawad. Koi bhi requirement ya query ho toh zaroor batayein sir. 🙏"
                )
            return
            
        # General greeting / assistance
        else:
            if session.get("has_photo") or session.get("quantity") or session.get("history_count", 0) > 1:
                if session.get("has_photo") and not session.get("quantity"):
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
                elif not session.get("has_photo") and session.get("quantity"):
                    send_whatsapp_text(
                        from_phone,
                        "Ji sir, aap button ka sample ya photo share kar dijiye, taaki hum sahi product identify kar sakein."
                    )
                else:
                    send_whatsapp_text(
                        from_phone,
                        f"Ji {salutation}, batayein sir, aage kya update hai?"
                    )
            else:
                welcome_msg = (
                    "Namaste! ABC Buttons mein aapka swagat hai.\n\n"
                    "Garments ke liye kisi bhi type ke buttons chahiye hon, toh aap button ki photo or design yahan share kar sakte hain.\n\n"
                    "Hum aapko available stock & suitable options check karke bata denge.\n\n"
                    "Batayein sir, aapko kis type ke buttons chahiye?"
                )
                send_whatsapp_text(from_phone, welcome_msg)

# ----------------- WEBHOOK ENDPOINTS -----------------

@app.get("/")
def home():
    return {
        "status": "online",
        "service": "ABC Buttons 24/7 WhatsApp AI Bot",
        "version": "2.2.0",
        "features": [
            "Customer Context Awareness",
            "No Repetition Rule",
            "One Question at a Time",
            "Commercial & Pricing Rules (1.1 - 7.0)",
            "Automatic Buyer Photo Scan",
            "Stock Verification & Rate Assistant"
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
    try:
        payload = await request.json()
        import datetime
        t_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        received_events.append({"time": t_str, "payload": payload})
        print(f"📥 [WEBHOOK ARRIVED at {t_str}] Payload: {json.dumps(payload)[:250]}")
        
        entry = payload.get("entry", [])
        if entry:
            changes = entry[0].get("changes", [])
            if changes:
                value = changes[0].get("value", {})
                if "messages" in value:
                    background_tasks.add_task(process_incoming_whatsapp_message, value)
    except Exception as e:
        print(f"Error handling webhook payload: {e}")
        
    return JSONResponse(content={"status": "received"}, status_code=200)

@app.get("/history")
def get_history():
    return {
        "total_events": len(received_events),
        "recent_events": received_events[-10:]
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("webhook_bot:app", host="0.0.0.0", port=port, reload=False)
