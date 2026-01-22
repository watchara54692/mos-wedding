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
app.secret_key = "secret_key_mos_inbox_v2"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]
DB_NAME = "mos_chat.db"

# *** ใส่ Token ของแต่ละเพจที่นี่ ***
PAGE_TOKENS = {
    "111111111111111": "token_page_A", 
    "222222222222222": "token_page_B",
}
DEFAULT_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# ================== DATABASE ==================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
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
init_db()

# ================== AI & GOOGLE ==================
def get_google_service(service_name, version):
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE): return None
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build(service_name, version, credentials=creds)
    except: return None

def get_ai_instruction():
    default = "Role: พี่มอส Mos Wedding. ตอบลูกค้าสั้นๆ เป็นกันเอง."
    if not SPREADSHEET_ID: return default
    service = get_google_service("sheets", "v4")
    if not service: return default
    try:
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="Config!B1").execute()
        vals = result.get("values", [])
        return vals[0][0] if vals else default
    except: return default

def ask_gemini(user_msg):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        instruction = get_ai_instruction()
        response = model.generate_content(f"{instruction}\n\nลูกค้าถาม: {user_msg}\nตอบสั้นๆ:")
        return response.text.strip()
    except Exception as e: return f"Error: AI Error ({e})"

def send_fb_message(recipient_id, text, specific_page_id=None):
    if not specific_page_id:
        with sqlite3.connect(DB_NAME) as conn:
            cursor = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? AND page_id IS NOT NULL LIMIT 1", (recipient_id,))
            row = cursor.fetchone()
            if row: specific_page_id = row[0]
    
    token = PAGE_TOKENS.get(specific_page_id, DEFAULT_TOKEN)
    if not token: return print(f"❌ No Token for Page {specific_page_id}")

    url = f"https://graph.facebook.com/v12.0/me/messages?access_token={token}"
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
        else: return "❌ รหัสผิด! <a href='/login'>ลองใหม่</a>"
    return render_template('login.html')

@app.route('/')
@login_required
def index():
    return render_template('index.html')

# --- API ใหม่สำหรับ Inbox ---

@app.route('/api/contacts')
@login_required
def get_contacts():
    """ดึงรายชื่อลูกค้าที่เคยคุยด้วย (เรียงตามล่าสุด)"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        # Query นี้จะดึงข้อความล่าสุดของแต่ละคนมาโชว์
        sql = """
        SELECT sender_id, message, timestamp, sender_type
        FROM chats 
        WHERE id IN (
            SELECT MAX(id) FROM chats GROUP BY sender_id
        )
        ORDER BY id DESC
        """
        cursor = conn.execute(sql)
        rows = [dict(row) for row in cursor.fetchall()]
    return jsonify(rows)

@app.route('/api/messages/<sender_id>')
@login_required
def get_messages(sender_id):
    """ดึงแชททั้งหมดของลูกค้าคนนี้"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute("SELECT * FROM chats WHERE sender_id = ? ORDER BY id ASC", (sender_id,))
        rows = [dict(row) for row in cursor.fetchall()]
    return jsonify(rows)

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
    return jsonify({"status": "sent"})

# ================== WEBHOOK ==================
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
                    
                    ai_reply = ask_gemini(user_msg)
                    
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", 
                                     (sender_id, page_id, user_msg, 'user'))
                        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", 
                                     (sender_id, page_id, ai_reply, 'ai_suggestion'))
        return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
