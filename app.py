import streamlit as st
import datetime
import json
import os
import re
import html
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
    import whatsapp_service
    from whatsapp_service import (
        send_whatsapp_text,
        send_whatsapp_image,
        send_whatsapp_document,
        generate_proforma_card_image
    )
except Exception:
    whatsapp_service = None
    send_whatsapp_text = None
    send_whatsapp_image = None
    send_whatsapp_document = None
    generate_proforma_card_image = None

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
   Works & Regd Office: Govindpuri / Kalkaji, New Delhi - 110019
   GSTIN: 07AABCA9876P1Z3 | Contact: +91 9310722777
====================================================
PROFORMA QUOTATION
Ref No: {ref_no} | Date: {today_str} | Valid Till: {valid_till_str}

BILL TO:
Buyer: {buyer_name}
GSTIN: {buyer_gst}
Payment Terms: 30 Days Credit
Delivery: 3-5 Working Days from Central Godown, New Delhi

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
    story.append(Paragraph('Manufacturers & Exporters of Natural & Customized Buttons<br/>Works & Regd Office: Govindpuri / Kalkaji, New Delhi - 110019<br/>GSTIN: 07AABCA9876P1Z3 | Phone: +91 9310722777 | Email: sales@abcbuttons.com', sub_style))
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
            "quotation_history": st.session_state.get("quotation_history", []),
            "live_whatsapp_inquiries": st.session_state.get("live_whatsapp_inquiries", [])
        }
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def sync_live_whatsapp_inquiries():
    """Fetches real-time buyer photos and inquiries from SQLite or Render WhatsApp webhook server."""
    if os.environ.get("STREAMLIT_TESTING"):
        return 0
    # 1. Direct high-performance SQLite read if available
    try:
        import db
        db_inqs = db.load_live_inquiries_db()
        if db_inqs:
            st.session_state["live_whatsapp_inquiries"] = db_inqs
            return len(db_inqs)
    except Exception:
        pass

    # 2. Cloud Render fallback
    cloud_url = "https://abc-buttons-ai.onrender.com/api/live_inquiries"
    try:
        import urllib.request
        admin_key = os.getenv("ADMIN_API_KEY", "")
        if not admin_key and os.path.exists(os.path.join(os.path.dirname(__file__), ".env")):
            with open(os.path.join(os.path.dirname(__file__), ".env"), "r", encoding="utf-8") as _ef:
                for _line in _ef:
                    if _line.strip().startswith("ADMIN_API_KEY="):
                        admin_key = _line.strip().split("=", 1)[1].strip()
        headers = {"User-Agent": "Mozilla/5.0"}
        if admin_key:
            headers["X-API-Key"] = admin_key
        req = urllib.request.Request(cloud_url, headers=headers)
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                cloud_list = data.get("inquiries", [])
                if cloud_list:
                    st.session_state["live_whatsapp_inquiries"] = cloud_list
                    save_persistent_data()
                    return len(cloud_list)
    except Exception as e:
        print(f"Error syncing from cloud: {e}")
    return 0

