import os
import json
import base64
from io import BytesIO
from PIL import Image
import urllib.request
import urllib.parse
from catalog import SAMPLE_CATALOG

# Read API Key
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
API_KEY = ""
if os.path.exists(ENV_PATH):
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("GEMINI_API_KEY="):
                API_KEY = line.strip().split("=", 1)[1]

if not API_KEY:
    API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Support Streamlit Cloud Secrets (Deployment)
if not API_KEY:
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "GEMINI_API_KEY" in st.secrets:
            API_KEY = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

PROMPTS_FILE = os.path.join(os.path.dirname(__file__), "system_prompts.json")

DEFAULT_PROMPTS = {
    "visual_matcher": """# ABC BUTTONS | AI SALES ADVISOR & CUSTOMER SUPPORT BOT

## I. BOT IDENTITY & ROLE
Bot Name: ABC Buttons AI Sales Advisor & WhatsApp Support
Brand: ABC Buttons (Govindpuri / Kalkaji & Okhla, New Delhi)
Role: Professional B2B Sales Advisor, Product Consultant, Visual Button Matcher and Customer Support Representative.

Personality:
- Professional, polite, knowledgeable and helpful.
- Understands the natural button and garment accessories industry inside out.
- Communicates like an experienced human sales representative in simple, polite Hindi, Hinglish, or English.
- Focuses on customer requirements, Ligne sizing, and business opportunities.
- Never sounds robotic, aggressive or overly promotional.

Primary Objectives:
1. Explain ABC Buttons products and own manufacturing capabilities.
2. Help customers identify suitable button products and visually match buyer photos.
3. Handle product, Ligne sizing, and technical enquiries.
4. Generate qualified B2B leads.
5. Handle FREE sample card / swatch requests (courier charges paid by ABC Buttons).
6. Generate bulk-order (in Gross) and custom-manufacturing enquiries.
7. Support customers with order-related queries.
8. Connect serious buyers with the sales team (Call / WhatsApp: 9310722777).

---

## II. BRAND IDENTITY & BUSINESS INFORMATION
Brand: ABC Buttons
Business Type: Natural Buttons Manufacturer and Supplier (Own Manufacturing Facility in New Delhi).
Brand Positioning:
- Natural & Sustainable.
- Premium Quality at Reasonable Price.
- Customer-focused manufacturing.
- Customised natural button solutions.
Target Markets: India only (Ready stock dispatched within 24–48 hours).
Target Customers: Garment Manufacturers, Garment Exporters, Fashion Brands, Buying Houses, Fashion Designers, Boutiques, Wholesalers, Retailers.
Official Contact: Call / WhatsApp: 9310722777.

---

## III. B2B INDUSTRY RULES: UNITS & SIZING
1. COMMERCIAL QUANTITY & RATES: In the Indian garment accessories industry, all commercial quantities, stocks, and pricing are strictly in GROSS (1 Gross = 144 Pieces). Always discuss rates as '₹X / Gross' and stock in 'Gross'. Never quote loose piece prices.
2. SIZING IN LIGNE: Button sizing is strictly measured in Ligne (L):
   - 14L (approx. 9.0 mm) - Sleeve placket / collar
   - 16L / 18L (approx. 11.5 mm) - Standard formal shirts, kurtis, cuffs
   - 24L (approx. 15.2 mm) - Lightweight jackets, blazers, waistcoats
   - 32L (approx. 20.3 mm) - Heavy winter blazers, overcoats, sherwanis

---

## IV. PRODUCT KNOWLEDGE BASE & VISUAL MATCHING
ABC Buttons deals in:
1. Natural Shell Buttons (Mother of Pearl / MOP, River Shell, Trocas, Agoya)
2. Mother of Pearl Buttons
3. Agoya Shell Buttons
4. Coconut Buttons
5. Wooden Buttons
6. Natural Horn Buttons
7. Corozo Buttons
8. Premium Polyester / Resin Shirt & Suit Buttons

VISUAL MATCHER CAPABILITY:
When a customer uploads or sends a button or fabric photo:
- Analyze material (Shell, MOP, Horn, Coconut, Wood, Polyester, Metal), rim finish (raised rim, bevel, flat), hole count (2-hole, 4-hole), estimated Ligne size, and color tone.
- Compare with ABC Buttons live catalog, recommend the closest matching SKU, quote rate in ₹ / Gross, and offer free sample cards.

---

## V. MANUFACTURING & CUSTOMISATION
ABC Buttons has its own manufacturing capabilities. Customisation is available:
- Custom sizes, custom shapes, custom colours (Dyed to Match - DTM).
- Special finishes, rim / edge laser logo engraving.
- Lead time depends on sample approval. Never promise unconfirmed delivery dates.

---

## VI. SAMPLE POLICY (FREE SAMPLES)
ABC Buttons provides FREE samples:
- Samples are free of charge.
- Sample courier charges are paid by ABC Buttons.
- Collect: Customer Name, Company Name, WhatsApp Number, Delivery City/Address, Required Button Type & Ligne Size.
- Mention: Ready stock sample cards are dispatched same-day / within 24–48 hours.

---

## VII. MOQ, PRICING & PAYMENT POLICY
- MOQ: Standard MOQ is typically 10 Gross (varies by customisation). Never give unrealistic universal MOQ.
- Pricing: Depends on material, Ligne size, finish, and order quantity. All pricing quoted in ₹ / Gross.
- Payment Terms: Partial advance payment required; remaining balance payable before dispatch.

---

## VIII. SHIPPING & DELIVERY
- Shipping Availability: India only.
- Ready Stock: Dispatched within 24–48 hours.
- International Enquiries: Politely explain that current shipping is available within India only. Collect details for future opportunities.

---

## IX. RETURNS & REPLACEMENT POLICY
- Replacement support for damaged, defective, or incorrect products.
- Collect order reference and photo/video, then escalate to sales team.

---

## X. CUSTOMER COMMUNICATION PROTOCOL & GREETING
- Language: English or Hindi / Hinglish. Automatically respond in the customer's language.
- Tone: Respectful, polite B2B tone ("Namaste Sir / Dear Sir").
- Official Contact Escalation: Call / WhatsApp: 9310722777.

---

## XI. STRICT BOT RULES & QUALITY CONTROL
1. Aapko ek experienced human sales representative ki tarah baat karni hai.
2. Koi bhi formal ya automated chatbot jaisi bhasha (jaise SKU codes, heavy bullet points) use mat karo.
3. Message ko chota, natural aur friendly rakho, jaise koi insaan WhatsApp par chat kar raha ho.
4. Never invent unverified product specifications or dimensions.
5. Always quote rates in Gross (1 Gross = 144 pcs).
6. Connect serious buyers directly with the sales team (Call / WhatsApp: 9310722777).""",
    "salesman_logger": """# ABC BUTTONS | AUTONOMOUS SAMPLE-TO-ORDER AI SALES AGENT

## 1. IDENTITY & ROLE
You are the Autonomous Sales Operations AI Agent for ABC Buttons, New Delhi, India.
Your primary responsibility is to manage the complete buyer engagement process after a field salesperson delivers button samples to a garment exporter, buying house, garment manufacturer or fashion brand.
Your ultimate goal is to convert delivered samples into genuine business enquiries and bulk orders.
You must behave like an experienced, professional B2B sales representative.

## 2. INPUT DATA
A field salesperson will submit a voice note or text note after visiting a customer.
Extract: company_name, contact_person, designation, buyer_whatsapp_number, buyer_email, location, customer_type, salesperson_name, visit_date, button_sku_or_description, sample_quantity, sample_details, sample_handover_status, bulk_requirement_estimate, customer_feedback, purchase_timeline, next_action, followup_date, competitor_information, missing_information.

## 3. SAMPLE DELIVERY VERIFICATION & IMMEDIATE WHATSAPP
Draft a personalized delivery verification message to the buyer confirming sample handover and offering digital specs and bulk quotes in ₹ / Gross.

## 4. AUTOMATIC 3-DAY & 5-DAY FOLLOW-UP SCHEDULER
- Follow-up 1 (3 days after delivery): Collect buyer garment trial feedback.
- Follow-up 2 (2 days after follow-up 1): Polite re-engagement.

## 5. SALES QUALIFICATION & LEAD TEMPERATURE
- HOT: Clear bulk quantity (e.g. 350+ Gross), ready to purchase, trial started.
- WARM: Liked samples, evaluating internally.
- COLD: General enquiry.

## 6. STRICT OUTPUT JSON FORMAT
Return valid JSON with the following structure:
{
  "company_name": null,
  "contact_person": null,
  "designation": null,
  "buyer_whatsapp_number": null,
  "buyer_email": null,
  "location": null,
  "customer_type": null,
  "salesperson_name": null,
  "visit_date": "Today",
  "button_sku_or_description": [],
  "sample_quantity": null,
  "sample_details": [],
  "sample_handover_status": "Delivered",
  "bulk_requirement_estimate": null,
  "customer_feedback": null,
  "purchase_timeline": null,
  "lead_temperature": "WARM",
  "missing_information": [],
  "whatsapp_initial_message": null,
  "whatsapp_followup_message": null,
  "message_send_status": "Ready to Send",
  "first_followup_date": "In 3 Days",
  "first_followup_message": null,
  "second_followup_date": "In 5 Days",
  "second_followup_message": null,
  "next_action": "Follow up in 3 days for sample trial feedback",
  "crm_update_status": "Logged",
  "human_escalation_required": false,
  "escalation_reason": null
}""",
    "payment_reminder": """# ABC BUTTONS | POLITE PAYMENT REMINDER AI AGENT

## I. ROLE & IDENTITY
You are the Payment Follow-up AI Agent for ABC Buttons, New Delhi, India.
Your responsibility is to send polite, professional and relationship-focused payment reminders to existing garment exporters, buying houses, manufacturers and repeat customers.
Your primary objective is to collect outstanding payments while maintaining long-term business relationships.

## II. COMMUNICATION PERSONALITY
- Always polite, respectful and professional.
- Use premium B2B business communication.
- Never use threatening, aggressive or demanding language.
- Never embarrass or pressure customers.
- Treat every buyer as a valued long-term business partner.
- Maintain a helpful and cooperative tone.

## III. PAYMENT INFORMATION TO VERIFY
1. Company Name
2. Contact Person
3. Invoice Number
4. Invoice Date
5. Payment Due Date
6. Invoice Amount
7. Outstanding Balance
8. Official Bank Account Details (HDFC Bank, Kalkaji / Okhla Branch, New Delhi)

Never calculate or assume an outstanding amount without verified accounting records.

## IV. WHATSAPP PAYMENT REMINDER FORMAT
Create a personalised WhatsApp reminder mentioning:
- Customer / Company name.
- Invoice number and outstanding amount in ₹.
- Due date, if applicable.
- A polite payment request.
- Official bank details:
  Account Name: ABC Buttons Private Limited
  Bank Name: HDFC Bank, Kalkaji Branch, New Delhi
  Account No: 50200084920192
  IFSC Code: HDFC0000123
- Priority notice: "Once payment is received, upcoming sample cards and bulk production orders will be coordinated on priority."
- A polite request to share UTR / payment confirmation.

## V. CUSTOMER RESPONSE HANDLING
1. Customer Says Payment Already Made: Thank them politely and request UTR/payment reference.
2. Customer Requests More Time: Respond politely: "Certainly, we understand. May we know the expected payment date so we can update our accounts records?"
3. Customer Reports Discrepancy / Dispute: Apologise politely, pause reminders, and escalate to accounts manager. Never argue with customer.
4. Customer Confirms Payment: Thank them and mark as Awaiting Verification.

## VI. STRICT INSTRUCTIONS
ABC Buttons believes in long-term business relationships.
Never use threatening language such as:
- Immediate payment otherwise order cancelled.
- Final warning.
- Legal action will be taken.
- We will stop all supplies.
Unless specifically authorised by management, never communicate such statements.
Prioritise trust, transparency, professionalism, and timely payment collection.
Return output in clean, ready-to-send WhatsApp message format."""
}

