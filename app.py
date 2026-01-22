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
app.secret_key = "mos_wedding_v8_closer"
app.permanent_session_lifetime = timedelta(days=365)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DB_NAME = "mos_chat.db"

PAGE_TOKENS = { 
    "336498580864850": "EAA36oXUv5vcBQp3t2Oh4MTS0ByxA0ndvSlLRX4A8BymU1nUzue02gaujziMZCfWrzjvnEjXmsG1VXY7urPLduyh9M7EZAlA487D4NPoTzZA92pzj8Bgcd7IVlgyIJVaWZBEm32GBXaqZCCJAK2MNkcjFlaIZBGp2s5fmEZBmZCFRmKDdu8DpwX0tlXAAlw1AT4m9Ip5kMcUIXwZDZD",
    "106344620734603": "EAA36oXUv5vcBQoHmOLSbFHieuH4WDrdzF0MSYC6Dw1DxZBQwyOQTboRYQCkGfK5Uq35ChF1dFEDDNF5ZBxc3naJpbT9lsI5Va7LiCzT6rZAsroBQWAv9aFywmeZCcF4Xvjw4BmWbKv2wIwMwhk1rFAuMLC3fPjEiqvrT7OqoneAIJKfgMaIBghnRs4hQTc1M1FIZCColQ"
}

def get_db():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

# ================== 2. DATABASE INIT ==================
def init_db():
    with get_db() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, page_id TEXT, message TEXT, sender_type TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                sender_id TEXT PRIMARY KEY, first_name TEXT, profile_pic TEXT, 
                ai_tag TEXT DEFAULT 'ยังไม่ชัดเจน', ai_chance INTEGER DEFAULT 0, 
                ai_budget TEXT DEFAULT 'ไม่ระบุ', last_active DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE TABLE IF NOT EXISTS knowledge (id INTEGER PRIMARY KEY AUTOINCREMENT, keyword TEXT, analysis TEXT, option_1 TEXT, option_2 TEXT)")
init_db()

# ================== 3. RECOVERY & SYNC ==================
def recover_fb_data():
    for pid, token in PAGE_TOKENS.items():
        try:
            r = requests.get(f"https://graph.facebook.com/v12.0/me/conversations?fields=participants,updated_time,snippet&limit=50&access_token={token}").json()
            with get_db() as conn:
                for conv in r.get('data', []):
                    sid = next((p['id'] for p in conv['participants']['data'] if p['id'] != pid), None)
                    if sid:
                        prof = requests.get(f"https://graph.facebook.com/{sid}?fields=first_name,picture.type(large)&access_token={token}").json()
                        conn.execute("INSERT OR REPLACE INTO users (sender_id, first_name, profile_pic, last_active) VALUES (?, ?, ?, ?)", 
                                     (sid, prof.get('first_name', 'ลูกค้าเก่า'), prof.get('picture', {}).get('data', {}).get('url', ''), conv['updated_time']))
                        # ดึง 30 แชทล่าสุด
                        m_res = requests.get(f"https://graph.facebook.com/v12.0/{conv['id']}/messages?fields=message,from,created_time&limit=30&access_token={token}").json()
                        for m in reversed(m_res.get('data', [])):
                            stype = 'user' if m['from']['id'] == sid else 'admin'
                            conn.execute("INSERT OR IGNORE INTO chats (sender_id, page_id, message, sender_type, timestamp) VALUES (?, ?, ?, ?, ?)", (sid, pid, m.get('message', ''), stype, m['created_time']))
        except: pass

