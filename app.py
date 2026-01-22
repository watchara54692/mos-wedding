import os
import sqlite3
import requests
import threading
import pandas as pd
import json
import time
from datetime import timedelta
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from openai import OpenAI 

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "mos_wedding_v10_transparent"
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
    conn.execute("PRAGMA journal_mode=WAL") #
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

# ================== 3. RECOVERY WITH STATUS ==================
def recover_fb_data():
    for pid, token in PAGE_TOKENS.items():
        try:
            r = requests.get(f"https://graph.facebook.com/v12.0/me/conversations?fields=participants,updated_time,snippet&limit=50&access_token={token}").json()
            with get_db() as conn:
                for conv in r.get('data', []):
                    sid = next((p['id'] for p in conv['participants']['data'] if p['id'] != pid), None)
                    if sid:
                        conn.execute("INSERT OR IGNORE INTO users (sender_id, first_name, last_active) VALUES (?, ?, ?)", 
                                     (sid, "กำลังซิงค์...", conv['updated_time']))
                        def fetch_full_prof(uid=sid, tk=token, conv_id=conv['id']):
                            try:
                                p_res = requests.get(f"https://graph.facebook.com/{uid}?fields=first_name,picture.type(large)&access_token={tk}").json()
                                m_res = requests.get(f"https://graph.facebook.com/v12.0/{conv_id}/messages?fields=message,from,created_time&limit=30&access_token={tk}").json()
                                with get_db() as conn2:
                                    conn2.execute("UPDATE users SET first_name=?, profile_pic=? WHERE sender_id=?", 
                                                 (p_res.get('first_name', 'ลูกค้าเก่า'), p_res.get('picture', {}).get('data', {}).get('url', ''), uid))
                                    for m in reversed(m_res.get('data', [])):
                                        stype = 'user' if m['from']['id'] == uid else 'admin'
                                        conn2.execute("INSERT OR IGNORE INTO chats (sender_id, page_id, message, sender_type, timestamp) VALUES (?, ?, ?, ?, ?)", (uid, pid, m.get('message', ''), stype, m['created_time']))
                            except: pass
                        threading.Thread(target=fetch_full_prof).start()
        except: pass

# ================== 4. SMART ANALYZER ==================
def analyze_for_closer(sid, pid, msg):
    client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    prompt = f"""[System: MoS Wedding AI - วิเคราะห์แชทเพื่อปิดการขาย]
ภารกิจ: วิเคราะห์ลูกค้าและตอบเป็น JSON เท่านั้น
JSON Format: {{
  "keyword": "คีย์เวิร์ดสั้นๆ (เช่น ราคา, ตกแต่ง, จองคิว, วันที่)",
  "category": "ประเภทงาน",
  "budget": "งบ หรือ 'ไม่ระบุ'",
  "chance": 0-100
}}
แชทล่าสุด: {msg}"""
    try:
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], response_format={"type": "json_object"})
        ai = json.loads(res.choices[0].message.content)
        
        with get_db() as conn:
            conn.row_factory = sqlite3.Row
            know = conn.execute("SELECT * FROM knowledge WHERE keyword LIKE ? OR ? LIKE '%' || keyword || '%' LIMIT 1", (f"%{ai['keyword']}%", msg)).fetchone()
            
            analysis = know['analysis'] if know else "กำลังประเมินความต้องการลูกค้าเบื้องต้น..."
            opt1 = know['option_1'] if know else "รบกวนขอทราบวันและพิกัดสถานที่จัดงานหน่อยครับ MoS Wedding จะได้เช็คคิวให้ครับ"
            opt2 = know['option_2'] if know else "สนใจให้เราช่วยร่างแบบพรอพและตกแต่งหน้างานให้ดูก่อนไหมครับ?"
            
            # Persistent Tags
            if ai['budget'] != 'ไม่ระบุ':
                conn.execute("UPDATE users SET ai_budget=? WHERE sender_id=?", (ai['budget'], sid))
            if ai['category'] != 'ยังไม่ชัดเจน' and ai['category'] != 'ไม่ระบุ':
                conn.execute("UPDATE users SET ai_tag=? WHERE sender_id=?", (ai['category'], sid))
            
            conn.execute("UPDATE users SET ai_chance=?, last_active=CURRENT_TIMESTAMP WHERE sender_id=?", (ai['chance'], sid))
            content = f"{analysis} ### {opt1} ### {opt2} ### {ai['category']} ### {ai['budget']} ### {ai['chance']}"
            conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, 'ai_suggestion')", (sid, pid, content))
    except: pass

# ================== 5. ROUTES ==================
@app.route('/api/contacts')
def get_contacts():
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) ORDER BY u.last_active DESC").fetchall()])

@app.route('/api/messages/<sid>')
def get_messages(sid):
    with get_db() as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC", (sid,)).fetchall()])

@app.route('/api/analyze_now/<sid>')
def api_analyze_now(sid):
    with get_db() as conn:
        row = conn.execute("SELECT page_id, message FROM chats WHERE sender_id=? AND sender_type='user' ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    if row:
        threading.Thread(target=analyze_for_closer, args=(sid, row[0], row[1])).start()
        return jsonify({"status": "processing"})
    return jsonify({"status": "no_data"})

@app.route('/api/train', methods=['POST'])
def train_db():
    if 'file' not in request.files: return jsonify({"status": "error", "msg": "ไม่พบไฟล์"}), 400
    try:
        df = pd.read_csv(request.files['file'])
        # ตรวจสอบหัวตาราง
        required = ['keyword', 'analysis', 'option_1', 'option_2']
        if not all(col in df.columns for col in required):
            return jsonify({"status": "error", "msg": "หัวตาราง CSV ไม่ถูกต้อง (ต้องมี keyword, analysis, option_1, option_2)"}), 400
        with get_db() as conn: df.to_sql('knowledge', conn, if_exists='append', index=False)
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "msg": f"ระบบติดขัด: {e}"}), 500

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session.permanent = True; session['logged_in'] = True
        threading.Thread(target=recover_fb_data).start() # เริ่มซิงค์ทันที
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/api/send_reply', methods=['POST'])
def send_reply():
    d = request.json; sid = str(d['sender_id'])
    with get_db() as conn:
        row = conn.execute("SELECT page_id FROM chats WHERE sender_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
    tk = PAGE_TOKENS.get(str(row[0]) if row else None, os.environ.get("FB_PAGE_ACCESS_TOKEN"))
    r = requests.post(f"https://graph.facebook.com/v12.0/me/messages?access_token={tk}", json={"recipient": {"id": sid}, "message": {"text": d['message']}})
    if r.status_code == 200:
        with get_db() as conn: 
            conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, 'admin')", (sid, d['message']))
            conn.execute("UPDATE users SET last_active=CURRENT_TIMESTAMP WHERE sender_id=?", (sid,))
        return jsonify({"status": "sent"})
    return jsonify({"status": "error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
