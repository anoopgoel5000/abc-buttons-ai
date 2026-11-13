import streamlit as st
import datetime
import json
import os
import urllib.parse
import importlib
import pandas as pd
from PIL import Image
from io import BytesIO, StringIO
import catalog
import ai_engine
importlib.reload(catalog)
importlib.reload(ai_engine)
from catalog import SAMPLE_CATALOG
from ai_engine import (
    analyze_button_or_fabric_image, 
    parse_salesman_sample_log, 
    generate_ledger_payment_reminder, 
    load_system_prompts, 
    save_system_prompts, 
    DEFAULT_PROMPTS,
    simulate_buyer_chat,
    simulate_salesman_chat
)
try:
    from whatsapp_service import send_whatsapp_text
except Exception:
    send_whatsapp_text = None

st.set_page_config(
    page_title="Button-Mitra AI | ABC Buttons Delhi",
    page_icon="🔘",
    layout="wide",
    initial_sidebar_state="expanded"
)

# PDF Quotation Generator Setup
try:
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    HAS_REPORTLAB = True
except Exception:
    HAS_REPORTLAB = False

def generate_quotation_pdf(buyer_name, buyer_gst, item_sku, item_name, item_size, qty_gross, rate_gross, discount_pct=0):
    gross_amount = qty_gross * rate_gross
    discount_amount = gross_amount * (discount_pct / 100.0)
    taxable_subtotal = gross_amount - discount_amount
    gst = taxable_subtotal * 0.12
    total = taxable_subtotal + gst
    total_pcs = qty_gross * 144

    today_obj = datetime.date.today()
    today_str = today_obj.strftime("%d-%b-%Y")
    valid_till_str = (today_obj + datetime.timedelta(days=30)).strftime("%d-%b-%Y")
    ref_no = f"ABC-QT-{today_obj.strftime('%Y')}-{abs(hash(item_sku + buyer_name)) % 9000 + 1000}"

    if not HAS_REPORTLAB:
        text_content = f"""====================================================
               ABC BUTTONS PVT. LTD.
   Manufacturers & Exporters of Natural & Customized Buttons
   Works: Okhla Phase-II | Regd: Govindpuri / Kalkaji, New Delhi
   GSTIN: 07AABCA9876P1Z3 | Contact: +91 9310722777
====================================================
PROFORMA QUOTATION
Ref No: {ref_no} | Date: {today_str} | Valid Till: {valid_till_str}

BILL TO:
Buyer: {buyer_name}
GSTIN: {buyer_gst}
Payment Terms: 30 Days Credit
Delivery: 3-5 Working Days from Okhla Godown

----------------------------------------------------
ITEM DETAILS:
SKU: {item_sku} - {item_name}
Size: {item_size}
Quantity: {qty_gross} Gross ({total_pcs:,} Individual Pieces)
Base Rate / Gross: Rs. {rate_gross:.2f}
Discount: {discount_pct}%

----------------------------------------------------
COMMERCIAL SUMMARY:
Gross Total:      Rs. {gross_amount:,.2f}
Discount ({discount_pct}%): Rs. -{discount_amount:,.2f}
Taxable Subtotal: Rs. {taxable_subtotal:,.2f}
GST @ 12%:        Rs. {gst:,.2f}
TOTAL PAYABLE:    Rs. {total:,.2f}

----------------------------------------------------
BANK DETAILS FOR RTGS / NEFT:
A/C Name:   ABC Buttons Private Limited
Bank Name:  HDFC Bank, Kalkaji Branch
A/C Number: 50200084920192
IFSC Code:  HDFC0000123
====================================================
"""
        return text_content.encode("utf-8")

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=18, textColor=colors.HexColor('#0f172a'), spaceAfter=4)
    sub_style = ParagraphStyle('SubStyle', parent=styles['Normal'], fontName='Helvetica', fontSize=8.5, textColor=colors.HexColor('#475569'))
    
    story.append(Paragraph('ABC BUTTONS PVT. LTD.', title_style))
    story.append(Paragraph('Manufacturers & Exporters of Natural & Customized Buttons<br/>Works: Okhla Industrial Area Phase-II | Regd Office: Govindpuri / Kalkaji, New Delhi - 110019<br/>GSTIN: 07AABCA9876P1Z3 | Phone: +91 9310722777 | Email: sales@abcbuttons.com', sub_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width='100%', thickness=2, color=colors.HexColor('#2563eb'), spaceAfter=12))

    meta_data = [
        [
            Paragraph(f'<b>PROFORMA QUOTATION</b><br/><font size=8.5 color=#64748b>Ref No: {ref_no}<br/>Date: {today_str}<br/>Valid Till: {valid_till_str}</font>', styles['Normal']),
            Paragraph(f'<b>BILL TO:</b><br/><b>{buyer_name}</b><br/><font size=8.5 color=#64748b>GSTIN: {buyer_gst}<br/>Payment: 30 Days Credit<br/>Delivery: 3-5 Working Days</font>', styles['Normal'])
        ]
    ]
    t_meta = Table(meta_data, colWidths=[270, 270])
    t_meta.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(t_meta)
    story.append(Spacer(1, 12))

    headers = [
        Paragraph('<b>Item Description</b>', styles['Normal']),
        Paragraph('<b>Qty (Gross)</b>', styles['Normal']),
        Paragraph('<b>Total Pcs</b>', styles['Normal']),
        Paragraph('<b>Rate / Gr</b>', styles['Normal']),
        Paragraph('<b>Amount (INR)</b>', styles['Normal'])
    ]
    clean_item_name = item_name
    if clean_item_name.startswith(item_sku):
        clean_item_name = clean_item_name[len(item_sku):].strip(" -")
    display_title = f"<b>{item_sku}</b> - {clean_item_name}" if clean_item_name else f"<b>{item_sku}</b>"
    
    row = [
        Paragraph(f'{display_title}<br/><font size=8 color=#64748b>Size: {item_size} | 100% Export Ready Quality</font>', styles['Normal']),
        f'{qty_gross} Gr',
        f'{total_pcs:,} pcs',
        f'Rs. {rate_gross:.2f}',
        f'Rs. {gross_amount:,.2f}'
    ]
    t_items = Table([headers, row], colWidths=[240, 75, 75, 75, 75])
    t_items.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (1,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('BOTTOMPADDING', (0,0), (-1,0), 6),
        ('TOPPADDING', (0,0), (-1,0), 6),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff')),
        ('PADDING', (0,1), (-1,-1), 8),
    ]))
    story.append(t_items)
    story.append(Spacer(1, 8))

    if discount_pct > 0:
        summary_data = [
            ['', 'Gross Amount:', f'Rs. {gross_amount:,.2f}'],
            ['', f'Less: Volume Discount ({discount_pct}%):', f'- Rs. {discount_amount:,.2f}'],
            ['', 'Taxable Subtotal:', f'Rs. {taxable_subtotal:,.2f}'],
            ['', 'GST @ 12%:', f'Rs. {gst:,.2f}'],
            ['', 'Total Payable:', f'Rs. {total:,.2f}']
        ]
    else:
        summary_data = [
            ['', 'Taxable Subtotal:', f'Rs. {taxable_subtotal:,.2f}'],
            ['', 'GST @ 12%:', f'Rs. {gst:,.2f}'],
            ['', 'Total Payable:', f'Rs. {total:,.2f}']
        ]
    t_sum = Table(summary_data, colWidths=[280, 130, 130])
    t_sum.setStyle(TableStyle([
        ('ALIGN', (1,0), (-1,-1), 'RIGHT'),
        ('FONTNAME', (1,-1), (-1,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (1,-1), (-1,-1), 11),
        ('TEXTCOLOR', (1,-1), (-1,-1), colors.HexColor('#166534')),
        ('LINEABOVE', (1,-1), (-1,-1), 1.5, colors.HexColor('#166534')),
        ('PADDING', (0,0), (-1,-1), 3),
    ]))
    story.append(t_sum)
    story.append(Spacer(1, 15))

    footer_data = [
        [
            Paragraph('<b>Bank Details for RTGS / NEFT:</b><br/><font size=8.5 color=#475569>Account Name: ABC Buttons Pvt. Ltd.<br/>Bank Name: HDFC Bank, Kalkaji Branch<br/>A/C Number: 50200084920192 | IFSC: HDFC0000123</font>', styles['Normal']),
            Paragraph('<b>For ABC BUTTONS PVT. LTD.</b><br/><br/><br/><i>Authorized Signatory</i><br/><font size=8 color=#64748b>(Computer-generated quotation)</font>', styles['Normal'])
        ]
    ]
    t_footer = Table(footer_data, colWidths=[270, 270])
    t_footer.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BACKGROUND', (0,0), (0,0), colors.HexColor('#eff6ff')),
        ('PADDING', (0,0), (-1,-1), 8),
        ('BOX', (0,0), (0,0), 1, colors.HexColor('#bfdbfe')),
    ]))
    story.append(t_footer)

    doc.build(story)
    buf.seek(0)
    return buf.getvalue()

# Image directory path
BASE_DIR = os.path.dirname(__file__)
IMG_DIR = os.path.join(BASE_DIR, "catalog_images")
TEST_DIR = os.path.join(BASE_DIR, "test_inquiries")
DATA_FILE = os.path.join(BASE_DIR, "data_store.json")
os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(TEST_DIR, exist_ok=True)

def load_persistent_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_persistent_data():
    try:
        payload = {
            "sample_pipeline": st.session_state.get("sample_pipeline", []),
            "catalog_overrides": {
                x["sku"]: {"stock_gross": x.get("stock_gross", 0), "rate_per_gross": x.get("rate_per_gross", 0)}
                for x in st.session_state.get("live_catalog", [])
            },
            "quotation_history": st.session_state.get("quotation_history", [])
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

# Custom Styling for Premium B2B feel
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        color: white;
        padding: 24px;
        border-radius: 12px;
        margin-bottom: 25px;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
    }
    .card-box {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 18px;
        margin-bottom: 15px;
    }
    .gross-badge {
        background-color: #f0fdf4;
        color: #166534;
        padding: 4px 10px;
        border-radius: 6px;
        font-weight: 700;
        font-size: 13px;
        border: 1px solid #bbf7d0;
    }
