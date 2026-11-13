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

WHATSAPP_TOKEN = "EAGZAh8GzgluUBS8ZBElz9b7b1Mzhf7jK7LtwuQDAe09ZA4acE5YvgjzwZBK7lKURmyaRLmP8FxN0HBHZAZCBzxQxFV5Uz38iug0NpEEW1k9W5WgTEx3DoEbmuosHST4jLex7brEbYf3WH2fWDnkonOxIb7OzYiAynCmFs4ryitHLc6UtSDKhaNabBhnc6QoiUsWm1wXbRSEgrP95ZBljzRfFKFveQIfpWLn2FoXGvorZA3eUfAjmOY8LItMM7SfLep8nHERZCLbaymcZAja19oYoLPZBYI9"
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