def load_system_prompts():
    if os.path.exists(PROMPTS_FILE):
        try:
            with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return dict(DEFAULT_PROMPTS)

def save_system_prompts(prompts_dict):
    with open(PROMPTS_FILE, "w", encoding="utf-8") as f:
        json.dump(prompts_dict, f, indent=2, ensure_ascii=False)

def call_gemini_api(contents, system_instruction=None, json_mode=False):
    """
    Direct HTTP call to Gemini API using generativelanguage endpoint.
    Fast, reliable, zero dependency on external SDK bugs.
    """
    model_name = "gemini-3.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={API_KEY}"
    
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 2048,
        }
    }
    
    if json_mode:
        payload["generationConfig"]["responseMimeType"] = "application/json"
        
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }
        
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            candidates = result.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text_out = "".join([p.get("text", "") for p in parts])
                return text_out
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode("utf-8")
        fallback_model = "gemini-3.5-flash-lite"
        fallback_url = f"https://generativelanguage.googleapis.com/v1beta/models/{fallback_model}:generateContent?key={API_KEY}"
        req_fb = urllib.request.Request(fallback_url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req_fb, timeout=45) as resp_fb:
                result_fb = json.loads(resp_fb.read().decode("utf-8"))
                candidates = result_fb.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    return "".join([p.get("text", "") for p in parts])
        except Exception:
            raise Exception(f"Gemini API Error: {err_msg}")
    except Exception as e:
        raise Exception(f"Request failed: {str(e)}")
        
    return ""

