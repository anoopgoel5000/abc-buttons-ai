"""
ABC Buttons Database Module - SQLite ACID Persistent Storage Engine
Provides transactional, multi-worker safe persistence for:
1. Buyer session state & active product tracking
2. Outbound WhatsApp message-to-SKU mapping (quoted reply resolution)
3. Persistent webhook message deduplication
4. Outbound delivery logging
5. Live inquiries and chat message synchronization
"""

import os
import json
import sqlite3
import datetime
import re
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "abc_buttons.db")
DS_PATH = os.path.join(os.path.dirname(__file__), "data_store.json")

def normalize_phone(phone: str) -> str:
    """Extract clean digits; canonical key uses last 10 digits when available."""
    clean = re.sub(r'\D', '', str(phone or ""))
    return clean[-10:] if len(clean) >= 10 else clean

@contextmanager
def get_db_connection():
    """Thread-safe and multi-worker safe SQLite connection with WAL mode."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Initialize database tables and indexes."""
    with get_db_connection() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS buyer_sessions (
            phone TEXT PRIMARY KEY,
            contact_name TEXT,
            matched_sku TEXT,
            matched_name TEXT,
            matched_size TEXT,
            quantity INTEGER,
            has_photo INTEGER DEFAULT 0,
            has_address INTEGER DEFAULT 0,
            history_count INTEGER DEFAULT 0,
            last_active_sku TEXT,
            waiting_for_similar_permission INTEGER DEFAULT 0,
            waiting_for_similar_approval INTEGER DEFAULT 0,
            suggested_alternatives TEXT,
            waiting_for_custom_mfg_qty INTEGER DEFAULT 0,
            courtesy_count INTEGER DEFAULT 0,
            updated_at TEXT
        );

        CREATE TABLE IF NOT EXISTS outbound_product_messages (
            wamid TEXT PRIMARY KEY,
            phone TEXT,
            sku TEXT,
            product_name TEXT,
            size_options TEXT,
            image_ref TEXT,
            timestamp TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_outbound_phone ON outbound_product_messages (phone);

        CREATE TABLE IF NOT EXISTS processed_messages (
            msg_id TEXT PRIMARY KEY,
            phone TEXT,
            received_at TEXT
        );

        CREATE TABLE IF NOT EXISTS outbound_delivery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            wamid TEXT,
            phone TEXT,
            msg_type TEXT,
            payload_preview TEXT,
            status TEXT,
            error_message TEXT,
            timestamp TEXT
        );

        CREATE TABLE IF NOT EXISTS live_inquiries (
            id TEXT PRIMARY KEY,
            phone TEXT UNIQUE,
            buyer_name TEXT,
            timestamp TEXT,
            photo_b64 TEXT,
            matched_sku TEXT,
            matched_name TEXT,
            matched_size TEXT,
            quantity INTEGER,
            status TEXT,
            notes TEXT,
            chat_messages TEXT,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_inquiries_phone ON live_inquiries (phone);
        """)

        # Ensure enterprise CRM and structured stock/quantity columns exist
        for col_def in [
            ("live_inquiries", "human_takeover", "INTEGER DEFAULT 0"),
            ("live_inquiries", "assigned_salesman", "TEXT DEFAULT 'Unassigned'"),
            ("live_inquiries", "crm_status", "TEXT DEFAULT 'New Inquiry'"),
            ("live_inquiries", "customer_required_quantity", "INTEGER DEFAULT 0"),
            ("live_inquiries", "catalog_available_stock", "INTEGER DEFAULT 0"),
            ("live_inquiries", "verified_live_stock", "INTEGER DEFAULT 0"),
            ("buyer_sessions", "human_takeover", "INTEGER DEFAULT 0"),
            ("buyer_sessions", "customer_required_quantity", "INTEGER DEFAULT 0"),
            ("buyer_sessions", "catalog_available_stock", "INTEGER DEFAULT 0"),
            ("buyer_sessions", "verified_live_stock", "INTEGER DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]};")
            except sqlite3.OperationalError:
                pass
        
    # Migrate existing data from data_store.json if database is empty
    migrate_from_data_store()

def migrate_from_data_store():
    """One-time hydration from data_store.json to SQLite."""
    if not os.path.exists(DS_PATH):
        return
    try:
        with open(DS_PATH, "r", encoding="utf-8") as fp:
            data = json.load(fp)
            
        inqs = data.get("live_whatsapp_inquiries", [])
        if not inqs:
            return
            
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM live_inquiries")
            if cur.fetchone()[0] == 0:
                for inq in inqs:
                    phone_norm = normalize_phone(inq.get("phone", ""))
                    if not phone_norm:
                        continue
                    cur.execute("""
                        INSERT OR REPLACE INTO live_inquiries 
                        (id, phone, buyer_name, timestamp, photo_b64, matched_sku, matched_name, matched_size, quantity, status, notes, chat_messages, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        inq.get("id", f"inq_{phone_norm}"),
                        phone_norm,
                        inq.get("buyer_name", "Buyer"),
                        inq.get("timestamp", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                        inq.get("photo_b64", ""),
                        inq.get("matched_sku", "Inquiry"),
                        inq.get("matched_name", "Button Inquiry"),
                        inq.get("matched_size", ""),
                        inq.get("quantity", 0),
                        inq.get("status", "Chat Active"),
                        inq.get("notes", ""),
                        json.dumps(inq.get("chat_messages", []), ensure_ascii=False),
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ))
                    # Also seed buyer session
                    cur.execute("""
                        INSERT OR REPLACE INTO buyer_sessions
                        (phone, contact_name, matched_sku, matched_name, matched_size, quantity, has_photo, last_active_sku, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        phone_norm,
                        inq.get("buyer_name", "Buyer"),
                        inq.get("matched_sku"),
                        inq.get("matched_name"),
                        inq.get("matched_size"),
                        inq.get("quantity"),
                        1 if (inq.get("photo_b64") or inq.get("matched_sku")) else 0,
                        inq.get("matched_sku"),
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    ))
    except Exception as e:
        print(f"Error migrating from data_store.json: {e}")

# ----------------- SESSION PERSISTENCE (Requirement 1 & 5) -----------------

def get_session_db(phone: str) -> dict:
    """Retrieve buyer session from transactional SQLite, with auto-initialization."""
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM buyer_sessions WHERE phone = ?", (key,))
        row = cur.fetchone()
        if row:
            d = dict(row)
            d["has_photo"] = bool(d["has_photo"])
            d["has_address"] = bool(d["has_address"])
            d["waiting_for_similar_permission"] = bool(d["waiting_for_similar_permission"])
            d["waiting_for_similar_approval"] = bool(d["waiting_for_similar_approval"])
            d["waiting_for_custom_mfg_qty"] = bool(d["waiting_for_custom_mfg_qty"])
            d["suggested_alternatives"] = json.loads(d["suggested_alternatives"]) if d.get("suggested_alternatives") else []
            d["customer_required_quantity"] = d.get("customer_required_quantity") if d.get("customer_required_quantity") is not None else d.get("quantity")
            d["catalog_available_stock"] = d.get("catalog_available_stock") or 0
            d["verified_live_stock"] = d.get("verified_live_stock") or 0
            return d
            
        # Check if live_inquiries has historical data for this buyer
        cur.execute("SELECT * FROM live_inquiries WHERE phone = ?", (key,))
        inq_row = cur.fetchone()
        
        init_sess = {
            "phone": key,
            "contact_name": inq_row["buyer_name"] if inq_row else "Sir",
            "matched_sku": inq_row["matched_sku"] if inq_row and inq_row["matched_sku"] != "Inquiry" else None,
            "matched_name": inq_row["matched_name"] if inq_row else None,
            "matched_size": inq_row["matched_size"] if inq_row else None,
            "quantity": inq_row["quantity"] if inq_row else None,
            "customer_required_quantity": inq_row["customer_required_quantity"] if (inq_row and "customer_required_quantity" in inq_row.keys()) else (inq_row["quantity"] if inq_row else None),
            "catalog_available_stock": inq_row["catalog_available_stock"] if (inq_row and "catalog_available_stock" in inq_row.keys()) else 0,
            "verified_live_stock": inq_row["verified_live_stock"] if (inq_row and "verified_live_stock" in inq_row.keys()) else 0,
            "has_photo": bool(inq_row and (inq_row["photo_b64"] or inq_row["matched_sku"])),
            "has_address": False,
            "history_count": 0,
            "last_active_sku": inq_row["matched_sku"] if inq_row and inq_row["matched_sku"] != "Inquiry" else None,
            "waiting_for_similar_permission": False,
            "waiting_for_similar_approval": False,
            "suggested_alternatives": [],
            "waiting_for_custom_mfg_qty": False,
            "courtesy_count": 0,
            "updated_at": now_str
        }
        
        cur.execute("""
            INSERT INTO buyer_sessions 
            (phone, contact_name, matched_sku, matched_name, matched_size, quantity, has_photo, has_address, history_count, last_active_sku, waiting_for_similar_permission, waiting_for_similar_approval, suggested_alternatives, waiting_for_custom_mfg_qty, courtesy_count, customer_required_quantity, catalog_available_stock, verified_live_stock, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key, init_sess["contact_name"], init_sess["matched_sku"], init_sess["matched_name"],
            init_sess["matched_size"], init_sess["quantity"], int(init_sess["has_photo"]),
            0, 0, init_sess["last_active_sku"], 0, 0, "[]", 0, 0,
            init_sess["customer_required_quantity"] or 0, init_sess["catalog_available_stock"] or 0, init_sess["verified_live_stock"] or 0, now_str
        ))
        return init_sess

def save_session_db(phone: str, session: dict):
    """Save session state to transactional SQLite with structured stock & requirement fields."""
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if session.get("quantity") is None and session.get("customer_required_quantity") is None:
        cust_qty = None
    elif session.get("quantity") is None:
        cust_qty = None
    else:
        cust_qty = session.get("customer_required_quantity") if session.get("customer_required_quantity") is not None else session.get("quantity")
    cat_stock = session.get("catalog_available_stock") or 0
    live_stock = session.get("verified_live_stock") or 0
    
    with get_db_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO buyer_sessions
            (phone, contact_name, matched_sku, matched_name, matched_size, quantity, has_photo, has_address, history_count, last_active_sku, waiting_for_similar_permission, waiting_for_similar_approval, suggested_alternatives, waiting_for_custom_mfg_qty, courtesy_count, customer_required_quantity, catalog_available_stock, verified_live_stock, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key,
            session.get("contact_name", "Sir"),
            session.get("matched_sku"),
            session.get("matched_name"),
            session.get("matched_size"),
            cust_qty,
            1 if session.get("has_photo") else 0,
            1 if session.get("has_address") else 0,
            session.get("history_count", 0),
            session.get("last_active_sku") or session.get("matched_sku"),
            1 if session.get("waiting_for_similar_permission") else 0,
            1 if session.get("waiting_for_similar_approval") else 0,
            json.dumps(session.get("suggested_alternatives", [])),
            1 if session.get("waiting_for_custom_mfg_qty") else 0,
            session.get("courtesy_count", 0),
            cust_qty or 0,
            cat_stock,
            live_stock,
            now_str
        ))