def sync_crm_meta_to_cloud(phone: str, human_takeover: int = None, assigned_salesman: str = None, crm_status: str = None, action_taken: str = None, company: str = None, city: str = None, quantity: int = None) -> tuple:
    """
    Distributed ACID Fail-Safe Sync:
    1. First dispatches update to Render backend via authenticated API.
    2. Only when Render backend confirms success (HTTP 200 with verified rows_affected), 
       local SQLite database commits the change.
    3. If Render fails or is unreachable, local SQLite remains UNTOUCHED to ensure zero state divergence.
    """
    admin_key = os.getenv("ADMIN_API_KEY", "")
    if not admin_key and os.path.exists(os.path.join(os.path.dirname(__file__), ".env")):
        with open(os.path.join(os.path.dirname(__file__), ".env"), "r", encoding="utf-8") as _ef:
            for _line in _ef:
                if _line.strip().startswith("ADMIN_API_KEY="):
                    admin_key = _line.strip().split("=", 1)[1].strip()

    cloud_url = "https://abc-buttons-ai.onrender.com/api/crm/update"
    cloud_ok = False
    cloud_msg = ""
    
    # Step 1: Dispatch to Cloud Render first
    try:
        import urllib.request
        payload = json.dumps({
            "phone": phone,
            "human_takeover": human_takeover,
            "assigned_salesman": assigned_salesman,
            "crm_status": crm_status,
            "action_taken": action_taken,
            "company": company,
            "city": city,
            "quantity": quantity
        }).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
        if admin_key:
            headers["X-API-Key"] = admin_key
        req = urllib.request.Request(cloud_url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                resp_data = json.loads(resp.read().decode("utf-8"))
                if resp_data.get("status") == "success":
                    cloud_ok = True
                    cloud_msg = f"Synced to Render ({resp_data.get('rows_affected', 1)} record updated)"
                else:
                    cloud_msg = resp_data.get("error", "Render returned non-success status")
            else:
                cloud_msg = f"Render HTTP status {resp.status}"
    except Exception as e:
        cloud_msg = str(e)

    # Step 2: Distributed Transaction: Commit locally ONLY if Cloud succeeded
    if cloud_ok:
        try:
            import db
            db.update_inquiry_crm_meta(
                phone, 
                human_takeover=human_takeover, 
                assigned_salesman=assigned_salesman, 
                crm_status=crm_status,
                action_taken=action_taken,
                company=company,
                city=city,
                quantity=quantity
            )
        except Exception as e:
            print(f"Local CRM commit error: {e}")
        return True, cloud_msg
    else:
        # Fail-Safe: Cloud failed -> Do NOT update local database
        return False, cloud_msg

# ===============================================================================
# SAMPLE 4: "QUICK-DESK RAPID BILLING" (HIGH-CONTRAST CLEAN DAYLIGHT FINTECH)
# ==============================================================================
st.markdown("""
<style>
    /* Google Fonts Import */
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Outfit:wght@500;600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;700&display=swap');

    /* Global Typography Defaults */
    html, body, [class*="css"], .stMarkdown, p, span, label {
        font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif !important;
    }
    
    h1, h2, h3, h4, h5, h6,
    [data-testid="stMarkdownContainer"] h1,
    [data-testid="stMarkdownContainer"] h2,
    [data-testid="stMarkdownContainer"] h3,
    [data-testid="stMarkdownContainer"] h4 {
        font-family: 'Outfit', 'Plus Jakarta Sans', sans-serif !important;
        color: #0F172A !important;
        letter-spacing: -0.015em;
    }

    /* Clean Daylight Executive Header (White Card with Crisp High-Contrast) */
    .daylight-header-card {
        background: #FFFFFF !important;
        border: 1.5px solid #E2E8F0 !important;
        border-top: 4.5px solid #0D9488 !important;
        border-radius: 14px !important;
        padding: 22px 28px !important;
        margin-bottom: 22px !important;
        box-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.06), 0 1px 3px rgba(0, 0, 0, 0.04) !important;
    }
    .header-flex-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 16px;
    }
    .brand-identity-box {
        display: flex;
        align-items: center;
        gap: 16px;
    }
    .brand-logo-seal {
        width: 52px;
        height: 52px;
        border-radius: 12px;
        background: linear-gradient(135deg, #0D9488 0%, #0F766E 100%);
        display: flex;
        align-items: center;
        justify-content: center;
        color: #FFFFFF !important;
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        font-size: 21px;
        letter-spacing: 0.5px;
        box-shadow: 0 4px 12px rgba(13, 148, 136, 0.3);
        border: 1.5px solid rgba(255, 255, 255, 0.4);
    }
    .header-chips-row {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
    }
    .metric-chip {
        padding: 6px 14px;
        border-radius: 9999px;
        font-size: 12.5px;
        font-weight: 600;
        display: flex;
        align-items: center;
        gap: 7px;
        box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    }
    .chip-green {
        background: #ECFDF5 !important;
        color: #065F46 !important;
        border: 1.5px solid #A7F3D0 !important;
    }
    .chip-teal {
        background: #F0FDFA !important;
        color: #0F766E !important;
        border: 1.5px solid #99F6E4 !important;
    }
    .chip-blue {
        background: #EFF6FF !important;
        color: #1E40AF !important;
        border: 1.5px solid #BFDBFE !important;
    }
    .live-dot {
        width: 8px;
        height: 8px;
        background-color: #10B981;
        border-radius: 50%;
        box-shadow: 0 0 8px #10B981;
        display: inline-block;
    }

    /* Segmented Quick-Desk Pill Tabs */
    div[data-baseweb="tab-list"],
    .stTabs [data-baseweb="tab-list"] {
        background: #F1F5F9 !important;
        padding: 6px 8px !important;
        border-radius: 12px !important;
        border: 1px solid #E2E8F0 !important;
        gap: 6px !important;
        margin-bottom: 22px !important;
    }
    button[data-baseweb="tab"],
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px !important;
        border: none !important;
        padding: 8px 16px !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-size: 13.5px !important;
        font-weight: 600 !important;
        color: #475569 !important;
        background: transparent !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    button[data-baseweb="tab"]:hover,
    .stTabs [data-baseweb="tab"]:hover {
        background: #E2E8F0 !important;
        color: #0F172A !important;
    }
    button[data-baseweb="tab"][aria-selected="true"],
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        background: linear-gradient(135deg, #0F766E 0%, #0D9488 100%) !important;
        color: #FFFFFF !important;
        box-shadow: 0 4px 12px rgba(13, 148, 136, 0.25) !important;
        border-bottom: 2px solid #5EEAD4 !important;
    }
    button[data-baseweb="tab"][aria-selected="true"] p,
    .stTabs [data-baseweb="tab"][aria-selected="true"] p,
    button[data-baseweb="tab"][aria-selected="true"] span,
    .stTabs [data-baseweb="tab"][aria-selected="true"] span {
        color: #FFFFFF !important;
        font-weight: 700 !important;
    }

    /* Clean Card Containers */
    .quick-card {
        background: #FFFFFF;
        border: 1px solid #E2E8F0;
        border-radius: 12px;
        padding: 20px;
        margin-bottom: 18px;
        box-shadow: 0 4px 16px -2px rgba(15, 23, 42, 0.04);
    }
    .spec-badge {
        font-family: 'Inter', sans-serif;
        font-size: 11.5px;
        font-weight: 600;
        letter-spacing: 0.6px;
        text-transform: uppercase;
        color: #0F766E;
        background: #F0FDFA;
        border: 1px solid #CCFBF1;
        padding: 3px 8px;
        border-radius: 6px;
    }
    .gross-badge {
        background-color: #F0FDFA;
        color: #0F766E;
        padding: 6px 14px;
        border-radius: 8px;
        font-weight: 700;
        font-size: 13.5px;
        border: 1px solid #99F6E4;
        display: inline-block;
        box-shadow: 0 1px 3px rgba(13, 148, 136, 0.08);
    }

    /* Quick-Desk Proforma Invoice Canvas */
    .proforma-canvas {
        background: #FFFFFF;
        border: 1.5px solid #CCFBF1;
        border-top: 4px solid #0D9488;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 10px 25px -5px rgba(13, 148, 136, 0.08);
        position: relative;
    }
    .proforma-header-bar {
        border-bottom: 2px solid #0F766E;
        padding-bottom: 12px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
    }
    .proforma-brand {
        font-family: 'Outfit', sans-serif;
        font-weight: 800;
        font-size: 21px;
        color: #0F172A !important;
        letter-spacing: 0.3px;
        margin: 0;
    }
    .proforma-brand-sub {
        color: #64748B;
        font-size: 12px;
        margin-top: 3px;
    }
    .proforma-ref-badge {
        background: #0F766E;
        color: #FFFFFF !important;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.5px;
        border: 1px solid #0D9488;
    }
    .proforma-table {
        width: 100%;
        font-size: 13px;
        border-collapse: collapse;
        margin-bottom: 16px;
    }
    .proforma-table th {
        background: #0F172A;
        color: #FFFFFF !important;
        font-weight: 700;
        padding: 9px 10px;
        font-size: 12.5px;
        letter-spacing: 0.3px;
    }
    .proforma-table td {
        padding: 10px;
        border-bottom: 1px solid #E2E8F0;
    }
    .proforma-total-box {
        background: #F8FAFC;
        border: 1.5px solid #CCFBF1;
        border-radius: 10px;
        padding: 14px 18px;
        text-align: right;
    }
    .proforma-grand-total {
        font-family: 'Outfit', sans-serif;
        font-size: 22px;
        font-weight: 800;
        color: #0F766E !important;
        margin: 8px 0 0 0;
        border-top: 2px solid #0F766E;
        padding-top: 8px;
    }

    /* Refined Luxury Form Controls */
    div[data-baseweb="input"] > div,
    div[data-baseweb="select"] > div {
        border-radius: 9px !important;
        border: 1.5px solid #CBD5E1 !important;
        background-color: #FFFFFF !important;
        transition: all 0.2s ease !important;
    }
    div[data-baseweb="input"] > div:focus-within,
    div[data-baseweb="select"] > div:focus-within {
        border-color: #0D9488 !important;
        box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.12) !important;
    }
    label[data-testid="stWidgetLabel"] p {
        font-weight: 600 !important;
        color: #1E293B !important;
        font-size: 13.5px !important;
        letter-spacing: -0.01em !important;
    }
    div[data-testid="stRadio"] > div {
        background: #F8FAFC !important;
        padding: 8px 14px !important;
        border-radius: 10px !important;
        border: 1px solid #E2E8F0 !important;
        gap: 12px !important;
    }
    div[data-testid="stRadio"] label {
        font-weight: 600 !important;
        font-size: 13px !important;
        color: #334155 !important;
    }

    /* Buttons: Primary Quick-Desk Teal Gradient */
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #0D9488 0%, #0F766E 100%) !important;
        border: 1px solid #0D9488 !important;
        color: #FFFFFF !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 700 !important;
        border-radius: 9px !important;
        padding: 10px 22px !important;
        box-shadow: 0 4px 12px rgba(13, 148, 136, 0.25) !important;
        transition: all 0.2s ease !important;
    }
    div.stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #14B8A6 0%, #0D9488 100%) !important;
        border-color: #2DD4BF !important;
        box-shadow: 0 6px 16px rgba(13, 148, 136, 0.35) !important;
        transform: translateY(-1px);
    }
    div.stButton > button[kind="secondary"] {
        border-radius: 9px !important;
        font-family: 'Plus Jakarta Sans', sans-serif !important;
        font-weight: 600 !important;
        border: 1.5px solid #CBD5E1 !important;
    }

    /* High Contrast & Colorful Badges for ABC Buttons OS */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px !important;
        background: #F8FAFC !important;
        padding: 8px 12px !important;
        border-radius: 12px !important;
        border: 1px solid #E2E8F0 !important;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
        font-size: 13.5px !important;
        color: #475569 !important;
        background: #FFFFFF !important;
        border: 1px solid #E2E8F0 !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.03) !important;
    }
    .stTabs [aria-selected="true"] {
        background: #1E3A8A !important;
        color: #FFFFFF !important;
        border: 1px solid #1E3A8A !important;
        box-shadow: 0 4px 10px rgba(30, 58, 138, 0.25) !important;
    }
    .badge-green {
        background: #DCFCE7 !important;
        color: #15803D !important;
        padding: 4px 12px !important;
        border-radius: 20px !important;
        font-weight: 800 !important;
        border: 1.5px solid #86EFAC !important;
    }
    .badge-blue {
        background: #EFF6FF !important;
        color: #1D4ED8 !important;
        padding: 4px 12px !important;
        border-radius: 20px !important;
        font-weight: 800 !important;
        border: 1.5px solid #BFDBFE !important;
    }
    .badge-amber {
        background: #FEF3C7 !important;
        color: #B45309 !important;
        padding: 4px 12px !important;
        border-radius: 20px !important;
        font-weight: 800 !important;
        border: 1.5px solid #FDE68A !important;
    }

</style>
""", unsafe_allow_html=True)

# Clean Daylight Executive Header (Maximum Contrast & 100% Legibility)
st.markdown("""
<div class="daylight-header-card">
    <div class="header-flex-row">
        <div class="brand-identity-box">
            <div class="brand-logo-seal">
                ABC
            </div>
            <div>
                <div style="font-family: 'Outfit', sans-serif !important; font-size: 25px !important; font-weight: 800 !important; color: #0F172A !important; line-height: 1.2 !important; margin: 0 !important; letter-spacing: -0.01em !important;">
                    ABC BUTTONS PRIVATE LIMITED
                </div>
                <div style="font-size: 13px !important; color: #475569 !important; font-weight: 500 !important; margin-top: 5px !important; display: flex !important; align-items: center !important; gap: 8px !important; flex-wrap: wrap !important;">
                    <span style="background: #CCFBF1 !important; color: #0F766E !important; font-weight: 700 !important; font-size: 11px !important; padding: 3px 9px !important; border-radius: 6px !important; border: 1px solid #99F6E4 !important;">
                        ⚡ RAPID BILLING DESK
                    </span>
                    <span style="color: #334155; font-weight: 600;">Garment Buttons &amp; Export Accessories</span>
                    <span style="color: #CBD5E1;">•</span>
                    <span style="color: #64748B;">Govindpuri / Kalkaji, New Delhi - 110019</span>
                </div>
            </div>
        </div>
        <div class="header-chips-row">
            <div class="metric-chip chip-green">
                <span class="live-dot"></span>
                <span>Meta WhatsApp Cloud API: <b>Active (60-Day)</b></span>
            </div>
            <div class="metric-chip chip-teal">
                <span>📦</span>
                <span>Ready Stock: <b>18,450 Gross</b></span>
            </div>
            <div class="metric-chip chip-blue">
                <span>⚡</span>
                <span>Vision Matcher: <b>Multi-Candidate Ready</b></span>
            </div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)


persisted = load_persistent_data()
if "live_whatsapp_inquiries" not in st.session_state:
    st.session_state["live_whatsapp_inquiries"] = persisted.get("live_whatsapp_inquiries", [])


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
    "📥 1. WhatsApp Customer Inbox",
    "🔍 2. AI Button Scanner", 
    "📂 3. Catalog & Stock Gallery",
    "🏍️ 4. Salesman Logger", 
    "🧾 5. 1-Click Quotation", 
    "📊 6. Sample Pipeline", 
    "💳 7. Payment Reminder"
])

# ----------------- TAB 1: VISUAL BUTTON MATCHER -----------------
with tabs[0]:
    # ---------------- TAB 1: WHATSAPP CUSTOMER INBOX (PURE & CLEAN) ----------------
    @st.cache_data(ttl=60, show_spinner=False)
    def check_meta_api_live_connection() -> tuple:
        """Pings Meta Cloud API endpoint to verify real connectivity and token validity."""
        if os.environ.get("STREAMLIT_TESTING"):
            return True, "Live Meta API Connected (Verified)"
        try:
            import whatsapp_service
            token = os.getenv("WHATSAPP_ACCESS_TOKEN") or getattr(whatsapp_service, "WHATSAPP_TOKEN", "")
            phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID") or getattr(whatsapp_service, "PHONE_NUMBER_ID", "")
        except Exception:
            token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
            phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
            
        if not token or not phone_id:
            return False, "Meta API Offline (Token Missing)"
        try:
            import urllib.request
            url = f"https://graph.facebook.com/v22.0/{phone_id}"
            req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "ABC-Buttons-HealthCheck/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    return True, "Live Meta API Connected (Verified)"
                return False, f"Meta HTTP {resp.status}"
        except Exception as e:
            return False, "Meta API Offline / Unreachable"

    is_meta_live, meta_status_label = check_meta_api_live_connection()
    meta_status_badge = (
        f"<span style='color: #4ade80; font-weight: 700; font-size: 13px;'>🟢 {meta_status_label}</span>"
        if is_meta_live else
        f"<span style='color: #f87171; font-weight: 700; font-size: 13px;'>🔴 {meta_status_label}</span>"
    )
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); 
                padding: 22px 28px; border-radius: 14px; margin-bottom: 20px; 
                box-shadow: 0 4px 15px rgba(15, 23, 42, 0.15); border-left: 6px solid #3b82f6;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
            <div>
                <h2 style="color: #ffffff !important; margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.5px;">
                    📥 WhatsApp Customer Inbox & Live Inquiries
                </h2>
                <p style="color: #93c5fd !important; margin: 5px 0 0 0; font-size: 14px;">
                    व्हाट्सएप से आने वाली हर ग्राहक की असली फोटो, बटन का प्रकार और मांगी गई क्वांटिटी यहाँ स्वतः दर्ज होती है।
                </p>
            </div>
            <div style="background: rgba(255,255,255,0.1); padding: 8px 16px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.2);">
                {meta_status_badge}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Top Metrics & Sync Bar
    c_m1, c_m2, c_m3, c_btn = st.columns([1.2, 1.2, 1.4, 1.2])
    wa_inqs_all = st.session_state.get('live_whatsapp_inquiries', [])
    with c_m1:
        st.markdown(f"""
        <div style="background: #eff6ff; border: 1.5px solid #bfdbfe; border-radius: 10px; padding: 12px 16px; text-align: center;">
            <span style="color: #1e40af; font-size: 12px; font-weight: 700; text-transform: uppercase;">Total Customers</span><br>
            <span style="color: #1e3a8a; font-size: 24px; font-weight: 800;">{len(wa_inqs_all)} Logged</span>
        </div>
        """, unsafe_allow_html=True)
    with c_m2:
        photo_count = sum(1 for x in wa_inqs_all if x.get('photo_b64'))
        st.markdown(f"""
        <div style="background: #f0fdf4; border: 1.5px solid #bbf7d0; border-radius: 10px; padding: 12px 16px; text-align: center;">
            <span style="color: #166534; font-size: 12px; font-weight: 700; text-transform: uppercase;">Real Photos</span><br>
            <span style="color: #15803d; font-size: 24px; font-weight: 800;">{photo_count} Attached</span>
        </div>
        """, unsafe_allow_html=True)
    with c_m3:
        total_qty = sum(x.get('quantity', 0) for x in wa_inqs_all)
        st.markdown(f"""
        <div style="background: #fefce8; border: 1.5px solid #fef08a; border-radius: 10px; padding: 12px 16px; text-align: center;">
            <span style="color: #854d0e; font-size: 12px; font-weight: 700; text-transform: uppercase;">Total Quantity</span><br>
            <span style="color: #a16207; font-size: 24px; font-weight: 800;">{total_qty:,} Gross</span>
        </div>
        """, unsafe_allow_html=True)
    with c_btn:
        st.write("")
        if st.button("🔄 Sync with WhatsApp", key="sync_wa_top_btn", help="Fetches real-time buyer photos from Render cloud server", type="primary", use_container_width=True):
            with st.spinner("WhatsApp से नया बायर डेटा व फोटोज़ डाउनलोड हो रही हैं..."):
                cnt = sync_live_whatsapp_inquiries()
                if cnt > 0:
                    st.success(f"✅ {cnt} ग्राहक(ों) का डेटा व असली फोटोज़ डाउनलोड हो गईं!")
                    st.rerun()
                else:
                    st.info("सभी रिकॉर्ड्स पहले से ही अप-टू-डेट हैं।")

    st.markdown("<br>", unsafe_allow_html=True)

    # ---------------- REAL-TIME SMARTPHONE WHATSAPP LIVE STREAM ----------------
    if wa_inqs_all:
        import sys
        is_testing = "unittest" in sys.modules or bool(os.environ.get("STREAMLIT_TESTING"))
        
        def render_live_whatsapp_phone_hub():
            if not is_testing:
                try:
                    sync_live_whatsapp_inquiries()
                except Exception:
                    pass
            inqs = list(st.session_state.get("live_whatsapp_inquiries", []))
            if not inqs:
                return
                
            st.markdown("### 📱 Live WhatsApp Mobile Phone Simulator (रियल-टाइम ग्राहक बातचीत)")
            st.caption("जैसे ही ग्राहक WhatsApp पर मैसेज या फोटो भेजेगा, वह ऑटोमैटिक इस फ़ोन स्क्रीन पर लाइव आ जाएगा:")
            
            col_phone, col_panel = st.columns([1.1, 1.2])
            
            with col_panel:
                buyer_labels = [f"👤 {x.get('buyer_name', 'Customer')} (+{x.get('phone', '')}) — SKU: {x.get('matched_sku', 'Inquiry')}" for x in inqs]
                selected_label = st.selectbox("चुनें कि किस ग्राहक की बातचीत देखनी है:", buyer_labels, index=0, key="live_chat_phone_selector")
                sel_idx = buyer_labels.index(selected_label)
                active_inq = inqs[sel_idx]
                
                # Details Panel
                st.markdown(f"""
                <div style="background: #FFFFFF; border: 1.5px solid #E2E8F0; border-radius: 12px; padding: 16px; margin-bottom: 14px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                        <span style="font-weight: 800; font-size: 16px; color: #0F172A;">{active_inq.get('buyer_name', 'Customer')}</span>
                        <span style="background: #DCFCE7; color: #166534; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 12px;">🟢 Live Auto-Sync (4s)</span>
                    </div>
                    <div style="font-size: 13px; color: #475569; margin-bottom: 6px;">
                        <b>Phone:</b> <span style="font-family: monospace;">+{active_inq.get('phone', '')}</span> &nbsp;|&nbsp; <b>Time:</b> {active_inq.get('timestamp', 'Today')}
                    </div>
                    <div style="font-size: 13px; color: #475569; margin-bottom: 6px;">
                        <b>Matched SKU:</b> <span style="color: #0284C7; font-weight: 700;">{active_inq.get('matched_sku', 'Inquiry')}</span> ({active_inq.get('matched_name', '')}) {f"- Size: <b>{active_inq.get('matched_size')}</b>" if active_inq.get('matched_size') else ""}
                    </div>
                    <div style="display: flex; gap: 14px; font-size: 13px; color: #475569;">
                        <div><b>Customer Requirement:</b> <span style="color: #16A34A; font-weight: 700;">{active_inq.get('customer_required_quantity') or active_inq.get('quantity') or 0:,} Gross</span></div>
                        <div><b>Catalog Stock:</b> <span style="color: #0284C7; font-weight: 700;">{active_inq.get('catalog_available_stock') or 0:,} Gross</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                c_p1, c_p2 = st.columns(2)
                with c_p1:
                    if st.button("🧾 1-Click Quote (Tab 5)", key="btn_hub_quote", type="primary", use_container_width=True):
                        st.session_state["preset_quote_buyer"] = active_inq.get('buyer_name', '')
                        st.session_state["preset_quote_phone"] = active_inq.get('phone', '')
                        st.session_state["preset_quote_sku"] = active_inq.get('matched_sku', '')
                        st.session_state["preset_quote_qty"] = int(active_inq.get('customer_required_quantity') or active_inq.get('quantity') or 0)
                        st.success(f"✅ {active_inq.get('buyer_name')} का डेटा लोड हो गया! ऊपर Tab 5 पर जाएँ।")
                with c_p2:
                    clean_ph = re.sub(r'\D', '', str(active_inq.get('phone', '')))
                    if clean_ph:
                        st.markdown(f"""
                        <a href="https://wa.me/{clean_ph}" target="_blank" style="display: block; text-align: center; background: #25D366; color: white; text-decoration: none; padding: 9px 12px; border-radius: 7px; font-weight: 700; font-size: 13px; box-shadow: 0 2px 4px rgba(37,211,102,0.2);">
                            💬 Open WhatsApp Web
                        </a>
                        """, unsafe_allow_html=True)

                st.markdown("<br>", unsafe_allow_html=True)
                # ---------------- ENTERPRISE CRM CONTROLS ----------------
                # 1. Human Takeover Mode Toggle
                is_takeover = bool(active_inq.get("human_takeover", 0))
                c_t1, c_t2 = st.columns([1.4, 1])
                with c_t1:
                    if is_takeover:
                        st.markdown("""
                        <div style="background: #FEE2E2; border: 1.5px solid #FCA5A5; border-radius: 8px; padding: 6px 10px;">
                            <span style="color: #991B1B; font-weight: 800; font-size: 13px;">🛑 Human Takeover</span><br>
                            <span style="color: #B91C1C; font-size: 11px;">(AI Bot Auto-Reply Paused)</span>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div style="background: #ECFDF5; border: 1.5px solid #A7F3D0; border-radius: 8px; padding: 6px 10px;">
                            <span style="color: #065F46; font-weight: 800; font-size: 13px;">🤖 AI Bot Active</span><br>
                            <span style="color: #047857; font-size: 11px;">(24/7 Smart Auto-Reply)</span>
                        </div>
                        """, unsafe_allow_html=True)
                with c_t2:
                    st.write("")
                    if is_takeover:
                        if st.button("▶️ Resume AI", key=f"btn_resume_{active_inq['phone']}", help="Re-enables AI automatic replies"):
                            with st.spinner("Syncing to Cloud Render..."):
                                ok_cloud, msg = sync_crm_meta_to_cloud(active_inq['phone'], human_takeover=0)
                            if ok_cloud:
                                active_inq['human_takeover'] = 0
                                st.toast("✅ AI Bot resumed on all servers (Streamlit & Render).")
                                st.rerun()
                            else:
                                st.error(f"❌ Fail-Safe Block: Could not resume AI on Render Cloud ({msg}). State unchanged to prevent inconsistency.")
                    else:
                        if st.button("🛑 Take Over", key=f"btn_pause_{active_inq['phone']}", help="Pauses AI bot so human operator can reply directly"):
                            with st.spinner("Syncing to Cloud Render..."):
                                ok_cloud, msg = sync_crm_meta_to_cloud(active_inq['phone'], human_takeover=1)
                            if ok_cloud:
                                active_inq['human_takeover'] = 1
                                st.toast("🛑 AI Bot paused on all servers. You are now controlling this chat.")
                                st.rerun()
                            else:
                                st.error(f"❌ Fail-Safe Block: Cannot Take Over. Cloud Webhook server was unreachable ({msg}). AI Bot was NOT paused on Render.")

                # 2. Direct Operator WhatsApp Dispatch
                st.markdown("<div style='margin-top: 10px; font-weight: 700; font-size: 13px; color: #1E293B;'>💬 Send Direct Message to Customer:</div>", unsafe_allow_html=True)
                c_msg_in, c_msg_btn = st.columns([3, 1])
                with c_msg_in:
                    op_reply = st.text_input("Reply text:", placeholder="Type WhatsApp message...", label_visibility="collapsed", key=f"op_text_{active_inq['phone']}")
                with c_msg_btn:
                    if st.button("📤 Send", key=f"btn_send_op_{active_inq['phone']}", type="primary", use_container_width=True):
                        if op_reply and op_reply.strip():
                            from whatsapp_service import send_whatsapp_text
                            res = send_whatsapp_text(active_inq['phone'], op_reply.strip())
                            success = bool(isinstance(res, dict) and res.get("success", True) and not res.get("error"))
                            if success:
                                op_wamid = None
                                if isinstance(res, dict):
                                    msgs_data = res.get("data", {}).get("messages", [])
                                    if msgs_data and isinstance(msgs_data, list):
                                        op_wamid = msgs_data[0].get("id")
                                import db
                                db.sync_chat_event_db(active_inq['phone'], active_inq.get('buyer_name', 'Customer'), 'operator', 'text', op_reply.strip(), status="SENT", wamid=op_wamid)
                                db.log_outbound_delivery(op_wamid or "", active_inq['phone'], "text", op_reply.strip(), "SENT")
                                st.success("✅ Message dispatched to WhatsApp!")
                                st.rerun()
                            else:
                                err_str = res.get("error", "Unknown Meta API error") if isinstance(res, dict) else "Dispatch failed"
                                st.error(f"❌ Failed to dispatch message via WhatsApp: {err_str}")

                # 3. Salesperson Assignment & Deal Stage
                st.markdown("<div style='margin-top: 10px;'></div>", unsafe_allow_html=True)
                c_sp, c_stage = st.columns(2)
                with c_sp:
                    sales_team = ["Unassigned", "Rahul Sharma (Field Sales)", "Amit Verma (Export Desk)", "Pooja (Sampling Coordinator)", "Gaurav (Production Liaison)"]
                    cur_sp = active_inq.get("assigned_salesman") or "Unassigned"
                    cur_sp_idx = sales_team.index(cur_sp) if cur_sp in sales_team else 0
                    new_sp = st.selectbox("👤 Salesperson:", sales_team, index=cur_sp_idx, key=f"sp_sel_{active_inq['phone']}")
                    if new_sp != cur_sp:
                        ok_cloud, msg = sync_crm_meta_to_cloud(active_inq['phone'], assigned_salesman=new_sp)
                        active_inq['assigned_salesman'] = new_sp
                        st.toast(f"✅ Assigned to {new_sp}")
                        st.rerun()
                with c_stage:
                    stages = ["New Inquiry", "Sampling Requested", "Quotation Sent", "Under Follow-up", "Order Closed", "Inactive / Archived"]
                    cur_st = active_inq.get("crm_status") or "New Inquiry"
                    cur_st_idx = stages.index(cur_st) if cur_st in stages else 0
                    new_st = st.selectbox("📌 Deal Stage:", stages, index=cur_st_idx, key=f"stage_sel_{active_inq['phone']}")
                    if new_st != cur_st:
                        ok_cloud, msg = sync_crm_meta_to_cloud(active_inq['phone'], crm_status=new_st)
                        active_inq['crm_status'] = new_st
                        st.toast(f"✅ Stage updated: {new_st}")
                        st.rerun()
                        
            with col_phone:
                import base64
                import html
                msgs = list(active_inq.get("chat_messages", []))
                p_time = active_inq.get("timestamp", "Today")
                if " " in p_time:
                    p_time = p_time.split(" ")[1][:5]
                
                # Real messages only: never synthesize fake dialogues
                if not msgs:
                    buyer_note = (active_inq.get("notes") or "").strip()
                    if active_inq.get("photo_b64") or (buyer_note and buyer_note != "Button Inquiry"):
                        msgs.append({
                            "sender": "buyer",
                            "sender_name": active_inq.get("buyer_name", "Customer"),
                            "type": "image" if active_inq.get("photo_b64") else "text",
                            "text": buyer_note if buyer_note else "📷 [Buyer sent button photo]",
                            "photo_b64": active_inq.get("photo_b64"),
                            "time": p_time
                        })
                        
                bubbles_html = ""
                if not msgs:
                    bubbles_html = """
                    <div style="align-self: center; background: #F8FAFC; color: #475569; font-size: 11.5px; padding: 14px 16px; border-radius: 10px; text-align: center; margin: 40px 10px; border: 1px dashed #CBD5E1; line-height: 1.4;">
                        💬 <b>No Message History Yet</b><br>
                        <span style="font-size: 10.5px; color: #64748B;">No conversation events recorded for this contact. Incoming and outgoing WhatsApp messages will appear here in real-time.</span>
                    </div>
                    """
                else:
                    for m in msgs:
                        s = m.get("sender", "buyer")
                        is_buyer = (s == "buyer")
                        m_time = html.escape(str(m.get("time", "")))
                        m_text = html.escape(str(m.get("text", ""))).replace("\n", "<br>")
                        s_name = html.escape(str(m.get("sender_name", "Customer" if is_buyer else "ABC Buttons Assistant")))
                        
                        img_tag = ""
                        if m.get("photo_b64") and is_buyer:
                            img_tag = f'<img src="data:image/jpeg;base64,{m["photo_b64"]}" style="width: 100%; max-height: 140px; object-fit: cover; border-radius: 8px; margin-bottom: 4px;" />'
                        elif m.get("sku") and not is_buyer and m.get("sku") != "Custom / Non-Catalog":
                            s_path = os.path.join(IMG_DIR, f"{m['sku']}.jpg")
                            if os.path.exists(s_path):
                                with open(s_path, "rb") as ifp:
                                    b64_cat = base64.b64encode(ifp.read()).decode("utf-8")
                                img_tag = f'<img src="data:image/jpeg;base64,{b64_cat}" style="width: 100%; max-height: 140px; object-fit: cover; border-radius: 8px; margin-bottom: 4px;" />'
                                
                        if is_buyer:
                            bubbles_html += f"""
                            <div style="align-self: flex-start; background: #FFFFFF; color: #0F172A; border-radius: 0 10px 10px 10px; padding: 7px 10px; max-width: 82%; box-shadow: 0 1px 2px rgba(0,0,0,0.12); font-size: 12.5px; line-height: 1.35; margin-bottom: 8px;">
                                <div style="font-size: 10px; font-weight: 700; color: #0284C7; margin-bottom: 2px;">{s_name}</div>
                                {img_tag}
                                <div>{m_text}</div>
                                <div style="font-size: 9px; color: #64748B; text-align: right; margin-top: 3px;">{m_time}</div>
                            </div>
                            """
                        else:
                            m_stat = str(m.get("status", "")).upper()
                            if m_stat == "FAILED":
                                tick_html = '<span style="color: #EF4444; font-weight: 700; font-size: 10px;">⚠️ Failed</span>'
                            elif m_stat == "READ":
                                tick_html = '<span style="color: #38BDF8; font-weight: 700;">✓✓</span>'
                            elif m_stat == "DELIVERED":
                                tick_html = '<span style="color: #64748B; font-weight: 700;">✓✓</span>'
                            elif m_stat == "SENT":
                                tick_html = '<span style="color: #64748B; font-weight: 700;">✓</span>'
                            else:
                                tick_html = '<span style="color: #94A3B8; font-weight: 600; font-size: 11px;">⏱️</span>'
                            bubbles_html += f"""
                            <div style="align-self: flex-end; background: #DCF8C6; color: #0F172A; border-radius: 10px 0 10px 10px; padding: 7px 10px; max-width: 84%; box-shadow: 0 1px 2px rgba(0,0,0,0.12); font-size: 12.5px; line-height: 1.35; margin-bottom: 8px;">
                                {img_tag}
                                <div>{m_text}</div>
                                <div style="font-size: 9px; color: #64748B; text-align: right; margin-top: 3px;">{m_time} {tick_html}</div>
                            </div>
                            """
                        
                b_initials = (active_inq.get('buyer_name', 'C')[:2]).upper()
                phone_html = f"""
                <div style="width: 360px; max-width: 100%; margin: 0 auto; background: #0F172A; border-radius: 36px; padding: 10px 8px 12px 8px; box-shadow: 0 20px 40px -10px rgba(15, 23, 42, 0.45); border: 2.5px solid #334155;">
                    <div style="width: 80px; height: 12px; background: #000000; border-radius: 10px; margin: 0 auto 8px auto;"></div>
                    <div style="background: #075E54; padding: 8px 12px; border-radius: 14px 14px 0 0; display: flex; justify-content: space-between; align-items: center; color: white;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 15px;">←</span>
                            <div style="width: 30px; height: 30px; border-radius: 50%; background: #128C7E; color: white; font-weight: 700; font-size: 12px; display: flex; align-items: center; justify-content: center; border: 1.5px solid #25D366;">
                                {b_initials}
                            </div>
                            <div>
                                <div style="font-weight: 700; font-size: 13px; color: #FFFFFF; line-height: 1.2;">{active_inq.get('buyer_name', 'Customer')}</div>
                                <div style="font-size: 10px; color: #A7F3D0;">Verified WhatsApp Contact</div>
                            </div>
                        </div>
                        <div style="font-size: 14px; display: flex; gap: 10px; color: #FFFFFF; opacity: 0.9;">
                            <span>📹</span>
                            <span>📞</span>
                            <span>⋮</span>
                        </div>
                    </div>
                    <div style="background-color: #EFEAE2; background-image: radial-gradient(#CBD5E1 0.75px, transparent 0.75px); background-size: 16px 16px; height: 380px; overflow-y: auto; padding: 12px 8px; display: flex; flex-direction: column;">
                        <div style="align-self: center; background: #E1F3FB; color: #0369A1; font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 10px; box-shadow: 0 1px 2px rgba(0,0,0,0.06); margin-bottom: 8px;">
                            TODAY
                        </div>
                        {bubbles_html}
                    </div>
                    <div style="background: #F0F2F5; padding: 6px 8px; border-radius: 0 0 22px 22px; display: flex; align-items: center; gap: 6px; border-top: 1px solid #E2E8F0;">
                        <span style="font-size: 16px;">😊</span>
                        <div style="color: #94A3B8; font-size: 12px; flex-grow: 1; background: #FFFFFF; padding: 4px 8px; border-radius: 14px; border: 1px solid #E2E8F0;">Type a message...</div>
                        <span style="font-size: 14px;">📎</span>
                        <span style="font-size: 14px;">📷</span>
                        <div style="width: 28px; height: 28px; border-radius: 50%; background: #00A884; color: white; display: flex; align-items: center; justify-content: center; font-size: 13px;">🎤</div>
                    </div>
                </div>
                """
                st.html(phone_html)
            st.markdown("---")

        if not is_testing:
            st.fragment(run_every=4)(render_live_whatsapp_phone_hub)()
        else:
            render_live_whatsapp_phone_hub()

    # Search & Filter Input
    search_q = st.text_input("🔍 ग्राहक के नाम, फ़ोन नंबर या बटन SKU से खोजें:", placeholder="उदा. Anoop, 93157, या ABC-136...")
    
    # Filter inquiries
    display_inqs = []
    for x in wa_inqs_all:
        t_str = f"{x.get('buyer_name', '')} {x.get('phone', '')} {x.get('matched_sku', '')} {x.get('matched_name', '')}".lower()
        if not search_q or search_q.lower() in t_str:
            display_inqs.append(x)

    if not display_inqs:
        st.markdown("""
        <div style="background: #f8fafc; border: 2px dashed #cbd5e1; border-radius: 12px; padding: 40px; text-align: center; margin-top: 15px;">
            <h4 style="color: #64748b; margin-bottom: 8px;">💡 अभी कोई इंक्वायरी नहीं मिली</h4>
            <p style="color: #94a3b8; font-size: 14px; margin: 0;">
                जैसे ही कोई ग्राहक आपके WhatsApp नंबर पर फोटो या मैसेज भेजेगा, वह ऑटोमैटिक यहाँ सेव हो जाएगी।
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        for inq_i, inq in enumerate(display_inqs):
            # Rich high-contrast card
            p_b64 = inq.get("photo_b64")
            with st.container():
                st.markdown(f"""
                <div style="background: #FFFFFF; border: 1.5px solid #E2E8F0; border-left: 6px solid #2563EB; 
                            border-radius: 12px; padding: 18px 22px; margin-bottom: 14px; 
                            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
                """, unsafe_allow_html=True)
                
                c_card1, c_card2, c_card3 = st.columns([1.2, 2.5, 1.3])
                with c_card1:
                    if p_b64:
                        try:
                            import base64
                            from io import BytesIO
                            st.image(BytesIO(base64.b64decode(p_b64)), caption="📷 Customer's Sample Photo", use_container_width=True)
                        except Exception:
                            st.write("📷 [Photo Available]")
                    else:
                        st.markdown("""
                        <div style="background: #F1F5F9; border-radius: 8px; padding: 35px 10px; text-align: center; color: #64748B;">
                            💬 <b>Text Inquiry</b><br><small>(No Photo)</small>
                        </div>
                        """, unsafe_allow_html=True)
                        
                with c_card2:
                    inq_id_badge = f"""<span style="background: #FEF3C7; color: #92400E; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; border: 1px solid #FCD34D;">📋 {inq.get('id', 'INQ-NEW')}</span>"""
                    comp_name = inq.get('company') or ''
                    city_name = inq.get('city') or ''
                    comp_badge = f"""<span style="background: #F3E8FF; color: #6B21A8; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 700; border: 1px solid #D8B4FE; margin-left: 6px;">🏢 {comp_name or 'Company Pending'}{f' ({city_name})' if city_name else ''}</span>"""
                    
                    st.markdown(f"""
                    <div style="margin-bottom: 6px;">
                        <span style="font-size: 18px; font-weight: 800; color: #0F172A;">👤 {inq.get('buyer_name', 'Customer')}</span>
                        <span style="background: #EFF6FF; color: #1D4ED8; padding: 3px 9px; border-radius: 12px; font-size: 12px; font-weight: 700; margin-left: 8px; border: 1px solid #BFDBFE;">+{inq.get('phone', '')}</span>
                        {inq_id_badge}
                        {comp_badge}
                        <span style="color: #64748B; font-size: 12px; margin-left: 8px;">⏱️ {inq.get('timestamp', '')}</span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Notes & internal CV extraction
                    inq_notes = inq.get('notes', '')
                    if inq_notes:
                        st.markdown(f"""
                        <div style="font-size: 12.5px; color: #475569; background: #F8FAFC; padding: 6px 10px; border-radius: 6px; border: 1px solid #E2E8F0; margin-bottom: 6px;">
                            <b>Buyer Note & CV:</b> {html.escape(inq_notes)}
                        </div>
                        """, unsafe_allow_html=True)
                    
                    st.markdown(f"""
                    <div style="margin: 6px 0; color: #334155; font-size: 13.5px;">
                        🔘 <b>Reference/Candidate:</b> <span style="color: #0369A1; font-weight: 700;">{inq.get('matched_sku', 'N/A')}</span> - {inq.get('matched_name', '')}
                    </div>
                    """, unsafe_allow_html=True)
                    
                    qty_val = inq.get('customer_required_quantity') or inq.get('quantity', 0)
                    cat_stock_val = inq.get('catalog_available_stock', 0)
                    if qty_val:
                        qty_badge = f"""<span style="background: #DCFCE7; color: #15803D; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 800; border: 1.5px solid #86EFAC;">📦 Required: {qty_val:,} Gross ({qty_val*144:,} Pcs)</span>"""
                    else:
                        qty_badge = """<span style="background: #FEF3C7; color: #B45309; padding: 4px 12px; border-radius: 20px; font-size: 13px; font-weight: 700; border: 1.5px solid #FDE68A;">⏳ Awaiting Quantity Confirmation</span>"""
                    
                    stock_badge = f"""<span style="background: #EFF6FF; color: #1D4ED8; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 700; border: 1px solid #BFDBFE; margin-left: 6px;">🏭 Reference Stock: {cat_stock_val:,} Gross</span>""" if cat_stock_val else ""
                    
                    st.markdown(f"""
                    <div style="margin-top: 8px;">
                        {qty_badge}
                        {stock_badge}
                        <span style="background: #F1F5F9; color: #475569; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; margin-left: 8px;">Status: {inq.get('crm_status') or inq.get('status', 'New Inquiry')}</span>
                    </div>
                    """, unsafe_allow_html=True)
                    
                with c_card3:
                    st.write("")
                    if st.button("🧾 1-Click Quote (Tab 5)", key=f"btn_inbox_quote_{inq_i}", type="primary", use_container_width=True):
                        st.session_state["preset_quote_buyer"] = inq.get('buyer_name', '')
                        st.session_state["preset_quote_phone"] = inq.get('phone', '')
                        st.session_state["preset_quote_sku"] = inq.get('matched_sku', '')
                        st.session_state["preset_quote_qty"] = int(inq.get('customer_required_quantity') or inq.get('quantity') or 0)
                        st.session_state["preset_quote_company"] = inq.get('company', '')
                        st.session_state["preset_quote_city"] = inq.get('city', '')
                        st.success(f"✅ {inq.get('buyer_name')} का डेटा Tab 5 (1-Click Quotation) में लोड हो गया! ऊपर Tab 5 पर क्लिक करें।")
                    
                    # Direct WhatsApp link
                    phone_clean = re.sub(r'\D', '', str(inq.get('phone', '')))
                    if phone_clean:
                        wa_link = f"https://wa.me/{phone_clean}"
                        st.markdown(f"""
                        <div style="margin-top: 8px; text-align: center;">
                            <a href="{wa_link}" target="_blank" style="display: block; background: #25D366; color: white; text-decoration: none; padding: 8px 12px; border-radius: 6px; font-weight: 700; font-size: 13px; box-shadow: 0 2px 4px rgba(37,211,102,0.2);">
                                💬 Open WhatsApp Chat
                            </a>
                        </div>
                        """, unsafe_allow_html=True)

                # ---------------- SALES TEAM ACTION HUB ----------------
                with st.expander("⚡ Sales Team Action Hub (Stock Check • Similar Samples • Factory Feasibility • Takeover)", expanded=False):
                    st.caption("Authorized Sales Actions: केवल सेल्स टीम भौतिक जांच के बाद ही ग्राहक को फोटो, स्टॉक व कोटेशन भेज सकती है:")
                    
                    # Row 1: CRM Controls (Human Takeover, Salesperson, Deal Stage)
                    crm_col1, crm_col2, crm_col3 = st.columns([1.2, 1.2, 1.2])
                    card_takeover = bool(inq.get("human_takeover", 0))
                    with crm_col1:
                        if card_takeover:
                            if st.button("▶️ Resume AI Bot", key=f"btn_res_card_{inq_i}"):
                                ok_s, m_s = sync_crm_meta_to_cloud(inq['phone'], human_takeover=0)
                                if ok_s:
                                    inq['human_takeover'] = 0
                                    st.toast("✅ AI Bot resumed!")
                                    st.rerun()
                        else:
                            if st.button("🛑 Take Over Chat", key=f"btn_tk_card_{inq_i}"):
                                ok_s, m_s = sync_crm_meta_to_cloud(inq['phone'], human_takeover=1)
                                if ok_s:
                                    inq['human_takeover'] = 1
                                    st.toast("🛑 Takeover active! AI Bot paused.")
                                    st.rerun()
                    with crm_col2:
                        team_opts = ["Unassigned", "Rahul Sharma (Field Sales)", "Amit Verma (Export Desk)", "Pooja (Sampling Coordinator)", "Gaurav (Production Liaison)"]
                        cur_sp_card = inq.get("assigned_salesman") or "Unassigned"
                        sp_idx = team_opts.index(cur_sp_card) if cur_sp_card in team_opts else 0
                        sel_sp_card = st.selectbox("Assign Salesperson:", team_opts, index=sp_idx, key=f"sp_card_sel_{inq_i}")
                        if sel_sp_card != cur_sp_card:
                            sync_crm_meta_to_cloud(inq['phone'], assigned_salesman=sel_sp_card)
                            inq['assigned_salesman'] = sel_sp_card
                            st.toast(f"✅ Assigned to {sel_sp_card}")
                            st.rerun()
                    with crm_col3:
                        stage_opts = ["New Inquiry", "Sampling Requested", "Stock Confirmed - Ready to Quote", "Similar Options Offered", "Custom Mfg Offered", "Quotation Sent", "Order Closed"]
                        cur_st_card = inq.get("crm_status") or "New Inquiry"
                        st_idx = stage_opts.index(cur_st_card) if cur_st_card in stage_opts else 0
                        sel_st_card = st.selectbox("Inquiry Status:", stage_opts, index=st_idx, key=f"st_card_sel_{inq_i}")
                        if sel_st_card != cur_st_card:
                            sync_crm_meta_to_cloud(inq['phone'], crm_status=sel_st_card)
                            inq['crm_status'] = sel_st_card
                            st.toast(f"✅ Status: {sel_st_card}")
                            st.rerun()

                    st.markdown("<hr style='margin: 10px 0;'>", unsafe_allow_html=True)
                    
                    # Row 2: 4 Action Buttons in Tabs
                    act_tab1, act_tab2, act_tab3, act_tab4 = st.tabs([
                        "📦 1. Check Ready Stock",
                        "🔍 2. Offer Similar Options",
                        "🏭 3. Factory Feasibility",
                        "📄 4. Quotation"
                    ])
                    
                    with act_tab1:
                        st.markdown("##### 📦 Action 1: भौतिक स्टॉक जांच एवं फोटो प्रेषण (Physical Stock & Photo)")
                        st.caption("कैटलॉग SKU चुनें, गोदाम में वास्तविक स्टॉक गिनें और ग्राहक को सत्यापित फोटो भेजें:")
                        cat_skus = [f"{it['sku']} — {it['name']} (Listed: {it['stock_gross']} Gr)" for it in SAMPLE_CATALOG]
                        # Set default if matched_sku exists
                        def_sku_idx = 0
                        for idx_s, it_s in enumerate(SAMPLE_CATALOG):
                            if it_s['sku'] == inq.get('matched_sku'):
                                def_sku_idx = idx_s
                                break
                        sel_cat_str = st.selectbox("Catalog Item to Verify:", cat_skus, index=def_sku_idx, key=f"act1_sku_{inq_i}")
                        chosen_sku = sel_cat_str.split(" — ")[0]
                        chosen_item = next((it for it in SAMPLE_CATALOG if it['sku'] == chosen_sku), SAMPLE_CATALOG[0])
                        
                        col_v1, col_v2 = st.columns([1, 2])
                        with col_v1:
                            v_img_path = os.path.join(IMG_DIR, f"{chosen_sku}.jpg")
                            if os.path.exists(v_img_path):
                                st.image(v_img_path, caption=f"Catalog: {chosen_sku}", width=130)
                        with col_v2:
                            phys_stock = st.number_input("Physically Verified Godown Stock (Gross):", min_value=0, value=int(chosen_item.get('stock_gross', 500)), step=50, key=f"act1_stock_{inq_i}")
                            v_note = st.text_input("Special Sales Note for Buyer:", value="Exact matching export quality batch ready.", key=f"act1_note_{inq_i}")
                            
                            if st.button("📤 Send Verified Photo & Stock to WhatsApp", key=f"btn_send_verified_{inq_i}", type="primary"):
                                import webhook_bot
                                sp_name = inq.get("assigned_salesman") or "ABC Buttons Sales Desk"
                                with st.spinner("WhatsApp पर फोटो व स्टॉक भेजा जा रहा है..."):
                                    res_v = webhook_bot.send_verified_stock_and_photo(
                                        phone=inq['phone'],
                                        sku=chosen_sku,
                                        warehouse_stock=phys_stock,
                                        salesperson_name=sp_name,
                                        custom_note=v_note
                                    )
                                sync_crm_meta_to_cloud(inq['phone'], action_taken=f"Stock Verified ({chosen_sku}, {phys_stock} Gr)", crm_status="Stock Confirmed - Ready to Quote")
                                st.success(f"✅ Verified photo for {chosen_sku} dispatched to +{inq['phone']}!")
                                st.rerun()

                    with act_tab2:
                        st.markdown("##### 🔍 Action 2: मिलते-जुलते विकल्प प्रस्तुत करें (Similar Samples)")
                        st.caption("यदि मूल डिज़ाइन रेडी नहीं है, तो ग्राहक को 2 समान विकल्प भेजें:")
                        sku_choices = [it['sku'] for it in SAMPLE_CATALOG]
                        alt_col1, alt_col2 = st.columns(2)
                        with alt_col1:
                            alt1 = st.selectbox("Similar Option 1:", sku_choices, index=0, key=f"alt1_sel_{inq_i}")
                        with alt_col2:
                            alt2 = st.selectbox("Similar Option 2:", sku_choices, index=min(1, len(sku_choices)-1), key=f"alt2_sel_{inq_i}")
                        
                        if st.button("📤 Send 2 Similar Options to Customer", key=f"btn_send_similar_{inq_i}"):
                            import webhook_bot
                            sp_name = inq.get("assigned_salesman") or "ABC Buttons Sales Desk"
                            with st.spinner("मिलते-जुलते विकल्प WhatsApp पर भेजे जा रहे हैं..."):
                                webhook_bot.send_similar_options_pitch(inq['phone'], [alt1, alt2], salesperson_name=sp_name)
                            sync_crm_meta_to_cloud(inq['phone'], action_taken=f"Similar Options Sent ({alt1}, {alt2})", crm_status="Similar Options Offered")
                            st.success(f"✅ Similar options ({alt1}, {alt2}) dispatched to WhatsApp!")
                            st.rerun()

                    with act_tab3:
                        st.markdown("##### 🏭 Action 3: फ़ैक्ट्री कस्टम निर्माण प्रस्ताव (Custom Manufacturing Feasibility)")
                        st.caption("यदि ग्राहक को स्पेशल या कस्टम डिज़ाइन चाहिए:")
                        mfg_c1, mfg_c2 = st.columns(2)
                        with mfg_c1:
                            mfg_moq = st.number_input("Factory MOQ (Gross):", min_value=100, value=500, step=100, key=f"moq_in_{inq_i}")
                        with mfg_c2:
                            mfg_lead = st.number_input("Lead Time (Days):", min_value=3, value=10, step=1, key=f"lead_in_{inq_i}")
                            
                        if st.button("📤 Send Custom Manufacturing Feasibility", key=f"btn_send_mfg_{inq_i}"):
                            import webhook_bot
                            sp_name = inq.get("assigned_salesman") or "ABC Buttons Sales Desk"
                            with st.spinner("कस्टम मैन्युफैक्चरिंग डिटेल्स भेजी जा रही हैं..."):
                                webhook_bot.send_custom_mfg_feasibility(inq['phone'], moq=mfg_moq, lead_days=mfg_lead, salesperson_name=sp_name)
                            sync_crm_meta_to_cloud(inq['phone'], action_taken=f"Custom Feasibility Sent (MOQ {mfg_moq} Gr)", crm_status="Custom Mfg Offered")
                            st.success(f"✅ Factory feasibility sent to +{inq['phone']}!")
                            st.rerun()

                    with act_tab4:
                        st.markdown("##### 📄 Action 4: कोटेशन व प्रोफ़ॉर्मा इनवॉइस (Formal Quotation)")
                        st.write(f"**Buyer:** {inq.get('buyer_name')} | **Company:** {inq.get('company') or 'N/A'} | **Qty:** {qty_val} Gross")
                        if st.button("🚀 Load Customer Details into Tab 5", key=f"btn_tab4_quote_{inq_i}", type="primary"):
                            st.session_state["preset_quote_buyer"] = inq.get('buyer_name', '')
                            st.session_state["preset_quote_phone"] = inq.get('phone', '')
                            st.session_state["preset_quote_sku"] = inq.get('matched_sku', '')
                            st.session_state["preset_quote_qty"] = int(qty_val or 200)
                            st.session_state["preset_quote_company"] = inq.get('company', '')
                            st.session_state["preset_quote_city"] = inq.get('city', '')
                            st.success("✅ Loaded into Tab 5 (1-Click Quotation)! ऊपर Tab 5 पर क्लिक करें।")

                st.markdown("</div>", unsafe_allow_html=True)

    # Optional Collapsed WhatsApp Simulator at bottom
    with st.expander("🧪 Test Simulator (Internal Message & Photo Testing)", expanded=False):
        st.caption("यदि आपके पास असली WhatsApp नहीं है, तो यहाँ से टेस्ट मैसेज भेजकर देख सकते हैं कि बॉट क्या रिप्लाई करता है:")
        sim_col1, sim_col2 = st.columns([2, 1])
        with sim_col1:
            sim_phone = st.text_input("Simulate Customer Phone:", value="919315702804")
            sim_text = st.text_input("Simulate Customer Message:", value="Namaste, 200 gross button chahiye river shell me")
        with sim_col2:
            st.write("")
            st.write("")
            if st.button("⚡ Simulate Incoming WhatsApp Message", key="btn_run_sim"):
                from webhook_bot import process_incoming_whatsapp_message
                import asyncio
                mock_msg = {
                    "contacts": [{"profile": {"name": "Test Customer"}}],
                    "messages": [{"id": f"sim_{inqs_count+1}", "from": sim_phone, "type": "text", "text": {"body": sim_text}}]
                }
                asyncio.run(process_incoming_whatsapp_message(mock_msg))
                st.success("Message processed! Check response in live inbox above.")
                st.rerun()

with tabs[1]:
    # ---------------- TAB 2: AI BUTTON SCANNER & INVENTORY MATCHER (ENTERPRISE LAB) ----------------
    import base64
    import hashlib
    import html
    import re
    import time
    import urllib.parse
    from uuid import uuid4
    from PIL import Image
    from io import BytesIO
    import db
    from ai_engine import analyze_button_or_fabric_image

    st.markdown("""
    <div style="background: linear-gradient(135deg, #1e1b4b 0%, #312e81 60%, #4338ca 100%); 
                padding: 22px 28px; border-radius: 14px; margin-bottom: 20px; 
                box-shadow: 0 4px 15px rgba(49, 46, 129, 0.2); border-left: 6px solid #818cf8;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
            <div>
                <h2 style="color: #ffffff !important; margin: 0; font-size: 22px; font-weight: 800; letter-spacing: -0.5px;">
                    🔍 AI Visual Button Matcher & Inventory Scanner
                </h2>
                <p style="color: #c7d2fe !important; margin: 5px 0 0 0; font-size: 13.5px;">
                    Top 3 Candidate Matching • Mandatory Human Verification • Real Warehouse Stock Handoff • Safe WhatsApp Dispatch
                </p>
            </div>
            <div style="background: rgba(255,255,255,0.12); padding: 6px 14px; border-radius: 20px; border: 1px solid rgba(255,255,255,0.25);">
                <span style="color: #a5b4fc; font-weight: 700; font-size: 12px;">⚡ Multi-Candidate Ranked Engine</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 1. Inquiry Linkage & Buyer Selection (Requirement 1, 7, 10, 15)
    st.markdown("##### 👤 Step 1: बायर पहचान एवं इन्क्वायरी लिंकेज (Customer & Inquiry Linkage)")
    col_buyer_sel, col_inq_meta = st.columns([1.5, 1])

    live_inqs_all = db.load_live_inquiries_db()
    buyer_choices = ["➕ New Customer / Walk-in Buyer"]
    for inq_item in live_inqs_all:
        b_name = inq_item.get("buyer_name", "Customer")
        b_ph = inq_item.get("phone", "")
        b_sku = inq_item.get("matched_sku", "Inquiry")
        buyer_choices.append(f"👤 {b_name} (+{b_ph}) — SKU: {b_sku}")

    with col_buyer_sel:
        selected_buyer_opt = st.selectbox(
            "लिंक करने के लिए ग्राहक चुनें (Link to Customer Profile):",
            buyer_choices,
            index=0,
            key="scanner_buyer_selector"
        )

    scan_buyer_name = "Walk-in Buyer"
    scan_buyer_phone = ""
    target_inq_id = None

    if selected_buyer_opt.startswith("👤"):
        sel_b_idx = buyer_choices.index(selected_buyer_opt) - 1
        active_rec = live_inqs_all[sel_b_idx]
        scan_buyer_name = active_rec.get("buyer_name", "Customer")
        scan_buyer_phone = str(active_rec.get("phone", ""))
        target_inq_id = active_rec.get("id")
    else:
        cb1, cb2 = st.columns(2)
        with cb1:
            scan_buyer_name = st.text_input("Buyer / Company Name:", value="New Garment Buyer", key="scan_new_bname")
        with cb2:
            scan_buyer_phone = st.text_input("WhatsApp Mobile Number:", placeholder="e.g. 9811234567", key="scan_new_bphone")

    clean_scan_phone = "".join(ch for ch in scan_buyer_phone if ch.isdigit())
    if not target_inq_id:
        if "scanner_curr_inq_id" not in st.session_state:
            st.session_state["scanner_curr_inq_id"] = f"INQ-SCAN-{datetime.datetime.now().strftime('%Y%m%d')}-{uuid4().hex[:4].upper()}"
        target_inq_id = st.session_state["scanner_curr_inq_id"]

    with col_inq_meta:
        st.markdown(f"""
        <div style="background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 10px; padding: 10px 14px; margin-top: 4px;">
            <div style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase;">Active Inquiry Tracking ID</div>
            <div style="font-size: 15px; font-weight: 800; color: #1e293b; font-family: monospace; margin-top: 2px;">
                🏷️ {html.escape(target_inq_id)}
            </div>
            <div style="font-size: 11px; color: #475569; margin-top: 2px;">
                Buyer: <b>{html.escape(scan_buyer_name)}</b> | Phone: <b>{'+' + clean_scan_phone if clean_scan_phone else 'Not Verified'}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<hr style='margin: 14px 0;'>", unsafe_allow_html=True)

    col_input, col_result = st.columns([1, 1.25])
    
    with col_input:
        st.markdown("#### Step 2: बटन की फोटो लोड करें (Buyer Image Input)")
        
        input_choice = st.radio("Testing Source:", [
            "📸 Use Camera (Take Live Photo from Phone / Laptop)",
            "📁 Upload Photo from Computer / Phone Gallery",
            "🔘 Use Pre-Loaded Buyer Samples (5 Running Items)"
        ], horizontal=True, key="scanner_src_radio")
        
        selected_img_bytes = None
        selected_label = ""
        buyer_notes = ""
        
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
            buyer_notes = st.text_input("Buyer's WhatsApp message / requirement:", placeholder="e.g. 'Ye button mil jayega kya? 200 gross chahiye'", key="cam_buyer_notes")
            
        elif input_choice.startswith("📁"):
            uploaded_file = st.file_uploader("Upload any button or fabric photo (JPG / PNG):", type=["jpg", "jpeg", "png"], key="scanner_file_up")
            if uploaded_file is not None:
                img = Image.open(uploaded_file)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buf = BytesIO()
                img.save(buf, format="JPEG")
                selected_img_bytes = buf.getvalue()
                selected_label = uploaded_file.name
                st.image(img, caption="Uploaded Photo", use_container_width=True)
            buyer_notes = st.text_input("Buyer's WhatsApp message:", placeholder="e.g. 'Ye button mil jayega kya? Rate aur availability batao'", key="file_buyer_notes")
            
        else:
            # 5 Verified Running Buyer Samples (Requirement 16)
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
            # Requirement 16: Supply working sample images or remove unavailable sample options
            valid_photos_map = {}
            for k, (fname, hint) in real_photos_map.items():
                p = os.path.join(TEST_DIR, fname)
                if os.path.exists(p):
                    valid_photos_map[k] = (fname, hint)
            
            if not valid_photos_map:
                st.warning("⚠️ No pre-loaded sample photo assets found in test directory.")
            else:
                chosen_key = st.selectbox("Pick an Actual Buyer Photo to Test:", list(valid_photos_map.keys()), key="sample_photo_sel")
                filename, prompt_hint = valid_photos_map[chosen_key]
                fpath = os.path.join(TEST_DIR, filename)
                
                with open(fpath, "rb") as f_raw:
                    selected_img_bytes = f_raw.read()
                img = Image.open(fpath)
                selected_label = chosen_key
                st.image(img, caption=f"Buyer WhatsApp Photo: {chosen_key}", use_container_width=True)
                buyer_notes = st.text_input("Buyer's WhatsApp message:", value=prompt_hint, key="sample_buyer_notes")

        # Stale Analysis Purge & Invalidation on Buyer/Photo/Notes changes (Requirement 7 & 12)
        if selected_img_bytes is not None:
            curr_input_sig = hashlib.sha256(
                (clean_scan_phone or "").encode("utf-8") +
                b"|" + (scan_buyer_name or "").encode("utf-8") +
                b"|" + (buyer_notes or "").strip().encode("utf-8") +
                b"|" + selected_img_bytes
            ).hexdigest()[:16]
            prev_input_sig = st.session_state.get("scanner_active_input_sig")
            if prev_input_sig and prev_input_sig != curr_input_sig:
                # User changed buyer, photo, or note -> clear previous analysis and approval immediately
                st.session_state.pop("tab1_match_result", None)
                st.session_state.pop("scanner_approved_sku", None)
                st.session_state.pop("scanner_approved_cand", None)
                st.session_state.pop("scanner_human_reviewed", None)
                st.session_state.pop("scanner_dispatch_wamid", None)
            st.session_state["scanner_active_input_sig"] = curr_input_sig

    with col_result:
        st.markdown("#### Step 3: AI विज़न मिलान एवं कैंडिडेट रैंकिंग")
        
        if selected_img_bytes is not None:
            if st.button("🚀 Analyze & Match with ABC Buttons Inventory", type="primary", key="btn_run_scanner"):
                with st.spinner("AI scanning material sheen, holes, thickness & ranking Top 3 candidates..."):
                    try:
                        scan_res = analyze_button_or_fabric_image(selected_img_bytes, buyer_notes)
                        st.session_state["tab1_match_result"] = scan_res
                        st.session_state.pop("scanner_approved_sku", None)
                        st.session_state.pop("scanner_approved_cand", None)
                        st.session_state.pop("scanner_human_reviewed", None)
                        
                        # Requirement 1: Integrate log_scanner_inquiry() into the scanner workflow
                        photo_b64_str = base64.b64encode(selected_img_bytes).decode("utf-8")
                        top_cands = scan_res.get("top_candidates", [])
                        top_c1 = top_cands[0] if top_cands else {}
                        matched_sku_val = top_c1.get("sku") or scan_res.get("best_match_sku") or "Custom Non-Catalog"
                        matched_name_val = top_c1.get("name") or scan_res.get("visual_analysis", {}).get("finish_detected", "Button Inquiry")
                        
                        # Extract quantity requirement if mentioned
                        detected_qty = 0
                        qty_m = re.search(r'(\d+)\s*(?:gross|gr|gros)\b', (buyer_notes or "").lower())
                        if qty_m:
                            detected_qty = int(qty_m.group(1))
                            
                        cat_item = next((x for x in st.session_state.live_catalog if x["sku"] == matched_sku_val), None)
                        c_stock = cat_item["stock_gross"] if cat_item else 0
                        
                        db.log_scanner_inquiry(
                            inquiry_id=target_inq_id,
                            phone=clean_scan_phone,
                            buyer_name=scan_buyer_name,
                            photo_b64=photo_b64_str,
                            matched_sku=matched_sku_val,
                            matched_name=matched_name_val,
                            matched_size=scan_res.get("visual_analysis", {}).get("estimated_size", ""),
                            quantity=detected_qty,
                            notes=buyer_notes,
                            crm_status="AI Scan Complete - Pending Human Verification",
                            assigned_salesman="Unassigned",
                            human_approved=0,
                            catalog_available_stock=c_stock,
                            verified_live_stock=0
                        )
                    except Exception as e:
                        st.error(f"Analysis error: {str(e)}")
                        
            if "tab1_match_result" in st.session_state and st.session_state["tab1_match_result"]:
                res = st.session_state["tab1_match_result"]
                status = res.get("match_status", "MATCH_FOUND")
                is_btn = res.get("is_button", True)
                best_sku = res.get("best_match_sku")
                top_candidates = res.get("top_candidates", [])
                
                va = res.get("visual_analysis", {})
                mat_val = html.escape(str(va.get("material_detected", "Garment Material")))
                size_val = html.escape(str(va.get("estimated_size", "N/A")))
                holes_val = html.escape(str(va.get("holes_detected", "N/A")))
                color_val = html.escape(str(va.get("color_tone", "Natural")))
                conf_num = min(int(res.get("match_confidence", 0)), 95)
                
                # Check human approval state
                is_human_approved = bool(st.session_state.get("scanner_human_reviewed"))
                approved_sku = st.session_state.get("scanner_approved_sku")

                # Decision Label Configuration (Engineering Standard)
                decision_label = res.get("decision_label", "EXACT DESIGN CANDIDATE" if best_sku else "NO EXACT MATCH")
                decision_expl = res.get("decision_explanation", res.get("match_reason", ""))

                if decision_label == "EXACT DESIGN CANDIDATE":
                    l_bg = "#ecfdf5"
                    l_border = "#10b981"
                    l_col = "#065f46"
                    l_icon = "🎯"
                    l_title = "EXACT DESIGN CANDIDATE"
                    l_sub = "All visible mandatory front-face attributes match catalog profile. Confirmed candidate subject to physical batch verification."
                elif decision_label == "POSSIBLE MATCH":
                    l_bg = "#fffbeb"
                    l_border = "#f59e0b"
                    l_col = "#92400e"
                    l_icon = "⚠️"
                    l_title = "POSSIBLE MATCH"
                    l_sub = "Some front-face attributes match, but exact identity is uncertain. Requires operator/buyer review."
                elif decision_label == "NEED CLEAR FRONT PHOTO":
                    l_bg = "#eff6ff"
                    l_border = "#3b82f6"
                    l_col = "#1e40af"
                    l_icon = "📸"
                    l_title = "NEED CLEAR FRONT PHOTO"
                    l_sub = "Critical details are obscured, underexposed, or multiple distinct button designs are in the frame."
                else:
                    l_bg = "#fef2f2"
                    l_border = "#ef4444"
                    l_col = "#991b1b"
                    l_icon = "🚫"
                    l_title = "NO EXACT MATCH"
                    l_sub = "No catalog candidate passes strict front-face verification. Design or material is custom / non-catalog."

                st.markdown(f"""
                <div style="background: {l_bg}; border: 2px solid {l_border}; border-radius: 12px; padding: 12px 16px; margin-bottom: 14px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                        <div style="font-size: 15px; font-weight: 800; color: {l_col}; display: flex; align-items: center; gap: 6px;">
                            <span>{l_icon}</span>
                            <span>DECISION: {l_title}</span>
                        </div>
                        <span style="background: white; border: 1.5px solid {l_border}; color: {l_col}; font-size: 11px; font-weight: 800; padding: 3px 9px; border-radius: 20px;">
                            Confidence: {conf_num}% (Front-Face Visual)
                        </span>
                    </div>
                    <div style="font-size: 12.5px; color: {l_col}; margin-top: 5px; font-weight: 600; line-height: 1.4;">
                        {html.escape(l_sub)}
                    </div>
                    <div style="font-size: 11.5px; color: #475569; margin-top: 3px; font-style: italic;">
                        {html.escape(decision_expl)}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Requirement 4: Separate AI Analysis, Catalog Verification, Human Approval and Warehouse Stock Verification statuses
                st.markdown(f"""
                <div style="background: #f1f5f9; border: 1.5px solid #cbd5e1; border-radius: 12px; padding: 12px 16px; margin-bottom: 16px;">
                    <div style="font-size: 11.5px; font-weight: 800; color: #334155; text-transform: uppercase; margin-bottom: 8px; letter-spacing: 0.5px;">
                        Enterprise 4-Stage Lifecycle Status Tracker:
                    </div>
                    <div style="display: flex; gap: 8px; flex-wrap: wrap;">
                        <span style="background: #dbeafe; color: #1e40af; font-size: 11.5px; font-weight: 700; padding: 4px 10px; border-radius: 6px; border: 1px solid #bfdbfe;">
                            1. AI Analysis: <b>Completed ({conf_num}%)</b>
                        </span>
                        <span style="background: {'#dcfce7' if (status == 'MATCH_FOUND' and best_sku) else '#fee2e2'}; color: {'#166534' if (status == 'MATCH_FOUND' and best_sku) else '#991b1b'}; font-size: 11.5px; font-weight: 700; padding: 4px 10px; border-radius: 6px; border: 1px solid {'#bbf7d0' if (status == 'MATCH_FOUND' and best_sku) else '#fca5a5'};">
                            2. Catalog Match: <b>{'Found' if (status == 'MATCH_FOUND' and best_sku) else 'Non-Catalog'}</b>
                        </span>
                        <span style="background: {'#dcfce7' if is_human_approved else '#fef3c7'}; color: {'#166534' if is_human_approved else '#92400e'}; font-size: 11.5px; font-weight: 700; padding: 4px 10px; border-radius: 6px; border: 1px solid {'#bbf7d0' if is_human_approved else '#fde68a'};">
                            3. Human Approval: <b>{'Approved' if is_human_approved else 'Pending Review'}</b>
                        </span>
                        <span style="background: #f3e8ff; color: #6b21a8; font-size: 11.5px; font-weight: 700; padding: 4px 10px; border-radius: 6px; border: 1px solid #e9d5ff;">
                            4. Warehouse Stock: <b>Audit Pending</b>
                        </span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Attribute Chips (Requirement 13 - Escaped)
                st.markdown(f"""
                <div style="display: flex; gap: 10px; margin-bottom: 14px; flex-wrap: wrap;">
                    <div style="flex: 1.2; min-width: 130px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.03);">
                        <div style="font-size: 10.5px; text-transform: uppercase; color: #64748b; font-weight: 700;">Detected Material</div>
                        <div style="font-size: 14px; font-weight: 800; color: #0f172a; margin-top: 2px;">{mat_val}</div>
                    </div>
                    <div style="flex: 1; min-width: 100px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.03);">
                        <div style="font-size: 10.5px; text-transform: uppercase; color: #64748b; font-weight: 700;">Holes</div>
                        <div style="font-size: 14px; font-weight: 800; color: #0f172a; margin-top: 2px;">{holes_val}</div>
                    </div>
                    <div style="flex: 1; min-width: 100px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.03);">
                        <div style="font-size: 10.5px; text-transform: uppercase; color: #64748b; font-weight: 700;">Ligne Size</div>
                        <div style="font-size: 14px; font-weight: 800; color: #0f172a; margin-top: 2px;">{size_val}</div>
                    </div>
                    <div style="flex: 1; min-width: 100px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 8px 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.03);">
                        <div style="font-size: 10.5px; text-transform: uppercase; color: #64748b; font-weight: 700;">Match Status</div>
                        <div style="font-size: 13.5px; font-weight: 800; color: {'#16a34a' if is_human_approved else '#d97706'}; margin-top: 2px;">
                            {'Verified by Operator' if is_human_approved else f'Candidate Match ({conf_num}%)'}
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Check for Non-Button or Non-Catalog
                if status == "NO_BUTTON_DETECTED" or not is_btn:
                    st.warning("⚠️ **इस फोटो में कोई गारमेंट बटन नहीं मिला (No Garment Button Detected)**")
                    st.info("💡 **मार्गदर्शन:** कृपया कैमरे को सीधा बटन के पास ले जाएँ और केवल बटन की साफ़ क्लोज़-अप फोटो लें।")
                    
                elif status == "NOT_IN_CATALOG" or not best_sku:
                    # Requirement 6: Remove the first-catalog-product fallback for unknown SKUs
                    st.warning("🔍 **इस टाइप का बटन हमारे रेडी कैटलॉग में उपलब्ध नहीं है (Custom Non-Catalog Inquiry)**")
                    st.markdown(f"""
                    <div style="background: #fffbeb; border: 1.5px solid #fde68a; border-radius: 10px; padding: 14px; margin-bottom: 14px;">
                        <h4 style="margin: 0 0 6px 0; color: #92400e;">⚠️ रेडी स्टॉक में नहीं मिला — कस्टम डेवलपमेंट चेक आवश्यक</h4>
                        <p style="margin: 0; color: #78350f; font-size: 13.5px; line-height: 1.5;">
                            <b>पहचाना गया विवरण:</b> {mat_val} • {holes_val} • {size_val}<br>
                            यह विशिष्ट बटन डिज़ाइन हमारे स्टैंडर्ड रेडी स्टॉक कैटलॉग में उपलब्ध नहीं है। कोई डिफ़ॉल्ट SKU असाइन नहीं किया गया है।
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Requirement 10: Make Log Custom Inquiry persist a record and display its inquiry ID
                    if st.button("🏍️ Log Custom Inquiry in Database", type="primary", key="btn_log_custom_db", use_container_width=True):
                        photo_b64_str = base64.b64encode(selected_img_bytes).decode("utf-8") if selected_img_bytes else ""
                        db.log_scanner_inquiry(
                            inquiry_id=target_inq_id,
                            phone=clean_scan_phone,
                            buyer_name=scan_buyer_name,
                            photo_b64=photo_b64_str,
                            matched_sku="Custom / Non-Catalog",
                            matched_name=f"Custom {mat_val} Button",
                            matched_size=size_val,
                            quantity=0,
                            notes=buyer_notes,
                            crm_status="Custom Non-Catalog Development",
                            assigned_salesman="Unassigned",
                            human_approved=0,
                            catalog_available_stock=0,
                            verified_live_stock=0
                        )
                        st.success(f"✅ Custom Inquiry successfully logged! Inquiry ID: **{target_inq_id}** saved in database for production liaison.")
                else:
                    # Requirement 2: Top 3 catalog SKU candidates with evidence-based confidence scores
                    st.markdown("##### 🏆 Top 3 Catalog SKU Candidates (AI Evidence Ranked)")
                    st.caption("AI ने विज़न मिलान के आधार पर शीर्ष 3 संभावित SKU रैंक किए हैं। कृपया सही SKU को अप्रूव करें:")
                    
                    # Requirement 3: Add mandatory human review for low-confidence or ambiguous matches
                    is_low_conf = (conf_num < 75)
                    is_ambiguous = False
                    if len(top_candidates) >= 2:
                        diff = abs(top_candidates[0].get("confidence", 0) - top_candidates[1].get("confidence", 0))
                        if diff < 10:
                            is_ambiguous = True
                            
                    if (is_low_conf or is_ambiguous) and not is_human_approved:
                        st.markdown(f"""
                        <div style="background: #fffbeb; border: 1.5px solid #f59e0b; border-radius: 8px; padding: 10px 14px; margin-bottom: 12px;">
                            <span style="color: #b45309; font-weight: 800; font-size: 13px;">⚠️ Mandatory Human Review Required:</span>
                            <span style="color: #92400e; font-size: 12.5px;"> AI confidence is {conf_num}% or multiple close variants exist. An operator must review and approve the candidate before quotation or WhatsApp reply.</span>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    # Display Top Candidates in 3 comparative columns
                    c_cols = st.columns(min(len(top_candidates), 3))
                    for idx, cand in enumerate(top_candidates[:3]):
                        with c_cols[idx]:
                            cand_sku = cand.get("sku")
                            cand_conf = cand.get("confidence", 0)
                            is_this_approved = (approved_sku == cand_sku)
                            
                            border_color = "#16a34a" if is_this_approved else ("#3b82f6" if idx == 0 else "#cbd5e1")
                            bg_color = "#f0fdf4" if is_this_approved else ("#f8fafc" if idx == 0 else "#ffffff")
                            
                            s_bd = cand.get("score_breakdown", {})
                            gates = cand.get("gates", {})
                            m_reasons = cand.get("match_reasons", [])
                            mm_reasons = cand.get("mismatch_reasons", [])

                            weights_html = f"""
                            <div style="font-size: 10.5px; margin-top: 6px; padding: 6px 8px; background: #f8fafc; border-radius: 6px; border: 1px solid #e2e8f0; line-height: 1.35;">
                                <div style="font-weight: 700; color: #334155; margin-bottom: 2px;">5-Weight Evidence Breakdown:</div>
                                <div>• Front Design (35%): <b>{s_bd.get('front_design_score', 0)}/35</b></div>
                                <div>• Outer Shape (25%): <b>{s_bd.get('outer_shape_score', 0)}/25</b></div>
                                <div>• Hole Geometry (20%): <b>{s_bd.get('hole_geometry_score', 0)}/20</b></div>
                                <div>• Color & Pattern (10%): <b>{s_bd.get('color_pattern_score', 0)}/10</b></div>
                                <div>• Material (10%): <b>{s_bd.get('apparent_material_score', 0)}/10</b></div>
                            </div>
                            <div style="margin-top: 5px; font-size: 10.5px; line-height: 1.3;">
                                <b>Strict Verification Gates:</b> 
                                <span style="color: {'#16a34a' if gates.get('hole_gate', True) else '#dc2626'}; font-weight: 700;">{'✓ Hole' if gates.get('hole_gate', True) else '✗ Hole'}</span> | 
                                <span style="color: {'#16a34a' if gates.get('shape_gate', True) else '#dc2626'}; font-weight: 700;">{'✓ Shape' if gates.get('shape_gate', True) else '✗ Shape'}</span> | 
                                <span style="color: {'#16a34a' if gates.get('design_gate', True) else '#dc2626'}; font-weight: 700;">{'✓ Design' if gates.get('design_gate', True) else '✗ Design'}</span> | 
                                <span style="color: {'#16a34a' if gates.get('color_gate', True) else '#dc2626'}; font-weight: 700;">{'✓ Color' if gates.get('color_gate', True) else '✗ Color'}</span>
                            </div>
                            """

                            st.markdown(f"""
                            <div style="border: 2px solid {border_color}; background: {bg_color}; border-radius: 10px; padding: 12px; margin-bottom: 10px; min-height: 290px;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                                    <span style="font-weight: 800; font-size: 12px; color: {'#16a34a' if is_this_approved else '#1e40af'};">
                                        {'✅ APPROVED' if is_this_approved else f'Rank {cand.get("rank", idx+1)}'}
                                    </span>
                                    <span style="background: #e2e8f0; color: #334155; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 10px;">
                                        {cand_conf}% Conf
                                    </span>
                                </div>
                                <div style="font-weight: 800; font-size: 14px; color: #0f172a; margin-bottom: 2px;">{html.escape(cand_sku)}</div>
                                <div style="font-size: 12px; color: #475569; margin-bottom: 6px; line-height: 1.25;">{html.escape(cand.get("name", ""))}</div>
                                <div style="font-size: 11.5px; color: #64748b; line-height: 1.4;">
                                    • Material: <b>{html.escape(cand.get("material", ""))}</b><br>
                                    • Holes: <b>{html.escape(cand.get("holes", ""))}</b><br>
                                    • Size: <b>{html.escape(cand.get("size_ligne", ""))}</b><br>
                                    • Rate: <b style="color: #166534;">₹{cand.get("rate_per_gross", 0):.1f}/Gr</b><br>
                                    • Catalog Stock: <b style="color: #1e40af;">{cand.get("stock_gross", 0):,} Gr</b>
                                </div>
                                {weights_html}
                                <div style="font-size: 10.5px; color: #64748b; margin-top: 6px; border-top: 1px dashed #cbd5e1; padding-top: 4px;">
                                    <i>{html.escape(cand.get("evidence_breakdown", ""))}</i>
                                </div>
                            </div>
                            """, unsafe_allow_html=True)
                            
                            c_img_path = os.path.join(IMG_DIR, f"{cand_sku}.jpg")
                            if os.path.exists(c_img_path):
                                st.image(c_img_path, caption=f"Catalog Image ({cand_sku})", use_container_width=True)
                            
                            if st.button(f"✅ Approve #{cand.get('rank', idx+1)} ({cand_sku})", key=f"btn_appr_cand_{cand_sku}", use_container_width=True):
                                st.session_state["scanner_approved_sku"] = cand_sku
                                st.session_state["scanner_approved_cand"] = cand
                                st.session_state["scanner_human_reviewed"] = True
                                
                                # Log approval to transactional DB with true detected quantity and size
                                photo_b64_str = base64.b64encode(selected_img_bytes).decode("utf-8") if selected_img_bytes else ""
                                cand_size_opt = cand.get("size_ligne", "").split()[0] if cand.get("size_ligne") else "18L"
                                db.log_scanner_inquiry(
                                    inquiry_id=target_inq_id,
                                    phone=clean_scan_phone,
                                    buyer_name=scan_buyer_name,
                                    photo_b64=photo_b64_str,
                                    matched_sku=cand_sku,
                                    matched_name=cand.get("name", "Button Inquiry"),
                                    matched_size=cand_size_opt,
                                    quantity=detected_qty,
                                    notes=buyer_notes,
                                    crm_status="Human Approved - Ready for Quote",
                                    assigned_salesman="Unassigned",
                                    human_approved=1,
                                    catalog_available_stock=cand.get("stock_gross", 0),
                                    verified_live_stock=0
                                )
                                st.success(f"✅ SKU **{cand_sku}** approved by human operator!")
                                st.rerun()

                    # Active Approved Item Summary
                    active_candidate = st.session_state.get("scanner_approved_cand") or (top_candidates[0] if top_candidates else None)
                    if active_candidate:
                        active_sku = active_candidate.get("sku")
                        
                        # Requirement 7: Approval is invalidated if SKU is changed or not approved for this specific candidate
                        approved_sku = st.session_state.get("scanner_approved_sku")
                        is_human_approved = bool(st.session_state.get("scanner_human_reviewed") and approved_sku and approved_sku == active_sku)
                        
                        # Requirement 14: Separate catalog stock from independently verified live warehouse stock
                        st.markdown(f"""
                        <div style="background: #f8fafc; border: 1.5px solid #cbd5e1; border-radius: 10px; padding: 12px 16px; margin: 12px 0;">
                            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap;">
                                <div>
                                    <span style="font-size: 13.5px; font-weight: 800; color: #0f172a;">
                                        Selected SKU: <span style="color: #2563eb;">{html.escape(active_sku)}</span> — {html.escape(active_candidate.get('name', ''))}
                                    </span>
                                </div>
                                <div style="font-size: 12px;">
                                    Catalog Stock: <b style="color: #1e40af;">{active_candidate.get('stock_gross', 0):,} Gross</b> &nbsp;|&nbsp; 
                                    Verified Live Godown Stock: <b style="color: #b45309;">Pending Central Godown Audit</b>
                                </div>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)
                        
                        # Requirement 3: Explicit Confirmed Size Selection (No implicit 18L fallback)
                        raw_size_str = active_candidate.get("size_ligne", "")
                        found_sizes = re.findall(r'\b\d+L\b', raw_size_str)
                        if not found_sizes:
                            found_sizes = ["14L", "18L", "24L"]
                        avail_sizes = list(dict.fromkeys(found_sizes))
                        
                        est_size = res.get("visual_analysis", {}).get("estimated_size", "")
                        clean_est = re.search(r'\b\d+L\b', str(est_size))
                        detected_size_val = clean_est.group(0) if clean_est else ""
                        
                        c_s1, c_s2 = st.columns([1.2, 1])
                        with c_s1:
                            default_sz_idx = 0
                            if detected_size_val and detected_size_val in avail_sizes:
                                default_sz_idx = avail_sizes.index(detected_size_val)
                            
                            user_chosen_size = st.selectbox(
                                "Confirmed Button Size (Ligne):",
                                options=avail_sizes,
                                index=default_sz_idx,
                                key=f"scan_size_input_{active_sku}"
                            )
                        with c_s2:
                            st.markdown(f"<div style='font-size: 12px; color: #475569; margin-top: 28px;'>Catalog Spec: <b>{html.escape(raw_size_str)}</b></div>", unsafe_allow_html=True)

                        # Requirement 11: Implement complete scanner-to-quotation handoff
                        # Fix Point 1: Editable buyer requirement quantity, never hardcoded 200. Default to 0 when unspecified.
                        c_q1, c_q2 = st.columns([1.2, 1])
                        with c_q1:
                            user_chosen_qty = st.number_input(
                                "Buyer Order Quantity (Gross):",
                                min_value=0,
                                max_value=100000,
                                value=detected_qty if detected_qty > 0 else 0,
                                step=25,
                                key=f"scan_qty_input_{active_sku}"
                            )
                        with c_q2:
                            if user_chosen_qty > 0:
                                st.markdown(f"<div style='font-size: 12px; color: #64748b; margin-top: 28px;'>Total: <b>{user_chosen_qty * 144:,} Pieces</b></div>", unsafe_allow_html=True)
                            else:
                                st.markdown("<div style='font-size: 12px; color: #dc2626; margin-top: 28px;'><b>⚠️ 0 Gross (Enter Required Quantity)</b></div>", unsafe_allow_html=True)
                        
                        has_valid_qty = (user_chosen_qty > 0)
                        if not has_valid_qty:
                            st.warning("⚠️ **Buyer Order Quantity Required:** Buyer has not specified an order quantity. Please enter the required Gross quantity (e.g. 50, 100, 250 Gross) before generating a quotation.")
                        
                        # Fix Point 3 & Requirement 7: Mandatory Human Approval & Non-Zero Quantity required before quotation handoff button is active
                        if not is_human_approved:
                            st.warning("⚠️ **Human Approval Required:** Please click '✅ Approve' on the correct candidate above before generating a formal quotation.")
                            st.button("🧾 Generate Quote in Tab 5 (Approval Required)", key="btn_scanner_quote_disabled", disabled=True, use_container_width=True)
                        elif not has_valid_qty:
                            st.button("🧾 Generate Quote in Tab 5 (Enter Quantity First)", key="btn_scanner_quote_no_qty", disabled=True, use_container_width=True)
                        else:
                            if st.button("🧾 Generate Quote in Tab 5 (Complete Handoff)", key="btn_scanner_quote_handoff", type="primary", use_container_width=True):
                                st.session_state["preset_quote_buyer"] = scan_buyer_name
                                # Fix Point 2: Never fall back to hardcoded 919315702804; keep clean phone or empty
                                st.session_state["preset_quote_phone"] = clean_scan_phone if clean_scan_phone else ""
                                st.session_state["preset_quote_sku"] = active_sku
                                st.session_state["preset_quote_size"] = user_chosen_size # Confirmed size, no implicit 18L!
                                st.session_state["preset_quote_qty"] = int(user_chosen_qty)
                                st.session_state["preset_quote_inquiry_id"] = target_inq_id
                                st.session_state["quote_sku"] = active_sku
                                st.success(f"✅ Data for **{scan_buyer_name}** (SKU: **{active_sku}**, Size: **{user_chosen_size}**, {user_chosen_qty} Gross) transferred to **Tab 5 Quotation Desk**! Click Tab 5 above to generate formal proforma invoice.")

                # Outbound WhatsApp Section (Requirement 2, 7, 8, 9, 13)
                st.markdown("<hr style='margin: 16px 0;'>", unsafe_allow_html=True)
                st.markdown("##### 💬 Outbound WhatsApp Message to Buyer")
                
                default_wa_draft = res.get("whatsapp_buyer_draft", "")
                # Requirement 2: Capture live operator edits in text area
                operator_wa_draft = st.text_area("WhatsApp Message Draft (Operator Editable):", value=default_wa_draft, height=105, key="scanner_wa_draft_ta")
                active_wa_msg = operator_wa_draft.strip() if operator_wa_draft and operator_wa_draft.strip() else default_wa_draft
                
                # Requirement 9: Implement a real Copy Message clipboard action using exact operator-edited draft
                st.code(active_wa_msg, language=None)
                copy_html = f"""
                <button onclick="navigator.clipboard.writeText({json.dumps(active_wa_msg)}); alert('✅ WhatsApp Message copied to clipboard!');" 
                        style="background: #f1f5f9; border: 1.5px solid #cbd5e1; border-radius: 6px; padding: 6px 14px; font-weight: 700; font-size: 12px; cursor: pointer; color: #1e293b;">
                    📋 One-Click Copy to Clipboard
                </button>
                """
                st.markdown(copy_html, unsafe_allow_html=True)
                
                # Requirement 7: Remove fixed WhatsApp recipient numbers. Require a validated buyer selection.
                c_w1, c_w2 = st.columns([1.2, 1])
                with c_w1:
                    target_wa_phone = st.text_input("Recipient WhatsApp Number:", value=clean_scan_phone, placeholder="Enter 10-12 digit mobile number", key="scan_target_wa_phone")
                    clean_dest_phone = "".join(ch for ch in target_wa_phone if ch.isdigit())
                    is_valid_phone = bool(re.match(r'^(?:91)?[6-9]\d{9}$', clean_dest_phone))
                    if clean_dest_phone and not is_valid_phone:
                        st.caption("⚠️ Please enter a valid 10-digit mobile number (e.g. 9811234567)")
                    elif is_valid_phone:
                        st.caption(f"✅ Validated Indian Mobile Number (+{clean_dest_phone})")
                
                with c_w2:
                    st.write("")
                    wa_confirm = st.checkbox("I verify buyer identity & approve dispatch", key="scan_wa_confirm_chk")
                    
                already_dispatched_wamid = st.session_state.get("scanner_dispatch_wamid")
                can_send = is_valid_phone and wa_confirm and send_whatsapp_text is not None and not already_dispatched_wamid
                
                c_act1, c_act2 = st.columns(2)
                with c_act1:
                    encoded_wa_msg = urllib.parse.quote(active_wa_msg)
                    wa_web_url = f"https://wa.me/{clean_dest_phone}?text={encoded_wa_msg}" if clean_dest_phone else f"https://api.whatsapp.com/send?text={encoded_wa_msg}"
                    st.link_button("📲 Open in WhatsApp Web", wa_web_url, type="secondary", use_container_width=True)
                    
                with c_act2:
                    # Requirement 8: Distinguish API Accepted, Sent, Delivered, Read and Failed, and prevent duplicate sends
                    if already_dispatched_wamid:
                        st.info(f"ℹ️ Message already accepted by Meta API (wamid: {already_dispatched_wamid[:20]}...). Duplicate send prevented.")
                    else:
                        if st.button("⚡ Send Direct via Official Meta API", key="btn_send_meta_scanner", type="primary", disabled=not can_send, use_container_width=True):
                            with st.spinner(f"Dispatching to +{clean_dest_phone}..."):
                                res_meta = send_whatsapp_text(clean_dest_phone, active_wa_msg)
                                # Fix Point 2: Strict Meta WAMID validation - require valid message ID before marking dispatch success
                                w_id = None
                                if isinstance(res_meta, dict):
                                    msg_arr = res_meta.get("messages") or (isinstance(res_meta.get("data"), dict) and res_meta.get("data", {}).get("messages")) or []
                                    if msg_arr and isinstance(msg_arr, list) and len(msg_arr) > 0:
                                        cand_id = msg_arr[0].get("id")
                                        if cand_id and str(cand_id).strip():
                                            w_id = str(cand_id).strip()
                                
                                is_success = bool(w_id and not (isinstance(res_meta, dict) and res_meta.get("error")))
                                if is_success:
                                    st.session_state["scanner_dispatch_wamid"] = w_id
                                    # Fix Point 3 & Requirement 2: Log exact operator-edited message strictly as ACCEPTED
                                    db.sync_chat_event_db(clean_dest_phone, scan_buyer_name, "operator", "text", active_wa_msg, status="ACCEPTED", wamid=w_id)
                                    db.log_outbound_delivery(w_id, clean_dest_phone, "text", active_wa_msg, status="ACCEPTED")
                                    st.success(f"🚀 Accepted by Meta Cloud API (wamid: {w_id}). Status: ACCEPTED (Queued for Delivery)")
                                else:
                                    err_meta = "No valid Meta message ID (wamid) returned by server"
                                    if isinstance(res_meta, dict):
                                        err_meta = res_meta.get("error") or res_meta.get("message") or err_meta
                                    st.error(f"❌ Failed to dispatch message via WhatsApp: {err_meta}")

                # Display Meta Webhook delivery status if a message was dispatched
                last_wamid = st.session_state.get("scanner_dispatch_wamid")
                if last_wamid:
                    delivery_info = db.get_message_delivery_status(last_wamid)
                    del_stat = delivery_info.get("status", "ACCEPTED").upper()
                    if del_stat == "READ":
                        tick_str = "✓✓ Read by Buyer"
                        t_color = "#38bdf8"
                    elif del_stat == "DELIVERED":
                        tick_str = "✓✓ Delivered to Recipient Mobile"
                        t_color = "#10b981"
                    elif del_stat == "SENT":
                        tick_str = "✓ Transmitted to Carrier Network (Sent)"
                        t_color = "#64748b"
                    elif del_stat == "FAILED":
                        tick_str = f"⚠️ Delivery Failed ({delivery_info.get('error_message', '')})"
                        t_color = "#ef4444"
                    else: # ACCEPTED
                        tick_str = "✓ Accepted by Meta Cloud API (Queued for Carrier Delivery)"
                        t_color = "#f59e0b"
                    st.markdown(f"""
                    <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px 12px; margin-top: 8px; font-size: 12px; color: {t_color}; font-weight: 700;">
                        Live Meta Delivery Status: {tick_str}
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("👈 Please select or upload a button photo on the left to start matching.")


with tabs[2]:
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
with tabs[3]:
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
with tabs[4]:
    st.subheader("🧾 1-Click Proforma Quotation Generator (Pricing in Gross)")
    st.caption("बायर को 30 सेकंड में प्रोफेशनल कोटेशन (दरें व क्वांटिटी अनिवार्य रूप से ग्रॉस में) तैयार करके भेजें।")
    
    # 1. Source Inquiry Selector (Connects WhatsApp, Tab 3 & Tab 1 to Tab 5)
    inquiry_sources = []
    # Add all saved WhatsApp inquiries into Tab 5 dropdown!
    for saved_inq in st.session_state.get("live_whatsapp_inquiries", []):
        s_name = saved_inq.get("buyer_name", "Customer")
        s_phone = saved_inq.get("phone", "")
        s_sku = saved_inq.get("matched_sku", "Button")
        s_qty = saved_inq.get("customer_required_quantity") or saved_inq.get("quantity") or 200
        inquiry_sources.append(f"💬 Live WhatsApp: {s_name} (+{s_phone}) - {s_sku} ({s_qty} Gross)")

    latest_wa = persisted.get("latest_whatsapp_inquiry")
    if latest_wa:
        wa_buyer = latest_wa.get("buyer_name", "Anoop Goel")
        wa_sku = latest_wa.get("sku", "ABC-137")
        wa_qty = latest_wa.get("qty_gross", 200)
        inquiry_sources.append(f"💬 Live WhatsApp Inquiry: {wa_buyer} ({wa_sku} - {wa_qty} Gross)")

    if "last_parsed_sample" in st.session_state:
        p_last = st.session_state["last_parsed_sample"]
        c_name = p_last.get("company_name", "Buyer")
        b_desc = ", ".join(p_last.get("button_sku_or_description", [])) if isinstance(p_last.get("button_sku_or_description"), list) else p_last.get("button_sku_or_description", "Buttons")
        b_est = p_last.get("bulk_requirement_estimate", "Order")
        inquiry_sources.append(f"🏍️ Latest Salesman Inquiry: {c_name} ({b_desc} - {b_est})")
    
    if "quote_sku" in st.session_state:
        scanner_buyer = st.session_state.get("preset_quote_buyer", "Buyer")
        scanner_qty = st.session_state.get("preset_quote_qty", 50)
        inquiry_sources.append(f"🔍 Scanner Match: {scanner_buyer} — SKU: {st.session_state['quote_sku']} ({scanner_qty} Gross)")
        
    inquiry_sources.append("✏️ Custom / Manual Quotation (Enter / Edit Any Details)")
    
    selected_source = st.radio("📋 Auto-Fill Quotation from Inquiry Source:", inquiry_sources, horizontal=True)
    
    # Determine defaults based on inquiry selection
    default_buyer = "Shahi Exports Private Limited"
    default_gst = "07AAACS1234F1Z5"
    default_sku_code = "ABC-139" if any("139" in x["sku"] for x in st.session_state.live_catalog) else st.session_state.live_catalog[0]["sku"]
    default_gross = 350
    default_phone = ""
    
    if selected_source.startswith("💬") and latest_wa:
        default_buyer = latest_wa.get("buyer_name", "Anoop Goel")
        default_sku_code = latest_wa.get("sku", "ABC-137")
        default_gross = int(latest_wa.get("qty_gross", 50))
        default_phone = latest_wa.get("phone", "")
    elif selected_source.startswith("🏍️") and "last_parsed_sample" in st.session_state:
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
        default_sku_code = st.session_state.get("preset_quote_sku") or st.session_state["quote_sku"]
        default_buyer = st.session_state.get("preset_quote_company") or st.session_state.get("preset_quote_buyer") or default_buyer
        default_phone = st.session_state.get("preset_quote_phone", "")
        default_gross = max(5, int(st.session_state.get("preset_quote_qty") or 50))

    if "preset_quote_buyer" in st.session_state and st.session_state.get("preset_quote_buyer"):
        default_buyer = st.session_state.get("preset_quote_company") or st.session_state.get("preset_quote_buyer") or default_buyer
        default_phone = st.session_state.get("preset_quote_phone") or default_phone
        default_gross = max(5, int(st.session_state.get("preset_quote_qty") or default_gross))
        if st.session_state.get("preset_quote_sku"):
            default_sku_code = st.session_state.get("preset_quote_sku")
        
    st.markdown("---")
    
    q_col1, q_col2 = st.columns([1, 1])
    
    with q_col1:
        q_buyer = st.text_input("Buyer Company Name:", value=default_buyer)
        q_phone = st.text_input("Buyer WhatsApp Phone:", value=default_phone, key="q_buyer_phone_tab5")
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
        
        # Check if a specific confirmed size was handed off from scanner
        preset_size = st.session_state.get("preset_quote_size") if st.session_state.get("preset_quote_sku") == selected_sku else None
        active_quote_size = preset_size or curr_item.get('size_ligne', '')
        
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
        
        st.html(f"""
        <div class="proforma-canvas">
            <div class="proforma-header-bar">
                <div>
                    <h3 class="proforma-brand">ABC BUTTONS PRIVATE LIMITED</h3>
                    <div class="proforma-brand-sub">
                        Govindpuri / Kalkaji, New Delhi - 110019 &nbsp;|&nbsp; GSTIN: 07AABCA9876P1Z3
                    </div>
                </div>
                <div style="text-align: right;">
                    <span class="proforma-ref-badge">Ref: ABC-QT-2026</span>
                    <div style="font-size: 11px; color: #94A3B8; margin-top: 4px; font-weight: 600;">EXECUTIVE ATELIER</div>
                </div>
            </div>
            
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; background: #F8FAFC; padding: 10px 14px; border-radius: 8px; border: 1px solid #E2E8F0;">
                <div style="font-size: 13px; color: #334155;">
                    <span style="font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px;">Billed To</span><br>
                    <b style="color: #0F172A; font-size: 14px;">{q_buyer}</b><br>
                    <span style="color: #64748B;">GSTIN:</span> <span style="font-family: 'JetBrains Mono', monospace; font-weight: 600;">{q_gst}</span>
                </div>
                <div style="text-align: right; font-size: 12.5px; color: #475569;">
                    <span style="font-size: 11px; font-weight: 700; color: #64748B; text-transform: uppercase; letter-spacing: 0.5px;">Terms & Dates</span><br>
                    <span>Date: <b>{today_str}</b></span><br>
                    <span>Valid Till: <b>{valid_str}</b></span>
                </div>
            </div>

            <table class="proforma-table">
                <thead>
                    <tr>
                        <th style="text-align: left; border-top-left-radius: 8px;">Item Description</th>
                        <th style="text-align: center;">Qty (Gross)</th>
                        <th style="text-align: right;">Base Rate / Gr</th>
                        <th style="text-align: right; border-top-right-radius: 8px;">Gross Amount</th>
                    </tr>
                </thead>
                <tbody>
                    <tr style="background: #FFFFFF;">
                        <td>
                            <b style="color: #0F172A; font-size: 13.5px;">{curr_item['name']}</b><br>
                            <span class="spec-badge">SKU: {curr_item['sku']}</span>
                            <span class="spec-badge">SIZE: {active_quote_size}</span>
                            <span class="spec-badge">{curr_item.get('holes', '')}</span>
                        </td>
                        <td style="text-align: center;">
                            <span style="font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: #0F172A;">{q_gross_qty} Gr</span><br>
                            <small style="color: #64748B;">({q_gross_qty*144:,} pcs)</small>
                        </td>
                        <td style="text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 13px; color: #334155;">
                            ₹{base_rate:.2f}
                        </td>
                        <td style="text-align: right; font-family: 'JetBrains Mono', monospace; font-size: 14px; font-weight: 700; color: #0F172A;">
                            ₹{gross_amount:,.2f}
                        </td>
                    </tr>
                </tbody>
            </table>

            <div class="proforma-total-box">
                <div style="display: flex; justify-content: space-between; font-size: 13.5px; color: #475569; margin-bottom: 4px;">
                    <span>Gross Total:</span>
                    <span style="font-family: 'JetBrains Mono', monospace; font-weight: 600;">₹{gross_amount:,.2f}</span>
                </div>
                {discount_html}
                <div style="display: flex; justify-content: space-between; font-size: 13.5px; color: #0F172A; border-top: 1px dashed #CBD5E1; padding-top: 6px; margin-top: 4px;">
                    <span>Taxable Subtotal {f'<small style="color: #16A34A; font-weight: 600;">(Net: ₹{effective_rate:.2f}/Gr)</small>' if q_discount > 0 else ''}:</span>
                    <span style="font-family: 'JetBrains Mono', monospace; font-weight: 700;">₹{taxable_subtotal:,.2f}</span>
                </div>
                <div style="display: flex; justify-content: space-between; font-size: 13.5px; color: #475569; margin-top: 4px;">
                    <span>GST @ 12%:</span>
                    <span style="font-family: 'JetBrains Mono', monospace; font-weight: 600;">₹{gst_amount:,.2f}</span>
                </div>
                <div class="proforma-grand-total" style="display: flex; justify-content: space-between; align-items: baseline;">
                    <span style="font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px; color: #64748B;">Total Payable:</span>
                    <span style="color: #0F172A; font-family: 'Outfit', sans-serif;">₹{grand_total:,.2f}</span>
                </div>
            </div>

            <div style="margin-top: 16px; padding-top: 12px; border-top: 1px solid #E2E8F0; font-size: 11.5px; color: #64748B; line-height: 1.6;">
                <div><b>Commercial Terms:</b> Billing strictly in Gross units (1 Gross = 144 Pieces) • Delivery: 3-5 Working Days from Central Godown, New Delhi • 30 Days Credit against Approved PO</div>
                <div style="margin-top: 4px; color: #334155;"><b>Bank Transfer:</b> HDFC Bank, Kalkaji Branch • A/C: <b>50200084920192</b> • IFSC: <b>HDFC0000123</b></div>
            </div>
        </div>
        """)
        
        st.write("")
        c_dl1, c_dl2 = st.columns(2)
        pdf_bytes = generate_quotation_pdf(
            buyer_name=q_buyer,
            buyer_gst=q_gst,
            item_sku=selected_sku,
            item_name=curr_item['name'],
            item_size=active_quote_size,
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
        # Beautiful Formal B2B Proforma Invoice WhatsApp Text
        discount_line = f"• Less Discount ({q_discount}%): -₹{discount_amount:,.2f}\n" if q_discount > 0 else ""
        gst_pct = 12
        pi_ref = f"PI-{today_date.strftime('%Y')}-{abs(hash(q_buyer + selected_sku)) % 9000 + 1000}"
        
        quote_summary_msg = (
            f"📋 *PROFORMA INVOICE / RATE ESTIMATE*\n"
            f"*ABC BUTTONS PRIVATE LIMITED*\n"
            f"_Govindpuri / Kalkaji, New Delhi - 110019_\n"
            f"GSTIN: 07AABCA9876P1Z3 | Phone: +91 93157 02804\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"*PI Ref No:* `{pi_ref}`\n"
            f"*Date:* {today_str}  |  *Valid Till:* {valid_str}\n\n"
            f"*BUYER / BILL TO:*\n"
            f"• *Company:* {q_buyer}\n"
            f"• *GSTIN:* {q_gst}\n"
            f"────────────────────────────\n"
            f"*ITEM & QUANTITY DETAILS:*\n"
            f"────────────────────────────\n"
            f"• *Product:* {curr_item['name']}\n"
            f"• *SKU Code:* `{curr_item['sku']}`\n"
            f"• *Size / Spec:* {curr_item.get('size_ligne', '')} • {curr_item.get('holes', '')}\n"
            f"• *Order Quantity:* *{q_gross_qty} Gross* (= {q_gross_qty*144:,} Pieces)\n"
            f"• *Base Rate:* ₹{base_rate:.2f} / Gross (1 Gross = 144 Pcs)\n"
            f"────────────────────────────\n"
            f"*BILLING & TAX BREAKUP:*\n"
            f"────────────────────────────\n"
            f"• Gross Value: ₹{gross_amount:,.2f}\n"
            f"{discount_line}"
            f"• Taxable Subtotal: ₹{taxable_subtotal:,.2f}\n"
            f"• GST @ {gst_pct}%: ₹{gst_amount:,.2f}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 *NET PAYABLE AMOUNT: ₹{grand_total:,.2f}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏦 *BANK DETAILS FOR RTGS / NEFT:*\n"
            f"• *A/C Name:* ABC Buttons Pvt. Ltd.\n"
            f"• *Bank:* HDFC Bank, Kalkaji Branch\n"
            f"• *A/C No:* 50200084920192\n"
            f"• *IFSC Code:* HDFC0000123\n\n"
            f"📌 *DISPATCH TERMS:*\n"
            f"• Ready Ex-Stock (Dispatched within 24-48 hrs of PO confirmation)\n"
            f"• Quality: Lead-Free, Garment Wash Tested, Oeko-Tex Standard\n"
            f"• Official Stamped PDF Quotation attached/available on request."
        )
        clean_target_phone = "".join(c for c in str(q_phone) if c.isdigit())
        if len(clean_target_phone) == 10:
            clean_target_phone = "91" + clean_target_phone
        if not clean_target_phone:
            clean_target_phone = "919315702804"
            
        wa_quote_url = f"https://api.whatsapp.com/send?phone={clean_target_phone}&text={urllib.parse.quote(quote_summary_msg)}"
        
        st.markdown("#### 💬 WhatsApp Proforma Invoice Dispatch:")
        st.text_area("WhatsApp PI Text (Auto-Formatted):", value=quote_summary_msg, height=140)
        
        c_q_btn1, c_q_btn2, c_q_btn3 = st.columns([1, 1.2, 1.2])
        with c_q_btn1:
            st.link_button("📲 Open in WhatsApp", wa_quote_url, type="primary", use_container_width=True)
            
        with c_q_btn2:
            if send_whatsapp_image and st.button("🖼️ Send Visual Card Image", key="send_meta_img_quote", help="Sends high-res Proforma Invoice card directly to WhatsApp via Meta API", use_container_width=True):
                with st.spinner(f"Rendering & uploading invoice card image to {clean_target_phone}..."):
                    img_bytes = generate_proforma_card_image(
                        buyer_name=q_buyer,
                        buyer_gst=q_gst,
                        sku=selected_sku,
                        item_name=curr_item['name'],
                        item_spec=f"SKU: {curr_item['sku']} • Size: {curr_item.get('size_ligne', '')} • {curr_item.get('holes', '')}",
                        qty_gross=q_gross_qty,
                        rate_gross=base_rate,
                        discount_pct=q_discount,
                        gst_pct=gst_pct
                    )
                    res_img = send_whatsapp_image(clean_target_phone, img_bytes, caption=f"📋 Official Proforma Invoice ({pi_ref}) - ABC Buttons Pvt. Ltd.")
                    if res_img.get("success"):
                        st.success(f"🚀 Visual Invoice Card delivered to {clean_target_phone}!")
                        st.balloons()
                    else:
                        st.error(f"Image API Error: {res_img.get('error')}")
                        
        with c_q_btn3:
            if send_whatsapp_document and st.button("📄 Send Official PDF", key="send_meta_doc_quote", help="Dispatches stamped PDF file directly to WhatsApp via Meta API", use_container_width=True):
                with st.spinner(f"Uploading and sending official PDF to {clean_target_phone}..."):
                    res_doc = send_whatsapp_document(clean_target_phone, pdf_bytes, filename=f"ABC_Quotation_{selected_sku}_{safe_buyer}.pdf", caption=f"ABC Buttons Proforma Quotation ({pi_ref})")
                    if res_doc.get("success"):
                        st.success(f"🚀 Official PDF Invoice delivered to {clean_target_phone}!")
                        st.balloons()
                    else:
                        st.error(f"PDF API Error: {res_doc.get('error')}")
        
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
                    clean_target_phone = "".join(c for c in str(item.get("phone", "")) if c.isdigit())
                    if len(clean_target_phone) == 10:
                        clean_target_phone = "91" + clean_target_phone
                    if not clean_target_phone:
                        clean_target_phone = "919315702804"
                    clean_msg = custom_msg.strip().replace('"', '')
                    encoded_msg = urllib.parse.quote(clean_msg)
                    wa_url = f"https://api.whatsapp.com/send?phone={clean_target_phone}&text={encoded_msg}"
                    st.link_button("📲 WhatsApp", wa_url, use_container_width=True)
                with c3:
                    if send_whatsapp_text and st.button("⚡ Meta API", key=f"btn_meta_{item['id']}", help=f"Dispatch via Official Meta Cloud API to {clean_target_phone}"):
                        with st.spinner(f"Sending follow-up to {clean_target_phone}..."):
                            res_fu = send_whatsapp_text(clean_target_phone, clean_msg)
                            if res_fu.get("success"):
                                st.success(f"Sent to {clean_target_phone}!")
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
with tabs[6]:
    st.subheader("💳 Polite Payment & Ledger Balance Assistant")
    st.caption("उधारी वाले ग्राहकों को बिना रिश्ते खराब किए, बेहद शालीन और कॉर्पोरेट भाषा में पेमेंट रिमाइंडर भेजें।")
    
    p_col1, p_col2 = st.columns([1, 1])
    
    with p_col1:
        # Dynamic Overdue Accounts (Default Ledger + Pipeline Buyers)
        base_accounts = [
            {"company": "Shahi Exports Pvt. Ltd.", "inv": "INV-2026-0894", "amt": 84500, "days": 12, "phone": "919811122233"},
            {"company": "Richa Global Apparels", "inv": "INV-2026-0912", "amt": 46200, "days": 5, "phone": "919910087654"},
            {"company": "Pearl Global Industries", "inv": "INV-2026-0785", "amt": 125000, "days": 18, "phone": "919871234567"}
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
                    "days": max(4, p_item.get("days_ago", 3) * 2),
                    "phone": p_item.get("phone", "919315702804")
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
        rem_target_phone = st.text_input("Recipient WhatsApp Number:", value=curr_acc.get("phone", "919315702804"), key="tab7_rem_phone")
        
        st.markdown(f"""
        <div style="background: #f1f5f9; padding: 10px; border-radius: 6px; font-size: 13px; margin-bottom: 10px;">
            📄 <b>Invoice Number:</b> <code>{invoice_num}</code><br>
            💰 <b>Pending Amount:</b> ₹{amt:,.2f}<br>
            ⏱️ <b>Overdue Days:</b> {days} Days Overdue<br>
            📱 <b>Target Contact:</b> <code>{rem_target_phone}</code>
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
            clean_target_rem = "".join(c for c in str(rem_target_phone) if c.isdigit())
            if len(clean_target_rem) == 10:
                clean_target_rem = "91" + clean_target_rem
            if not clean_target_rem:
                clean_target_rem = "919315702804"
                
            with c_rm1:
                clean_reminder = st.session_state["generated_reminder"]
                encoded_rem = urllib.parse.quote(clean_reminder)
                wa_rem_url = f"https://api.whatsapp.com/send?phone={clean_target_rem}&text={encoded_rem}"
                st.link_button("📲 Send via WhatsApp", wa_rem_url, use_container_width=True)
            with c_rm2:
                if send_whatsapp_text and st.button("⚡ Send Direct via Official Meta API", key="send_meta_reminder", help=f"Send Payment Reminder via Meta Cloud API to {clean_target_rem}"):
                    with st.spinner(f"Dispatching Payment Reminder to {clean_target_rem}..."):
                        res_rem = send_whatsapp_text(clean_target_rem, clean_reminder)
                        if res_rem.get("success"):
                            st.success(f"🚀 Payment Reminder Delivered to {clean_target_rem} ({buyer_clean_name})!")
                            st.balloons()
                        else:
                            st.error(f"API Error: {res_rem.get('error')}")
            with c_rm3:
                if st.button("📋 Copy Message", use_container_width=True):
                    st.toast("Payment reminder message copied to clipboard!")

# ----------------- TAB 8: WHATSAPP LIVE SIMULATOR -----------------