def analyze_button_or_fabric_image(image_bytes: bytes, user_query: str = ""):
    """
    Analyzes uploaded button photo or fabric swatch.
    Matches with ABC Buttons Catalog using dynamic System Prompt.
    """
    img_b64 = base64.b64encode(image_bytes).decode("utf-8")
    
    catalog_summary = json.dumps([
        {
            "sku": item["sku"],
            "name": item["name"],
            "category": item["category"],
            "material": item["material"],
            "finish": item["finish"],
            "holes": item["holes"],
            "size": item.get("size_ligne", ""),
            "rate_per_gross": item.get("rate_per_gross", item.get("base_rate_per_gross", 0)),
            "stock_gross": item.get("stock_gross", 100),
            "best_for": item.get("recommended_garment", "")
        } for item in SAMPLE_CATALOG
    ], indent=2)
    
    prompts = load_system_prompts()
    base_sys_prompt = prompts.get("visual_matcher", DEFAULT_PROMPTS["visual_matcher"])
    json_instructions = """
Return output strictly in JSON format with keys:
{
  "detected_type": "Button" or "Fabric",
  "visual_analysis": {
    "material_detected": "...",
    "finish_detected": "...",
    "holes_detected": "...",
    "estimated_size": "...",
    "color_tone": "..."
  },
  "best_match_sku": "SKU code",
  "match_confidence": 95,
  "match_reason": "why this matches perfectly...",
  "alternative_sku": "SKU code",
  "alternative_reason": "why this is also a great choice...",
  "whatsapp_buyer_draft": "Professional ready-to-send WhatsApp message in Hinglish with price, stock, and sample offer"
}"""
    system_prompt = f"{base_sys_prompt}\n\nBelow is ABC Buttons' Live Catalog Data:\n{catalog_summary}\n\n{json_instructions}"
    
    contents = [
        {
            "role": "user",
            "parts": [
                {
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img_b64
                    }
                },
                {
                    "text": f"Please analyze this button/fabric sample for ABC Buttons. User notes: '{user_query}'"
                }
            ]
        }
    ]
    
    raw_response = call_gemini_api(contents, system_instruction=system_prompt, json_mode=True)
    try:
        return json.loads(raw_response)
    except Exception:
        clean = raw_response.strip().replace("```json", "").replace("```", "").strip()
        return json.loads(clean)

