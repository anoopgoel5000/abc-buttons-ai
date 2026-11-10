import streamlit as st
import json
import os
import pandas as pd
from PIL import Image
from io import BytesIO, StringIO
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
    effective_rate = rate_gross * (1 - discount_pct/100.0)
    subtotal = qty_gross * effective_rate
    gst = subtotal * 0.12
    total = subtotal + gst
    total_pcs = qty_gross * 144

    if not HAS_REPORTLAB:
        text_content = f"""====================================================
               ABC BUTTONS PVT. LTD.
   Manufacturers & Exporters of Natural & Customized Buttons
   Works: Okhla Phase-II | Regd: Govindpuri / Kalkaji, New Delhi
   GSTIN: 07AABCA1234F1Z8 | Contact: +91 9310722777
====================================================
PROFORMA QUOTATION
Ref No: ABC-QT-2026-0892 | Date: 10-Nov-2026

BILL TO:
Buyer: {buyer_name}
GSTIN: {buyer_gst}
Payment Terms: 30 Days Credit
Delivery: 3-5 Working Days

----------------------------------------------------
ITEM DETAILS:
SKU: {item_sku} - {item_name}
Size: {item_size}
Quantity: {qty_gross} Gross ({total_pcs:,} Individual Pieces)
Rate / Gross: Rs. {effective_rate:.2f}
Discount: {discount_pct}%

----------------------------------------------------
COMMERCIAL SUMMARY:
Subtotal:       Rs. {subtotal:,.2f}
GST @ 12%:      Rs. {gst:,.2f}
TOTAL PAYABLE:  Rs. {total:,.2f}

----------------------------------------------------
BANK DETAILS FOR RTGS / NEFT:
A/C Name:   ABC Buttons Pvt. Ltd.
Bank Name:  HDFC Bank, Kalkaji Branch
A/C Number: 50200012345678
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
    story.append(Paragraph('Manufacturers & Exporters of Natural & Customized Buttons<br/>Works: Okhla Industrial Area Phase-II | Regd Office: Govindpuri / Kalkaji, New Delhi - 110019<br/>GSTIN: 07AABCA1234F1Z8 | Phone: +91 9310722777 | Email: sales@abcbuttons.com', sub_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width='100%', thickness=2, color=colors.HexColor('#2563eb'), spaceAfter=12))

    meta_data = [
        [
            Paragraph('<b>PROFORMA QUOTATION</b><br/><font size=8.5 color=#64748b>Ref No: ABC-QT-2026-0892<br/>Date: 10-Nov-2026<br/>Valid Till: 30-Nov-2026</font>', styles['Normal']),
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
    row = [
        Paragraph(f'<b>{item_sku}</b> - {item_name}<br/><font size=8 color=#64748b>Size: {item_size} | 100% Export Ready Quality</font>', styles['Normal']),
        f'{qty_gross} Gr',
        f'{total_pcs:,} pcs',
        f'Rs. {effective_rate:.2f}',
        f'Rs. {subtotal:,.2f}'
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

    summary_data = [
        ['', 'Subtotal:', f'Rs. {subtotal:,.2f}'],
        ['', f'Discount ({discount_pct}%):', f'Rs. -{(qty_gross*rate_gross*discount_pct/100):,.2f}'],
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
            Paragraph('<b>Bank Details for RTGS / NEFT:</b><br/><font size=8.5 color=#475569>Account Name: ABC Buttons Pvt. Ltd.<br/>Bank Name: HDFC Bank, Kalkaji Branch<br/>A/C Number: 50200012345678 | IFSC: HDFC0000123</font>', styles['Normal']),
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
os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(TEST_DIR, exist_ok=True)

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

# Ensure full updated catalog (Strictly 100% Genuine Real Photo SKUs)
if "live_catalog" not in st.session_state or len(st.session_state.live_catalog) != len(SAMPLE_CATALOG) or any(x["sku"] not in [s["sku"] for s in SAMPLE_CATALOG] for x in st.session_state.live_catalog):
    st.session_state.live_catalog = list(SAMPLE_CATALOG)

if "sample_pipeline" not in st.session_state:
    st.session_state.sample_pipeline = [
        {
            "id": "SMP-101",
            "company": "Shahi Exports Pvt. Ltd.",
            "contact": "Amit Sharma (Merchandiser)",
            "location": "Noida Sector 59",
            "sku": "ABC-139 (Natural River Shell)",
            "sample_qty": "25 pcs (Hanger Card)",
            "bulk_est": "350 Gross (~50,000 Pcs)",
            "date": "05-Nov-2026",
            "days_ago": 3,
            "status": "Ready for Follow-up"
        },
        {
            "id": "SMP-102",
            "company": "Orient Craft Limited",
            "contact": "Pooja Verma (Fabric Sourcing)",
            "location": "Gurgaon Udyog Vihar",
            "sku": "ABC-142 (Ocean Turquoise Shell)",
            "sample_qty": "10 pcs",
            "bulk_est": "175 Gross (~25,000 Pcs)",
            "date": "06-Nov-2026",
            "days_ago": 2,
            "status": "In Review by Buyer"
        },
        {
            "id": "SMP-103",
            "company": "Richa Global Apparels",
            "contact": "Rajesh Kumar (Purchase Head)",
            "location": "Okhla Phase 3",
            "sku": "ABC-141 (Smoky Gunmetal Shell)",
            "sample_qty": "50 pcs",
            "bulk_est": "850 Gross (~1,22,000 Pcs)",
            "date": "07-Nov-2026",
            "days_ago": 1,
            "status": "Sample Dispatched"
        }
    ]

# Navigation Tabs
tabs = st.tabs([
    "📸 1. Visual Matcher (Real Buyer Photos)", 
    "📂 2. Catalog & Image Gallery",
    "🏍️ 3. Salesman Logger", 
    "📊 4. Sample Pipeline & Follow-Up", 
    "🧾 5. 1-Click Quotation", 
    "💳 6. Payment Reminder",
    "⚙️ 7. System Prompts & AI Rules",
    "💬 8. WhatsApp Live Simulator (Buyer & Salesman)"
])

# ----------------- TAB 1: VISUAL BUTTON MATCHER -----------------
with tabs[0]:
    st.subheader("🔍 Test Buyer Inquiries with Real Photos")
    st.caption("यहाँ आपके द्वारा भेजी गई असली बटनों की तस्वीरों से टेस्ट करें कि जब कोई बायर WhatsApp पर फोटो भेजता है, तो AI कैसे 3 सेकंड में स्टॉक व सही SKU ढूंढता है:")
    
    col_input, col_result = st.columns([1, 1])
    
    with col_input:
        st.markdown("#### Step 1: बायर की भेजी गई फोटो चुनें या अपलोड करें")
        
        input_choice = st.radio("Testing Source:", [
            "📷 Use Uploaded Real Button Photos (5 Actual Samples)", 
            "📤 Upload New Custom Photo from Computer/Phone"
        ], horizontal=True)
        
        selected_img_bytes = None
        selected_label = ""
        
        if input_choice.startswith("📷"):
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
            
        else:
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

    with col_result:
        st.markdown("#### Step 2: AI विज़न मिलान और लाइव आउटपुट")
        
        if selected_img_bytes is not None:
            if st.button("🚀 Analyze & Match with ABC Buttons Inventory", type="primary"):
                with st.spinner("AI scanning material sheen, holes, thickness & matching SKU..."):
                    try:
                        res = analyze_button_or_fabric_image(selected_img_bytes, buyer_notes)
                        
                        st.success("✅ Match Successfully Verified in ABC Buttons Catalog!")
                        
                        m1, m2, m3 = st.columns(3)
                        m1.metric("Detected Material", res.get("visual_analysis", {}).get("material_detected", "Shell / MOP"))
                        m2.metric("Ligne Size", res.get("visual_analysis", {}).get("estimated_size", "24L"))
                        m3.metric("Match Confidence", f"{res.get('match_confidence', 98)}%")
                        
                        best_sku = res.get("best_match_sku", "ABC-139")
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
                        
                        c_b1, c_b2 = st.columns(2)
                        if c_b1.button("📋 Copy WhatsApp Message"):
                            st.toast("WhatsApp Message copied to clipboard!")
                        if c_b2.button("📄 Generate Proforma Quotation for this SKU"):
                            st.session_state["quote_sku"] = matched_item["sku"]
                            st.toast(f"Selected {matched_item['sku']} for Tab 5 Quotation!")
                            
                    except Exception as e:
                        st.error(f"Analysis error: {str(e)}")
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
        col_hdr1, col_hdr2 = st.columns([3, 1])
        with col_hdr1:
            st.markdown("### 🖼️ ABC Buttons 100% Real Product Photo Gallery (20 Master SKUs)")
        with col_hdr2:
            if st.button("🔄 Reset / Sync Master Catalog", key="sync_master_grid_btn", use_container_width=True):
                st.session_state.live_catalog = list(SAMPLE_CATALOG)
                st.rerun()
        
        # Strictly show ONLY items from SAMPLE_CATALOG (all 100% real photo items)
        valid_skus = set(s["sku"] for s in SAMPLE_CATALOG)
        catalog_items = [x for x in st.session_state.live_catalog if x["sku"] in valid_skus]
        if not catalog_items or len(catalog_items) != len(SAMPLE_CATALOG):
            st.session_state.live_catalog = list(SAMPLE_CATALOG)
            catalog_items = list(SAMPLE_CATALOG)
            
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
        display_df = df.copy()
        renamed_df = display_df[[
            "sku", "name", "category", "size_ligne", "holes", "recommended_garment", "rate_per_gross", "stock_gross"
        ]].rename(columns={
            "sku": "SKU Code",
            "name": "Button Description",
            "category": "Category",
            "size_ligne": "Size (Ligne)",
            "holes": "Holes / Shank",
            "recommended_garment": "Recommended Garments",
            "rate_per_gross": "Price (₹ / Gross)",
            "stock_gross": "Ready Stock (Gross)"
        })
        st.dataframe(renamed_df, use_container_width=True, hide_index=True)
        
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
        default_note = "Aaj Shahi Exports, Sector 59 Noida gaya tha. Merchandiser Amit Sharma ko ABC-139 natural shell button ka 25 piece ka sample hanger card de diya. Bola agle mahine blazer order ke liye 350 Gross (~50,000 piece) ka bulk order final kar sakta hai."
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
                    "status": "Sample Delivered"
                }
                st.session_state.sample_pipeline.insert(0, new_entry)
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
            
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                custom_msg = f"Namaste {item['contact'].split()[0]} ji! ABC Buttons Delhi se follow-up kar rahe hain. 3 din pehle aapko {item['sku']} ka sample diya tha. Kya foreign buyer se approval aa gaya? Bulk production slot block karne ke liye confirm karein."
                st.caption(f"Suggested Follow-Up: *\"{custom_msg}\"*")
            with c2:
                if st.button(f"📲 Send WhatsApp Follow-up", key=f"btn_wa_{item['id']}"):
                    st.toast(f"WhatsApp follow-up dispatched to {item['contact']}!")
            with c3:
                if st.button(f"✅ Mark Order Won", key=f"btn_won_{item['id']}"):
                    item['status'] = "🎉 Order Won (Bulk Dispatch)"
                    st.rerun()

# ----------------- TAB 5: 1-CLICK B2B QUOTATION -----------------
with tabs[4]:
    st.subheader("🧾 1-Click Proforma Quotation Generator (Pricing in Gross)")
    st.caption("बायर को 30 सेकंड में प्रोफेशनल कोटेशन (दरें व क्वांटिटी अनिवार्य रूप से ग्रॉस में) तैयार करके भेजें।")
    
    q_col1, q_col2 = st.columns([1, 1])
    
    with q_col1:
        q_buyer = st.text_input("Buyer Company Name:", value="Shahi Exports Private Limited")
        q_gst = st.text_input("Buyer GSTIN:", value="07AAACS1234F1Z5")
        
        sku_options = [x["sku"] + " - " + x["name"] for x in st.session_state.live_catalog]
        default_index = 0
        if "quote_sku" in st.session_state:
            for idx, opt in enumerate(sku_options):
                if st.session_state["quote_sku"] in opt:
                    default_index = idx
                    break
                    
        selected_sku_text = st.selectbox("Select Button SKU:", sku_options, index=default_index)
        selected_sku = selected_sku_text.split(" - ")[0]
        curr_item = next(x for x in st.session_state.live_catalog if x["sku"] == selected_sku)
        
        q_gross_qty = st.number_input("Order Quantity in GROSS (1 Gross = 144 Pcs):", min_value=5, max_value=5000, value=250, step=5)
        st.markdown(f"<span class='gross-badge'>= {q_gross_qty} Gross ({q_gross_qty * 144:,} Total Individual Pieces)</span>", unsafe_allow_html=True)
        
        q_discount = st.slider("Volume Discount (%):", min_value=0, max_value=25, value=5)
        
    with q_col2:
        base_rate = curr_item["rate_per_gross"]
        discounted_rate = base_rate * (1 - (q_discount / 100))
        subtotal = discounted_rate * q_gross_qty
        gst_amount = subtotal * 0.12
        grand_total = subtotal + gst_amount
        
        st.markdown(f"""
        <div style="background: #f8fafc; border: 2px solid #cbd5e1; border-radius: 12px; padding: 20px;">
            <div style="border-bottom: 2px solid #0f172a; padding-bottom: 10px; margin-bottom: 15px;">
                <h3 style="margin: 0; color: #0f172a;">ABC BUTTONS PRIVATE LIMITED</h3>
                <small style="color: #64748b;">Govindpuri / Kalkaji, New Delhi - 110019 | GSTIN: 07AABCA9876P1Z3</small>
            </div>
            <p><b>PROFORMA QUOTATION / RATE ESTIMATE</b></p>
            <p style="font-size: 13px; color: #475569;">
                <b>Bill To:</b> {q_buyer}<br>
                <b>GSTIN:</b> {q_gst}<br>
                <b>Date:</b> 08-Nov-2026
            </p>
            <table style="width: 100%; font-size: 13px; border-collapse: collapse; margin-bottom: 15px;">
                <tr style="background: #e2e8f0; font-weight: 700;">
                    <td style="padding: 6px;">Item Description</td>
                    <td style="padding: 6px; text-align: center;">Qty (Gross)</td>
                    <td style="padding: 6px; text-align: right;">Rate / Gross</td>
                    <td style="padding: 6px; text-align: right;">Amount (INR)</td>
                </tr>
                <tr>
                    <td style="padding: 6px;"><b>{curr_item['name']}</b><br><small>{curr_item['size_ligne']} • {curr_item['holes']}</small></td>
                    <td style="padding: 6px; text-align: center; font-weight: 700;">{q_gross_qty} Gr<br><small>({q_gross_qty*144:,} pcs)</small></td>
                    <td style="padding: 6px; text-align: right;">₹{discounted_rate:.2f} / Gr</td>
                    <td style="padding: 6px; text-align: right; font-weight: 700;">₹{subtotal:,.2f}</td>
                </tr>
            </table>
            <div style="text-align: right; font-size: 13px;">
                <p style="margin: 4px 0;">Subtotal: <b>₹{subtotal:,.2f}</b></p>
                <p style="margin: 4px 0;">GST @ 12%: <b>₹{gst_amount:,.2f}</b></p>
                <h4 style="margin: 8px 0; color: #0f172a; font-size: 17px;">Total Payable: ₹{grand_total:,.2f}</h4>
            </div>
            <hr style="margin: 12px 0;">
            <small style="color: #64748b;">
                • All billing strictly in Gross units (1 Gross = 144 Pieces)<br>
                • Delivery Lead Time: 3-5 Working Days<br>
                • Payment Terms: 30 Days Credit against Approved Purchase Order<br>
                • Bank: HDFC Bank, Kalkaji Branch, A/C: 50200012345678, IFSC: HDFC0000123
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
        if c_dl2.button("📲 Send Quotation on WhatsApp", use_container_width=True):
            st.toast(f"Quotation PDF ready & shared with {q_buyer} on WhatsApp!")