# ----------------- OUTBOUND PRODUCT TRACKING & QUOTED REPLIES (Requirement 2 & 4) -----------------

def record_outbound_product(wamid: str, phone: str, sku: str, product_name: str, size_options: str = "", image_ref: str = ""):
    """Record outbound product message ID against SKU for quoted reply resolution."""
    if not wamid:
        return
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO outbound_product_messages (wamid, phone, sku, product_name, size_options, image_ref, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (wamid, key, sku, product_name, size_options, image_ref, now_str))

def resolve_quoted_sku(context_msg_id: str, phone: str) -> dict:
    """Resolve an incoming WhatsApp reply-to context ID to the originally quoted product."""
    if not context_msg_id:
        return None
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM outbound_product_messages WHERE wamid = ?", (context_msg_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
            
        # Fallback: check the latest outbound product sent to this buyer
        key = normalize_phone(phone)
        cur.execute("SELECT * FROM outbound_product_messages WHERE phone = ? ORDER BY timestamp DESC LIMIT 1", (key,))
        latest_row = cur.fetchone()
        if latest_row:
            return dict(latest_row)
    return None

# ----------------- WEBHOOK MESSAGE DEDUPLICATION (Requirement 6) -----------------

def is_message_processed(msg_id: str, phone: str) -> bool:
    """Check if WhatsApp message ID was already processed. If not, mark as processed atomically."""
    if not msg_id:
        return False
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT msg_id FROM processed_messages WHERE msg_id = ?", (msg_id,))
        if cur.fetchone():
            return True
        cur.execute("INSERT INTO processed_messages (msg_id, phone, received_at) VALUES (?, ?, ?)", (msg_id, key, now_str))
        return False

