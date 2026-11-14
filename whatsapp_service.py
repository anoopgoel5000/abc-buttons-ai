"""
Official Meta WhatsApp Cloud API Service for ABC Buttons Private Limited
Handles automated WhatsApp messaging for Quotations, Visual Match alerts,
Factory Job-Cards, and Payment Reminders.
Uses 100% standard library (urllib, json, os) - no extra dependencies required.
"""

import os
import json
import urllib.request
import urllib.parse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, ".env")

WHATSAPP_TOKEN = "EAGZAh8GzgluUBS0hzJZA1R5RlqjuMaZCmmDNNy800ZBUl1i2gSbT0ZCjI98u71libl0ShwarXZB46l9ZB2xm1LTHwarb7JlYfxXf7LLqV971zZCrOc2GZBeUaaY4ni4u40Gh0TpNi5GZCvzU6EThnzluUxvnzGA1orRXZCYRVBqAFcwlyf2Tqd4xPeaZBqdJIA2JmZA3xPxpwPGbyZACfF1nNSmKEvhZBo8GwBa8MHR4o8CdVOxLA6JGPEWYXoeDBOkDqEDFzEY6dId6ddGwT2dkYfFhbm5vPghhQZDZD"
PHONE_NUMBER_ID = "1406479542552212"
DEFAULT_RECIPIENT = "919315702804"

# 1. Try reading from .env file
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("WHATSAPP_ACCESS_TOKEN="):
                WHATSAPP_TOKEN = line.split("=", 1)[1].strip()
            elif line.startswith("WHATSAPP_PHONE_NUMBER_ID="):
                PHONE_NUMBER_ID = line.split("=", 1)[1].strip()
            elif line.startswith("TEST_RECIPIENT_PHONE="):
                DEFAULT_RECIPIENT = line.split("=", 1)[1].strip()

# 2. Try reading from Streamlit Secrets (for Streamlit Cloud deployment)
try:
    import streamlit as st
    if hasattr(st, "secrets"):
        if "WHATSAPP_ACCESS_TOKEN" in st.secrets:
            WHATSAPP_TOKEN = st.secrets["WHATSAPP_ACCESS_TOKEN"]
        if "WHATSAPP_PHONE_NUMBER_ID" in st.secrets:
            PHONE_NUMBER_ID = str(st.secrets["WHATSAPP_PHONE_NUMBER_ID"])
except Exception:
    pass

# 3. Fallback to os.environ
if not WHATSAPP_TOKEN:
    WHATSAPP_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")

def send_whatsapp_text(to_phone: str, message_text: str) -> dict:
    """
    Sends an official WhatsApp text message via Meta Cloud API.
    to_phone: 10 or 12 digit phone number (e.g. '919315702804')
    """
    clean_phone = "".join(c for c in str(to_phone) if c.isdigit())
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone
        
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": message_text
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"success": True, "data": data}
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "read"):
            try:
                err_msg = e.read().decode("utf-8")
            except Exception:
                pass
        return {"success": False, "error": err_msg}

def upload_whatsapp_media(file_bytes: bytes, mime_type: str, filename: str) -> dict:
    """
    Uploads media (image or PDF) to Meta Cloud API and returns media_id.
    """
    boundary = '----WebKitFormBoundaryABCButtonsMedia99'
    body = bytearray()

    def add_field(name, value):
        body.extend(f'--{boundary}\r\n'.encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode('utf-8'))
        body.extend(f'{value}\r\n'.encode('utf-8'))

    def add_file(name, fname, data, mime):
        body.extend(f'--{boundary}\r\n'.encode('utf-8'))
        body.extend(f'Content-Disposition: form-data; name="{name}"; filename="{fname}"\r\n'.encode('utf-8'))
        body.extend(f'Content-Type: {mime}\r\n\r\n'.encode('utf-8'))
        body.extend(data)
        body.extend(b'\r\n')

    add_field('messaging_product', 'whatsapp')
    add_file('file', filename, file_bytes, mime_type)
    body.extend(f'--{boundary}--\r\n'.encode('utf-8'))

    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/media"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            'Authorization': f'Bearer {WHATSAPP_TOKEN}',
            'Content-Type': f'multipart/form-data; boundary={boundary}'
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return {"success": True, "media_id": data.get("id")}
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "read"):
            try:
                err_msg = e.read().decode("utf-8")
            except Exception:
                pass
        return {"success": False, "error": err_msg}

def send_whatsapp_image(to_phone: str, image_bytes: bytes, caption: str = "") -> dict:
    """
    Sends an image directly via Meta WhatsApp Cloud API.
    """
    clean_phone = "".join(c for c in str(to_phone) if c.isdigit())
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    up = upload_whatsapp_media(image_bytes, "image/png", "proforma_invoice.png")
    if not up.get("success"):
        return up

    media_id = up["media_id"]
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "image",
        "image": {
            "id": media_id,
            "caption": caption
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"success": True, "data": data}
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "read"):
            try:
                err_msg = e.read().decode("utf-8")
            except Exception:
                pass
        return {"success": False, "error": err_msg}

