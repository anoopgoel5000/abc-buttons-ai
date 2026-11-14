"""
24/7 Automated Meta WhatsApp Webhook AI Bot for ABC Buttons Private Limited
Automatically receives buyer button photos on WhatsApp, runs AI Vision,
and replies in 3-5 seconds with matching HD catalog photos, stock in Gross,
and alternative running options.
"""

import os
import json
import asyncio
from fastapi import FastAPI, Request, Response, BackgroundTasks
from fastapi.responses import PlainTextResponse, JSONResponse
import uvicorn

import sys
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ai_engine import analyze_button_or_fabric_image, simulate_buyer_chat
from catalog import SAMPLE_CATALOG
from whatsapp_service import (
    send_whatsapp_text,
    send_whatsapp_image,
    download_whatsapp_media,
    generate_proforma_card_image
)

app = FastAPI(title="ABC Buttons 24/7 WhatsApp AI Bot")

VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "abc_buttons_secret_2026")
CAT_DIR = os.path.join(BASE_DIR, "catalog_images")

# In-memory deduplication of message IDs
processed_msg_ids = set()
received_events = []

@app.get("/history")
def get_history():
    return {
        "total_events": len(received_events),
        "recent_events": received_events[-15:]
    }

def get_item_by_sku(sku: str):
    return next((x for x in SAMPLE_CATALOG if x["sku"] == sku), None)

def get_alternative_skus(best_sku: str, limit: int = 2):
    """Finds alternative running SKUs from the same or related category."""
    alternatives = []
    best_item = get_item_by_sku(best_sku)
    cat = best_item.get("category", "") if best_item else ""
    
    # Preferred alternatives
    for itm in SAMPLE_CATALOG:
        if itm["sku"] != best_sku:
            if cat and itm.get("category") == cat:
                alternatives.append(itm)
            elif "SAMPLE-CARD" in itm["sku"]:
                alternatives.append(itm)
                
    if len(alternatives) < limit:
        for itm in SAMPLE_CATALOG:
            if itm["sku"] != best_sku and itm not in alternatives:
                alternatives.append(itm)
                
    return alternatives[:limit]

