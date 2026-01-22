import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
from datetime import timedelta
from functools import wraps
from flask import Flask, request, render_template, jsonify, session, redirect, url_for

# Google & Gemini
import google.generativeai as genai

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "mos_wedding_ultimate_v3_1_stable"
app.permanent_session_lifetime = timedelta(days=365)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DATABASE_URL = os.environ.get("DATABASE_URL") # URL จาก Neon.tech

PAGE_TOKENS = {
    "YOUR_PAGE_ID_1": "YOUR_TOKEN_1",
}
DEFAULT_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")

# ================== 2. DATABASE INIT (PostgreSQL) ==================
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # สร้างตาราง chats (Postgres ใช้ SERIAL แทน AUTOINCREMENT)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id SERIAL PRIMARY KEY,
            sender_id TEXT,
            page_id TEXT,
            message TEXT,
            sender_type TEXT, 
            timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # สร้างตาราง users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            sender_id TEXT PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            profile_pic TEXT,
            tags TEXT DEFAULT ''
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# ================== 3. AI LOGIC (Psychology-Driven) ==================
def ask_gemini(user_msg):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")
        
        # คำสั่ง AI ที่ปรับให้เหมาะกับคุณ (ไม่แนะนำกิจกรรมสังสรรค์หรือแอลกอฮอล์)
        instruction = """
        Role: มอธ Mos Wedding (ผู้เชี่ยวชาญงานแต่ง). 
        Style: เป็นกันเอง จริงใจ แนะนำแบบเพื่อน พี่น้อง สุภาพ พูดลงท้ายว่า ครับ.
        Format: วิเคราะห์: [จิตวิทยา] ### [ข้อความตอบลูกค้า] ### [โอกาส 0-100] ### [งบประมาณ]
        """
        prompt = f"{instruction}\n\nลูกค้าถาม: {user_msg}"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        if "429" in str(e): return "วิเคราะห์: ⏳ AI พักเหนื่อย ### ⏳ ขอพักดื่มน้ำ 2 นาทีครับ ### 0 ### ไม่ระบุ"
        return f"วิเคราะห์: ⚠️ ระบบสะดุด ### ⚠️ เกิดข้อผิดพลาด ({str(e)}) ### 0 ### ไม่ระบุ"

# ================== 4. FACEBOOK HELPER ==================
def get_facebook_profile(sender_id, page_id):
    token = PAGE_TOKENS.get(page_id, DEFAULT_TOKEN)
    try:
        url = f"https://graph.facebook.com/{sender_id}?fields=first_name,last_name,profile_pic&access_token={token}"
        r = requests.get(url).json()
        return r.get('first_name', 'ลูกค้า'), r.get('last_name', ''), r.get('profile_pic', '')
    except: return "ลูกค้า", "", ""

def send_fb_message(recipient_id, text):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT page_id FROM chats WHERE sender_id = %s LIMIT 1", (recipient_id,))
    row = cur.fetchone()
    pid = row[0] if row else None
    cur.close()
    conn.close()
    
    token = PAGE_TOKENS.get(pid, DEFAULT_TOKEN)
    url = f"https://graph.facebook.com/v12.0/me/messages?access_token={token}"
    requests.post(url, json={"recipient": {"id": recipient_id}, "message": {"text": text}})

# ================== 5. APP ROUTES ==================
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
def get_contacts():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    sql = """
        SELECT c.*, u.first_name, u.profile_pic, u.tags 
        FROM chats c 
        LEFT JOIN users u ON c.sender_id = u.sender_id 
        WHERE c.id IN (SELECT MAX(id) FROM chats GROUP BY sender_id) 
        ORDER BY c.id DESC
    """
    cur.execute(sql)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

@app.route('/api/messages/<sender_id>')
def get_messages(sender_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    sql = "SELECT c.*, u.first_name, u.profile_pic, u.tags FROM chats c LEFT JOIN users u ON c.sender_id = u.sender_id WHERE c.sender_id = %s ORDER BY c.id ASC"
    cur.execute(sql, (sender_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

@app.route('/api/update_tags', methods=['POST'])
def update_tags():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET tags = %s WHERE sender_id = %s", (data.get('tags'), data.get('sender_id')))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "success"})

@app.route('/api/send_reply', methods=['POST'])
def send_reply():
    data = request.json
    send_fb_message(data.get("sender_id"), data.get("message"))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (%s, %s, %s)", 
                (data.get("sender_id"), data.get("message"), 'admin'))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status": "sent"})

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": 
        return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], event["sender"]["id"], event["recipient"]["id"]
                conn = get_db_connection()
                cur = conn.cursor()
                
                cur.execute("SELECT sender_id FROM users WHERE sender_id = %s", (sid,))
                if not cur.fetchone():
                    fname, lname, pic = get_facebook_profile(sid, pid)
                    cur.execute("INSERT INTO users (sender_id, first_name, last_name, profile_pic) VALUES (%s, %s, %s, %s)", 
                                (sid, fname, lname, pic))
                
                ai_reply = ask_gemini(msg)
                cur.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (%s, %s, %s, %s)", (sid, pid, msg, 'user'))
                cur.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (%s, %s, %s, %s)", (sid, pid, ai_reply, 'ai_suggestion'))
                
                conn.commit()
                cur.close()
                conn.close()
    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