def send_whatsapp_document(to_phone: str, doc_bytes: bytes, filename: str, caption: str = "") -> dict:
    """
    Sends a PDF document directly via Meta WhatsApp Cloud API.
    """
    clean_phone = "".join(c for c in str(to_phone) if c.isdigit())
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    up = upload_whatsapp_media(doc_bytes, "application/pdf", filename)
    if not up.get("success"):
        return up

    media_id = up["media_id"]
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_phone,
        "type": "document",
        "document": {
            "id": media_id,
            "caption": caption,
            "filename": filename
        }
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"success": True, "data": data}
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "read"):
            try:
                err_msg = e.read().decode("utf-8")
            except Exception:
                pass
        return {"success": False, "error": err_msg}

def generate_proforma_card_image(
    buyer_name="Shahi Exports",
    buyer_gst="07AAACS1234F1Z5",
    sku="ABC-139",
    item_name="ABC-139 Natural White River Shell Button (2-Hole Raised Rim)",
    item_spec="SKU: ABC-139 • Size: 24L • 2-Hole with Raised Outer Rim",
    qty_gross=350,
    rate_gross=290.0,
    discount_pct=5.0,
    gst_pct=12.0
) -> bytes:
    """
    Renders an exact visual replica of the Proforma Quotation Card as a PNG image in memory.
    """
    from PIL import Image, ImageDraw, ImageFont
    import io

    width = 900
    height = 1050
    img = Image.new("RGB", (width, height), color="#f1f5f9")
    draw = ImageDraw.Draw(img)

    try:
        font_company = ImageFont.truetype("arialbd.ttf", 32)
        font_title = ImageFont.truetype("arialbd.ttf", 22)
        font_bold = ImageFont.truetype("arialbd.ttf", 17)
        font_reg = ImageFont.truetype("arial.ttf", 15)
        font_small = ImageFont.truetype("arial.ttf", 13)
        font_total = ImageFont.truetype("arialbd.ttf", 26)
    except Exception:
        font_company = font_title = font_bold = font_reg = font_small = font_total = ImageFont.load_default()

    card_margin = 25
    draw.rounded_rectangle(
        [(card_margin, card_margin), (width - card_margin, height - card_margin)],
        radius=14,
        fill="#ffffff",
        outline="#cbd5e1",
        width=2
    )

    x = card_margin + 30
    y = card_margin + 30
    draw.text((x, y), "ABC BUTTONS PRIVATE LIMITED", fill="#0f172a", font=font_company)
    y += 42
    draw.text((x, y), "Govindpuri / Kalkaji, New Delhi - 110019 | GSTIN: 07AABCA9876P1Z3", fill="#64748b", font=font_small)
    y += 30

    draw.line([(x, y), (width - card_margin - 30, y)], fill="#0f172a", width=2)
    y += 18

    draw.text((x, y), "PROFORMA QUOTATION / RATE ESTIMATE", fill="#0f172a", font=font_title)
    pill_text = "Ref: ABC-QT-2026"
    draw.rounded_rectangle([(width - card_margin - 170, y - 2), (width - card_margin - 30, y + 26)], radius=6, fill="#e2e8f0")
    draw.text((width - card_margin - 158, y + 4), pill_text, fill="#334155", font=font_bold)
    y += 40

    draw.text((x, y), f"Bill To: {buyer_name}", fill="#1e293b", font=font_bold)
    y += 24
    draw.text((x, y), f"GSTIN: {buyer_gst}", fill="#475569", font=font_reg)
    y += 22
    draw.text((x, y), "Date: 13-Nov-2026 | Valid Till: 13-Dec-2026", fill="#64748b", font=font_reg)
    y += 36

    tbl_left = x
    tbl_right = width - card_margin - 30
    tbl_h_height = 42
    draw.rectangle([(tbl_left, y), (tbl_right, y + tbl_h_height)], fill="#1e293b")

    col_desc_x = tbl_left + 15
    col_qty_x = tbl_left + 460
    col_rate_x = tbl_left + 590
    col_amt_x = tbl_right - 15

    draw.text((col_desc_x, y + 10), "Item Description", fill="#ffffff", font=font_bold)
    draw.text((col_qty_x, y + 10), "Qty (Gross)", fill="#ffffff", font=font_bold)
    draw.text((col_rate_x, y + 10), "Base Rate / Gr", fill="#ffffff", font=font_bold)
    draw.text((col_amt_x - 110, y + 10), "Gross Amount", fill="#ffffff", font=font_bold)
    y += tbl_h_height

    gross_amount = qty_gross * rate_gross
    discount_amount = gross_amount * (discount_pct / 100.0)
    taxable_subtotal = gross_amount - discount_amount
    gst_amount = taxable_subtotal * (gst_pct / 100.0)
    grand_total = taxable_subtotal + gst_amount
    effective_rate = taxable_subtotal / qty_gross if qty_gross else rate_gross

    row_top = y
    row_height = 100
    draw.rectangle([(tbl_left, row_top), (tbl_right, row_top + row_height)], fill="#ffffff", outline="#cbd5e1", width=1)

    draw.text((col_desc_x, row_top + 16), str(item_name)[:48], fill="#0f172a", font=font_bold)
    draw.text((col_desc_x, row_top + 44), str(item_spec)[:55], fill="#64748b", font=font_small)
    draw.text((col_desc_x, row_top + 64), "(Oeko-Tex Standard 100 • Lead Free)", fill="#94a3b8", font=font_small)

    draw.text((col_qty_x, row_top + 24), f"{qty_gross} Gr", fill="#0f172a", font=font_bold)
    draw.text((col_qty_x, row_top + 48), f"({qty_gross*144:,} pcs)", fill="#64748b", font=font_small)

    draw.text((col_rate_x, row_top + 34), f"₹{rate_gross:,.2f} / Gr", fill="#0f172a", font=font_reg)
    amt_str = f"₹{gross_amount:,.2f}"
    draw.text((col_amt_x - 110, row_top + 34), amt_str, fill="#0f172a", font=font_bold)

    y += row_height + 25

    summary_top = y
    summary_height = 210
    draw.rounded_rectangle([(tbl_left, summary_top), (tbl_right, summary_top + summary_height)], radius=8, fill="#f8fafc", outline="#e2e8f0", width=1)

    sy = summary_top + 15
    rx = tbl_right - 25

    def right_text(label, val, y_pos, font_l=font_reg, font_v=font_bold, fill_l="#475569", fill_v="#0f172a"):
        draw.text((rx - 380, y_pos), label, fill=fill_l, font=font_l)
        draw.text((rx - 150, y_pos), val, fill=fill_v, font=font_v)

    right_text("Gross Total:", f"₹{gross_amount:,.2f}", sy)
    sy += 32
    if discount_pct > 0:
        right_text(f"Less: Volume Discount ({discount_pct:.0f}%):", f"- ₹{discount_amount:,.2f}", sy, fill_l="#16a34a", fill_v="#16a34a")
        sy += 32
    right_text("Taxable Subtotal:", f"₹{taxable_subtotal:,.2f}", sy)
    draw.text((rx - 540, sy), f"(Effective Net: ₹{effective_rate:,.2f}/Gr)", fill="#16a34a", font=font_small)
    sy += 32
    right_text(f"GST @ {gst_pct:.0f}%:", f"₹{gst_amount:,.2f}", sy)
    sy += 34

    draw.line([(tbl_left + 15, sy), (tbl_right - 15, sy)], fill="#0f172a", width=2)
    sy += 14

    draw.text((rx - 380, sy), "Total Payable:", fill="#0f172a", font=font_total)
    draw.text((rx - 190, sy), f"₹{grand_total:,.2f}", fill="#0f172a", font=font_total)

    y += summary_height + 25

    draw.text((x, y), "• All billing strictly in Gross units (1 Gross = 144 Pieces)", fill="#475569", font=font_small)
    y += 22
    draw.text((x, y), "• Delivery Lead Time: Ready Ex-Stock, 24-48 hrs from Okhla Godown", fill="#475569", font=font_small)
    y += 22
    draw.text((x, y), "• Bank Details: HDFC Bank, Kalkaji Branch | A/C: 50200084920192 | IFSC: HDFC0000123", fill="#1e40af", font=font_bold)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def download_whatsapp_media(media_id: str) -> bytes:
    """
    Downloads media bytes from Meta WhatsApp Cloud API given a media_id.
    """
    url_info = f"https://graph.facebook.com/v22.0/{media_id}"
    req1 = urllib.request.Request(url_info, headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"})
    with urllib.request.urlopen(req1, timeout=15) as resp1:
        info = json.loads(resp1.read().decode("utf-8"))
        media_url = info.get("url")
        if not media_url:
            raise Exception(f"No media URL returned by Meta for media_id {media_id}")

    req2 = urllib.request.Request(media_url, headers={
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "User-Agent": "curl/7.68.0"
    })
    with urllib.request.urlopen(req2, timeout=25) as resp2:
        return resp2.read()

def send_whatsapp_template(to_phone: str, template_name: str = "hello_world", lang_code: str = "en_US") -> dict:
    """
    Sends an approved Meta WhatsApp template to open a 24-hr customer service window.
    """
    clean_phone = "".join(c for c in str(to_phone) if c.isdigit())
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone
        
    url = f"https://graph.facebook.com/v22.0/{PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": clean_phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {
                "code": lang_code
            }
        }
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return {"success": True, "data": data}
    except Exception as e:
        err_msg = str(e)
        if hasattr(e, "read"):
            try:
                err_msg = e.read().decode("utf-8")
            except Exception:
                pass
        return {"success": False, "error": err_msg}

if __name__ == "__main__":
    res = send_whatsapp_text(DEFAULT_RECIPIENT, "🚀 Official Meta API Connected: ABC Buttons Automation is LIVE!")
    print("Test Result:", res)
