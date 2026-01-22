import os
import sqlite3
import requests
import threading
import pandas as pd
import json
from datetime import timedelta
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from openai import OpenAI 

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "moth_wedding_v5_3_ultimate"
app.permanent_session_lifetime = timedelta(days=365)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DB_NAME = "mos_chat.db"

PAGE_TOKENS = { 
    "336498580864850": "EAA36oXUv5vcBQp3t2Oh4MTS0ByxA0ndvSlLRX4A8BymU1nUzue02gaujziMZCfWrzjvnEjXmsG1VXY7urPLduyh9M7EZAlA487D4NPoTzZA92pzj8Bgcd7IVlgyIJVaWZBEm32GBXaqZCCJAK2MNkcjFlaIZBGp2s5fmEZBmZCFRmKDdu8DpwX0tlXAAlw1AT4m9Ip5kMcUIXwZDZD",
    "106344620734603": "EAA36oXUv5vcBQoHmOLSbFHieuH4WDrdzF0MSYC6Dw1DxZBQwyOQTboRYQCkGfK5Uq35ChF1dFEDDNF5ZBxc3naJpbT9lsI5Va7LiCzT6rZAsroBQWAv9aFywmeZCcF4Xvjw4BmWbKv2wIwMwhk1rFAuMLC3fPjEiqvrT7OqoneAIJKfgMaIBghnRs4hQTc1M1FIZCColQ"
}

# ================== 2. DATABASE INIT ==================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, page_id TEXT, message TEXT, sender_type TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("CREATE TABLE IF NOT EXISTS users (sender_id TEXT PRIMARY KEY, first_name TEXT, profile_pic TEXT, ai_tag TEXT DEFAULT 'ข้อมูลไม่พอ', ai_chance INTEGER DEFAULT 0, ai_budget TEXT DEFAULT 'ข้อมูลไม่พอ')")
        conn.execute("CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT, analysis TEXT, option_1 TEXT, option_2 TEXT)")
init_db()

# ================== 3. GROQ AI (STRICT JSON) ==================
def ask_groq_brain(user_msg, history=""):
    client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    # ป้องกันเรื่องไม้กวาดและบังคับ JSON
    prompt = f"""คุณคือ AI ค้นหาคีย์เวิร์ดของ 'มอธเวดดิ้ง' (Moth Wedding) ธุรกิจ Wedding Organizer (ตกแต่งสถานที่/รันคิว)
หน้าที่: วิเคราะห์แชทและส่งค่ากลับเป็น JSON เท่านั้น ห้ามพูดเรื่องทำความสะอาดหรือไม้กวาดเด็ดขาด!
JSON Schema: {{
  "search_keyword": "คำสั้นๆเพื่อค้นหาใน DB",
  "category": "ประเภทงาน",
  "budget": "ตัวเลขงบ หรือ 'ข้อมูลไม่พอ'",
  "chance": 0-100
}}
แชทล่าสุด: {user_msg}
ประวัติ: {history}"""
    
    try:
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content)
    except:
        return {"search_keyword": "ทั่วไป", "category": "ข้อมูลไม่พอ", "budget": "ข้อมูลไม่พอ", "chance": 0}