# ================== 4. SMART AI ENGINE ==================
def ask_groq_brain(user_msg, history=""):
    client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    prompt = f"""คุณคือ AI ผู้ช่วยวิเคราะห์ลูกค้าของ 'MoS Wedding' (Wedding & Organize)
ภารกิจ: สกัดคีย์เวิร์ด เจตนา งบประมาณ และโอกาสซื้อ เป็น JSON เท่านั้น
JSON Schema: {{
  "keyword": "คีย์เวิร์ดสั้นๆ (เช่น ราคา, ตกแต่ง, จองคิว, วันที่, พาร์ทเนอร์)",
  "category": "ประเภทงาน",
  "budget": "ตัวเลขงบ หรือ 'ไม่ระบุ'",
  "chance": 0-100
}}
แชทล่าสุด: {user_msg} | ประวัติ: {history}"""
    try:
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content)
    except: return {"keyword": "ทั่วไป", "category": "ไม่ระบุ", "budget": "ไม่ระบุ", "chance": 0}

def analyze_and_suggest(sid, pid, msg):
    with get_db() as conn:
        h = conn.execute("SELECT message FROM chats WHERE sender_id=? AND sender_type='user' ORDER BY id DESC LIMIT 5", (sid,)).fetchall()
        history = " | ".join([x[0] for x in h])
    
    ai = ask_groq_brain(msg, history)
    
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        keyword = ai.get('keyword', 'ทั่วไป')
        know = conn.execute("SELECT * FROM knowledge WHERE keyword LIKE ? OR ? LIKE '%' || keyword || '%' LIMIT 1", (f"%{keyword}%", msg)).fetchone()
        
        analysis_text = know['analysis'] if know else "ไม่พบข้อมูลในระบบ แนะนำให้ถามเป้าหมายหลักลูกค้า"
        opt1 = know['option_1'] if know else "รบกวนขอทราบวันและพิกัดสถานที่จัดงานหน่อยครับ MoS Wedding จะได้เช็คคิวให้ครับ"
        opt2 = know['option_2'] if know else "สนใจให้ MoS Wedding ช่วยออกแบบธีมงานและจัดหาพาร์ทเนอร์เบื้องต้นก่อนไหมครับ?"
        content = f"{analysis_text} ### {opt1} ### {opt2} ### {ai['category']} ### {ai['budget']} ### {ai['chance']}"
        
        # Smart Tag Update: ไม่ทับงบประมาณเดิมถ้า AI หาค่าใหม่ไม่เจอ
        if ai['budget'] != 'ไม่ระบุ':
            conn.execute("UPDATE users SET ai_budget=? WHERE sender_id=?", (ai['budget'], sid))
        conn.execute("UPDATE users SET ai_tag=?, ai_chance=?, last_active=CURRENT_TIMESTAMP WHERE sender_id=?", (ai['category'], ai['chance'], sid))
        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, 'ai_suggestion')", (sid, pid, content))

# ================== 5. API ROUTES ==================
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], str(event["sender"]["id"]), str(event["recipient"]["id"])
                with get_db() as conn:
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, 'user')", (sid, pid, msg))
                threading.Thread(target=analyze_and_suggest, args=(sid, pid, msg)).start()
    return "OK", 200

@app.route('/api/contacts')
def get_contacts():
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        # เรียงตาม Last Active (ใหม่สุดอยู่บน)
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) ORDER BY u.last_active DESC").fetchall()])

@app.route('/api/train', methods=['POST'])
def train_db():
    try:
        df = pd.read_csv(request.files['file'])
        with get_db() as conn: df.to_sql('knowledge', conn, if_exists='append', index=False)
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 500

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

@app.route('/api/messages/<sid>')
def get_messages(sid):
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC", (sid,)).fetchall()])

@app.route('/api/send_reply', methods=['POST'])
def send_reply():
    d = request.json; sid = str(d['sender_id'])
    with get_db() as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    tk = PAGE_TOKENS.get(str(row[0]) if row else None, os.environ.get("FB_PAGE_ACCESS_TOKEN"))
    r = requests.post(f"https://graph.facebook.com/v12.0/me/messages?access_token={tk}", json={"recipient": {"id": sid}, "message": {"text": d['message']}})
    if r.status_code == 200:
        with get_db() as conn: conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, 'admin')", (sid, d['message']))
        return jsonify({"status": "sent"})
    return jsonify({"status": "error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
