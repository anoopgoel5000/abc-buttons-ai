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
            "history_count": 0
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
    Enforces One Question at a Time Rule, Never Asks Repeated Questions, and remembers all context.
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
                
            # 4. Handle button not in catalog
            if status == "NOT_IN_CATALOG" or not best_sku:
                send_whatsapp_text(
                    from_phone,
                    f"Ji {salutation}, ye specific button design abhi hamare ready catalog stock me active nahi hai. "
                    f"Hum apni production team se baat karke update karte hain ki kya ye custom tayyar kiya ja sakta hai."
                )
                return
                
            # 5. Handle Verified Catalog Match -> Update Session Context
            matched_item = get_item_by_sku(best_sku) or SAMPLE_CATALOG[0]
            session["has_photo"] = True
            session["matched_sku"] = matched_item["sku"]
            session["matched_name"] = matched_item["name"]
            session["matched_size"] = matched_item.get("size_ligne", "")
            
            # Message 1: Primary Match Image + Specs
            p_img_path = os.path.join(CAT_DIR, f"{matched_item['sku']}.jpg")
            if os.path.exists(p_img_path):
                with open(p_img_path, "rb") as fp:
                    p_img_bytes = fp.read()
                best_caption = (
                    f"🏆 *100% Matching Stock: {matched_item['name']}*\n"
                    f"• Size: {matched_item.get('size_ligne', '')} • {matched_item.get('holes', '')}\n"
                    f"• Ready Godown Stock: *{matched_item.get('stock_gross', 0):,} Gross* ({matched_item.get('stock_gross', 0)*144:,} Pcs)\n"
                    f"• Stock Status: Available in Godown\n\n"
                    f"Same quality aur premium export finish ready mil jayegi."
                )
                send_whatsapp_image(from_phone, p_img_bytes, best_caption)
                await asyncio.sleep(1.5)
                
            # Message 2 & 3: Alternative Running Options
            alternatives = get_alternative_skus(best_sku, limit=2)
            for idx, alt_item in enumerate(alternatives, start=2):
                alt_path = os.path.join(CAT_DIR, f"{alt_item['sku']}.jpg")
                if os.path.exists(alt_path):
                    with open(alt_path, "rb") as afp:
                        alt_bytes = afp.read()
                    alt_caption = (
                        f"🔘 *Option {idx}: {alt_item['name']}*\n"
                        f"• Size: {alt_item.get('size_ligne', '')} • {alt_item.get('holes', '')}\n"
                        f"• Ready Stock: *{alt_item.get('stock_gross', 0):,} Gross*\n"
                        f"• Stock Status: Ready Godown Stock"
                    )
                    send_whatsapp_image(from_phone, alt_bytes, alt_caption)
                    await asyncio.sleep(1.5)
                    
            # ONE QUESTION AT A TIME RULE (IDEAL CUSTOMER RESPONSE)
            if not session.get("quantity"):
                cta_text = (
                    "Ji sir, aapke share kiye hue sample ka matching stock hamare paas available hai.\n\n"
                    "Aapko kitni quantity chahiye?"
                )
            else:
                # If quantity already provided earlier
                cta_text = (
                    f"Ji sir, aapka sample identify ho gaya hai. "
                    f"Aapki {session['quantity']} Gross requirement ke according hum quotation check karte hain."
                )
            send_whatsapp_text(from_phone, cta_text)
            print(f"📤 Sent Ideal One-Question-At-A-Time CTA to {from_phone}")
            
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

        # Parse quantity if stated
        gross_match = re.search(r'(\d+)\s*(?:gross|gr)', lower_text)
        pcs_match = re.search(r'(\d+)\s*(?:pcs|pieces)', lower_text)
        cleaned_for_num = re.sub(r'option\s*\d+', '', lower_text) # remove 'option 3'
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

            # Check Situations:
            if session.get("has_photo"):
                # Situation 2: Customer has shared photo and quantity
                reply = "Ji sir, aapki requirement samajh aa gayi hai. Hum iske according quotation check karte hain."
                send_whatsapp_text(from_phone, reply)
                return
            else:
                # Situation 3: Customer has shared quantity but not product design
                reply = "Ji sir, aap button ka sample ya photo share kar dijiye, taaki hum sahi product identify kar sakein."
                send_whatsapp_text(from_phone, reply)
                return

        # Sub-Case B: Address Provided by Buyer
        if any(w in lower_text for w in ["plot", "sector", "phase", "road", "gali", "noida", "gurgaon", "okhla", "delhi", "pin", "near"]):
            session["has_address"] = True
            send_whatsapp_text(
                from_phone,
                f"Ji dhanyawad {salutation}! Delivery address note kar liya hai.\n"
                f"Hamari dispatch team aaj hi sample hanger card courier me nikalwa degi aur tracking details aapse share kar denge sir."
            )
            return

        # Sub-Case C: Sample card inquiry
        if any(w in lower_text for w in ["sample", "card", "hanger", "swatch", "trial", "pcs"]):
            card_path = os.path.join(CAT_DIR, "ABC-SAMPLE-CARD-01.jpg")
            if os.path.exists(card_path):
                with open(card_path, "rb") as cfp:
                    card_bytes = cfp.read()
                card_caption = (
                    f"📦 *ABC Buttons Official Shell Button Sample Hanger Card*\n"
                    f"Isme 14L se 24L tak ke running River Shell, MOP, Agoya aur Trocas ke samples lage hue hain.\n\n"
                    f"Ji {salutation}, aap factory ya office ka delivery address aur pin code share kar dijiye, hum aaj hi sample card courier dispatch karwa denge sir."
                )
                send_whatsapp_image(from_phone, card_bytes, card_caption)
            else:
                send_whatsapp_text(
                    from_phone,
                    f"Ji {salutation}, hamara full range sample card bilkul ready hai. "
                    f"Kripya factory delivery address aur pin code share kar dijiye, hum aaj hi courier dispatch karwa denge sir."
                )
            return
            
        # Sub-Case D: Rate / Pricing Inquiry
        elif any(w in lower_text for w in ["rate", "price", "quotation", "quote", "cost", "bhaav", "paisa", "kitne ka", "charges"]):
            if session.get("has_photo") and session.get("quantity"):
                send_whatsapp_text(
                    from_phone,
                    "Ji sir, aapki requirement samajh aa gayi hai. Hum iske according quotation check karte hain."
                )
            elif session.get("has_photo") and not session.get("quantity"):
                # Situation 1: Has photo, no quantity
                send_whatsapp_text(
                    from_phone,
                    "Ji sir, aapka sample identify ho gaya hai. Aapko kitni quantity chahiye?"
                )
            elif not session.get("has_photo") and session.get("quantity"):
                # Situation 3: Has quantity, no photo
                send_whatsapp_text(
                    from_phone,
                    "Ji sir, aap button ka sample ya photo share kar dijiye, taaki hum sahi product identify kar sakein."
                )
            else:
                # Neither shared
                rate_reply = (
                    "Ji sir, button ka rate uske design, quality aur quantity par depend karta hai.\n\n"
                    "Aap button ki photo ya design share kar dijiye. Saath hi batayein, aapko kitni quantity chahiye?\n\n"
                    "Hum aapko uske according best rate aur quotation bata denge."
                )
                send_whatsapp_text(from_phone, rate_reply)
            return

        # Sub-Case E: Courtesy & Acknowledgement (ok, thanks, theek hai, done)
        elif any(lower_text.strip() == w for w in [
            "ok", "okay", "ok ji", "theek hai", "thik hai", "thanks", "thank you", 
            "shukriya", "dhanyawad", "done", "ji", "sure", "alright", "great", 
            "perfect", "done sir", "ok sir", "theek hai sir", "k", "kk", "ok done", "theek h"
        ]):
            send_whatsapp_text(
                from_phone,
                f"Ji bilkul {salutation}! Jaise hi parcel dispatch hota hai, tracking / docket details aapse share kar denge. Koi bhi nayi requirement ho toh zaroor batayein sir. 🙏"
            )
            return
            
        # Sub-Case F: General greeting / assistance
        else:
            # Rule 4: Conversation Continuity (Never restart or send generic welcome in middle of ongoing chat!)
            if session.get("has_photo") or session.get("quantity") or session.get("history_count", 0) > 1:
                if session.get("has_photo") and not session.get("quantity"):
                    send_whatsapp_text(
                        from_phone,
                        "Ji sir, aapka sample identify ho gaya hai. Aapko kitni quantity chahiye?"
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
                # Brand new customer first-time greeting
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
        "version": "2.1.0",
        "features": [
            "Customer Context Awareness",
            "No Repetition Rule",
            "One Question at a Time",
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