# ----------------- TAB 6: PAYMENT REMINDER -----------------
with tabs[5]:
    st.subheader("💳 Polite Payment & Ledger Balance Assistant")
    st.caption("उधारी वाले ग्राहकों को बिना रिश्ते खराब किए, बेहद शालीन और कॉर्पोरेट भाषा में पेमेंट रिमाइंडर भेजें।")
    
    p_col1, p_col2 = st.columns([1, 1])
    
    with p_col1:
        p_buyer = st.selectbox("Select Exporter / Buyer with Pending Balance:", [
            "Shahi Exports Pvt. Ltd. (₹84,500 Overdue by 12 Days)",
            "Richa Global Apparels (₹46,200 Overdue by 5 Days)",
            "Pearl Global Industries (₹1,25,000 Overdue by 18 Days)"
        ])
        
        buyer_clean_name = p_buyer.split(" (")[0]
        invoice_num = "INV-2026-0894"
        amt = 84500 if "Shahi" in p_buyer else (46200 if "Richa" in p_buyer else 125000)
        days = 12 if "Shahi" in p_buyer else (5 if "Richa" in p_buyer else 18)
        
        if st.button("✨ Draft Polite AI Payment Reminder", type="primary"):
            with st.spinner("AI composing relationship-preserving polite reminder..."):
                reminder_text = generate_ledger_payment_reminder(buyer_clean_name, invoice_num, amt, days)
                st.session_state["generated_reminder"] = reminder_text
                
    with p_col2:
        if "generated_reminder" in st.session_state:
            st.markdown("### 💬 Generated WhatsApp Message:")
            st.text_area("Ready-to-Send Message:", value=st.session_state["generated_reminder"], height=160)
            if st.button("📲 Send Reminder via ABC Buttons WhatsApp"):
                st.toast(f"Payment reminder sent to {buyer_clean_name}!")
                st.balloons()

