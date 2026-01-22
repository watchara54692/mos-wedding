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
app.secret_key = "mos_wedding_autonomous_v3_2"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DB_NAME = "mos_chat.db"

PAGE_TOKENS = { "336498580864850": "EAA36oXUv5vcBQp3t2Oh4MTS0ByxA0ndvSlLRX4A8BymU1nUzue02gaujziMZCfWrzjvnEjXmsG1VXY7urPLduyh9M7EZAlA487D4NPoTzZA92pzj8Bgcd7IVlgyIJVaWZBEm32GBXaqZCCJAK2MNkcjFlaIZBGp2s5fmEZBmZCFRmKDdu8DpwX0tlXAAlw1AT4m9Ip5kMcUIXwZDZD",
              "106344620734603": "EAA36oXUv5vcBQoHmOLSbFHieuH4WDrdzF0MSYC6Dw1DxZBQwyOQTboRYQCkGfK5Uq35ChF1dFEDDNF5ZBxc3naJpbT9lsI5Va7LiCzT6rZAsroBQWAv9aFywmeZCcF4Xvjw4BmWbKv2wIwMwhk1rFAuMLC3fPjEiqvrT7OqoneAIJKfgMaIBghnRs4hQTc1M1FIZCColQ"
              
              }
DEFAULT_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# ================== 2. DATABASE INIT ==================
def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS chats (id INTEGER PRIMARY KEY AUTOINCREMENT, sender_id TEXT, page_id TEXT, message TEXT, sender_type TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)")
        # ปรับปรุงตาราง users ให้เก็บสถานะที่ AI วิเคราะห์
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                sender_id TEXT PRIMARY KEY, 
                first_name TEXT, 
                last_name TEXT, 
                profile_pic TEXT, 
                ai_tag TEXT DEFAULT 'กำลังวิเคราะห์...', 
                ai_chance INTEGER DEFAULT 0, 
                ai_budget TEXT DEFAULT 'ไม่ระบุ'
            )
        """)
init_db()

# ================== 3. AI AUTONOMOUS LOGIC ==================
def ask_gemini(user_msg, history_context=""):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = f"""คุณคือผู้เชี่ยวชาญด้านการขายของ 'มอธเวดดิ้ง' (Mos Wedding) 
บริบท: เรารับจัดงานทุกรูปแบบ (งานแต่ง, งานบวช, อีเว้นท์, บายเนียร์, งานเลี้ยง)
ภารกิจ: วิเคราะห์บทสนทนาและร่างคำตอบเพื่อปิดการขาย

ประวัติการคุย: {history_context}
ข้อความล่าสุดจากลูกค้า: {user_msg}

ตอบตาม Format นี้เท่านั้น (ห้ามขาด):
วิเคราะห์: (สรุปจิตวิทยาการขายสั้นๆ)
###
(ร่างคำตอบสั้นๆ ไม่เกิน 2 ประโยค เหมือนแชท Messenger)
###
(ระบุประเภทงานที่ลูกค้าติดต่อ: เช่น งานแต่ง, งานบวช, อีเว้นท์, บายเนียร์ หรือ 'ยังไม่ชัดเจน')
###
(โอกาสปิดการขาย 0-100 เป็นตัวเลขเท่านั้น)
###
(งบประมาณที่ระบุในแชท ถ้าไม่มีให้ใส่ 'ไม่ระบุ')"""

        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        if "429" in str(e): return "AI พักเหนื่อย ### AI ขอพัก 1 นาทีครับ ### ยังไม่ชัดเจน ### 0 ### ไม่ระบุ"
        return f"ระบบขัดข้อง ### ขออภัยครับ ระบบสะดุด ### ยังไม่ชัดเจน ### 0 ### ไม่ระบุ"

# ================== 4. ROUTES & WEBHOOK ==================
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], event["sender"]["id"], event["recipient"]["id"]
                with sqlite3.connect(DB_NAME) as conn:
                    # 1. จัดการข้อมูลลูกค้า
                    if not conn.execute("SELECT sender_id FROM users WHERE sender_id = ?", (sid,)).fetchone():
                        fname, lname, pic = "ลูกค้า", "", "" # (ฟังก์ชันดึงโปรไฟล์ FB ใส่ตรงนี้ได้)
                        conn.execute("INSERT INTO users (sender_id, first_name, last_name, profile_pic) VALUES (?, ?, ?, ?)", (sid, fname, lname, pic))
                    
                    # 2. ดึงประวัติย้อนหลัง 5 ข้อความมาให้ AI วิเคราะห์
                    history = conn.execute("SELECT message FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT 5", (sid,)).fetchall()
                    history_text = " | ".join([h[0] for h in history])
                    
                    # 3. ให้ AI วิเคราะห์แบบเจาะลึก
                    ai_res = ask_gemini(msg, history_text)
                    parts = ai_res.split('###')
                    
                    # 4. อัปเดตสถานะ AI ลงในตาราง users ทันที
                    if len(parts) >= 5:
                        conn.execute("UPDATE users SET ai_tag = ?, ai_chance = ?, ai_budget = ? WHERE sender_id = ?", 
                                     (parts[2].strip(), parts[3].strip(), parts[4].strip(), sid))
                    
                    # 5. บันทึกแชท
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, msg, 'user'))
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, ai_res, 'ai_suggestion'))
    return "OK", 200

# (Routes อื่นๆ เช่น login, index, api/contacts เหมือนเวอร์ชั่น 3.1)
@app.route('/api/contacts')
def get_contacts():
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        sql = "SELECT c.*, u.first_name, u.profile_pic, u.ai_tag, u.ai_chance, u.ai_budget FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) ORDER BY c.id DESC"
        return jsonify([dict(row) for row in conn.execute(sql).fetchall()])

@app.route('/api/messages/<sender_id>')
def get_messages(sender_id):
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        return jsonify([dict(row) for row in conn.execute("SELECT c.*, u.* FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = ? ORDER BY c.id ASC", (sender_id,)).fetchall()])

@app.route('/api/send_reply', methods=['POST'])
def send_reply():
    data = request.json
    # (ฟังก์ชันส่งข้อความ FB จริงใส่ตรงนี้)
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", (data.get("sender_id"), data.get("message"), 'admin'))
    return jsonify({"status": "sent"})

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST' and request.form.get('password') == ADMIN_PASSWORD:
        session.permanent = True
        session['logged_in'] = True
        return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/')
def index():
    if not session.get('logged_in'): return redirect(url_for('login'))
    return render_template('index.html')

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
