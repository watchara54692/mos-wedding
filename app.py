import os
import sqlite3
import requests
from datetime import timedelta
from functools import wraps
from flask import Flask, request, render_template, jsonify, session, redirect, url_for

# Google & Gemini
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "mos_wedding_ultimate_v3"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SERVICE_ACCOUNT_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]
DB_NAME = "mos_chat.db"

# ใส่ Page ID และ Token ของแต่ละเพจ
PAGE_TOKENS = {
    "336498580864850": "EAA36oXUv5vcBQq9MoyzWO32xSTGZCO9mQGSCyhHlxp5ElRuebM8w1ZCzhX08EIK16PNwLIwfXqSPyaDh6d1uMdqZACmnQtpDE4MdJymxwYfKvJZAoHNBIbPU9Lz8KNbjpgiLoh4ZB0u0tYnoKdHcZBT5zZBZBSXjFaVrQcsNbO7cc8ohfCieoY30Mfu8oswxfrSziUscA2je5gZDZD",
    "106344620734603": "EAA36oXUv5vcBQrGZB4kQ1Ibw4gj6Ii90ZB6pAF42KL1ZBDhBA3c80zOSgQA4ZAOgKN9uDBGPl8OQEnaN77YpqMcRiDlWjYHt69Pk7bzkEzWX5z74HUqpZA1akIfmIn8Xdh7oliV55oeGmMAPqIRfmCwUuQxK22HmLRPevZCAZBhLKZBXfo2Ys9jAVeHlrgC3YZCGZC0bJi0TOF",
}
DEFAULT_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# ================== 2. DATABASE INIT ==================
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                sender_id TEXT PRIMARY KEY,
                first_name TEXT,
                last_name TEXT,
                profile_pic TEXT,
                tags TEXT DEFAULT ''
            )
        """)
init_db()

# ================== 3. AI & FACEBOOK LOGIC ==================
def ask_gemini(user_msg):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        # ดึงคำสั่งจาก Sheets หรือใช้ Default
        instruction = "Role: พี่มอส Mos Wedding. ตอบสั้น เป็นกันเอง. Format: วิเคราะห์: ... ### ข้อความตอบ: ..."
        prompt = f"{instruction}\n\nลูกค้าถาม: {user_msg}\n\nตอบโดยแยกบทวิเคราะห์ด้วย ###"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        if "429" in str(e) or "quota" in str(e).lower():
            return "วิเคราะห์: ⏳ AI กำลังพักเหนื่อย (คนใช้งานเยอะ) ### ⏳ AI ขอพักดื่มน้ำสัก 2 นาทีนะครับ เดี๋ยวมาตอบใหม่ครับ"
        return f"วิเคราะห์: ⚠️ ระบบขัดข้อง ### ⚠️ AI สะดุดเล็กน้อย ({str(e)})"

def get_facebook_profile(sender_id, page_id):
    token = PAGE_TOKENS.get(page_id, DEFAULT_TOKEN)
    if not token: return "ลูกค้า", "", ""
    try:
        url = f"https://graph.facebook.com/{sender_id}?fields=first_name,last_name,profile_pic&access_token={token}"
        r = requests.get(url).json()
        return r.get('first_name', 'ลูกค้า'), r.get('last_name', ''), r.get('profile_pic', '')
    except: return "ลูกค้า", "", ""

def send_fb_message(recipient_id, text):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? LIMIT 1", (recipient_id,)).fetchone()
        page_id = row[0] if row else None
    token = PAGE_TOKENS.get(page_id, DEFAULT_TOKEN)
    url = f"https://graph.facebook.com/v12.0/me/messages?access_token={token}"
    requests.post(url, json={"recipient": {"id": recipient_id}, "message": {"text": text}})

# ================== 4. ROUTES ==================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session.permanent = True
        session['logged_in'] = True
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/')
@login_required
def index(): return render_template('index.html')

@app.route('/api/contacts')
@login_required
def get_contacts():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT c.*, u.first_name, u.profile_pic, u.tags FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) ORDER BY c.id DESC"
        return jsonify([dict(row) for row in conn.execute(sql).fetchall()])

@app.route('/api/messages/<sender_id>')
@login_required
def get_messages(sender_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT c.*, u.first_name, u.profile_pic, u.tags FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC"
        return jsonify([dict(row) for row in conn.execute(sql, (sender_id,)).fetchall()])

@app.route('/api/update_tags', methods=['POST'])
@login_required
def update_tags():
    data = request.json
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE users SET tags = ? WHERE sender_id = ?", (data.get('tags'), data.get('sender_id')))
    return jsonify({"status": "success"})

@app.route('/api/send_reply', methods=['POST'])
@login_required
def send_reply():
    data = request.json
    send_fb_message(data.get("sender_id"), data.get("message"))
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", (data.get("sender_id"), data.get("message"), 'admin'))
    return jsonify({"status": "sent"})

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], event["sender"]["id"], event["recipient"]["id"]
                with sqlite3.connect(DB_NAME) as conn:
                    if not conn.execute("SELECT sender_id FROM users WHERE sender_id = ?", (sid,)).fetchone():
                        fname, lname, pic = get_facebook_profile(sid, pid)
                        conn.execute("INSERT INTO users (sender_id, first_name, last_name, profile_pic) VALUES (?, ?, ?, ?)", (sid, fname, lname, pic))
                    ai_reply = ask_gemini(msg)
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, msg, 'user'))
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, ai_reply, 'ai_suggestion'))
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