# ----------------- OUTBOUND DELIVERY LOGGING (Requirement 12) -----------------

def log_outbound_delivery(wamid: str, phone: str, msg_type: str, preview: str, status: str = "SENT", error: str = ""):
    """Persist outbound delivery attempts and failures."""
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO outbound_delivery_logs (wamid, phone, msg_type, payload_preview, status, error_message, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (wamid or "", key, msg_type, (preview or "")[:200], status, error or "", now_str))

def update_message_delivery_status(wamid: str, new_status: str, error: str = "", phone: str = None) -> bool:
    """
    Updates the delivery status of an outbound message in outbound_delivery_logs and live_inquiries chat transcript.
    Status transitions: SENT -> DELIVERED -> READ (or FAILED).
    """
    if not wamid:
        return False
    
    clean_status = (new_status or "").upper()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updated = False
    
    with get_db_connection() as conn:
        # 1. Update outbound_delivery_logs
        conn.execute("""
            UPDATE outbound_delivery_logs 
            SET status = ?, error_message = ?, timestamp = ?
            WHERE wamid = ?
        """, (clean_status, error or "", now_str, wamid))
        
        # 2. Update chat_messages in live_inquiries
        cur = conn.cursor()
        if phone:
            cur.execute("SELECT id, phone, chat_messages FROM live_inquiries WHERE phone = ?", (normalize_phone(phone),))
            rows = cur.fetchall()
        else:
            cur.execute("SELECT id, phone, chat_messages FROM live_inquiries WHERE chat_messages LIKE ?", (f"%{wamid}%",))
            rows = cur.fetchall()
            
        for r in rows:
            r_dict = dict(r)
            msgs = json.loads(r_dict.get("chat_messages") or "[]")
            msg_changed = False
            for m in msgs:
                if m.get("wamid") == wamid:
                    m["status"] = clean_status
                    msg_changed = True
                    updated = True
            if msg_changed:
                cur.execute("""
                    UPDATE live_inquiries 
                    SET chat_messages = ?, updated_at = ?
                    WHERE id = ?
                """, (json.dumps(msgs, ensure_ascii=False), now_str, r_dict["id"]))
                
    if updated:
        export_to_data_store_json()
    return updated

