import os
import sqlite3
import requests
import threading
from datetime import timedelta
from functools import wraps
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import google.generativeai as genai
from openai import OpenAI 

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "mos_wedding_v4_2_auto"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DB_NAME = "mos_chat.db"

OPENTHAIGPT_CONFIG = {
    "api_key": "float16-AG0F8yNce5s1DiXm1ujcNrTaZquEdaikLwhZBRhyZQNeS7Dv0X",
    "base_url": "https://api.float16.cloud/dedicate/78y8fJLuzE/v1/",
    "model": "openthaigpt/openthaigpt1.5-7b-instruct"
}

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
                sender_id TEXT PRIMARY KEY, first_name TEXT, last_name TEXT, profile_pic TEXT, 
                ai_tag TEXT DEFAULT 'ยังไม่ชัดเจน', ai_chance INTEGER DEFAULT 0, ai_budget TEXT DEFAULT '-'
            )
        """)
init_db()

# ================== 3. AI SMART FAILOVER ==================
def ask_ai_expert(user_msg, history_context=""):
    prompt = f"Role: ผู้เชี่ยวชาญการขาย 'มอธเวดดิ้ง' (Mos Wedding). ตอบสั้น 2 ประโยค. ประวัติ: {history_context}. ลูกค้า: {user_msg}. Format: วิเคราะห์: ... ### คำตอบ: ... ### ประเภทงาน ### โอกาส(0-100) ### งบ"
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        return model.generate_content(prompt).text.strip()
    except Exception:
        try:
            client = OpenAI(api_key=OPENTHAIGPT_CONFIG["api_key"], base_url=OPENTHAIGPT_CONFIG["base_url"])
            res = client.chat.completions.create(model=OPENTHAIGPT_CONFIG["model"], messages=[{"role": "user", "content": prompt}])
            return "(สำรอง) ### " + res.choices[0].message.content
        except:
            return "วิเคราะห์: AI พักเหนื่อย ### ขออภัยครับ ระบบหน่วงชั่วคราว ### ยังไม่ชัดเจน ### 0 ### -"

# ================== 4. BACKGROUND PROCESSOR ==================
def process_webhook_tasks(sid, pid, msg):
    # 1. โหลดโปรไฟล์
    token = PAGE_TOKENS.get(str(pid), DEFAULT_TOKEN)
    try:
        r = requests.get(f"https://graph.facebook.com/{sid}?fields=first_name,picture.type(large)&access_token={token}", timeout=5).json()
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("UPDATE users SET first_name = ?, profile_pic = ? WHERE sender_id = ?", (r.get('first_name', 'ลูกค้า'), r.get('picture', {}).get('data', {}).get('url', ''), sid))
    except: pass
    
    # 2. วิเคราะห์ AI
    with sqlite3.connect(DB_NAME) as conn:
        h = conn.execute("SELECT message FROM chats WHERE sender_id = ? AND sender_type != 'ai_suggestion' ORDER BY id DESC LIMIT 5", (sid,)).fetchall()
        ai_res = ask_ai_expert(msg, " | ".join([x[0] for x in h]))
        p = ai_res.split('###')
        if len(p) >= 5:
            conn.execute("UPDATE users SET ai_tag = ?, ai_chance = ?, ai_budget = ? WHERE sender_id = ?", (p[2].strip(), p[3].strip(), p[4].strip(), sid))
        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, ai_res, 'ai_suggestion'))

# ================== 5. ROUTES ==================
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], str(event["sender"]["id"]), str(event["recipient"]["id"])
                with sqlite3.connect(DB_NAME) as conn:
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, msg, 'user'))
                    if not conn.execute("SELECT sender_id FROM users WHERE sender_id = ?", (sid,)).fetchone():
                        conn.execute("INSERT INTO users (sender_id, first_name) VALUES (?, ?)", (sid, "ลูกค้าใหม่..."))
                threading.Thread(target=process_webhook_tasks, args=(sid, pid, msg)).start()
    return "OK", 200

@app.route('/api/contacts')
def get_contacts():
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        sql = """
            SELECT c.*, u.* FROM chats c 
            LEFT JOIN users u ON c.sender_id = u.sender_id 
            WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) 
            ORDER BY c.id DESC 
            LIMIT ? OFFSET ?
        """
        return jsonify([dict(row) for row in conn.execute(sql, (limit, offset)).fetchall()])

@app.route('/api/messages/<sid>')
def get_messages(sid):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC", (sid,)).fetchall()])

@app.route('/api/sync_history/<sid>')
def api_sync(sid):
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? AND page_id IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    if not row: return jsonify({"status": "error"}), 404
    token = PAGE_TOKENS.get(str(row[0]), DEFAULT_TOKEN)
    try:
        res = requests.get(f"https://graph.facebook.com/v12.0/me/conversations?fields=participants&access_token={token}").json()
        cid = next((c['id'] for c in res.get('data', []) if sid in [p['id'] for p in c.get('participants', {}).get('data', [])]), None)
        if cid:
            m_res = requests.get(f"https://graph.facebook.com/v12.0/{cid}/messages?fields=message,from,created_time&limit=30&access_token={token}").json()
            with sqlite3.connect(DB_NAME) as conn:
                for m in reversed(m_res.get('data', [])):
                    stype = 'user' if m['from']['id'] == sid else 'admin'
                    conn.execute("INSERT OR IGNORE INTO chats (sender_id, page_id, message, sender_type, timestamp) VALUES (?, ?, ?, ?, ?)", (sid, row[0], m.get('message'), stype, m['created_time']))
            return jsonify({"status": "success"})
    except: pass
    return jsonify({"status": "failed"}), 404

@app.route('/api/send_reply', methods=['POST'])
def send_reply():
    d = request.json
    sid = str(d['sender_id'])
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    tk = PAGE_TOKENS.get(str(row[0]) if row else None, DEFAULT_TOKEN)
    r = requests.post(f"https://graph.facebook.com/v12.0/me/messages?access_token={tk}", json={"recipient": {"id": sid}, "message": {"text": d['message']}})
    if r.status_code == 200:
        with sqlite3.connect(DB_NAME) as conn:
            conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", (sid, d['message'], 'admin'))
        return jsonify({"status": "sent"})
    return jsonify({"status": "error"}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session.permanent = True; session['logged_in'] = True
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('index.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
