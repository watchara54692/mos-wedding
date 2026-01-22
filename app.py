import os
import datetime
import sqlite3
import json
import requests
from flask import Flask, request, render_template, jsonify

# Google & Gemini
from google.oauth2 import service_account
from googleapiclient.discovery import build
import google.generativeai as genai

app = Flask(__name__)

# ================== CONFIG ==================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
FB_PAGE_ACCESS_TOKEN = os.environ.get("FB_PAGE_ACCESS_TOKEN")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Service Account (ใช้ไฟล์เดิมที่มีอยู่แล้ว)
SERVICE_ACCOUNT_FILE = "credentials.json"
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly", "https://www.googleapis.com/auth/spreadsheets.readonly"]

# ================== DATABASE (ความจำถาวร) ==================
DB_NAME = "mos_chat.db"

def init_db():
    """สร้างตารางเก็บแชท ถ้ายังไม่มี"""
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT,
            message TEXT,
            sender_type TEXT, -- 'user' หรือ 'admin' หรือ 'ai_suggestion'
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'unread'
        )
        """)

# เรียกใช้งานทันทีเมื่อเริ่มแอป
init_db()

# ================== HELPER FUNCTIONS ==================
def get_google_service(service_name, version):
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE): return None
        creds = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build(service_name, version, credentials=creds)
    except Exception as e:
        print(f"Service Error: {e}")
        return None

def get_ai_instruction():
    # อ่าน Config จาก Sheets (ถ้ามี) หรือใช้ค่า Default
    default = "Role: พี่มอส Mos Wedding. ตอบลูกค้าสั้นๆ เป็นกันเอง."
    if not SPREADSHEET_ID: return default
    service = get_google_service("sheets", "v4")
    if not service: return default
    try:
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range="Config!B1").execute()
        vals = result.get("values", [])
        return vals[0][0] if vals else default
    except: return default

def ask_gemini(user_msg):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash") # รุ่นที่คุณใช้ได้
        instruction = get_ai_instruction()
        # ใส่ Logic ดึงปฏิทิน/แพ็กเกจตรงนี้เพิ่มได้ตามเดิม
        prompt = f"{instruction}\n\nลูกค้าถาม: {user_msg}\nตอบสั้นๆ:"
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Error: {e}"

def send_fb_message(recipient_id, text):
    """ส่งข้อความกลับเข้า Facebook จริงๆ"""
    url = f"https://graph.facebook.com/v12.0/me/messages?access_token={FB_PAGE_ACCESS_TOKEN}"
    payload = {
        "recipient": {"id": recipient_id},
        "message": {"text": text}
    }
    requests.post(url, json=payload)

# ================== WEB ROUTES (หน้าจอแอป) ==================
@app.route("/")
def index():
    # เปิดหน้าจอแชท
    return render_template("index.html")

@app.route("/api/chats")
def get_chats():
    # ดึงประวัติแชทล่าสุดไปโชว์หน้าจอ
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        # ดึง 50 ข้อความล่าสุด
        cursor = conn.execute("SELECT * FROM chats ORDER BY id DESC LIMIT 50")
        rows = [dict(row) for row in cursor.fetchall()]
    return jsonify(rows[::-1]) # กลับด้านให้ข้อความเก่าอยู่บน

@app.route("/api/send_reply", methods=["POST"])
def send_reply():
    # แอดมินกดปุ่มส่งจากหน้าเว็บ
    data = request.json
    recipient_id = data.get("sender_id")
    text = data.get("message")
    
    # 1. ส่งเข้า FB
    send_fb_message(recipient_id, text)
    
    # 2. บันทึกลง DB ว่าแอดมินตอบแล้ว
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", 
                     (recipient_id, text, 'admin'))
    
    return jsonify({"status": "sent"})

# ================== WEBHOOK (รับข้อความ FB) ==================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Failed", 403

    if request.method == "POST":
        data = request.json
        entries = data.get("entry", [])
        for entry in entries:
            for event in entry.get("messaging", []):
                if "message" in event and "text" in event["message"]:
                    user_msg = event["message"]["text"]
                    sender_id = event["sender"]["id"]
                    
                    # 1. ให้ AI คิดคำตอบรอไว้ (Suggestion)
                    ai_reply = ask_gemini(user_msg)
                    
                    # 2. บันทึกลง DB (เพื่อให้หน้าเว็บเห็น)
                    with sqlite3.connect(DB_NAME) as conn:
                        # บันทึกข้อความลูกค้า
                        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", 
                                     (sender_id, user_msg, 'user'))
                        # บันทึกคำแนะนำ AI (ซ่อนไว้ก่อน รอแอดมินกดส่ง)
                        conn.execute("INSERT INTO chats (sender_id, message, sender_type) VALUES (?, ?, ?)", 
                                     (sender_id, ai_reply, 'ai_suggestion'))

        return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