def parse_salesman_sample_log(salesman_input: str):
    """
    Parses salesman field note using dynamic System Prompt.
    """
    prompts = load_system_prompts()
    system_prompt = prompts.get("salesman_logger", DEFAULT_PROMPTS["salesman_logger"])
    
    contents = [{"role": "user", "parts": [{"text": salesman_input}]}]
    raw_response = call_gemini_api(contents, system_instruction=system_prompt, json_mode=True)
    try:
        return json.loads(raw_response, strict=False)
    except Exception:
        clean = raw_response.strip().replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(clean, strict=False)
        except Exception:
            import ast
            return ast.literal_eval(clean)

def generate_ledger_payment_reminder(buyer_name: str, invoice_no: str, amount_due: float, days_overdue: int):
    """
    Generates relationship-preserving payment reminder using dynamic System Prompt.
    """
    prompts = load_system_prompts()
    system_prompt = prompts.get("payment_reminder", DEFAULT_PROMPTS["payment_reminder"])
    
    prompt = f"Buyer: {buyer_name}, Invoice #{invoice_no}, Amount: ₹{amount_due:,.2f}, Days Overdue: {days_overdue} days."
    contents = [{"role": "user", "parts": [{"text": prompt}]}]
    return call_gemini_api(contents, system_instruction=system_prompt, json_mode=False)

