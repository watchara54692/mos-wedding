import os
import sqlite3
import requests
from datetime import timedelta
from functools import wraps
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import google.generativeai as genai
from openai import OpenAI 

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "mos_wedding_failover_v3_8_1"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DB_NAME = "mos_chat.db"

# สำรองด้วย OpenThaiGPT (float16.cloud)
OPENTHAIGPT_CONFIG = {
    "api_key": "float16-AG0F8yNce5s1DiXm1ujcNrTaZquEdaikLwhZBRhyZQNeS7Dv0X",
    "base_url": "https://api.float16.cloud/dedicate/78y8fJLuzE/v1/",
    "model": "openthaigpt/openthaigpt1.5-7b-instruct"
}

# Page Tokens ของคุณ
PAGE_TOKENS = { 
    "336498580864850": "EAA36oXUv5vcBQp3t2Oh4MTS0ByxA0ndvSlLRX4A8BymU1nUzue02gaujziMZCfWrzjvnEjXmsG1VXY7urPLduyh9M7EZAlA487D4NPoTzZA92pzj8Bgcd7IVlgyIJVaWZBEm32GBXaqZCCJAK2MNkcjFlaIZBGp2s5fmEZBmZCFRmKDdu8DpwX0tlXAAlw1AT4m9Ip5kMcUIXwZDZD",
    "106344620734603": "EAA36oXUv5vcBQoHmOLSbFHieuH4WDrdzF0MSYC6Dw1DxZBQwyOQTboRYQCkGfK5Uq35ChF1dFEDDNF5ZBxc3naJpbT9lsI5Va7LiCzT6rZAsroBQWAv9aFywmeZCcF4Xvjw4BmWbKv2wIwMwhk1rFAuMLC3fPjEiqvrT7OqoneAIJKfgMaIBghnRs4hQTc1M1FIZCColQ"
}
DEFAULT_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# ================== 2. DATABASE INIT ==================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, page_id TEXT, message TEXT, sender_type TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                sender_id TEXT PRIMARY KEY, 
                first_name TEXT, 
                last_name TEXT, 
                profile_pic TEXT, 
                ai_tag TEXT DEFAULT 'ยังไม่ชัดเจน', 
                ai_chance INTEGER DEFAULT 0, 
                ai_budget TEXT DEFAULT 'ไม่ระบุ'
            )
        """)
init_db()

# ================== 3. AI SMART FAILOVER ==================
def ask_ai_expert(user_msg, history_context=""):
    prompt = f"""คุณคือผู้เชี่ยวชาญการขายของ 'มอธเวดดิ้ง' (Mos Wedding) 
เรารับจัด: งานแต่ง, งานบวช, อีเว้นท์, บายเนียร์, จัดเลี้ยง, ซุ้มดอกไม้
หน้าที่: ร่างคำตอบปิดการขาย สั้น กระชับ (ไม่เกิน 2 ประโยค)
ประวัติ: {history_context}
ลูกค้า: {user_msg}
Format: วิเคราะห์: ... ### คำตอบ: ... ### ประเภทงาน ### โอกาส(0-100) ### งบ"""

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        res = model.generate_content(prompt)
        return res.text.strip()
    except Exception as e:
        if "429" in str(e): # ถ้า Gemini ติดลิมิต สลับไป OpenThaiGPT
            try:
                client = OpenAI(api_key=OPENTHAIGPT_CONFIG["api_key"], base_url=OPENTHAIGPT_CONFIG["base_url"])
                res = client.chat.completions.create(
                    model=OPENTHAIGPT_CONFIG["model"],
                    messages=[{"role": "user", "content": prompt}]
                )
                return "วิเคราะห์: (สลับใช้ OpenThaiGPT สำรอง) ### " + res.choices[0].message.content
            except:
                return "วิเคราะห์: AI พักเหนื่อย ### AI ขอพัก 1 นาทีครับ ### ยังไม่ชัดเจน ### 0 ### -"
        return f"วิเคราะห์: ระบบขัดข้อง ### ขออภัยครับ ระบบสะดุด ### ยังไม่ชัดเจน ### 0 ### -"