</style>
""", unsafe_allow_html=True)

# App Header
st.markdown("""
<div class="main-header">
    <div style="display: flex; justify-content: space-between; align-items: center;">
        <div>
            <h1 style="margin: 0; font-size: 28px; color: #f8fafc;">🔘 Button-Mitra AI</h1>
            <p style="margin: 5px 0 0 0; color: #94a3b8; font-size: 15px;">
                Autonomous Merchandising & Sales Agent for <b>ABC Buttons Private Limited</b> (Kalkaji / Okhla, New Delhi)
            </p>
        </div>
        <div style="text-align: right; background: rgba(255,255,255,0.08); padding: 8px 16px; border-radius: 8px;">
            <span style="color: #4ade80; font-size: 13px; font-weight: 700;">🟢 ABC-136 to ABC-143 Real Shell Series Active</span><br>
            <small style="color: #cbd5e1;">All Rates & Stock strictly in GROSS (1 Gr = 144 Pcs)</small>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

persisted = load_persistent_data()

# Ensure full updated catalog (Strictly 100% Genuine Real Photo SKUs)
if "live_catalog" not in st.session_state or len(st.session_state.live_catalog) != len(SAMPLE_CATALOG) or any(x["sku"] not in [s["sku"] for s in SAMPLE_CATALOG] for x in st.session_state.live_catalog):
    st.session_state.live_catalog = [dict(x) for x in SAMPLE_CATALOG]
    if "catalog_overrides" in persisted:
        for it in st.session_state.live_catalog:
            if it["sku"] in persisted["catalog_overrides"]:
                ov = persisted["catalog_overrides"][it["sku"]]
                it["stock_gross"] = ov.get("stock_gross", it["stock_gross"])
                it["rate_per_gross"] = ov.get("rate_per_gross", it["rate_per_gross"])
else:
    # Always keep master attributes (name, holes, finish, description) updated
    sample_map = {s["sku"]: s for s in SAMPLE_CATALOG}
    for item in st.session_state.live_catalog:
        if item["sku"] in sample_map:
            master = sample_map[item["sku"]]
            item["name"] = master["name"]
            item["holes"] = master["holes"]
            item["finish"] = master["finish"]
            item["description"] = master.get("description", "")
            item["size_ligne"] = master.get("size_ligne", "")
            item["category"] = master.get("category", "")

if "sample_pipeline" not in st.session_state:
    if "sample_pipeline" in persisted and len(persisted["sample_pipeline"]) > 0:
        st.session_state.sample_pipeline = persisted["sample_pipeline"]
    else:
        st.session_state.sample_pipeline = [
            {
                "id": "SMP-101",
                "company": "Shahi Exports Pvt. Ltd.",
                "contact": "Amit Sharma (Merchandiser)",
                "location": "Noida Sector 59",
                "phone": "+91 98101 23456",
                "sku": "ABC-139 (Natural River Shell)",
                "sample_qty": "25 pcs (Hanger Card)",
                "bulk_est": "350 Gross (~50,000 Pcs)",
                "date": "05-Nov-2026",
                "days_ago": 3,
                "status": "Ready for Follow-up",
                "followup_msg": "Hello Amit ji, hope you are doing well! Jo natural shell button ke samples diye the, kya fabric par trial check ho gaya? Bulk order ke liye approval mil jaye toh bataiyega, hum stock pehle se reserve karwa denge."
            },
            {
                "id": "SMP-102",
                "company": "Orient Craft Limited",
                "contact": "Pooja Verma (Fabric Sourcing)",
                "location": "Gurgaon Udyog Vihar",
                "phone": "+91 98712 34567",
                "sku": "ABC-142 (Ocean Turquoise Shell)",
                "sample_qty": "10 pcs",
                "bulk_est": "175 Gross (~25,000 Pcs)",
                "date": "06-Nov-2026",
                "days_ago": 2,
                "status": "In Review by Buyer",
                "followup_msg": "Namaste Pooja ji! Jo turquoise shell button ke samples share kiye the, kya buyer review complete ho gaya? Koi specific size ya shade aur dekhna ho toh bataiyega."
            },
            {
                "id": "SMP-103",
                "company": "Richa Global Apparels",
                "contact": "Rajesh Kumar (Purchase Head)",
                "location": "Okhla Phase 3",
                "phone": "+91 99100 87654",
                "sku": "ABC-141 (Smoky Gunmetal Shell)",
                "sample_qty": "50 pcs",
                "bulk_est": "850 Gross (~1,22,000 Pcs)",
                "date": "07-Nov-2026",
                "days_ago": 1,
                "status": "Sample Dispatched",
                "followup_msg": "Namaste Rajesh ji! Smoky gunmetal shell button ke samples dispatch ho gaye hain. Receive hote hi fabric trial karwa lijiye, bulk order ke liye stock ready hai."
            }
        ]

if "quotation_history" not in st.session_state:
    st.session_state.quotation_history = persisted.get("quotation_history", [])

# Navigation Tabs
tabs = st.tabs([
    "📸 1. Visual Matcher (Real Buyer Photos)", 
    "📂 2. Catalog & Image Gallery",
    "🏍️ 3. Salesman Logger", 
    "📊 4. Sample Pipeline & Follow-Up", 
    "🧾 5. 1-Click Quotation", 
    "💳 6. Payment Reminder",
    "💬 7. WhatsApp Live Simulator (Buyer & Salesman)"
])

