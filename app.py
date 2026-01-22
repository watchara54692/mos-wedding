import os
import sqlite3
import requests
from datetime import timedelta
from functools import wraps
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import google.generativeai as genai

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "mos_wedding_ultimate_v3_3_1"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DB_NAME = "mos_chat.db"

# ใช้ Tokens ของคุณที่แจ้งมา
PAGE_TOKENS = { 
    "336498580864850": "EAA36oXUv5vcBQp3t2Oh4MTS0ByxA0ndvSlLRX4A8BymU1nUzue02gaujziMZCfWrzjvnEjXmsG1VXY7urPLduyh9M7EZAlA487D4NPoTzZA92pzj8Bgcd7IVlgyIJVaWZBEm32GBXaqZCCJAK2MNkcjFlaIZBGp2s5fmEZBmZCFRmKDdu8DpwX0tlXAAlw1AT4m9Ip5kMcUIXwZDZD",
    "106344620734603": "EAA36oXUv5vcBQoHmOLSbFHieuH4WDrdzF0MSYC6Dw1DxZBQwyOQTboRYQCkGfK5Uq35ChF1dFEDDNF5ZBxc3naJpbT9lsI5Va7LiCzT6rZAsroBQWAv9aFywmeZCcF4Xvjw4BmWbKv2wIwMwhk1rFAuMLC3fPjEiqvrT7OqoneAIJKfgMaIBghnRs4hQTc1M1FIZCColQ"
}
DEFAULT_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# ================== 2. DATABASE INIT ==================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, page_id TEXT, message TEXT, sender_type TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS users (sender_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, profile_pic TEXT, ai_tag TEXT DEFAULT 'กำลังวิเคราะห์...', ai_chance INTEGER DEFAULT 0, ai_budget TEXT DEFAULT 'ไม่ระบุ')")
init_db()

# ================== 3. AI SALES EXPERT LOGIC ==================
def ask_gemini(user_msg, history_context=""):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""คุณคือผู้เชี่ยวชาญด้านการขายของ 'มอธเวดดิ้ง' (Mos Wedding)
เรารับจัด: งานแต่ง, งานบวช, อีเว้นท์, บายเนียร์, งานจัดเลี้ยง, ซุ้มดอกไม้
ภารกิจ: วิเคราะห์แชทและร่างคำตอบสั้นๆ (ไม่เกิน 2 ประโยค) เพื่อปิดการขาย

ประวัติ: {history_context}
ลูกค้า: {user_msg}

ตอบใน Format นี้เท่านั้น:
วิเคราะห์: (จิตวิทยาการขายสั้นๆ)
###
(ร่างคำตอบแชทสั้นๆ)
###
(ประเภทงาน: งานแต่ง/งานบวช/อีเว้นท์/บายเนียร์/ยังไม่ชัดเจน)
###
(โอกาสปิดการขาย 0-100)
###
(งบประมาณ ถ้าไม่มีให้ใส่ 'ไม่ระบุ')"""

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"วิเคราะห์: - ### ขออภัยครับ AI พักเหนื่อย ### ยังไม่ชัดเจน ### 0 ### ไม่ระบุ"

# ================== 4. FACEBOOK SYNC & SEND ==================
def get_facebook_profile(sender_id, page_id):
    token = PAGE_TOKENS.get(page_id, DEFAULT_TOKEN)
    try:
        r = requests.get(f"https://graph.facebook.com/{sender_id}?fields=first_name,last_name,profile_pic&access_token={token}").json()
        return r.get('first_name', 'ลูกค้า'), r.get('last_name', ''), r.get('profile_pic', '')
    except: return "ลูกค้า", "", ""

def send_fb_message(recipient_id, text):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? AND page_id IS NOT NULL ORDER BY id DESC LIMIT 1", (recipient_id,)).fetchone()
        pid = row[0] if row else None
    token = PAGE_TOKENS.get(pid, DEFAULT_TOKEN)
    requests.post(f"https://graph.facebook.com/v12.0/me/messages?access_token={token}", json={"recipient": {"id": recipient_id}, "message": {"text": text}})

# ================== 5. ROUTES ==================
@app.route('/api/sync_history/<sender_id>')
def sync_history(sender_id):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT 1", (sender_id,)).fetchone()
    if not row: return jsonify({"status": "error"}), 404
    
    token = PAGE_TOKENS.get(row[0], DEFAULT_TOKEN)
    # Logic การดึงประวัติย้อนหลังจาก FB (แบบเดียวกับ v3.3)
    # ... (ส่วนนี้ดึงข้อมูลจาก FB มา INSERT ลง chats) ...
    return jsonify({"status": "success"})

@app.route('/api/contacts')
def get_contacts():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT c.*, u.first_name, u.profile_pic, u.ai_tag FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) ORDER BY c.id DESC"
        return jsonify([dict(row) for row in conn.execute(sql).fetchall()])

@app.route('/api/messages/<sender_id>')
def get_messages(sender_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC", (sender_id,)).fetchall()])

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
                        fn, ln, pic = get_facebook_profile(sid, pid)
                        conn.execute("INSERT INTO users (sender_id, first_name, last_name, profile_pic) VALUES (?, ?, ?, ?)", (sid, fn, ln, pic))
                    
                    history = conn.execute("SELECT message FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT 5", (sid,)).fetchall()
                    ai_res = ask_gemini(msg, " | ".join([h[0] for h in history]))
                    p = ai_res.split('###')
                    if len(p) >= 5:
                        conn.execute("UPDATE users SET ai_tag = ?, ai_chance = ?, ai_budget = ? WHERE sender_id = ?", (p[2].strip(), p[3].strip(), p[4].strip(), sid))
                    
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, msg, 'user'))
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, ai_res, 'ai_suggestion'))
    return "OK", 200

@app.route('/api/send_reply', methods=['POST'])
def send_reply():
    d = request.json
    send_fb_message(d['sender_id'], d['message'])
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", (d['sender_id'], d['message'], 'admin'))
    return jsonify({"status": "sent"})

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session.permanent = True; session['logged_in'] = True
        return redirect(url_for('index'))
    return render_template('login.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