def get_message_delivery_status(wamid: str) -> dict:
    """Retrieve actual delivery status of an outbound message from SQLite."""
    if not wamid:
        return {"status": "UNKNOWN", "wamid": "", "timestamp": "", "error_message": ""}
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM outbound_delivery_logs WHERE wamid = ? ORDER BY id DESC LIMIT 1", (wamid,))
            row = cur.fetchone()
            if row:
                return dict(row)
    except Exception as e:
        print(f"Error querying delivery status: {e}")
    return {"status": "SENT", "wamid": wamid, "timestamp": "", "error_message": ""}

def log_scanner_inquiry(
    inquiry_id: str,
    phone: str,
    buyer_name: str,
    photo_b64: str,
    matched_sku: str,
    matched_name: str,
    matched_size: str,
    quantity: int,
    notes: str,
    crm_status: str = "Scanner In Review",
    assigned_salesman: str = "Unassigned",
    human_approved: int = 0,
    catalog_available_stock: int = 0,
    verified_live_stock: int = 0
) -> bool:
    """
    Permanently links uploaded scanner photo, inquiry ID, buyer notes, AI analysis, 
    and CRM record in transactional SQLite and data_store.json.
    """
    key = normalize_phone(phone) if phone and any(ch.isdigit() for ch in phone) else f"scan_{inquiry_id[-8:]}"
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time_short = datetime.datetime.now().strftime("%H:%M")
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT chat_messages FROM live_inquiries WHERE phone = ? OR id = ?", (key, inquiry_id))
        row = cur.fetchone()
        chat_list = json.loads(row["chat_messages"]) if row and row["chat_messages"] else []
        
        chat_list.append({
            "wamid": None,
            "sender": "scanner",
            "sender_name": "AI Visual Scanner Lab",
            "type": "scan_event",
            "text": f"Scanned button photo. Candidate: {matched_sku} ({matched_name}). Status: {crm_status}. Notes: {notes}",
            "photo_b64": photo_b64,
            "sku": matched_sku,
            "time": time_short,
            "t_raw": now_str,
            "status": "APPROVED" if human_approved else "PENDING_APPROVAL"
        })
        
        cur.execute("""
            INSERT OR REPLACE INTO live_inquiries
            (id, phone, buyer_name, timestamp, photo_b64, matched_sku, matched_name, matched_size, 
             quantity, status, notes, chat_messages, updated_at, human_takeover, assigned_salesman, 
             crm_status, customer_required_quantity, catalog_available_stock, verified_live_stock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            inquiry_id, key, buyer_name or "Buyer", now_str, photo_b64 or "",
            matched_sku or "Inquiry", matched_name or "Button Inquiry", matched_size or "",
            quantity or 0, f"Scanned: {matched_sku}", notes or "",
            json.dumps(chat_list, ensure_ascii=False), now_str, 0, assigned_salesman or "Unassigned",
            crm_status, quantity or 0, catalog_available_stock or 0, verified_live_stock or 0
        ))
        
        if phone and any(ch.isdigit() for ch in phone):
            cur.execute("""
                INSERT OR REPLACE INTO buyer_sessions
                (phone, contact_name, matched_sku, matched_name, matched_size, quantity, 
                 has_photo, last_active_sku, customer_required_quantity, catalog_available_stock, 
                 verified_live_stock, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """, (
                key, buyer_name or "Buyer", matched_sku, matched_name, matched_size,
                quantity or 0, matched_sku, quantity or 0, catalog_available_stock or 0,
                verified_live_stock or 0, now_str
            ))
            
    export_to_data_store_json()
    return True

# ----------------- LIVE INQUIRY & CHAT SYNC (Requirement 10 & 15) -----------------

def sync_chat_event_db(phone: str, buyer_name: str, sender: str, msg_type: str, text: str, photo_b64: str = None, sku: str = None, size: str = None, qty: int = None, status: str = "SENT", wamid: str = None, customer_required_quantity: int = None, catalog_available_stock: int = None, verified_live_stock: int = None):
    """
    Transactional chat logging and dual-sync with data_store.json
    Guarantees thread-safety and preserves Streamlit dashboard functionality.
    Maintains separate structured fields for customer_required_quantity, catalog_available_stock, and verified_live_stock.
    """
    key = normalize_phone(phone)
    t_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    time_short = datetime.datetime.now().strftime("%H:%M")
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM live_inquiries WHERE phone = ?", (key,))
        row = cur.fetchone()
        
        if row:
            entry = dict(row)
            chat_list = json.loads(entry.get("chat_messages") or "[]")
        else:
            entry = {
                "id": f"inq_{key}",
                "phone": key,
                "buyer_name": buyer_name or "Buyer",
                "timestamp": t_now,
                "photo_b64": photo_b64 if sender == "buyer" and photo_b64 else "",
                "matched_sku": sku or "Inquiry",
                "matched_name": "Button Inquiry",
                "matched_size": size or "",
                "quantity": qty or 0,
                "customer_required_quantity": customer_required_quantity or qty or 0,
                "catalog_available_stock": catalog_available_stock or 0,
                "verified_live_stock": verified_live_stock or 0,
                "status": "Chat Active",
                "notes": text if msg_type == "text" else ""
            }
            chat_list = []
            
        # Deduplication: only ignore if identical WAMID already logged, or exact duplicate packet in same second
        is_dup = False
        if wamid:
            if any(m.get("wamid") == wamid for m in chat_list):
                is_dup = True
        elif chat_list:
            last_m = chat_list[-1]
            # Identical text from same sender with identical timestamp is a duplicate packet;
            # distinct consecutive messages (e.g. repeated "ok", "yes") across different seconds are preserved.
            if (last_m.get("sender") == sender and 
                last_m.get("text") == text and 
                last_m.get("t_raw") == t_now and 
                (not photo_b64 or last_m.get("photo_b64") == photo_b64)):
                is_dup = True

        if not is_dup:
            sender_display = buyer_name if sender == "buyer" else ("Operator (Sales Desk)" if sender == "operator" else "ABC Buttons Assistant")
            chat_list.append({
                "wamid": wamid,
                "sender": sender,
                "sender_name": sender_display,
                "type": msg_type,
                "text": text,
                "photo_b64": photo_b64,
                "sku": sku,
                "time": time_short,
                "t_raw": t_now,
                "status": status.upper()
            })
        
        # Update inquiry fields
        if buyer_name and buyer_name not in ["Sir", "Buyer"]:
            entry["buyer_name"] = buyer_name
        if photo_b64 and sender == "buyer":
            entry["photo_b64"] = photo_b64
        if sku and sku != "Inquiry":
            entry["matched_sku"] = sku
        if size:
            entry["matched_size"] = size
        if qty:
            entry["quantity"] = qty
            entry["customer_required_quantity"] = customer_required_quantity or qty
            entry["status"] = f"Quotation Requested ({qty:,} Gross)"
        elif customer_required_quantity:
            entry["customer_required_quantity"] = customer_required_quantity
            entry["quantity"] = customer_required_quantity
            
        if catalog_available_stock:
            entry["catalog_available_stock"] = catalog_available_stock
        if verified_live_stock is not None:
            entry["verified_live_stock"] = verified_live_stock
            
        cur.execute("""
            INSERT OR REPLACE INTO live_inquiries
            (id, phone, buyer_name, timestamp, photo_b64, matched_sku, matched_name, matched_size, quantity, status, notes, chat_messages, updated_at, human_takeover, assigned_salesman, crm_status, customer_required_quantity, catalog_available_stock, verified_live_stock)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry["id"], key, entry["buyer_name"], t_now, entry.get("photo_b64", ""),
            entry.get("matched_sku", "Inquiry"), entry.get("matched_name", "Button Inquiry"),
            entry.get("matched_size", ""), entry.get("quantity", 0), entry.get("status", "Chat Active"),
            entry.get("notes", ""), json.dumps(chat_list, ensure_ascii=False), t_now,
            entry.get("human_takeover", 0), entry.get("assigned_salesman", "Unassigned"), entry.get("crm_status", "New Inquiry"),
            entry.get("customer_required_quantity") or entry.get("quantity", 0),
            entry.get("catalog_available_stock", 0),
            entry.get("verified_live_stock", 0)
        ))
        
    # Safe atomic export to data_store.json for Streamlit frontend
    export_to_data_store_json()