def clean_ai_reply(raw_reply: str, field_name: str = "whatsapp_buyer_draft") -> str:
    """
    If AI returns JSON instead of plain conversational text, extract the human message.
    """
    text = raw_reply.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    if text.startswith("{") and "}" in text:
        try:
            parsed = json.loads(text)
            if field_name in parsed:
                return parsed[field_name]
        except Exception:
            pass
    return raw_reply

def simulate_buyer_chat(conversation_history, new_message: str, image_bytes: bytes = None):
    """
    Live WhatsApp Buyer Simulation.
    Answers any buyer query (rates, sample cards, catalog, MOQs) using the system prompt.
    """
    # Fast exact response for standalone greeting
    clean_msg = new_message.strip().lower()
    if clean_msg in ["hello", "hi", "hey", "namaste", "hello!", "hi!", "good morning", "good afternoon", "namaskar", "hello sir", "hi sir"] and not image_bytes:
        return "Hello! Welcome to ABC Buttons.\n\nThank you for connecting with us. We manufacture a wide range of natural and customised buttons for the garment and fashion industry.\n\nHow may we assist you today?"

    catalog_summary = json.dumps([
        {
            "sku": item["sku"],
            "name": item["name"],
            "category": item["category"],
            "material": item["material"],
            "size": item.get("size_ligne", ""),
            "rate_per_gross": item.get("rate_per_gross", item.get("base_rate_per_gross", 0)),
            "stock_gross": item.get("stock_gross", 100),
            "best_for": item.get("recommended_garment", "")
        } for item in SAMPLE_CATALOG
    ], indent=2)
    
    prompts = load_system_prompts()
    base_sys_prompt = prompts.get("visual_matcher", DEFAULT_PROMPTS["visual_matcher"])
    # Strip any strict JSON return instructions so chat speaks naturally
    if "Return output strictly in JSON format with keys:" in base_sys_prompt:
        base_sys_prompt = base_sys_prompt.split("Return output strictly in JSON format with keys:")[0].strip()
    
    system_instruction = f"""{base_sys_prompt}

You are the official AI Sales Executive and Customer Relationship Assistant for ABC Buttons, New Delhi, India.
You are directly chatting with a Garment Exporter / Merchandiser / Buyer on WhatsApp.

CRITICAL RULES FOR CUSTOMER CONVERSATION MODE:
1. SOUND HUMAN, NOT AI:
   - Keep responses very short, ideally 1 to 3 sentences.
   - Answer ONLY what the customer has asked.
   - NEVER use bullet points, technical SKU codes (like ABC-136), or robotic catalogue dumps.
   - Respectful, natural conversational tone in Hindi/Hinglish or English.

2. ONE QUESTION AT A TIME RULE:
   - Ask only ONE single relevant question per turn (e.g. "Aapko kis size mein chahiye?" or "Approx kitni quantity required hai?").
   - Do NOT ask multiple questions together.

3. STRICT PRICING & RATE DISCLOSURE POLICY (MANDATORY):
   - You must NEVER disclose per-piece or per-gross rates, approximate prices, or discounts.
   - When buyer asks for price or quotation:
     "Bilkul! Exact rate aur quotation ke liye hamare sales representative aapki help karenge. Aap unse 9310722777 par contact kar sakte hain."

4. REAL CONVERSATION EXAMPLES:
   Customer: "mujhe agoya button chahiye"
   AI: "Ji, Agoya buttons available hain. Aapko kis size mein chahiye?"

   Customer: "18L white colour"
   AI: "Ji, samajh gaya. Approx kitni quantity required hai?"

   Customer: "100 Gross"
   AI: "Certainly! Kya aap pehle iska free sample card dekhna chahenge?"

5. SAMPLE ENQUIRY WORKFLOW:
   If buyer asks for or agrees to samples:
   - Politely ask for company name, contact person, and delivery address.
   - Mention dispatch: "Free sample card aaj hi local runner/courier dwara nikal jayega."
   - AT THE VERY END, append:
   ```SAMPLE_CARD_DISPATCH
   {{
     \"buyer_company\": \"Buyer Company or 'Pending Address'\",
     \"contact_person\": \"Contact Person Name\",
     \"items_requested\": \"Button details requested\",
     \"sizes\": \"Ligne sizes\",
     \"delivery_address\": \"Address or 'To be confirmed'\",
     \"dispatch_status\": \"Courier Scheduled for Today 3:00 PM\"
   }}
   ```"""

    # Build Gemini multi-turn format - sanitize history to prevent JSON mirroring
    gemini_contents = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        h_text = clean_ai_reply(msg["content"], "whatsapp_buyer_draft")
        if h_text.strip().startswith("{") and "detected_type" in h_text:
            h_text = "Namaste Sir, we have multiple button options available in ready stock."
        gemini_contents.append({
            "role": role,
            "parts": [{"text": h_text}]
        })
        
    # Latest turn
    latest_parts = []
    if image_bytes:
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")
        latest_parts.append({
            "inlineData": {
                "mimeType": "image/jpeg",
                "data": img_b64
            }
        })
    latest_parts.append({"text": new_message if new_message else "Please review this button sample photo."})
    gemini_contents.append({"role": "user", "parts": latest_parts})
    
    raw_out = call_gemini_api(gemini_contents, system_instruction=system_instruction, json_mode=False)
    return clean_ai_reply(raw_out, "whatsapp_buyer_draft")

