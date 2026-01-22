import os
import datetime
import sqlite3
import json
import requests
from datetime import timedelta
from functools import wraps
from flask import Flask, request, render_template, jsonify, session, redirect, url_for

# Google & Gemini
from google.oauth2 import service_account
from googleapiclient.discovery import build
import google.generativeai as genai

app = Flask(__name__)

# ================== CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "secret_key_mos_crm_v2.5"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]
DB_NAME = "mos_chat.db"

# --- Page Config: จับคู่ ID เพจ กับ ชื่อย่อ/ชื่อเต็ม ---
PAGE_MAP = {
    # "Page_ID": {"short": "ตัวย่อ", "name": "ชื่อเต็ม", "token": "Access_Token"}
    "111111111111111": {"short": "WD", "name": "Mos Wedding", "token": "token_page_wedding"},
    "222222222222222": {"short": "ST", "name": "Mos Suit", "token": "token_page_suit"},
}
DEFAULT_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# ================== DATABASE UPDATE ==================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        # 1. ตารางเก็บข้อความ (Chats)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT,
                page_id TEXT,
                message TEXT,
                sender_type TEXT, 
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 2. ตารางเก็บข้อมูลลูกค้า (Customers CRM) - ใหม่!
        conn.execute("""
            CREATE TABLE IF NOT EXISTS customers (
                user_id TEXT PRIMARY KEY,
                page_id TEXT,
                event_tag TEXT DEFAULT 'อื่นๆ',
                status_tag TEXT DEFAULT 'รอตอบ',
                win_prob INTEGER DEFAULT 0,
                est_budget TEXT DEFAULT '-',
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
init_db()

# ================== AI INTELLIGENCE ==================
def get_chat_history(user_id, limit=5):
    """ดึงประวัติ 5 ข้อความล่าสุดเพื่อส่งให้ AI วิเคราะห์บริบท"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.execute("SELECT sender_type, message FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit))
        rows = cursor.fetchall()
    # เรียงจากเก่า -> ใหม่
    history = "\n".join([f"{'Me' if r[0]=='admin' or r[0]=='ai_suggestion' else 'Customer'}: {r[1]}" for r in rows[::-1]])
    return history

