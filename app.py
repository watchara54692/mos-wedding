import os
import sqlite3
import requests
import threading
import csv # ใช้ตัวนี้แทน pandas เพื่อตัดปัญหา Error
import json
from datetime import timedelta
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from openai import OpenAI 

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "moth_wedding_v5_3_no_pandas"
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                keyword TEXT, 
                analysis TEXT, 
                option_1 TEXT, 
                option_2 TEXT
            )
        """)
init_db()

# ================== 3. GROQ AI ENGINE ==================
def ask_groq_identifier(user_msg, history=""):
    client = OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")
    prompt = f"""[System: คุณคือ AI ค้นหาคีย์เวิร์ดของ 'มอธเวดดิ้ง' (Wedding Organizer)]
ภารกิจ: วิเคราะห์แชทล่าสุดและส่งกลับเป็น JSON เท่านั้น
{{ "keyword": "คำค้น", "budget": "ตัวเลขงบ", "chance": "0-100", "category": "ประเภทงาน" }}

แชทล่าสุด: {user_msg}
ประวัติ: {history}"""
    try:
        res = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}], response_format={ "type": "json_object" })
        return json.loads(res.choices[0].message.content)
    except:
        return {"keyword": "ทั่วไป", "budget": "ข้อมูลไม่พอ", "chance": 0, "category": "ข้อมูลไม่พอ"}

# ================== 4. SMART RETRIEVAL (DATA WAREHOUSE) ==================
def get_suggestion(sid, pid, msg):
    with sqlite3.connect(DB_NAME) as conn:
        h = conn.execute("SELECT message FROM chats WHERE sender_id = ? AND sender_type = 'user' ORDER BY id DESC LIMIT 3", (sid,)).fetchall()
        history_text = " | ".join([x[0] for x in h])
    
    ai_id = ask_groq_identifier(msg, history_text)
    
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        search_term = ai_id.get('keyword', 'ทั่วไป')
        know = conn.execute("SELECT * FROM knowledge WHERE keyword LIKE ? OR ? LIKE '%' || keyword || '%' LIMIT 1", (f'%{search_term}%', msg)).fetchone()
        
        if know:
            final_res = f"{know['analysis']} ### {know['option_1']} ### {know['option_2']} ### {ai_id['category']} ### {ai_id['budget']} ### {ai_id['chance']}"
        else:
            final_res = f"ยังไม่มีบทวิเคราะห์เรื่องนี้ในคลังข้อมูล แนะนำให้สอบถามรายละเอียดเพิ่ม ### รบกวนขอทราบวันที่และสถานที่จัดงานครับ มอธจะได้เช็คคิวทีมงานให้ครับ ### สนใจให้มอธส่งภาพตัวอย่างงานตกแต่งล่าสุดให้ดูทางไลน์ไหมครับ? ### {ai_id['category']} ### {ai_id['budget']} ### {ai_id['chance']}"
        
        conn.execute("UPDATE users SET ai_tag=?, ai_budget=?, ai_chance=? WHERE sender_id=?", 
                     (ai_id['category'], ai_id['budget'], ai_id['chance'], sid))
        conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, 'ai_suggestion')", (sid, pid, final_res))

# ================== 5. API & ROUTES ==================
@app.route('/api/train', methods=['POST'])
def train_ai():
    if 'file' not in request.files: return "No file", 400
    file = request.files['file']
    if not file.filename.endswith('.csv'): return "Invalid file type", 400
    
    # อ่านไฟล์แบบไม่ง้อ pandas
    stream = file.read().decode("utf-8").splitlines()
    reader = csv.DictReader(stream)
    
    with sqlite3.connect(DB_NAME) as conn:
        for row in reader:
            conn.execute(
                "INSERT INTO knowledge (keyword, analysis, option_1, option_2) VALUES (?, ?, ?, ?)",
                (row['keyword'], row['analysis'], row['option_1'], row['option_2'])
            )
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session.permanent = True; session['logged_in'] = True
        return redirect(url_for('index'))
    return render_template('login.html')

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
                threading.Thread(target=get_suggestion, args=(sid, pid, msg)).start()
    return "OK", 200

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

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('index.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