# ================== 4. SUGGESTION LOGIC ==================
def generate_suggestion(sid, pid, msg):
    with sqlite3.connect(DB_NAME) as conn:
        h = conn.execute("SELECT message FROM chats WHERE sender_id=? AND sender_type='user' ORDER BY id DESC LIMIT 3", (sid,)).fetchall()
        history = " | ".join([x[0] for x in h])
    
    analysis = ask_groq_brain(msg, history)
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        keyword = analysis.get('search_keyword', 'ทั่วไป')
        # ค้นหาบทวิเคราะห์จาก Database
        know = conn.execute("SELECT * FROM knowledge WHERE keyword LIKE ? OR ? LIKE '%' || keyword || '%' LIMIT 1", (f'%{keyword}%', msg)).fetchone()
        
        if know:
            content = f"{know['analysis']} ### {know['option_1']} ### {know['option_2']} ### {analysis['category']} ### {analysis['budget']} ### {analysis['chance']}"
        else:
            content = f"ยังไม่พบข้อมูลในระบบ แนะนำให้ถามเพื่อระบุความต้องการ ### รบกวนขอทราบวันและสถานที่จัดงานครับ มอธจะได้เช็คคิวให้ครับ ### สนใจให้มอธช่วยออกแบบธีมงานเบื้องต้นให้ก่อนไหมครับ? ### {analysis['category']} ### {analysis['budget']} ### {analysis['chance']}"
        
        conn.execute("UPDATE users SET ai_tag=?, ai_budget=?, ai_chance=? WHERE sender_id=?", (analysis['category'], analysis['budget'], analysis['chance'], sid))
        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, 'ai_suggestion')", (sid, pid, content))

# ================== 5. FACEBOOK RECOVERY ==================
def recover_fb_data():
    """กู้คืนรายชื่อลูกค้าเก่าทันทีที่ Login (ข้อ 1)"""
    for pid, token in PAGE_TOKENS.items():
        try:
            r = requests.get(f"https://graph.facebook.com/v12.0/me/conversations?fields=participants,updated_time,snippet&limit=50&access_token={token}").json()
            with sqlite3.connect(DB_NAME) as conn:
                for conv in r.get('data', []):
                    sid = next((p['id'] for p in conv['participants']['data'] if p['id'] != pid), None)
                    if sid:
                        prof = requests.get(f"https://graph.facebook.com/{sid}?fields=first_name,picture.type(large)&access_token={token}").json()
                        conn.execute("INSERT OR REPLACE INTO users (sender_id, first_name, profile_pic) VALUES (?, ?, ?)", 
                                     (sid, prof.get('first_name', 'ลูกค้าเก่า'), prof.get('picture', {}).get('data', {}).get('url', '')))
                        conn.execute("INSERT OR IGNORE INTO chats (sender_id, page_id, message, sender_type, timestamp) VALUES (?, ?, ?, 'user', ?)", 
                                     (sid, pid, conv.get('snippet', ''), conv['updated_time']))
        except: pass

# ================== 6. ROUTES ==================
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], str(event["sender"]["id"]), str(event["recipient"]["id"])
                with sqlite3.connect(DB_NAME) as conn:
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, 'user')", (sid, pid, msg))
                    if not conn.execute("SELECT sender_id FROM users WHERE sender_id=?", (sid,)).fetchone():
                        conn.execute("INSERT INTO users (sender_id, first_name) VALUES (?, 'ลูกค้าใหม่')", (sid,))
                threading.Thread(target=generate_suggestion, args=(sid, pid, msg)).start()
    return "OK", 200

@app.route('/api/train', methods=['POST'])
def train_db():
    df = pd.read_csv(request.files['file'])
    with sqlite3.connect(DB_NAME) as conn:
        df.to_sql('knowledge', conn, if_exists='append', index=False)
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session.permanent = True; session['logged_in'] = True
        threading.Thread(target=recover_fb_data).start()
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/contacts')
def get_contacts():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) ORDER BY c.id DESC").fetchall()])

@app.route('/api/messages/<sid>')
def get_messages(sid):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC", (sid,)).fetchall()])

@app.route('/api/send_reply', methods=['POST'])
def send_reply():
    d = request.json; sid = str(d['sender_id'])
    with sqlite3.connect(DB_NAME) as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id = ? AND page_id IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    tk = PAGE_TOKENS.get(str(row[0]) if row else None, os.environ.get("FB_PAGE_ACCESS_TOKEN"))
    requests.post(f"https://graph.facebook.com/v12.0/me/messages?access_token={tk}", json={"recipient": {"id": sid}, "message": {"text": d['message']}})
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, 'admin')", (sid, d['message']))
    return jsonify({"status": "sent"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