def load_live_inquiries_db() -> list:
    """Direct high-performance read of live inquiries from SQLite."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM live_inquiries ORDER BY updated_at DESC LIMIT 50")
            rows = cur.fetchall()
            res = []
            for r in rows:
                d = dict(r)
                d["chat_messages"] = json.loads(d["chat_messages"]) if d.get("chat_messages") else []
                res.append(d)
            return res
    except Exception as e:
        print(f"Error loading inquiries from SQLite: {e}")
        return []

def update_inquiry_crm_meta(phone: str, human_takeover: int = None, assigned_salesman: str = None, crm_status: str = None) -> tuple:
    """
    Updates CRM metadata (Human Takeover, Salesperson, Deal Stage) for a specific buyer in SQLite.
    Returns (success: bool, rows_affected: int).
    """
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_updated = 0
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM live_inquiries WHERE phone = ?", (key,))
        exists = cur.fetchone()
        
        if not exists:
            # If no inquiry row exists yet for this customer, create an initialized entry
            cur.execute("""
                INSERT INTO live_inquiries 
                (id, phone, buyer_name, timestamp, matched_sku, matched_name, quantity, status, notes, chat_messages, updated_at, human_takeover, assigned_salesman, crm_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"inq_{key}", key, "Customer", now_str, "Inquiry", "Button Inquiry", 0, "Chat Active", "", "[]", now_str,
                int(human_takeover) if human_takeover is not None else 0,
                assigned_salesman or "Unassigned",
                crm_status or "New Inquiry"
            ))
            total_updated = 1
        else:
            if human_takeover is not None:
                cur.execute("UPDATE live_inquiries SET human_takeover = ?, updated_at = ? WHERE phone = ?", (int(human_takeover), now_str, key))
                total_updated = max(total_updated, cur.rowcount)
                conn.execute("UPDATE buyer_sessions SET human_takeover = ?, updated_at = ? WHERE phone = ?", (int(human_takeover), now_str, key))
            if assigned_salesman is not None:
                cur.execute("UPDATE live_inquiries SET assigned_salesman = ?, updated_at = ? WHERE phone = ?", (assigned_salesman, now_str, key))
                total_updated = max(total_updated, cur.rowcount)
            if crm_status is not None:
                cur.execute("UPDATE live_inquiries SET crm_status = ?, updated_at = ? WHERE phone = ?", (crm_status, now_str, key))
                total_updated = max(total_updated, cur.rowcount)
                
    export_to_data_store_json()
    return True, total_updated

def export_to_data_store_json():
    """Safe atomic sync from SQLite to data_store.json using temporary file."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM live_inquiries ORDER BY updated_at DESC LIMIT 50")
            rows = cur.fetchall()
            
        inqs = []
        for r in rows:
            d = dict(r)
            d["chat_messages"] = json.loads(d["chat_messages"]) if d.get("chat_messages") else []
            inqs.append(d)
            
        ds = {}
        if os.path.exists(DS_PATH):
            with open(DS_PATH, "r", encoding="utf-8") as fp:
                ds = json.load(fp)
                
        ds["live_whatsapp_inquiries"] = inqs
        
        # Atomic write
        tmp_path = DS_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fp:
            json.dump(ds, fp, indent=2, ensure_ascii=False)
        os.replace(tmp_path, DS_PATH)
    except Exception as e:
        print(f"Error exporting to data_store.json: {e}")

# Initialize DB on load
init_db()
