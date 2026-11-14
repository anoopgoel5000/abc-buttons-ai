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
    download_whatsapp_media
)

app = FastAPI(title="ABC Buttons 24/7 WhatsApp AI Bot")

VERIFY_TOKEN = os.environ.get("WEBHOOK_VERIFY_TOKEN", "abc_buttons_secret_2026")
CAT_DIR = os.path.join(BASE_DIR, "catalog_images")

# In-memory deduplication of message IDs
processed_msg_ids = set()

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
                    f"Namaste {contact_name}! Aapne jo photo share ki hai, usme button clear nahi dikh raha hai. "
                    f"Kripya button ki ek close-up photo achhi roshni me bhejiye, hum turant ready stock check karke batate hain."
                )
                print(f"⚠️ Sent NO_BUTTON_DETECTED warning to {from_phone}")
                return
                
            # 4. Handle button not in catalog
            if status == "NOT_IN_CATALOG" or not best_sku:
                send_whatsapp_text(
                    from_phone,
                    f"Namaste {contact_name}! Ye specific button design abhi hamare ready catalog stock me active nahi hai. "
                    f"Hum apni factory production team se baat karke aapko update karte hain ki kya ye aapki required quantity ke liye custom tayyar kiya ja sakta hai."
                )
                print(f"⚠️ Sent NOT_IN_CATALOG notice to {from_phone}")
                return
                
            # 5. Handle Verified Catalog Match -> Send Full Option Pack!
            matched_item = get_item_by_sku(best_sku) or SAMPLE_CATALOG[0]
            
            # Message 1: Intro Greeting
            greeting_res = send_whatsapp_text(
                from_phone,
                f"Namaste {contact_name}! Welcome to ABC Buttons.\n"
                f"Aapke bheje gaye sample ke aadhar par ye hamare paas 100% Verified Match aur running options ready stock me uplabdh hain:"
            )
            print(f"📤 Sent Intro text to {from_phone}: {greeting_res.get('success')}")
            await asyncio.sleep(1)
            
            # Message 2: Primary Match Image + Specs
            p_img_path = os.path.join(CAT_DIR, f"{matched_item['sku']}.jpg")
            if os.path.exists(p_img_path):
                with open(p_img_path, "rb") as fp:
                    p_img_bytes = fp.read()
                best_caption = (
                    f"🏆 *100% Best Match: {matched_item['name']}*\n"
                    f"• Official SKU: `{matched_item['sku']}`\n"
                    f"• Size: {matched_item.get('size_ligne', '')} • {matched_item.get('holes', '')}\n"
                    f"• Ready Stock: *{matched_item.get('stock_gross', 0):,} Gross* ({matched_item.get('stock_gross', 0)*144:,} Pcs)\n"
                    f"• B2B Rate: ₹{matched_item.get('rate_per_gross', 0)} / Gross (1 Gr = 144 Pcs)"
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
                        f"• SKU: `{alt_item['sku']}` | Category: {alt_item['category']}\n"
                        f"• Size: {alt_item.get('size_ligne', '')} • {alt_item.get('holes', '')}\n"
                        f"• Available Stock: *{alt_item.get('stock_gross', 0):,} Gross*\n"
                        f"• Rate: ₹{alt_item.get('rate_per_gross', 0)} / Gross"
                    )
                    alt_res = send_whatsapp_image(from_phone, alt_bytes, alt_caption)
                    print(f"📤 Sent Option {idx} Image ({alt_item['sku']}): {alt_res.get('success')}")
                    await asyncio.sleep(1.5)
                    
            # Message 5: Closing CTA
            cta_res = send_whatsapp_text(
                from_phone,
                f"Inme se aapko kaun sa design perfect lag raha hai? Aur approx kitne Gross quantity ki requirement hai?"
            )
            print(f"📤 Sent Closing CTA: {cta_res.get('success')}")
            
        except Exception as e:
            print(f"❌ Error processing image from {from_phone}: {e}")
            send_whatsapp_text(
                from_phone,
                f"Namaste {contact_name}! Aapka photo sample prapt hua hai. Hamare sales representative turant isko verify karke aapse sampark karenge."
            )

    # ---------------- CASE 2: BUYER SENT A TEXT MESSAGE ----------------
    elif msg_type == "text":
        text_body = msg.get("text", {}).get("body", "").strip()
        lower_text = text_body.lower()
        
        # Sample card inquiry
        if any(w in lower_text for w in ["sample", "card", "hanger", "swatch"]):
            card_path = os.path.join(CAT_DIR, "ABC-SAMPLE-CARD-01.jpg")
            if os.path.exists(card_path):
                with open(card_path, "rb") as cfp:
                    card_bytes = cfp.read()
                send_whatsapp_image(
                    from_phone,
                    card_bytes,
                    "📦 *ABC Buttons Official Shell Button Sample Hanger Card*\n"
                    "Includes running sizes (14L to 24L) of River Shell, MOP, Agoya & Trocas.\n"
                    "Ready for immediate courier dispatch!"
                )
                await asyncio.sleep(1)
            send_whatsapp_text(
                from_phone,
                f"Namaste {contact_name}! Hamara full range sample card bilkul ready hai. "
                f"Kripya apna factory / office delivery address share kar dijiye, hum aaj hi courier dispatch karwa denge."
            )
            
        # Pricing / Quotation inquiry
        elif any(w in lower_text for w in ["rate", "price", "quotation", "quote", "cost", "bhaav"]):
            send_whatsapp_text(
                from_phone,
                f"Namaste {contact_name}! B2B bulk orders ke liye exact rate quantity (Gross) par depend karta hai. "
                f"Kripya button ki photo ya SKU code aur apni required quantity (Gross) share karein, hum turant 1-click Proforma Quotation generate kar denge."
            )
            
        # General greeting / assistance
        else:
            try:
                ai_reply = simulate_buyer_chat(text_body, history=[])
                send_whatsapp_text(from_phone, ai_reply)
            except Exception:
                send_whatsapp_text(
                    from_phone,
                    f"Namaste {contact_name}! ABC Buttons Private Limited me aapka swagat hai. "
                    f"Aap hume button ki photo bhej kar live stock aur rate pata kar sakte hain. Hum aapki kya sahayata kar sakte hain?"
                )

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