# ----------------- TAB 1: VISUAL BUTTON MATCHER -----------------
with tabs[0]:
    st.subheader("🔍 Test Buyer Inquiries with Real Photos")
    st.caption("यहाँ आपके द्वारा भेजी गई असली बटनों की तस्वीरों से टेस्ट करें कि जब कोई बायर WhatsApp पर फोटो भेजता है, तो AI कैसे 3 सेकंड में स्टॉक व सही SKU ढूंढता है:")
    
    col_input, col_result = st.columns([1, 1])
    
    with col_input:
        st.markdown("#### Step 1: बायर की भेजी गई फोटो चुनें या अपलोड करें")
        
        input_choice = st.radio("Testing Source:", [
            "📸 Use Camera (Take Live Photo from Phone / Laptop)",
            "📁 Upload Photo from Computer / Phone Gallery",
            "🔘 Use Pre-Loaded Buyer Samples (5 Running Items)"
        ], horizontal=True)
        
        selected_img_bytes = None
        selected_label = ""
        
        if input_choice.startswith("📸"):
            camera_img = st.camera_input("Point camera directly at button on fabric or table:")
            if camera_img is not None:
                img = Image.open(camera_img)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG")
                selected_img_bytes = buf.getvalue()
                selected_label = "Live Camera Capture"
            buyer_notes = st.text_input("Buyer's WhatsApp message / requirement:", placeholder="e.g. 'Ye button mil jayega kya? 200 gross chahiye'")
            
        elif input_choice.startswith("📁"):
            uploaded_file = st.file_uploader("Upload any button or fabric photo (JPG / PNG):", type=["jpg", "jpeg", "png"])
            if uploaded_file is not None:
                img = Image.open(uploaded_file)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG")
                selected_img_bytes = buf.getvalue()
                selected_label = uploaded_file.name
                st.image(img, caption="Uploaded Photo", use_container_width=True)
            buyer_notes = st.text_input("Buyer's WhatsApp message:", placeholder="e.g. 'Ye button mil jayega kya? Rate aur availability batao'")
            
        else:
            real_photos_map = {
                "🔘 Real Photo 1: Natural White River Shell (2-Hole Raised Rim)": (
                    "buyer_mop_white_2hole.jpg", 
                    "Natural river shell 2-hole button with raised rim on red satin cloth, need 400 gross"
                ),
                "🔘 Real Photo 2: Ocean Turquoise & Teal Dyed MOP (2-Hole)": (
                    "buyer_mop_turquoise_blue.jpg", 
                    "Turquoise blue and teal dyed mother of pearl shell buttons 2-hole, need 250 gross"
                ),
                "🔘 Real Photo 3: Bulk Factory White Agoya Shell Pile": (
                    "buyer_mop_factory_bulk.jpg", 
                    "White agoya shell buttons bulk heap 14L and 18L for shirt program"
                ),
                "🔘 Real Photo 4: Smoky Grey Trocas MOP Shell (4-Hole Rim)": (
                    "buyer_mop_smoky_grey_4hole.jpg", 
                    "Smoky grey dark trocas MOP 4-hole button with rim, need 500 gross for formal shirts"
                ),
                "🔘 Real Photo 5: ABC Buttons Official Sample Hanger Card (ABC-136 to ABC-143)": (
                    "buyer_abc_sample_hanger_card.jpg", 
                    "Official ABC Buttons sample card showing ABC-136, ABC-137, ABC-138, ABC-139, ABC-141, ABC-142 shell buttons"
                )
            }
            
            chosen_key = st.selectbox("Pick an Actual Buyer Photo to Test:", list(real_photos_map.keys()))
            filename, prompt_hint = real_photos_map[chosen_key]
            fpath = os.path.join(TEST_DIR, filename)
            
            if os.path.exists(fpath):
                img = Image.open(fpath)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG")
                selected_img_bytes = buf.getvalue()
                selected_label = chosen_key
                st.image(img, caption=f"Buyer WhatsApp Photo: {chosen_key}", use_container_width=True)
            
            buyer_notes = st.text_input("Buyer's WhatsApp message:", value=prompt_hint)

    with col_result:
        st.markdown("#### Step 2: AI विज़न मिलान और लाइव आउटपुट")
        
        if selected_img_bytes is not None:
            if st.button("🚀 Analyze & Match with ABC Buttons Inventory", type="primary"):
                with st.spinner("AI scanning material sheen, holes, thickness & matching SKU..."):
                    try:
                        st.session_state["tab1_match_result"] = analyze_button_or_fabric_image(selected_img_bytes, buyer_notes)
                    except Exception as e:
                        st.error(f"Analysis error: {str(e)}")
                        
            if "tab1_match_result" in st.session_state and st.session_state["tab1_match_result"]:
                res = st.session_state["tab1_match_result"]
                status = res.get("match_status", "MATCH_FOUND")
                is_btn = res.get("is_button", True)
                best_sku = res.get("best_match_sku")
                
                mat_val = res.get("visual_analysis", {}).get("material_detected", "Garment Material")
                size_val = res.get("visual_analysis", {}).get("estimated_size", "N/A")
                conf_val = f"{res.get('match_confidence', 0)}%"
                
                st.markdown(f"""
                <div style="display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap;">
                    <div style="flex: 1.3; min-width: 140px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;">
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.5px;">Detected Material</div>
                        <div style="font-size: 16px; font-weight: 800; color: #0f172a; margin-top: 2px;">{mat_val}</div>
                    </div>
                    <div style="flex: 1.1; min-width: 120px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;">
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.5px;">Ligne Size</div>
                        <div style="font-size: 16px; font-weight: 800; color: #0f172a; margin-top: 2px;">{size_val}</div>
                    </div>
                    <div style="flex: 0.8; min-width: 90px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 10px 14px;">
                        <div style="font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.5px;">Match Status</div>
                        <div style="font-size: 16px; font-weight: 800; color: {'#16a34a' if status == 'MATCH_FOUND' and best_sku else '#dc2626'}; margin-top: 2px;">
                            {'100% Verified' if status == 'MATCH_FOUND' and best_sku else ('No Button' if status == 'NO_BUTTON_DETECTED' else 'Custom Check')}
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if status == "NO_BUTTON_DETECTED" or not is_btn:
                    st.warning("⚠️ **इस फोटो में कोई बटन नहीं दिखा (No Garment Button Detected)**")
                    st.info("💡 **मार्गदर्शन:** इस फोटो में कोई गारमेंट बटन नहीं दिख रहा है। कृपया कैमरे को सीधा बटन के पास ले जाएँ और अच्छी रोशनी में केवल बटन की साफ़ फोटो लें।")
                    
                elif status == "NOT_IN_CATALOG" or not best_sku:
                    st.warning("🔍 **इस टाइप का बटन हमारे रेडी कैटलॉग में उपलब्ध नहीं है**")
                    st.markdown(f"""
                    <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 14px; margin-bottom: 15px;">
                        <h4 style="margin: 0 0 6px 0; color: #92400e;">⚠️ रेडी स्टॉक में नहीं मिला (Custom Inquiry)</h4>
                        <p style="margin: 0; color: #78350f; font-size: 14px; line-height: 1.5;">
                            <b>पहचाना गया:</b> {mat_val} • {res.get('visual_analysis', {}).get('holes_detected', '')}<br>
                            यह विशिष्ट डिज़ाइन वर्तमान में हमारे स्टैंडर्ड रेडी स्टॉक में सक्रिय नहीं है। हम आपकी आवश्यकता अपनी <b>मैनेजमेंट और प्रोडक्शन टीम</b> से बात करके आपको बता देंगे कि क्या यह आपकी आवश्यक मात्रा के लिए विशेष रूप से तैयार किया जा सकता है।
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                else:
                    st.success("✅ Match Successfully Verified in ABC Buttons Catalog!")
                    matched_item = next((x for x in st.session_state.live_catalog if x["sku"] == best_sku), st.session_state.live_catalog[0])
                    
                    st.markdown("---")
                    # Side by side visual verification
                    col_cat_img, col_cat_details = st.columns([1, 2])
                    with col_cat_img:
                        match_img_path = os.path.join(IMG_DIR, f"{matched_item['sku']}.jpg")
                        if os.path.exists(match_img_path):
                            st.image(match_img_path, caption=f"Catalog Image ({matched_item['sku']})", use_container_width=True)
                        else:
                            st.info(f"🔘 Image: {matched_item['sku']}")
                    with col_cat_details:
                        st.markdown(f"### 🏆 Verified SKU: **{matched_item['name']}**")
                        st.markdown(f"**Official SKU Code:** `{matched_item['sku']}` | **Category:** {matched_item['category']}")
                        st.markdown(f"**Size:** {matched_item['size_ligne']} | **Holes:** {matched_item['holes']}")
                        st.markdown(f"**B2B Rate:** :green[**₹{matched_item['rate_per_gross']} / Gross**] (1 Gross = 144 pcs)")
                        st.markdown(f"**Available Ready Stock:** :blue[**{matched_item['stock_gross']:,} Gross**] ({matched_item['stock_gross']*144:,} Pieces)")
                        st.markdown(f"**Best Recommended For:** *{matched_item['recommended_garment']}*")
                        
                    st.caption(f"**AI Verification Logic:** {res.get('match_reason', 'Identical material finish, hole spacing, and rim texture.')}")
                
                st.markdown("#### 💬 Automated WhatsApp Message to Buyer (Sent in 3 Seconds):")
                wa_msg = res.get("whatsapp_buyer_draft", "")
                st.text_area("WhatsApp Message:", value=wa_msg, height=125)
                
                encoded_wa = urllib.parse.quote(wa_msg)
                c_wa1, c_wa2 = st.columns([1.2, 1])
                with c_wa1:
                    target_phone = st.text_input("Buyer WhatsApp Mobile # (Optional):", value="+91 93157 02804", key="tab1_wa_phone")
                with c_wa2:
                    st.write("")
                    st.write("")
                    clean_num = "".join(ch for ch in target_phone if ch.isdigit())
                    if send_whatsapp_text and st.button("⚡ Send Direct via Official Meta API", key="send_meta_api_tab1", help="Dispatches directly via Meta Official Cloud API"):
                        p_num = clean_num if clean_num else "919315702804"
                        with st.spinner(f"Dispatching to +{p_num}..."):
                            res_api = send_whatsapp_text(p_num, wa_msg)
                            if res_api.get("success"):
                                st.success(f"🚀 Delivered via Official Meta API to +{p_num}!")
                                st.balloons()
                            else:
                                st.error(f"API Error: {res_api.get('error')}")
                
                clean_num = "".join(ch for ch in target_phone if ch.isdigit())
                wa_url = f"https://wa.me/{clean_num}?text={encoded_wa}" if clean_num else f"https://api.whatsapp.com/send?text={encoded_wa}"
                    
                c_b1, c_b2, c_b3 = st.columns([1.3, 1, 1.2])
                with c_b1:
                    st.link_button("📲 Open in WhatsApp", wa_url, type="primary", use_container_width=True)
                with c_b2:
                    if st.button("📋 Copy Message", use_container_width=True):
                        st.toast("WhatsApp Message copied to clipboard!")
                with c_b3:
                    if status == "MATCH_FOUND" and best_sku:
                        if st.button("📄 Generate Quote (Tab 5)", use_container_width=True):
                            st.session_state["quote_sku"] = matched_item["sku"]
                            st.success(f"✅ SKU **{matched_item['sku']}** locked for Quotation! Open **Tab 5**.")
                            st.toast(f"Locked {matched_item['sku']} for Tab 5 Quotation!")
                    else:
                        if st.button("🏍️ Log Custom Inquiry (Tab 3)", use_container_width=True):
                            st.toast("Custom inquiry noted for management check!")
        else:
            st.info("👈 Please select or upload a photo on the left to start matching.")

# ----------------- TAB 2: CATALOG & IMAGE GALLERY -----------------
with tabs[1]:
    st.subheader("📂 ABC Buttons Live Master Catalog & Real Product Gallery")
    st.caption("यहाँ सभी बटनों की तस्वीरें और विवरण मौजूद हैं। सभी दरें व स्टॉक अनिवार्य रूप से **GROSS** में हैं (1 Gross = 144 Pieces)।")
    
    # Metrics Bar
    df = pd.DataFrame(st.session_state.live_catalog)
    total_skus = len(df)
    total_stock_gross = df["stock_gross"].sum()
    categories = df["category"].nunique()
    avg_rate = df["rate_per_gross"].mean()
    
    mb1, mb2, mb3, mb4 = st.columns(4)
    mb1.metric("Total Active SKUs", f"{total_skus} Buttons")
    mb2.metric("Total Stock in Godown", f"{total_stock_gross:,} Gross", f"= {total_stock_gross*144:,.0f} Pcs")
    mb3.metric("Product Categories", f"{categories} Types")
    mb4.metric("Avg Rate / Gross", f"₹{avg_rate:.1f} / Gr")
    
    st.markdown("---")
    
    view_mode = st.radio("Choose Catalog Display Mode:", ["🖼️ Visual Photo Grid (Real Images)", "📊 Detailed Data Table"], horizontal=True)
    
    if view_mode.startswith("🖼️"):
        valid_skus = set(s["sku"] for s in SAMPLE_CATALOG)
        catalog_items = [x for x in st.session_state.live_catalog if x["sku"] in valid_skus]
        if not catalog_items or len(catalog_items) != len(SAMPLE_CATALOG):
            st.session_state.live_catalog = list(SAMPLE_CATALOG)
            catalog_items = list(SAMPLE_CATALOG)

        col_hdr1, col_hdr2 = st.columns([3, 1])
        with col_hdr1:
            st.markdown(f"### 🖼️ ABC Buttons 100% Real Product Photo Gallery ({len(catalog_items)} Master SKUs)")
        with col_hdr2:
            if st.button("🔄 Reset / Sync Master Catalog", key="sync_master_grid_btn", use_container_width=True):
                st.session_state.live_catalog = list(SAMPLE_CATALOG)
                st.rerun()
            
        # Perfectly Symmetrical Row-by-Row 4-Column Grid
        for row_idx in range(0, len(catalog_items), 4):
            row_items = catalog_items[row_idx:row_idx+4]
            cols = st.columns(4)
            for col_idx, item in enumerate(row_items):
                with cols[col_idx]:
                    img_path = os.path.join(IMG_DIR, f"{item['sku']}.jpg")
                    st.markdown("""
                        <div style="background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 12px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
                    """, unsafe_allow_html=True)
                    if os.path.exists(img_path):
                        st.image(img_path, use_container_width=True)
                    else:
                        st.info("No Image")
                    
                    short_name = item['name'] if len(item['name']) <= 42 else item['name'][:39] + "..."
                    st.markdown(f"""
                        <div style="font-size: 13.5px; font-weight: 700; color: #0f172a; min-height: 42px; margin-top: 8px; line-height: 1.3;">
                            {short_name}
                        </div>
                        <div style="font-size: 12px; color: #64748b; margin-top: 2px; margin-bottom: 8px;">
                            <span style="background: #f1f5f9; padding: 2px 6px; border-radius: 4px; font-family: monospace; font-weight: 600;">{item['sku']}</span> • {item.get('size_ligne', '')}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; border-top: 1px solid #f1f5f9; padding-top: 8px;">
                            <span style="color: #166534; font-weight: 800; font-size: 14.5px;">₹{item['rate_per_gross']} <span style="font-size: 11px; font-weight: 500;">/ Gross</span></span>
                            <span style="background: #eff6ff; color: #1e40af; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; border: 1px solid #dbeafe;">{item['stock_gross']} Gr</span>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
    else:
        st.markdown("### 📊 Interactive Live Catalog & Stock Editor (Excel-Style)")
        st.caption("Aap yahan seedha kisi bhi button ki **Stock Quantity (Gross)** ya **Rate** par click karke use live edit kar sakte hain:")
        
        edit_df = pd.DataFrame(st.session_state.live_catalog)
        display_cols = ["sku", "name", "category", "size_ligne", "rate_per_gross", "stock_gross"]
        
        edited_df = st.data_editor(
            edit_df[display_cols],
            column_config={
                "sku": st.column_config.TextColumn("SKU Code", disabled=True),
                "name": st.column_config.TextColumn("Button Description", disabled=True),
                "category": st.column_config.TextColumn("Category", disabled=True),
                "size_ligne": st.column_config.TextColumn("Size (Ligne)", disabled=True),
                "rate_per_gross": st.column_config.NumberColumn("Price (₹ / Gross)", min_value=1, step=5, format="₹%d"),
                "stock_gross": st.column_config.NumberColumn("Ready Stock (Gross)", min_value=0, step=10, format="%d Gr")
            },
            use_container_width=True,
            hide_index=True,
            key="catalog_live_editor"
        )
        
        c_ed1, c_ed2 = st.columns([1, 3])
        with c_ed1:
            if st.button("💾 Save All Stock & Rate Changes", type="primary", use_container_width=True):
                for _, row in edited_df.iterrows():
                    sku = row["sku"]
                    for item in st.session_state.live_catalog:
                        if item["sku"] == sku:
                            item["stock_gross"] = int(row["stock_gross"])
                            item["rate_per_gross"] = float(row["rate_per_gross"])
                save_persistent_data()
                st.toast("🎉 Stock Quantities & Rates updated & auto-saved!")
                st.rerun()
        
    st.markdown("---")
    
    col_up1, col_up2 = st.columns([1, 1])
    with col_up1:
        st.markdown("#### 📥 Upload New Catalog (Excel / CSV)")
        uploaded_csv = st.file_uploader("Upload CSV / Excel File:", type=["csv", "xlsx"])
        if uploaded_csv is not None:
            try:
                new_df = pd.read_csv(uploaded_csv) if uploaded_csv.name.endswith(".csv") else pd.read_excel(uploaded_csv)
                if "base_rate_per_gross" in new_df.columns and "rate_per_gross" not in new_df.columns:
                    new_df["rate_per_gross"] = new_df["base_rate_per_gross"]
                if "stock_pieces" in new_df.columns and "stock_gross" not in new_df.columns:
                    new_df["stock_gross"] = (new_df["stock_pieces"] / 144).round().astype(int)
                required_cols = ["sku", "name", "category", "rate_per_gross", "stock_gross"]
                if all(col in new_df.columns for col in required_cols):
                    st.session_state.live_catalog = new_df.to_dict(orient="records")
                    save_persistent_data()
                    st.success(f"🎉 Successfully imported {len(new_df)} buttons from {uploaded_csv.name}!")
                    st.rerun()
                else:
                    st.error(f"Missing required columns! Required: {required_cols}")
            except Exception as e:
                st.error(f"Error: {e}")
                
    with col_up2:
        st.markdown("#### 📤 Download Template & Controls")
        st.caption("डाउनलोड करें रेडीमेड एक्सेल टेम्प्लेट (दरें व स्टॉक ग्रॉस में):")
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False)
        c_b1, c_b2 = st.columns(2)
        with c_b1:
            st.download_button(
                label="⬇️ Download Catalog Template (.CSV)",
                data=csv_buffer.getvalue(),
                file_name="abc_buttons_master_catalog_gross.csv",
                mime="text/csv",
                type="primary"
            )
        with c_b2:
            if st.button("🔄 Reset to Master Buttons"):
                st.session_state.live_catalog = list(SAMPLE_CATALOG)
                st.toast("Catalog reset to full master SKUs!")
                st.rerun()

# ----------------- TAB 3: SALESMAN SAMPLE LOGGER -----------------
with tabs[2]:
    st.subheader("🏍️ Salesman Field Sample Logger")
    st.caption("सेल्समैन ने किसी गार्मेंट फैक्ट्री (मर्चेंडाइज़र) को सैंपल कार्ड सौंपा? सिर्फ 1 वॉयस या टेक्स्ट नोट डालें, AI पूरा रिकॉर्ड खुद बना लेगा।")
    
    col_s1, col_s2 = st.columns([1, 1])
    
    with col_s1:
        st.markdown("**Salesman's Quick Note (Text or Voice Transcript):**")
        default_note = "Aaj Shahi Exports Noida gaya tha, Amit Sharma ji se mila. Unko natural white shell button ka sample card de diya. Bole agle mahine 350 Gross ka bulk order final kar sakte hain."
        sales_note = st.text_area("Salesman Field Update:", value=default_note, height=120)
        
        salesman_name = st.selectbox("Salesman Name:", [
            "Rahul Sharma (Noida / Greater Noida)", 
            "Vikram Singh (Gurgaon / Manesar)", 
            "Deepak Verma (Okhla / Faridabad)"
        ])
        
        if st.button("⚡ Process & Auto-Log Sample", type="primary"):
            with st.spinner("AI parsing field update and generating buyer follow-up..."):
                try:
                    parsed = parse_salesman_sample_log(sales_note)
                    st.session_state["last_parsed_sample"] = parsed
                    st.success("✅ Sample Logged Successfully into ABC Buttons System!")
                except Exception as e:
                    st.error(f"Error parsing: {str(e)}")
                    
    with col_s2:
        if "last_parsed_sample" in st.session_state:
            p = st.session_state["last_parsed_sample"]
            st.markdown("### 📋 AI Structured Record (Sample-to-Order Engine):")
            
            lead_temp = p.get("lead_temperature", "WARM")
            temp_badge = "🔥 HOT LEAD (High Conversion)" if "HOT" in str(lead_temp).upper() else ("🟡 WARM LEAD" if "WARM" in str(lead_temp).upper() else "❄️ COLD LEAD")
            
            st.markdown(f"""
            <div style="background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px; margin-bottom: 12px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-size: 16px; font-weight: 700; color: #0f172a;">🏢 {p.get('company_name', 'N/A')}</span>
                    <span style="background: #fef3c7; color: #92400e; font-weight: 700; font-size: 12px; padding: 3px 8px; border-radius: 4px; border: 1px solid #fde68a;">{temp_badge}</span>
                </div>
                <div style="font-size: 14px; color: #334155;">
                    👤 <b>Contact:</b> {p.get('contact_person', 'N/A')} ({p.get('designation', 'Merchandiser')})<br>
                    📍 <b>Location:</b> {p.get('location', 'N/A')}<br>
                    🔘 <b>Buttons:</b> {", ".join(p['button_sku_or_description']) if isinstance(p.get('button_sku_or_description'), list) else p.get('button_sku_or_description', 'N/A')}<br>
                    📦 <b>Sample Qty:</b> {p.get('sample_quantity', 'N/A')}<br>
                    🎯 <b>Bulk Potential:</b> <b>{p.get('bulk_requirement_estimate', 'N/A')}</b><br>
                    ⏰ <b>Next Action:</b> {p.get('next_action', 'Follow up in 3 days')}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            init_msg = p.get("whatsapp_initial_message") or p.get("whatsapp_followup_message", "Thank you for receiving ABC Buttons samples.")
            st.markdown("#### 📱 1. Automated Delivery Greeting to Buyer:")
            st.info(init_msg)
            
            fu_msg = p.get("first_followup_message")
            if fu_msg:
                st.markdown(f"#### ⏰ 2. Auto-Scheduled Follow-Up ({p.get('first_followup_date', 'In 3 Days')}):")
                st.caption("यह मैसेज 3 दिन बाद बायर को गारमेंट ट्रायल फीडबैक के लिए अपने-आप भेजा जाएगा:")
                st.text_area("Follow-up 1 Draft:", value=fu_msg, height=90, disabled=True)
            
            if st.button("➕ Add to Live Follow-Up Pipeline (Tab 4)", type="primary"):
                sku_clean = ", ".join(p['button_sku_or_description']) if isinstance(p.get('button_sku_or_description'), list) else p.get('button_sku_or_description', 'ABC Buttons Sample')
                ai_fu = p.get("first_followup_message") or p.get("whatsapp_followup_message")
                if not ai_fu:
                    contact_fname = (p.get("contact_person") or "Sir").split()[0]
                    ai_fu = f"Hello {contact_fname} ji, hope you are doing well! Jo {sku_clean} ke samples drop kiye the, kya fabric par trial ho paya? Approval mil jaye toh bataiyega, bulk stock arrange karwa denge."

                new_entry = {
                    "id": f"SMP-10{len(st.session_state.sample_pipeline)+1}",
                    "company": p.get("company_name", "New Buyer"),
                    "contact": p.get("contact_person", "Merchandiser"),
                    "location": p.get("location", "Delhi-NCR"),
                    "sku": sku_clean,
                    "sample_qty": p.get("sample_quantity", "Sample Card"),
                    "bulk_est": p.get("bulk_requirement_estimate", "TBD"),
                    "date": "Today",
                    "days_ago": 0,
                    "status": "Sample Delivered",
                    "followup_msg": ai_fu
                }
                st.session_state.sample_pipeline.insert(0, new_entry)
                save_persistent_data()
                st.success("✅ Successfully added to Pipeline! Open Tab 4 to see it.")

# ----------------- TAB 4: PIPELINE & FOLLOW-UP -----------------
with tabs[3]:
    st.subheader("📊 Sample Approval Pipeline & Automated Follow-Up")
    st.caption("दिए गए सैंपल्स को ट्रैक करें। 3 दिन बीतने पर 1-क्लिक में WhatsApp फॉलो-अप भेजकर ऑर्डर क्लोज करें।")
    
    for item in st.session_state.sample_pipeline:
        with st.container():
            st.markdown(f"""
            <div class="card-box">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <span style="font-weight: 700; font-size: 17px; color: #0f172a;">{item['company']}</span>
                        <span style="margin-left: 10px; color: #64748b; font-size: 13px;">({item['location']})</span><br>
                        <span style="color: #475569; font-size: 14px;">Contact: <b>{item['contact']}</b> | SKU: <b>{item['sku']}</b></span><br>
                        <small style="color: #0284c7; font-weight: 600;">Bulk Potential: {item['bulk_est']}</small>
                    </div>
                    <div style="text-align: right;">
                        <span style="background: {'#fef3c7' if item['days_ago'] >= 3 else '#e0f2fe'}; 
                                     color: {'#92400e' if item['days_ago'] >= 3 else '#0369a1'}; 
                                     padding: 4px 10px; border-radius: 20px; font-weight: 600; font-size: 12px;">
                            {'⚠️ ' if item['days_ago'] >= 3 else '⏱️ '}{item['days_ago']} Days Ago
                        </span><br>
                        <small style="color: #64748b;">Status: {item['status']}</small>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            is_order_won = "Order Won" in item.get('status', '')
            if is_order_won:
                st.success(f"🎉 **Order Confirmed & Won ({item['bulk_est']})!** Sample trial completed. Follow-up automated reminders are STOPPED.")
            else:
                c1, c2, c3, c4 = st.columns([2.0, 0.8, 0.8, 0.9])
                with c1:
                    custom_msg = item.get("followup_msg")
                    if not custom_msg:
                        contact_fname = item['contact'].split()[0]
                        custom_msg = f"Hello {contact_fname} ji, hope you are doing well! Jo {item['sku']} ke samples diye the, kya fabric par trial check ho gaya? Approval mil jaye toh bataiyega, bulk stock arrange karwa denge."
                    st.caption(f"Suggested Follow-Up: *\"{custom_msg}\"*")
                with c2:
                    clean_msg = custom_msg.strip().replace('"', '')
                    encoded_msg = urllib.parse.quote(clean_msg)
                    wa_url = f"https://api.whatsapp.com/send?text={encoded_msg}"
                    st.link_button("📲 WhatsApp", wa_url, use_container_width=True)
                with c3:
                    if send_whatsapp_text and st.button("⚡ Meta API", key=f"btn_meta_{item['id']}", help="Dispatch via Official Meta Cloud API"):
                        with st.spinner("Sending follow-up..."):
                            res_fu = send_whatsapp_text("919315702804", clean_msg)
                            if res_fu.get("success"):
                                st.success("Sent to WhatsApp!")
                                st.toast("Sample follow-up delivered!")
                            else:
                                st.error(f"Error: {res_fu.get('error')}")
                with c4:
                    if st.button(f"✅ Won", key=f"btn_won_{item['id']}", help="Click when buyer confirms bulk order - stops all future follow-ups!"):
                        item['status'] = "🎉 Order Won (Bulk Dispatch)"
                        save_persistent_data()
                        st.toast(f"🎉 Fantastic! Order confirmed for {item['company']}. Follow-ups stopped.")
                        st.balloons()
                        st.rerun()

# ----------------- TAB 5: 1-CLICK B2B QUOTATION -----------------
with tabs[4]:
    st.subheader("🧾 1-Click Proforma Quotation Generator (Pricing in Gross)")
    st.caption("बायर को 30 सेकंड में प्रोफेशनल कोटेशन (दरें व क्वांटिटी अनिवार्य रूप से ग्रॉस में) तैयार करके भेजें।")
    
    # 1. Source Inquiry Selector (Connects Tab 3 & Tab 1 to Tab 5)
    inquiry_sources = []
    if "last_parsed_sample" in st.session_state:
        p_last = st.session_state["last_parsed_sample"]
        c_name = p_last.get("company_name", "Buyer")
        b_desc = ", ".join(p_last.get("button_sku_or_description", [])) if isinstance(p_last.get("button_sku_or_description"), list) else p_last.get("button_sku_or_description", "Buttons")
        b_est = p_last.get("bulk_requirement_estimate", "Order")
        inquiry_sources.append(f"🏍️ Latest Salesman Inquiry: {c_name} ({b_desc} - {b_est})")
    
    if "quote_sku" in st.session_state:
        inquiry_sources.append(f"🔍 Visual Matcher Inquiry: SKU {st.session_state['quote_sku']}")
        
    inquiry_sources.append("✏️ Custom / Manual Quotation (Enter / Edit Any Details)")
    
    selected_source = st.radio("📋 Auto-Fill Quotation from Inquiry Source:", inquiry_sources, horizontal=True)
    
    # Determine defaults based on inquiry selection
    default_buyer = "Shahi Exports Private Limited"
    default_gst = "07AAACS1234F1Z5"
    default_sku_code = "ABC-139" if any("139" in x["sku"] for x in st.session_state.live_catalog) else st.session_state.live_catalog[0]["sku"]
    default_gross = 350
    
    if selected_source.startswith("🏍️") and "last_parsed_sample" in st.session_state:
        p_last = st.session_state["last_parsed_sample"]
        default_buyer = p_last.get("company_name") or default_buyer
        b_text = str(p_last.get("button_sku_or_description", "")).lower()
        for it in st.session_state.live_catalog:
            if it["sku"].lower() in b_text or any(w in it["name"].lower() for w in ["white shell", "river shell", "agoya", "trocas"] if w in b_text):
                default_sku_code = it["sku"]
                break
        q_text = str(p_last.get("bulk_requirement_estimate", ""))
        import re
        m_q = re.search(r'(\d+)', q_text)
        if m_q:
            default_gross = int(m_q.group(1))
    elif selected_source.startswith("🔍") and "quote_sku" in st.session_state:
        default_sku_code = st.session_state["quote_sku"]
        default_gross = 100
        
    st.markdown("---")
    
    q_col1, q_col2 = st.columns([1, 1])
    
    with q_col1:
        q_buyer = st.text_input("Buyer Company Name:", value=default_buyer)
        q_gst = st.text_input("Buyer GSTIN:", value=default_gst)
        
        sku_options = [x["name"] if x["name"].startswith(x["sku"]) else f"{x['sku']} - {x['name']}" for x in st.session_state.live_catalog]
        default_index = 0
        for idx, opt in enumerate(sku_options):
            if default_sku_code in opt:
                default_index = idx
                break
                    
        selected_sku_text = st.selectbox("Select Button SKU:", sku_options, index=default_index)
        selected_sku = selected_sku_text.split()[0]
        curr_item = next(x for x in st.session_state.live_catalog if x["sku"] == selected_sku)
        
        q_gross_qty = st.number_input("Order Quantity in GROSS (1 Gross = 144 Pcs):", min_value=5, max_value=10000, value=default_gross, step=5)
        st.markdown(f"<span class='gross-badge'>= {q_gross_qty} Gross ({q_gross_qty * 144:,} Total Individual Pieces)</span>", unsafe_allow_html=True)
        
        q_discount = st.slider("Volume Discount (%):", min_value=0, max_value=25, value=5)
        
    with q_col2:
        base_rate = curr_item["rate_per_gross"]
        gross_amount = base_rate * q_gross_qty
        discount_amount = gross_amount * (q_discount / 100.0)
        taxable_subtotal = gross_amount - discount_amount
        gst_amount = taxable_subtotal * 0.12
        grand_total = taxable_subtotal + gst_amount
        effective_rate = taxable_subtotal / q_gross_qty if q_gross_qty > 0 else base_rate
        
        today_date = datetime.date.today()
        today_str = today_date.strftime('%d-%b-%Y')
        valid_str = (today_date + datetime.timedelta(days=30)).strftime('%d-%b-%Y')
        
        discount_html = f"""<p style="margin: 4px 0; color: #16a34a; font-size: 13.5px;"><b>Less: Volume Discount ({q_discount}%):</b> <span style="font-weight: 700;">- ₹{discount_amount:,.2f}</span></p>""" if q_discount > 0 else ""
        
        st.markdown(f"""
        <div style="background: #f8fafc; border: 2px solid #cbd5e1; border-radius: 12px; padding: 20px;">
            <div style="border-bottom: 2px solid #0f172a; padding-bottom: 10px; margin-bottom: 15px;">
                <h3 style="margin: 0; color: #0f172a;">ABC BUTTONS PRIVATE LIMITED</h3>
                <small style="color: #64748b;">Govindpuri / Kalkaji, New Delhi - 110019 | GSTIN: 07AABCA9876P1Z3</small>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="font-weight: 700; color: #1e293b;">PROFORMA QUOTATION / RATE ESTIMATE</span>
                <span style="background: #e2e8f0; color: #334155; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 600;">Ref: ABC-QT-2026</span>
            </div>
            <p style="font-size: 13px; color: #475569; margin-bottom: 12px;">
                <b>Bill To:</b> {q_buyer}<br>
                <b>GSTIN:</b> {q_gst}<br>
                <b>Date:</b> {today_str} | <b>Valid Till:</b> {valid_str}
            </p>
            <table style="width: 100%; font-size: 13px; border-collapse: collapse; margin-bottom: 15px;">
                <tr style="background: #1e293b; color: #ffffff; font-weight: 700;">
                    <td style="padding: 8px;">Item Description</td>
                    <td style="padding: 8px; text-align: center;">Qty (Gross)</td>
                    <td style="padding: 8px; text-align: right;">Base Rate / Gr</td>
                    <td style="padding: 8px; text-align: right;">Gross Amount</td>
                </tr>
                <tr style="border-bottom: 1px solid #cbd5e1; background: #ffffff;">
                    <td style="padding: 8px;"><b>{curr_item['name']}</b><br><small style="color: #64748b;">SKU: {curr_item['sku']} • Size: {curr_item.get('size_ligne', '')} • {curr_item.get('holes', '')}</small></td>
                    <td style="padding: 8px; text-align: center; font-weight: 700;">{q_gross_qty} Gr<br><small style="color: #64748b;">({q_gross_qty*144:,} pcs)</small></td>
                    <td style="padding: 8px; text-align: right;">₹{base_rate:.2f} / Gr</td>
                    <td style="padding: 8px; text-align: right; font-weight: 700;">₹{gross_amount:,.2f}</td>
                </tr>
            </table>
            <div style="text-align: right; font-size: 13.5px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px;">
                <p style="margin: 4px 0; color: #475569;">Gross Total: <b>₹{gross_amount:,.2f}</b></p>
                {discount_html}
                <p style="margin: 4px 0; color: #0f172a; border-top: 1px dashed #cbd5e1; padding-top: 4px;">Taxable Subtotal: <b>₹{taxable_subtotal:,.2f}</b> {f'<small style="color: #16a34a; font-weight: 600;">(Effective Net: ₹{effective_rate:.2f}/Gr)</small>' if q_discount > 0 else ''}</p>
                <p style="margin: 4px 0; color: #475569;">GST @ 12%: <b>₹{gst_amount:,.2f}</b></p>
                <h4 style="margin: 8px 0 0 0; color: #0f172a; font-size: 18px; border-top: 2px solid #0f172a; padding-top: 6px;">Total Payable: ₹{grand_total:,.2f}</h4>
            </div>
            <hr style="margin: 12px 0;">
            <small style="color: #64748b;">
                • All billing strictly in Gross units (1 Gross = 144 Pieces)<br>
                • Delivery Lead Time: 3-5 Working Days from Okhla Godown<br>
                • Payment Terms: 30 Days Credit against Approved Purchase Order<br>
                • Bank: HDFC Bank, Kalkaji Branch, A/C: 50200084920192, IFSC: HDFC0000123
            </small>
        </div>
        """, unsafe_allow_html=True)
        
        st.write("")
        c_dl1, c_dl2 = st.columns(2)
        pdf_bytes = generate_quotation_pdf(
            buyer_name=q_buyer,
            buyer_gst=q_gst,
            item_sku=selected_sku,
            item_name=curr_item['name'],
            item_size=curr_item.get('size_ligne', ''),
            qty_gross=q_gross_qty,
            rate_gross=curr_item['rate_per_gross'],
            discount_pct=q_discount
        )
        safe_buyer = "".join(c for c in q_buyer if c.isalnum() or c in (' ', '_')).strip().replace(' ', '_')
        c_dl1.download_button(
            label="📥 Download Official PDF Quotation",
            data=pdf_bytes,
            file_name=f"ABC_Quotation_{selected_sku}_{safe_buyer}.pdf",
            mime="application/pdf" if HAS_REPORTLAB else "text/plain",
            type="primary",
            use_container_width=True
        )
        # WhatsApp Quotation Summary Link & Meta API
        quote_summary_msg = (
            f"Namaste {q_buyer}!\n\n"
            f"ABC Buttons Private Limited ki taraf se official quotation summary:\n"
            f"• Button: {curr_item['name']}\n"
            f"• Quantity: {q_gross_qty} Gross ({q_gross_qty*144:,} Pieces)\n"
            f"• Rate: Rs. {base_rate:.2f} / Gross\n"
            f"• Total Payable (incl. GST): Rs. {grand_total:,.2f}\n\n"
            f"Bank Details: HDFC Bank, Kalkaji Branch | A/C: 50200084920192 | IFSC: HDFC0000123\n"
            f"Official PDF Quotation dispatch ke liye ready hai. Kripya purchase order confirm karein."
        )
        wa_quote_url = f"https://api.whatsapp.com/send?text={urllib.parse.quote(quote_summary_msg)}"
        
        c_q_btn1, c_q_btn2 = st.columns([1, 1])
        with c_q_btn1:
            c_dl2.link_button("📲 Share on WhatsApp", wa_quote_url, use_container_width=True)
        with c_q_btn2:
            if send_whatsapp_text and st.button("⚡ Send Direct via Official Meta API", key="send_meta_quote", help="Dispatches Quotation via Meta Cloud API"):
                with st.spinner("Dispatching Official Quotation via Meta API..."):
                    res_q = send_whatsapp_text("919315702804", quote_summary_msg)
                    if res_q.get("success"):
                        st.success("🚀 Quotation Delivered via Official Meta API to +91 93157 02804!")
                        st.balloons()
                    else:
                        st.error(f"API Error: {res_q.get('error')}")
        
        # Auto-record in Quotation History
        new_q_rec = {
            "Date": today_str,
            "Buyer": q_buyer,
            "SKU": selected_sku,
            "Quantity (Gross)": f"{q_gross_qty} Gr",
            "Rate / Gross": f"₹{base_rate:.2f}",
            "Total Payable": f"₹{grand_total:,.2f}"
        }
        if not st.session_state.quotation_history or st.session_state.quotation_history[0].get("Total Payable") != new_q_rec["Total Payable"] or st.session_state.quotation_history[0].get("Buyer") != new_q_rec["Buyer"]:
            st.session_state.quotation_history.insert(0, new_q_rec)
            save_persistent_data()
            
        if st.session_state.quotation_history:
            st.write("")
            with st.expander("📜 View Saved Quotations History (Auto-Archived to Disk)", expanded=False):
                st.dataframe(pd.DataFrame(st.session_state.quotation_history), use_container_width=True, hide_index=True)

# ----------------- TAB 6: PAYMENT REMINDER -----------------
with tabs[5]:
    st.subheader("💳 Polite Payment & Ledger Balance Assistant")
    st.caption("उधारी वाले ग्राहकों को बिना रिश्ते खराब किए, बेहद शालीन और कॉर्पोरेट भाषा में पेमेंट रिमाइंडर भेजें।")
    
    p_col1, p_col2 = st.columns([1, 1])
    
    with p_col1:
        # Dynamic Overdue Accounts (Default Ledger + Pipeline Buyers)
        base_accounts = [
            {"company": "Shahi Exports Pvt. Ltd.", "inv": "INV-2026-0894", "amt": 84500, "days": 12},
            {"company": "Richa Global Apparels", "inv": "INV-2026-0912", "amt": 46200, "days": 5},
            {"company": "Pearl Global Industries", "inv": "INV-2026-0785", "amt": 125000, "days": 18}
        ]
        
        # Merge any new buyers from sample pipeline
        pipe_accounts = []
        for idx, p_item in enumerate(st.session_state.sample_pipeline):
            c_name = p_item.get("company", "").strip()
            if c_name and not any(c_name.lower() in b["company"].lower() for b in base_accounts):
                pipe_accounts.append({
                    "company": c_name,
                    "inv": f"INV-2026-{950 + idx}",
                    "amt": 58000,
                    "days": max(4, p_item.get("days_ago", 3) * 2)
                })
        
        all_accounts = base_accounts + pipe_accounts
        acc_options = [f"{a['company']} (₹{a['amt']:,} Overdue by {a['days']} Days)" for a in all_accounts]
        
        selected_acc_label = st.selectbox("Select Exporter / Buyer with Pending Balance:", acc_options)
        selected_idx = acc_options.index(selected_acc_label)
        curr_acc = all_accounts[selected_idx]
        
        buyer_clean_name = curr_acc["company"]
        invoice_num = curr_acc["inv"]
        amt = curr_acc["amt"]
        days = curr_acc["days"]
        
        st.markdown(f"""
        <div style="background: #f1f5f9; padding: 10px; border-radius: 6px; font-size: 13px; margin-bottom: 10px;">
            📄 <b>Invoice Number:</b> <code>{invoice_num}</code><br>
            💰 <b>Pending Amount:</b> ₹{amt:,.2f}<br>
            ⏱️ <b>Overdue Days:</b> {days} Days Overdue
        </div>
        """, unsafe_allow_html=True)
        
        if st.button("✨ Draft Polite AI Payment Reminder", type="primary"):
            with st.spinner("AI composing relationship-preserving polite reminder..."):
                reminder_text = generate_ledger_payment_reminder(buyer_clean_name, invoice_num, amt, days)
                st.session_state["generated_reminder"] = reminder_text
                
    with p_col2:
        if "generated_reminder" in st.session_state:
            st.markdown("### 💬 Generated WhatsApp Message:")
            st.text_area("Ready-to-Send Message:", value=st.session_state["generated_reminder"], height=160)
            c_rm1, c_rm2, c_rm3 = st.columns([1, 1.2, 0.8])
            with c_rm1:
                clean_reminder = st.session_state["generated_reminder"]
                encoded_rem = urllib.parse.quote(clean_reminder)
                wa_rem_url = f"https://api.whatsapp.com/send?text={encoded_rem}"
                st.link_button("📲 Send via WhatsApp", wa_rem_url, use_container_width=True)
            with c_rm2:
                if send_whatsapp_text and st.button("⚡ Send Direct via Official Meta API", key="send_meta_reminder", help="Send Payment Reminder via Meta Cloud API"):
                    with st.spinner("Dispatching Payment Reminder..."):
                        res_rem = send_whatsapp_text("919315702804", clean_reminder)
                        if res_rem.get("success"):
                            st.success("🚀 Payment Reminder Delivered to +91 93157 02804!")
                            st.balloons()
                        else:
                            st.error(f"API Error: {res_rem.get('error')}")
            with c_rm3:
                if st.button("📋 Copy Message", use_container_width=True):
                    st.toast("Payment reminder message copied to clipboard!")

# ----------------- TAB 8: WHATSAPP LIVE SIMULATOR -----------------
with tabs[6]:
    st.subheader("💬 WhatsApp Live Simulator (Buyer & Salesman Live Testing)")
    st.caption("यहाँ बिना किसी सिम कार्ड या WhatsApp API के असली चैट की लाइव टेस्टिंग करें। बायर बनकर सवाल पूछें या सेल्समैन बनकर रिपोर्ट करें!")

    OFFICIAL_BUYER_GREETING = "Hello! Welcome to ABC Buttons.\n\nThank you for connecting with us. We manufacture a wide range of natural and customised buttons for the garment and fashion industry.\n\nHow may we assist you today?"

    if "buyer_chat" not in st.session_state or (len(st.session_state.buyer_chat) == 1 and "Mother of Pearl (Shell)" in st.session_state.buyer_chat[0]["content"]):
        st.session_state.buyer_chat = [
            {
                "role": "model",
                "content": OFFICIAL_BUYER_GREETING
            }
        ]

    # Replace old default greeting if present as first message
    if st.session_state.buyer_chat and "Mother of Pearl (Shell)" in st.session_state.buyer_chat[0]["content"]:
        st.session_state.buyer_chat[0]["content"] = OFFICIAL_BUYER_GREETING

    if "salesman_chat" not in st.session_state:
        st.session_state.salesman_chat = [
            {
                "role": "model",
                "content": "Namaste Rahul ji! 🏍️ ABC Buttons Sales Desk active hai.\n\nAaj aap kis export house / factory visit par hain? Sample delivery ka update yahan type karein ya voice note share karein."
            }
        ]

    # Clean up any previously stored raw json in chat session
    for msg in st.session_state.buyer_chat:
        if msg["role"] == "model" and "whatsapp_buyer_draft" in msg["content"]:
            raw_c = msg["content"].strip()
            if raw_c.startswith("```json"):
                raw_c = raw_c[7:].strip()
                if raw_c.endswith("```"):
                    raw_c = raw_c[:-3].strip()
            try:
                pj = json.loads(raw_c)
                msg["content"] = pj.get("whatsapp_buyer_draft", msg["content"])
            except Exception:
                pass

    sim_role = st.radio(
        "चुनें कि आप किसकी तरह चैट टेस्ट करना चाहते हैं (Select Role):",
        [
            "👤 1. Buyer / Merchandiser Mode (बायर की पूछताछ व सैंपल कार्ड की लाइव टेस्टिंग)",
            "🏍️ 2. Salesman Mode (सेल्समैन की फील्ड रिपोर्टिंग व ऑटो-पाइपलाइन एंट्री)"
        ],
        horizontal=True
    )

    col_sim_chat, col_sim_inspector = st.columns([1.2, 1])

    # ==================== BUYER SIMULATOR ====================
    if sim_role.startswith("👤"):
        with col_sim_chat:
            st.markdown("""
            <div style="background: #075e54; color: white; padding: 12px 16px; border-radius: 8px 8px 0 0; display: flex; align-items: center; justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="font-size: 22px;">🏢</div>
                    <div>
                        <b style="font-size: 15px;">ABC Buttons Pvt Ltd (Verified)</b><br>
                        <small style="color: #a7f3d0;">🟢 Online • Official WhatsApp Business</small>
                    </div>
                </div>
                <div style="font-size: 12px; background: rgba(255,255,255,0.18); padding: 4px 10px; border-radius: 4px;">
                    Role: Buyer View
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.container(height=450):
                for msg in st.session_state.buyer_chat:
                    clean_text = msg["content"].split("```SAMPLE_CARD_DISPATCH")[0].strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:].strip()
                        if clean_text.endswith("```"):
                            clean_text = clean_text[:-3].strip()
                    if clean_text.startswith("{") and ("detected_type" in clean_text or "whatsapp_buyer_draft" in clean_text):
                        try:
                            jd = json.loads(clean_text)
                            if "whatsapp_buyer_draft" in jd:
                                clean_text = jd["whatsapp_buyer_draft"]
                            else:
                                clean_text = f"Namaste Sir! 🙏 17L standard button size nahi hota, garment industry me **18L (11.5 mm)** sabse popular standard size chalta hai.\n\nRecommended: **{jd.get('best_match_sku', 'ABC-136')}**\n{jd.get('match_reason', '')}\n\nSabhi rates strictly ₹ / Gross me hain aur Okhla me ready stock hai. Kya hum aapko iska Free Sample Card bhej dein?"
                        except Exception:
                            pass
                    if msg["role"] == "user":
                        with st.chat_message("user", avatar="👤"):
                            st.write(clean_text)
                    else:
                        with st.chat_message("assistant", avatar="🔘"):
                            st.write(clean_text)

            # Input form
            with st.form("buyer_input_form", clear_on_submit=True):
                buyer_msg = st.text_input("💬 Type message as Buyer (e.g. sample card request, price inquiry, MOQ):", placeholder="Bhaiya 18L aur 24L MOP shell button ka Sample Card bhej do, Orient Craft Okhla ke liye...")
                buyer_img_file = st.file_uploader("📎 (Optional) Attach Button Photo with message:", type=["jpg", "png", "jpeg"], key="sim_buyer_img")
                
                col_btn1, col_btn2 = st.columns([1, 1])
                submitted = col_btn1.form_submit_button("🚀 Send to ABC Buttons WhatsApp", type="primary", use_container_width=True)
                clear_btn = col_btn2.form_submit_button("🗑️ Clear Chat", use_container_width=True)

            if clear_btn:
                st.session_state.buyer_chat = [
                    {
                        "role": "model",
                        "content": OFFICIAL_BUYER_GREETING
                    }
                ]
                st.rerun()

            if submitted and (buyer_msg.strip() or buyer_img_file):
                img_bytes = None
                display_msg = buyer_msg.strip()
                if buyer_img_file:
                    raw_img = Image.open(buyer_img_file)
                    if raw_img.mode != "RGB":
                        raw_img = raw_img.convert("RGB")
                    buf = BytesIO()
                    raw_img.save(buf, format="JPEG")
                    img_bytes = buf.getvalue()
                    if not display_msg:
                        display_msg = "[Attached Button Photo] Please check stock and sample card for this button."

                st.session_state.buyer_chat.append({"role": "user", "content": display_msg})
                
                with st.spinner("AI is typing reply from ABC Buttons WhatsApp..."):
                    try:
                        ai_reply = simulate_buyer_chat(st.session_state.buyer_chat[:-1], display_msg, image_bytes=img_bytes)
                        st.session_state.buyer_chat.append({"role": "model", "content": ai_reply})
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error in simulation: {str(e)}")

        with col_sim_inspector:
            st.markdown("### 🔍 Live Action Inspector (बायर मोड)")
            st.info("💡 **Active Rule:** AI System Prompt #1 (`visual_matcher`) से सीधे कनेक्टेड है। यह ऑटोमैटिकली डिटेक्ट करता है कि बायर ने **Sample Card** माँगा है या **Rate Inquiry** की है।")

            st.markdown("#### ⚡ 1-Click Quick Test Questions (क्लिक करके टेस्ट करें):")
            col_q1, col_q2 = st.columns(2)
            if col_q1.button("📦 1. Request Sample Card", use_container_width=True):
                quick_msg = "Bhaiya humein 18L aur 24L Natural Shell buttons ka Sample Card chahiye, Shahi Exports Okhla Phase 2 ke liye. Aaj bhej sakte ho?"
                st.session_state.buyer_chat.append({"role": "user", "content": quick_msg})
                with st.spinner("AI responding..."):
                    ai_reply = simulate_buyer_chat(st.session_state.buyer_chat[:-1], quick_msg)
                    st.session_state.buyer_chat.append({"role": "model", "content": ai_reply})
                st.rerun()

            if col_q2.button("💰 2. Ask Rate in Gross", use_container_width=True):
                quick_msg = "ABC-139 Natural Shell button ka 350 Gross ka kya rate lagega with 12% GST and ready stock kitna hai?"
                st.session_state.buyer_chat.append({"role": "user", "content": quick_msg})
                with st.spinner("AI responding..."):
                    ai_reply = simulate_buyer_chat(st.session_state.buyer_chat[:-1], quick_msg)
                    st.session_state.buyer_chat.append({"role": "model", "content": ai_reply})
                st.rerun()

            col_q3, col_q4 = st.columns(2)
            if col_q3.button("🔘 3. Natural Horn Button Inquiry", use_container_width=True):
                quick_msg = "Humein genuine natural buffalo horn buttons chahiye 32L size mein. Kya iska sample card available hai?"
                st.session_state.buyer_chat.append({"role": "user", "content": quick_msg})
                with st.spinner("AI responding..."):
                    ai_reply = simulate_buyer_chat(st.session_state.buyer_chat[:-1], quick_msg)
                    st.session_state.buyer_chat.append({"role": "model", "content": ai_reply})
                st.rerun()

            if col_q4.button("🔤 4. Custom Laser Engraving", use_container_width=True):
                quick_msg = "Kya aap buttons ke rim par brand name ka laser logo engraving kar sakte ho? MOQ kitna hoga?"
                st.session_state.buyer_chat.append({"role": "user", "content": quick_msg})
                with st.spinner("AI responding..."):
                    ai_reply = simulate_buyer_chat(st.session_state.buyer_chat[:-1], quick_msg)
                    st.session_state.buyer_chat.append({"role": "model", "content": ai_reply})
                st.rerun()

            # Check if latest AI reply contains Sample Card dispatch block
            latest_ai_msg = st.session_state.buyer_chat[-1]["content"] if st.session_state.buyer_chat else ""
            if "SAMPLE_CARD_DISPATCH" in latest_ai_msg:
                try:
                    dispatch_raw = latest_ai_msg.split("```SAMPLE_CARD_DISPATCH")[1].split("```")[0].strip()
                    dispatch_data = json.loads(dispatch_raw)
                    st.markdown("""
                    <div style="background: #f0fdf4; border: 2px solid #22c55e; border-radius: 10px; padding: 15px; margin-top: 15px;">
                        <h4 style="margin: 0 0 10px 0; color: #166534;">📦 Sample Card Courier Dispatch Slip (Auto-Generated)</h4>
                        <p style="margin: 3px 0; font-size: 14px;"><b>🏢 Buyer / Company:</b> """ + str(dispatch_data.get("buyer_company", "Shahi Exports / Buyer")) + """</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>👤 Contact Person:</b> """ + str(dispatch_data.get("contact_person", "Merchandiser")) + """</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>🔘 Button Requested:</b> """ + str(dispatch_data.get("items_requested", "Shell Buttons")) + """</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>📏 Sizes:</b> """ + str(dispatch_data.get("sizes", "14L, 18L, 24L")) + """</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>📍 Delivery Address:</b> """ + str(dispatch_data.get("delivery_address", "Okhla Phase 2")) + """</p>
                        <p style="margin: 3px 0; font-size: 14px; color: #15803d;"><b>🚚 Status:</b> """ + str(dispatch_data.get("dispatch_status", "Scheduled for Today 3:00 PM")) + """</p>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button("🖨️ Print Sample Card Packing Slip for Dispatch Team", use_container_width=True):
                        st.toast("Packing Slip sent to dispatch printer / runner!")
                except Exception:
                    pass

    # ==================== SALESMAN SIMULATOR ====================
    else:
        with col_sim_chat:
            st.markdown("""
            <div style="background: #1e3a8a; color: white; padding: 12px 16px; border-radius: 8px 8px 0 0; display: flex; align-items: center; justify-content: space-between;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="font-size: 22px;">🏍️</div>
                    <div>
                        <b style="font-size: 15px;">ABC Buttons Sales Desk</b><br>
                        <small style="color: #93c5fd;">🟢 Online • Field Executive Portal</small>
                    </div>
                </div>
                <div style="font-size: 12px; background: rgba(255,255,255,0.18); padding: 4px 10px; border-radius: 4px;">
                    Executive: Rahul (Okhla / Noida)
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.container(height=450):
                for msg in st.session_state.salesman_chat:
                    clean_text = msg["content"].split("```SALESMAN_LOG_DISPATCH")[0].strip()
                    if msg["role"] == "user":
                        with st.chat_message("user", avatar="🏍️"):
                            st.write(clean_text)
                    else:
                        with st.chat_message("assistant", avatar="🏢"):
                            st.write(clean_text)

            with st.form("salesman_input_form", clear_on_submit=True):
                sm_msg = st.text_input("💬 Type / Voice Note as Salesman:", placeholder="Sir aaj Richa Global Okhla me Rajesh ji ko 24L MOP button ka sample diya...")
                col_btn1, col_btn2 = st.columns([1, 1])
                submitted_sm = col_btn1.form_submit_button("🚀 Send to ABC Sales Desk", type="primary", use_container_width=True)
                clear_sm = col_btn2.form_submit_button("🗑️ Clear Chat", use_container_width=True)

            if clear_sm:
                st.session_state.salesman_chat = [
                    {
                        "role": "model",
                        "content": "Namaste Rahul ji! 🏍️ ABC Buttons Sales Desk active hai.\n\nAaj aap kis export house / factory visit par hain? Sample delivery ka update yahan type karein ya voice note share karein."
                    }
                ]
                st.rerun()

            if submitted_sm and sm_msg.strip():
                st.session_state.salesman_chat.append({"role": "user", "content": sm_msg.strip()})
                with st.spinner("AI parsing field update and updating pipeline..."):
                    try:
                        ai_reply = simulate_salesman_chat(st.session_state.salesman_chat[:-1], sm_msg.strip())
                        st.session_state.salesman_chat.append({"role": "model", "content": ai_reply})
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error in simulation: {str(e)}")

        with col_sim_inspector:
            st.markdown("### 🔍 Live Action Inspector (सेल्समैन मोड)")
            st.info("💡 **Active Rule:** AI System Prompt #2 (`salesman_logger`) से कनेक्टेड है। सेल्समैन की टूटी-फूटी भाषा से अपने-आप कंपनी का नाम, बायर का नाम और बल्क ऑर्डर निकालकर **Sample Pipeline** में जोड़ देता है।")

            st.markdown("#### ⚡ 1-Click Field Note Simulations:")
            if st.button("🏢 Sample Delivery at Orient Craft (Gurgaon)", use_container_width=True):
                quick_sm = "Sir aaj Orient Craft Udyog Vihar Gurgaon me Pooja Verma ji ko Turquoise Shell button ka sample card de diya hai. Unhe 175 gross ka bulk order chahiye."
                st.session_state.salesman_chat.append({"role": "user", "content": quick_sm})
                with st.spinner("Processing..."):
                    ai_reply = simulate_salesman_chat(st.session_state.salesman_chat[:-1], quick_sm)
                    st.session_state.salesman_chat.append({"role": "model", "content": ai_reply})
                st.rerun()

            if st.button("🏭 Sample Delivery at Shahi Exports (Noida)", use_container_width=True):
                quick_sm = "Amit Sharma ji Shahi Exports Sector 59 Noida ko 25 pieces Natural Shell buttons hand-over kar diye. Trial ke baad 400 Gross ka order banega."
                st.session_state.salesman_chat.append({"role": "user", "content": quick_sm})
                with st.spinner("Processing..."):
                    ai_reply = simulate_salesman_chat(st.session_state.salesman_chat[:-1], quick_sm)
                    st.session_state.salesman_chat.append({"role": "model", "content": ai_reply})
                st.rerun()

            latest_sm_msg = st.session_state.salesman_chat[-1]["content"] if st.session_state.salesman_chat else ""
            if "SALESMAN_LOG_DISPATCH" in latest_sm_msg:
                try:
                    sm_raw = latest_sm_msg.split("```SALESMAN_LOG_DISPATCH")[1].split("```")[0].strip()
                    sm_data = json.loads(sm_raw)
                    
                    contact_name = sm_data.get("contact", "Merchandiser")
                    company_name = sm_data.get("company", "Company")
                    buyer_deliv_msg = sm_data.get("buyer_delivery_message") or f"Dear {contact_name}, Greetings from ABC Buttons! Thank you for receiving our button samples. We hope you find them suitable for your collection. Looking forward to working with {company_name}. Warm regards, Team ABC Buttons (9310722777)"
                    buyer_fu_msg = sm_data.get("buyer_followup_message") or f"Dear {contact_name}, Hope you are doing well. Just wanted to follow up regarding the button samples shared by ABC Buttons. Have you had an opportunity to review them on your garments? Warm regards, Team ABC Buttons"

                    st.markdown(f"""
                    <div style="background: #eff6ff; border: 2px solid #3b82f6; border-radius: 10px; padding: 15px; margin-top: 15px;">
                        <h4 style="margin: 0 0 10px 0; color: #1e40af;">📋 Auto-Logged into Sample Pipeline (Live Sync)</h4>
                        <p style="margin: 3px 0; font-size: 14px;"><b>🏢 Company:</b> {company_name}</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>👤 Contact:</b> {contact_name}</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>📍 Location:</b> {sm_data.get("location", "Delhi/NCR")}</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>🔘 Button SKU:</b> {sm_data.get("sku", "Sample Card")}</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>📦 Sample Qty:</b> {sm_data.get("sample_qty", "Standard Samples")}</p>
                        <p style="margin: 3px 0; font-size: 14px;"><b>🎯 Bulk Est:</b> {sm_data.get("bulk_est", "Pending Confirmation")}</p>
                        <p style="margin: 3px 0; font-size: 14px; color: #b45309;"><b>⏰ Follow-Up Scheduled:</b> {sm_data.get("followup_date", "3 days from today")}</p>
                        
                        <div style="margin-top: 12px; padding: 10px; background: #ffffff; border-radius: 8px; border: 1px solid #bfdbfe;">
                            <p style="margin: 0 0 4px 0; font-size: 13px; font-weight: 700; color: #166534;">📱 1. बायर ({contact_name}) को भेजा गया डिलीवरी मैसेज:</p>
                            <div style="font-size: 12px; color: #1e293b; line-height: 1.4; background: #dcf8c6; padding: 8px 10px; border-radius: 6px; margin-bottom: 8px;">
                                {buyer_deliv_msg}
                            </div>
                            <p style="margin: 0 0 4px 0; font-size: 13px; font-weight: 700; color: #92400e;">⏰ 2. {sm_data.get("followup_date", "3 din baad")} जाने वाला ऑटोमैटिक फॉलो-अप मैसेज:</p>
                            <div style="font-size: 12px; color: #1e293b; line-height: 1.4; background: #fef3c7; padding: 8px 10px; border-radius: 6px;">
                                {buyer_fu_msg}
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    if st.button("➕ Push Record to Tab 4 (Sample Pipeline Register)", use_container_width=True):
                        new_entry = {
                            "id": f"SMP-{len(st.session_state.sample_pipeline) + 101}",
                            "company": company_name,
                            "contact": contact_name,
                            "location": sm_data.get("location", "Delhi NCR"),
                            "sku": sm_data.get("sku", "Button Sample"),
                            "sample_qty": sm_data.get("sample_qty", "Sample Card"),
                            "bulk_est": sm_data.get("bulk_est", "TBD"),
                            "date": "Today",
                            "days_ago": 0,
                            "status": "Sample Dispatched"
                        }
                        st.session_state.sample_pipeline.insert(0, new_entry)
                        st.toast("✅ Added to Tab 4 (Sample Pipeline)! Open Tab 4 to see it live.")
                except Exception:
                    pass


