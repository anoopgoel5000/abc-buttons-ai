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

        # Ensure enterprise CRM columns exist
        for col_def in [
            ("live_inquiries", "human_takeover", "INTEGER DEFAULT 0"),
            ("live_inquiries", "assigned_salesman", "TEXT DEFAULT 'Unassigned'"),
            ("live_inquiries", "crm_status", "TEXT DEFAULT 'New Inquiry'"),
            ("buyer_sessions", "human_takeover", "INTEGER DEFAULT 0")
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
            (phone, contact_name, matched_sku, matched_name, matched_size, quantity, has_photo, has_address, history_count, last_active_sku, waiting_for_similar_permission, waiting_for_similar_approval, suggested_alternatives, waiting_for_custom_mfg_qty, courtesy_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key, init_sess["contact_name"], init_sess["matched_sku"], init_sess["matched_name"],
            init_sess["matched_size"], init_sess["quantity"], int(init_sess["has_photo"]),
            0, 0, init_sess["last_active_sku"], 0, 0, "[]", 0, 0, now_str
        ))
        return init_sess

def save_session_db(phone: str, session: dict):
    """Save session state to transactional SQLite."""
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO buyer_sessions
            (phone, contact_name, matched_sku, matched_name, matched_size, quantity, has_photo, has_address, history_count, last_active_sku, waiting_for_similar_permission, waiting_for_similar_approval, suggested_alternatives, waiting_for_custom_mfg_qty, courtesy_count, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key,
            session.get("contact_name", "Sir"),
            session.get("matched_sku"),
            session.get("matched_name"),
            session.get("matched_size"),
            session.get("quantity"),
            1 if session.get("has_photo") else 0,
            1 if session.get("has_address") else 0,
            session.get("history_count", 0),
            session.get("last_active_sku") or session.get("matched_sku"),
            1 if session.get("waiting_for_similar_permission") else 0,
            1 if session.get("waiting_for_similar_approval") else 0,
            json.dumps(session.get("suggested_alternatives", [])),
            1 if session.get("waiting_for_custom_mfg_qty") else 0,
            session.get("courtesy_count", 0),
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

# ----------------- LIVE INQUIRY & CHAT SYNC (Requirement 10 & 15) -----------------

def sync_chat_event_db(phone: str, buyer_name: str, sender: str, msg_type: str, text: str, photo_b64: str = None, sku: str = None, size: str = None, qty: int = None):
    """
    Transactional chat logging and dual-sync with data_store.json
    Guarantees thread-safety and preserves Streamlit dashboard functionality.
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
                "status": "Chat Active",
                "notes": text if msg_type == "text" else ""
            }
            chat_list = []
            
        # Deduplication: do not append identical message from same sender consecutively
        is_dup = False
        if chat_list:
            last_m = chat_list[-1]
            if last_m.get("sender") == sender and last_m.get("text") == text and (not photo_b64 or last_m.get("photo_b64") == photo_b64):
                is_dup = True

        if not is_dup:
            chat_list.append({
                "sender": sender,
                "sender_name": buyer_name if sender == "buyer" else "ABC Buttons Assistant",
                "type": msg_type,
                "text": text,
                "photo_b64": photo_b64,
                "sku": sku,
                "time": time_short
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
            entry["status"] = f"Quotation Requested ({qty:,} Gross)"
            
        cur.execute("""
            INSERT OR REPLACE INTO live_inquiries
            (id, phone, buyer_name, timestamp, photo_b64, matched_sku, matched_name, matched_size, quantity, status, notes, chat_messages, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            entry["id"], key, entry["buyer_name"], t_now, entry.get("photo_b64", ""),
            entry.get("matched_sku", "Inquiry"), entry.get("matched_name", "Button Inquiry"),
            entry.get("matched_size", ""), entry.get("quantity", 0), entry.get("status", "Chat Active"),
            entry.get("notes", ""), json.dumps(chat_list, ensure_ascii=False), t_now
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

def update_inquiry_crm_meta(phone: str, human_takeover: int = None, assigned_salesman: str = None, crm_status: str = None):
    """Updates CRM metadata (Human Takeover, Salesperson, Deal Stage) for a specific buyer in SQLite."""
    key = normalize_phone(phone)
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        if human_takeover is not None:
            conn.execute("UPDATE live_inquiries SET human_takeover = ?, updated_at = ? WHERE phone = ?", (int(human_takeover), now_str, key))
            conn.execute("UPDATE buyer_sessions SET human_takeover = ?, updated_at = ? WHERE phone = ?", (int(human_takeover), now_str, key))
        if assigned_salesman is not None:
            conn.execute("UPDATE live_inquiries SET assigned_salesman = ?, updated_at = ? WHERE phone = ?", (assigned_salesman, now_str, key))
        if crm_status is not None:
            conn.execute("UPDATE live_inquiries SET crm_status = ?, updated_at = ? WHERE phone = ?", (crm_status, now_str, key))
    export_to_data_store_json()

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