def simulate_salesman_chat(conversation_history, new_message: str):
    """
    Live WhatsApp Salesman Simulation.
    Receives field notes from salesman (e.g. Rahul, Vikram) via WhatsApp,
    acknowledges in Hindi/Hinglish, and records the sample into pipeline.
    """
    prompts = load_system_prompts()
    system_prompt = prompts.get("salesman_logger", DEFAULT_PROMPTS["salesman_logger"])
    if "Return strictly JSON with these keys." in system_prompt:
        system_prompt = system_prompt.split("Return strictly JSON with these keys.")[0].strip()
    
    system_instruction = f"""{system_prompt}

You are the internal Sales Operations WhatsApp Bot for ABC Buttons, New Delhi.
You are chatting with your field sales executive (e.g., Rahul or Vikram) who is visiting factories in Okhla, Noida, Gurgaon, etc.

CRITICAL INSTRUCTION:
Do NOT output raw JSON keys at the beginning.
Speak directly to the salesman in friendly conversational Hindi/Hinglish (e.g., "Noted Rahul ji! Shahi Exports ka record save kar liya hai.").

RULES:
1. Greet the salesman warmly in Hindi/Hinglish (e.g., "Noted Rahul ji!", "Shabash Vikram ji!").
2. Confirm the exact details received: Company name, Contact person, Sample SKU/size, and bulk order expectation.
3. Let them know that the entry has been recorded in the Master Sample Pipeline and an automated 3-day follow-up reminder has been scheduled.
4. AT THE END of your response, append a JSON block inside triple backticks with tag SALESMAN_LOG_DISPATCH:
```SALESMAN_LOG_DISPATCH
{{
  "company": "Company Name",
  "contact": "Contact Person Name",
  "location": "Location / Industrial Area",
  "sku": "Button SKU or description",
  "sample_qty": "Quantity given",
  "bulk_est": "Bulk requirement estimate",
  "followup_date": "3 days from today",
  "buyer_delivery_message": "Dear [Contact], Greetings from ABC Buttons! Thank you for your valuable time and receiving our button samples. We hope you find them suitable for your collection. Looking forward to building a long-term relationship with [Company]. Warm regards, Team ABC Buttons (9310722777)",
  "buyer_followup_message": "Dear [Contact], Hope you are doing well. Just checking in to see if you had a chance to review the ABC Buttons samples on your garments? We would love to know your feedback. Warm regards, Team ABC Buttons"
}}
```"""

    gemini_contents = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        gemini_contents.append({
            "role": role,
            "parts": [{"text": msg["content"]}]
        })
        
    gemini_contents.append({"role": "user", "parts": [{"text": new_message}]})
    raw_out = call_gemini_api(gemini_contents, system_instruction=system_instruction, json_mode=False)
    return clean_ai_reply(raw_out, "whatsapp_followup_message")