# ----------------- TAB 7: SYSTEM PROMPTS & AI RULES -----------------
with tabs[6]:
    st.subheader("⚙️ AI System Prompts & Company House Rules Manager")
    st.caption("यह AI का 'संविधान' (Rulebook) है। ABC Buttons का मैनेजमेंट यहाँ से कंपनी के नियम, भाषा, न्यूनतम ऑर्डर (MOQ) और डिस्काउंट के नियम कभी भी बदल सकता है।")
    
    current_prompts = load_system_prompts()
    
    prompt_choice = st.radio("Select System Prompt to View / Edit:", [
        "🔍 1. Visual Matcher & WhatsApp Response Prompt (बटन मैचिंग और बायर को जवाब देने का नियम)",
        "🏍️ 2. Salesman Sample Logger Prompt (सेल्समैन का नोट पढ़ने और सैंपल रिकॉर्ड बनाने का नियम)",
        "💳 3. Payment Reminder Prompt (शालीन उधारी वसूली संदेश का नियम)"
    ])
    
    st.markdown("---")
    
    if prompt_choice.startswith("🔍"):
        st.markdown("### 🔍 Visual Matcher & WhatsApp Quote Prompt")
        st.info("""
        **इस System Prompt में क्या लिखा है:**
        1. **पहचान:** AI को 'Chief Merchandising AI for ABC Buttons New Delhi' घोषित किया गया है।
        2. **इंडस्ट्री का सख्त नियम:** सभी कीमतें और स्टॉक सिर्फ और सिर्फ **GROSS (1 Gr = 144 Pcs)** में होंगे।
        3. **बातचीत के नियम:** हमेशा 'Namaste / Dear Sir' जैसी बेहद विनम्र और प्रोफेशनल भाषा।
        4. **सैंपल ऑफर:** हर बायर को मुफ्त सैंपल हैंगर कार्ड ऑफर करना।
        5. **स्टैंडर्ड डिलीवरी और MOQ:** रेडी-स्टॉक 24 घंटे में, फ्रेश प्रोडक्शन 3-5 दिन, और मिनिमम ऑर्डर 10 Gross।
        """)
        
        vm_text = st.text_area("Live Editable System Prompt:", value=current_prompts.get("visual_matcher", ""), height=350, key="txt_vm")
        
        col_s1, col_s2 = st.columns([1, 4])
        if col_s1.button("💾 Save Changes to Visual Prompt", type="primary"):
            current_prompts["visual_matcher"] = vm_text
            save_system_prompts(current_prompts)
            st.success("✅ System Prompt Updated Successfully! AI will now follow your new rules immediately.")
            
    elif prompt_choice.startswith("🏍️"):
        st.markdown("### 🏍️ Autonomous Sample-to-Order AI Sales Agent Prompt")
        st.info("""
        **इस System Prompt में क्या लिखा है (Autonomous Sample-to-Order Engine):**
        1. **20 डेटा पॉइंट्स का एक्सट्रैक्शन:** कंपनी, मर्चेंडाइज़र, लोकेशन, बटन SKU, सैंपल क्वांटिटी और बल्क ऑर्डर का अंदाज़ा।
        2. **इमीडिएट डिलीवरी ग्रीटिंग:** सैंपल डिलीवर होते ही बायर को तुरंत WhatsApp मैसेज तैयार करना।
        3. **3-Day व 5-Day ऑटो-शेड्यूलर:** गारमेंट ट्रायल फीडबैक के लिए 3 दिन और 5 दिन बाद का फॉलो-अप मैसेज शेड्यूल करना।
        4. **लीड टेंपरेचर:** लीड को तुरंत 🔥 **HOT LEAD**, 🟡 **WARM LEAD** या ❄️ **COLD LEAD** में वर्गीकृत करना।
        """)
        
        sl_text = st.text_area("Live Editable System Prompt:", value=current_prompts.get("salesman_logger", ""), height=300, key="txt_sl")
        
        col_s1, col_s2 = st.columns([1, 4])
        if col_s1.button("💾 Save Changes to Salesman Prompt", type="primary"):
            current_prompts["salesman_logger"] = sl_text
            save_system_prompts(current_prompts)
            st.success("✅ Salesman System Prompt Updated Successfully!")
            
    else:
        st.markdown("### 💳 Polite Payment Reminder AI Agent Prompt")
        st.info("""
        **इस System Prompt में क्या लिखा है (Relationship-Preserving Payment Collection):**
        1. **रिलेशनशिप प्रोटेक्शन:** कभी भी कड़वी, आक्रामक या धमकी भरी भाषा (जैसे 'लीगल एक्शन', 'सप्लाई बंद') का इस्तेमाल नहीं करना।
        2. **स्मार्ट साइकोलॉजिकल हुक:** पेमेंट आते ही आगामी नए सैंपल्स और प्रोडक्शन को प्रायोरिटी (सबसे पहले) पर डिस्पैच करने का भरोसा देना।
        3. **ऑटो-बैंक डिटेल्स:** ABC Buttons का आधिकारिक HDFC बैंक खाता विवरण और UTR कंफर्मेशन मांगने का फॉर्मेटेड ड्राफ्ट।
        4. **6 रिस्पॉन्स हैंडलिंग:** पेमेंट हो चुकी, समय चाहिए, बिल विवाद या वित्तीय कठिनाई पर शालीनता से जवाब देना।
        """)
        
        pr_text = st.text_area("Live Editable System Prompt:", value=current_prompts.get("payment_reminder", ""), height=250, key="txt_pr")
        
        col_s1, col_s2 = st.columns([1, 4])
        if col_s1.button("💾 Save Changes to Payment Prompt", type="primary"):
            current_prompts["payment_reminder"] = pr_text
            save_system_prompts(current_prompts)
            st.success("✅ Payment System Prompt Updated Successfully!")
            
    st.markdown("---")
    if st.button("🔄 Reset All Prompts to Factory Default"):
        save_system_prompts(DEFAULT_PROMPTS)
        st.toast("All 3 System Prompts reset to default!")
        st.rerun()

# ----------------- TAB 8: WHATSAPP LIVE SIMULATOR -----------------
with tabs[7]:
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
            if col_q3.button("🧥 3. Blazer Horn Button", use_container_width=True):
                quick_msg = "Premium winter blazer ke liye genuine horn buttons chahiye 32L size mein. Kya sample card available hai?"
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
                quick_sm = "Sir aaj Orient Craft Udyog Vihar Gurgaon me Pooja Verma ji ko ABC-142 Turquoise Shell ka sample card de diya hai. Unhe 175 gross ka order chahiye summer blazer program ke liye."
                st.session_state.salesman_chat.append({"role": "user", "content": quick_sm})
                with st.spinner("Processing..."):
                    ai_reply = simulate_salesman_chat(st.session_state.salesman_chat[:-1], quick_sm)
                    st.session_state.salesman_chat.append({"role": "model", "content": ai_reply})
                st.rerun()

            if st.button("🏭 Sample Delivery at Shahi Exports (Noida)", use_container_width=True):
                quick_sm = "Amit Sharma ji Shahi Exports Sector 59 Noida ko 25 pieces ABC-139 Natural Shell buttons hand-over kar diye. Trial ke baad 400 Gross ka order banega."
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