def ask_gemini_crm(user_msg, user_id):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash") # หรือ gemini-1.5-pro
        
        # ดึงบริบทเก่าๆ มาด้วย เพื่อให้วิเคราะห์แม่นยำ
        context = get_chat_history(user_id)
        
        # Prompt สั่ง AI ให้คืนค่าเป็น JSON
        prompt = f"""
        Role: คุณคือเซลล์อัจฉริยะของร้าน Mos Wedding (รับจัดงานแต่ง/เช่าชุด)
        Task: 
        1. ตอบคำถามลูกค้า (สั้นๆ เป็นกันเอง)
        2. วิเคราะห์ประเภทงาน: [งานแต่ง, งานบวช, สงกรานต์, ลอยกระทง, งานเลี้ยง, หรือ อื่นๆ]
        3. วิเคราะห์สถานะลูกค้า: [รอตอบ, กำลังตัดสินใจ, จองแล้ว, กำลังจะเริ่มงาน, สิ้นสุด]
        4. ประเมินโอกาสปิดการขาย (0-100%) จากน้ำเสียงและความสนใจ
        5. ประเมินงบที่ลูกค้าไหว (เช่น '15,000-20,000' หรือ 'ไม่ระบุ')
        
        History:
        {context}
        Customer Recent: {user_msg}

        **IMPORTANT: ตอบกลับเป็น JSON Format เท่านั้น โดยไม่มี Markdown**
        Structure:
        {{
            "reply": "ข้อความตอบลูกค้า...",
            "event": "ชื่อประเภทงาน",
            "status": "สถานะลูกค้า",
            "probability": 80,
            "budget": "งบประมาณ"
        }}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.strip()
        
        # Clean Markdown json block if exists
        if text_resp.startswith("```json"):
            text_resp = text_resp.replace("```json", "").replace("```", "").strip()
            
        return json.loads(text_resp) # แปลง String เป็น Dictionary
        
    except Exception as e:
        print(f"AI Error: {e}")
        # กรณี AI เอ๋อ ให้คืนค่า Default
        return {
            "reply": "ขออภัยครับ ระบบประมวลผลขัดข้องชั่วคราว",
            "event": "อื่นๆ",
            "status": "รอตอบ",
            "probability": 0,
            "budget": "-"
        }

def send_fb_message(recipient_id, text, specific_page_id=None):
    if not specific_page_id:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.execute("SELECT page_id FROM customers WHERE user_id = ?", (recipient_id,))
            row = cursor.fetchone()
            if row: specific_page_id = row[0]
            
    page_info = PAGE_MAP.get(specific_page_id)
    token = page_info["token"] if page_info else DEFAULT_TOKEN
    
    if not token: return

    url = f"[https://graph.facebook.com/v12.0/me/messages?access_token=](https://graph.facebook.com/v12.0/me/messages?access_token=){token}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    requests.post(url, json=payload)

# ================== ROUTES ==================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session.permanent = True
            session['logged_in'] = True
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/')
@login_required
def index():
    return render_template('index.html')

# --- API ใหม่: ดึงรายชื่อพร้อม Status CRM ---
@app.route('/api/contacts')
@login_required
def get_contacts():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        # Join ตาราง chats กับ customers เพื่อเอาข้อมูลล่าสุดมาโชว์
        sql = """
        SELECT c.user_id, c.page_id, c.event_tag, c.status_tag, c.win_prob, c.est_budget,
               (SELECT message FROM chats WHERE sender_id = c.user_id ORDER BY id DESC LIMIT 1) as last_msg,
               (SELECT sender_type FROM chats WHERE sender_id = c.user_id ORDER BY id DESC LIMIT 1) as last_sender_type,
               c.last_updated
        FROM customers c
        ORDER BY c.last_updated DESC
        """
        cursor = conn.execute(sql)
        contacts = []
        for row in cursor.fetchall():
            r = dict(row)
            # เพิ่มชื่อเพจย่อ
            p_info = PAGE_MAP.get(r['page_id'])
            r['page_short'] = p_info['short'] if p_info else "FB"
            contacts.append(r)
            
    return jsonify(contacts)

@app.route('/api/messages/<sender_id>')
@login_required
def get_messages(sender_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM chats WHERE sender_id = ? ORDER BY id ASC", (sender_id,))
        rows = [dict(row) for row in cursor.fetchall()]
        
        # ดึงข้อมูล CRM มาด้วยเพื่อโชว์ในห้องแชท
        cust_cursor = conn.execute("SELECT * FROM customers WHERE user_id = ?", (sender_id,))
        cust = cust_cursor.fetchone()
        crm_data = dict(cust) if cust else {}
        
    return jsonify({"messages": rows, "crm": crm_data})

@app.route('/api/send_reply', methods=['POST'])
@login_required
def send_reply():
    data = request.json
    recipient_id = data.get("sender_id")
    text = data.get("message")
    
    send_fb_message(recipient_id, text)
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", 
                     (recipient_id, text, 'admin'))
        # อัปเดตเวลาล่าสุดให้ลูกค้าเด้งขึ้นบน
        conn.execute("UPDATE customers SET last_updated = CURRENT_TIMESTAMP WHERE user_id = ?", (recipient_id,))
        
    return jsonify({"status": "sent"})

# ================== WEBHOOK INTELLIGENCE ==================
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)

    if request.method == "POST":
        data = request.json
        entries = data.get("entry", [])
        for entry in entries:
            for event in entry.get("messaging", []):
                if "message" in event and "text" in event["message"]:
                    user_msg = event["message"]["text"]
                    sender_id = event["sender"]["id"]
                    page_id = event.get("recipient", {}).get("id")
                    
                    # 1. ให้ AI คิดวิเคราะห์ CRM + คำตอบ (JSON)
                    ai_result = ask_gemini_crm(user_msg, sender_id)
                    
                    with sqlite3.connect(DB_NAME) as conn:
                        # 2. บันทึกแชทลูกค้า
                        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", 
                                     (sender_id, page_id, user_msg, 'user'))
                        
                        # 3. บันทึกคำแนะนำ AI (เฉพาะส่วน reply text)
                        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", 
                                     (sender_id, page_id, ai_result['reply'], 'ai_suggestion'))
                        
                        # 4. อัปเดตข้อมูล CRM ลงตาราง customers (Upsert)
                        conn.execute("""
                            INSERT INTO customers (user_id, page_id, event_tag, status_tag, win_prob, est_budget, last_updated)
                            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                            ON CONFLICT(user_id) DO UPDATE SET
                                page_id=excluded.page_id,
                                event_tag=excluded.event_tag,
                                status_tag=excluded.status_tag,
                                win_prob=excluded.win_prob,
                                est_budget=excluded.est_budget,
                                last_updated=CURRENT_TIMESTAMP
                        """, (sender_id, page_id, ai_result.get('event','อื่นๆ'), ai_result.get('status','รอตอบ'), 
                              ai_result.get('probability',0), ai_result.get('budget','-')))
                              
        return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