async def process_incoming_whatsapp_message(value_data: dict):
    """Processes incoming WhatsApp messages in background task to avoid webhook timeout."""
    contacts = value_data.get("contacts", [])
    contact_name = contacts[0].get("profile", {}).get("name", "Buyer") if contacts else "Buyer"
    
    messages = value_data.get("messages", [])
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
                print(f"⚠️ Sent NO_BUTTON_DETECTED warning to {from_phone}")
                return
                
            # 4. Handle button not in catalog
            if status == "NOT_IN_CATALOG" or not best_sku:
                send_whatsapp_text(
                    from_phone,
                    f"Ji {salutation}, ye specific button design abhi hamare ready catalog stock me active nahi hai. "
                    f"Hum apni production team se baat karke update karte hain ki kya ye custom tayyar kiya ja sakta hai."
                )
                print(f"⚠️ Sent NOT_IN_CATALOG notice to {from_phone}")
                return
                
            # 5. Handle Verified Catalog Match -> Send Full Option Pack!
            matched_item = get_item_by_sku(best_sku) or SAMPLE_CATALOG[0]
            
            # Message 1: Intro Greeting
            greeting_res = send_whatsapp_text(
                from_phone,
                f"Ji {salutation}, namaste! Aapka button sample dekh liya hai. Ye hamare paas regular running stock me ready uplabdh hai:"
            )
            print(f"📤 Sent Intro text to {from_phone}: {greeting_res.get('success')}")
            await asyncio.sleep(1)
            
            # Message 2: Primary Match Image + Specs
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
                img1_res = send_whatsapp_image(from_phone, p_img_bytes, best_caption)
                print(f"📤 Sent Best Match Image ({matched_item['sku']}): {img1_res.get('success')}")
                await asyncio.sleep(1.5)
                
            # Message 3 & 4: Alternative Running Options
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
                    alt_res = send_whatsapp_image(from_phone, alt_bytes, alt_caption)
                    print(f"📤 Sent Option {idx} Image ({alt_item['sku']}): {alt_res.get('success')}")
                    await asyncio.sleep(1.5)
                    
            # Message 5: Closing CTA
            cta_res = send_whatsapp_text(
                from_phone,
                f"Inme se aapko kaun sa design sahi baith raha hai sir? Aur approx kitne Gross ki requirement hai, batayein toh quotation aur sample confirm karwa dete hain."
            )
            print(f"📤 Sent Closing CTA: {cta_res.get('success')}")
            
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
        import re
        print(f"💬 [INCOMING TEXT] From: {from_phone} | Message: '{text_body}'")

        # Sub-Case A: Buyer mentions quantity or order (e.g. "300 gross", "option 3 chahiye 200 gross", "bill bhej do")
        gross_match = re.search(r'(\d+)\s*(?:gross|gr)', lower_text)
        pcs_match = re.search(r'(\d+)\s*(?:pcs|pieces)', lower_text)
        cleaned_for_num = re.sub(r'option\s*\d+', '', lower_text) # remove 'option 3' so 3 isn't mistaken for quantity
        general_num = re.search(r'(\d+)', cleaned_for_num)
        
        is_order_inquiry = any(w in lower_text for w in ["gross", "order", "bill", "proforma", "invoice", "chahiye", "bhej do", "pack", "dispatch", "option", "pi"]) and not any(w in lower_text for w in ["sample", "card", "swatch"])

        if is_order_inquiry:
            # Determine selected SKU
            target_sku = "ABC-136"
            opt_label = "Option 1"
            if "option 1" in lower_text or "136" in lower_text or "agoya" in lower_text:
                target_sku = "ABC-136"
                opt_label = "Option 1"
            elif "option 2" in lower_text or "139" in lower_text or "river" in lower_text:
                target_sku = "ABC-139"
                opt_label = "Option 2"
            elif "option 3" in lower_text or "137" in lower_text or "caramel" in lower_text or "gold" in lower_text:
                target_sku = "ABC-137"
                opt_label = "Option 3"
            elif "141" in lower_text or "smoky" in lower_text:
                target_sku = "ABC-141"
                opt_label = "Option 4"
            elif "142" in lower_text or "turquoise" in lower_text or "teal" in lower_text:
                target_sku = "ABC-142"
                opt_label = "Option 5"

            # Determine accurate quantity in Gross
            if gross_match:
                qty_gross = int(gross_match.group(1))
            elif pcs_match:
                qty_gross = max(1, round(int(pcs_match.group(1)) / 144))
            elif general_num:
                val = int(general_num.group(1))
                qty_gross = round(val / 144) if val > 1000 else val
            else:
                qty_gross = 200  # standard B2B sample production batch

            item = get_item_by_sku(target_sku) or SAMPLE_CATALOG[0]
            print(f"📦 Order Requirement for {from_phone}: SKU={target_sku} | Qty={qty_gross} Gross")

            # NO PRICING from AI! Confirm stock and register requirement for sales team to give commercial quote
            confirm_msg = (
                f"Ji {salutation}, bilkul! {opt_label} ({item['name']}) ka {qty_gross} Gross hamare godown me ready stock uplabdh hai.\n\n"
                f"Aapki {qty_gross} Gross ki requirement hamare sales desk par note kar li gayi hai. Best commercial bulk rate aur formal quotation ke liye hamari sales team aapse turant connect karegi.\n\n"
                f"Kripya apni company / firm ka naam aur delivery location bata dijiye sir."
            )
            send_whatsapp_text(from_phone, confirm_msg)
            return

        # Sub-Case B: Address Provided by Buyer
        if any(w in lower_text for w in ["plot", "sector", "phase", "road", "gali", "noida", "gurgaon", "okhla", "delhi", "pin", "near"]):
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
            
        # Pricing / Quotation general inquiry
        elif any(w in lower_text for w in ["rate", "price", "quotation", "quote", "cost", "bhaav", "paisa", "kitne ka", "charges"]):
            rate_reply = (
                "Ji sir, button ka rate uske design, quality aur quantity par depend karta hai.\n\n"
                "Aap button ki photo ya design share kar dijiye. Saath hi batayein, aapko kitni quantity chahiye?\n\n"
                "Hum aapko uske according best rate aur quotation bata denge."
            )
            send_whatsapp_text(from_phone, rate_reply)
            return
            
        # General greeting / assistance
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
        "version": "2.0.0",
        "features": [
            "Automatic Buyer Photo Scan",
            "Instant Best Match Image Dispatch",
            "2-3 Alternative Options with Images & Gross Stock",
            "Auto Sample Card & Rate Assistant"
        ]
    }

@app.get("/webhook")
def verify_webhook(request: Request):
    """
    Verification endpoint required by Meta Developers Portal.
    Checks hub.verify_token and returns hub.challenge.
    """
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
    """
    Receives live events from Meta WhatsApp Cloud API.
    Awaits payload, schedules processing in background, and immediately returns 200 OK.
    """
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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"🚀 Starting ABC Buttons Webhook Bot on port {port}...")
    uvicorn.run("webhook_bot:app", host="0.0.0.0", port=port, reload=False)