# ================== 4. FACEBOOK HELPERS ==================
def get_facebook_profile(sender_id, page_id):
    token = PAGE_TOKENS.get(str(page_id), DEFAULT_TOKEN)
    try:
        url = f"https://graph.facebook.com/{sender_id}?fields=first_name,last_name,picture.type(large)&access_token={token}"
        r = requests.get(url).json()
        pic = r.get('picture', {}).get('data', {}).get('url', '')
        return r.get('first_name', 'ลูกค้า'), r.get('last_name', ''), pic
    except: return "ลูกค้า", "", ""

def sync_chat_history(sender_id, page_id):
    token = PAGE_TOKENS.get(str(page_id), DEFAULT_TOKEN)
    try:
        conv_url = f"https://graph.facebook.com/v12.0/me/conversations?fields=participants&access_token={token}"
        res = requests.get(conv_url).json()
        conv_id = next((c['id'] for c in res.get('data', []) if sender_id in [p['id'] for p in c.get('participants', {}).get('data', [])]), None)
        if not conv_id: return False
        msg_url = f"https://graph.facebook.com/v12.0/{conv_id}/messages?fields=message,from,created_time&limit=30&access_token={token}"
        msg_res = requests.get(msg_url).json()
        with sqlite3.connect(DB_NAME) as conn:
            for m in reversed(msg_res.get('data', [])):
                stype = 'user' if m['from']['id'] == sender_id else 'admin'
                conn.execute("INSERT OR IGNORE INTO chats (sender_id, page_id, message, sender_type, timestamp) VALUES (?, ?, ?, ?, ?)", 
                             (sender_id, page_id, m.get('message'), stype, m['created_time']))
        return True
    except: return False

# ================== 5. ROUTES ==================
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
def index():
    return render_template('index.html')

@app.route('/api/contacts')
@login_required
def get_contacts():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) ORDER BY c.id DESC"
        return jsonify([dict(row) for row in conn.execute(sql).fetchall()])

@app.route('/api/messages/<sender_id>')
@login_required
def get_messages(sender_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC", (sender_id,)).fetchall()])

@app.route('/api/sync_history/<sender_id>')
@login_required
def api_sync(sender_id):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? AND page_id IS NOT NULL ORDER BY id DESC LIMIT 1", (sender_id,)).fetchone()
    if row and sync_chat_history(sender_id, row[0]): return jsonify({"status": "success"})
    return jsonify({"status": "failed"}), 404

@app.route('/api/send_reply', methods=['POST'])
@login_required
def send_reply():
    d = request.json
    sid = str(d['sender_id'])
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    token = PAGE_TOKENS.get(str(row[0]) if row else None, DEFAULT_TOKEN)
    requests.post(f"https://graph.facebook.com/v12.0/me/messages?access_token={token}", json={"recipient": {"id": sid}, "message": {"text": d['message']}})
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", (sid, d['message'], 'admin'))
    return jsonify({"status": "sent"})

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], str(event["sender"]["id"]), str(event["recipient"]["id"])
                with sqlite3.connect(DB_NAME) as conn:
                    fn, ln, pic = get_facebook_profile(sid, pid)
                    conn.execute("INSERT OR REPLACE INTO users (sender_id, first_name, last_name, profile_pic) VALUES (?, ?, ?, ?)", (sid, fn, ln, pic))
                    h = conn.execute("SELECT message FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT 5", (sid,)).fetchall()
                    ai = ask_ai_expert(msg, " | ".join([x[0] for x in h]))
                    p = ai.split('###')
                    if len(p) >= 5:
                        conn.execute("UPDATE users SET ai_tag = ?, ai_chance = ?, ai_budget = ? WHERE sender_id = ?", (p[2].strip(), p[3].strip(), p[4].strip(), sid))
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, msg, 'user'))
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, ai, 'ai_suggestion'))
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
