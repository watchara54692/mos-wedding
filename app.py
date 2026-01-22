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

# ================== CONFIG & SECURITY ==================
# ตั้งค่ารหัสผ่าน (ถ้าไม่ตั้งใน Render จะใช้ 'mos1234')
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "secret_key_mos_wedding_2026_super_secure"
app.permanent_session_lifetime = timedelta(days=365) # จำล็อกอิน 1 ปี

# API Keys
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Google Service Account
SERVICE_ACCOUNT_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]

# Database
DB_NAME = "mos_chat.db"

# ================== DATABASE INIT ==================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id TEXT,
                message TEXT,
                sender_type TEXT, 
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
init_db()

# ================== HELPER FUNCTIONS ==================
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
    except Exception as e: return f"Error: {e}"

def send_fb_message(recipient_id, text):
    url = f"https://graph.facebook.com/v12.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}"
    payload = {"recipient": {"id": recipient_id}, "message": {"text": text}}
    requests.post(url, json=payload)

# ================== LOGIN DECORATOR ==================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# ================== ROUTES ==================
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session.permanent = True # จำยาวๆ
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return "❌ รหัสผิด! <a href='/login'>ลองใหม่</a>"
    return render_template('login.html')

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/chats')
@login_required
def get_chats():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        # ดึง 50 ข้อความล่าสุด
        cursor = conn.execute("SELECT * FROM chats ORDER BY id DESC LIMIT 50")
        rows = [dict(row) for row in cursor.fetchall()]
    return jsonify(rows[::-1]) # ส่งกลับแบบ เก่า -> ใหม่

@app.route('/api/send_reply', methods=['POST'])
@login_required
def send_reply():
    data = request.json
    recipient_id = data.get("sender_id")
    text = data.get("message")
    
    # 1. ยิงเข้า Facebook
    send_fb_message(recipient_id, text)
    
    # 2. บันทึกว่าแอดมินตอบแล้ว
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", 
                     (recipient_id, text, 'admin'))
    return jsonify({"status": "sent"})

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Failed", 403

    if request.method == "POST":
        data = request.json
        entries = data.get("entry", [])
        for entry in entries:
            for event in entry.get("messaging", []):
                if "message" in event and "text" in event["message"]:
                    user_msg = event["message"]["text"]
                    sender_id = event["sender"]["id"]
                    
                    # 1. ให้ AI คิดรอไว้
                    ai_reply = ask_gemini(user_msg)
                    
                    # 2. บันทึกลง DB
                    with sqlite3.connect(DB_NAME) as conn:
                        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", 
                                     (sender_id, user_msg, 'user'))
                        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", 
                                     (sender_id, ai_reply, 'ai_suggestion'))
        return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
