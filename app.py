import os
import datetime
import requests
from flask import Flask, request

# Google & Gemini
from google.oauth2 import service_account
from googleapiclient.discovery import build
import google.generativeai as genai

app = Flask(__name__)

# ================== CONFIG ==================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Service Account
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]
SERVICE_ACCOUNT_FILE = "credentials.json"

# ================== 🧠 MEMORY STORAGE (ความจำ) ==================
# ตัวแปรนี้จะเก็บประวัติการคุยของลูกค้าแต่ละคน
# รูปแบบ: { "facebook_id_123": ["ลูกค้า: ดีครับ", "มอส: สวัสดีครับ", ...] }
chat_history = {}

# ================== GOOGLE SERVICE HELPER ==================
def get_google_service(service_name, version):
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE): return None
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        return build(service_name, version, credentials=creds)
    except Exception as e:
        print(f"Service Error: {e}")
        return None

# ================== READ BRAIN (Sheets) ==================
def get_ai_instruction():
    default_instruction = "Role: Mos Wedding Admin."
    if not SPREADSHEET_ID: return default_instruction
    service = get_google_service("sheets", "v4")
    if not service: return default_instruction
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range="Config!B1"
        ).execute()
        values = result.get("values", [])
        return values[0][0] if values and len(values) > 0 else default_instruction
    except Exception: return default_instruction

# ================== DATA FETCHERS ==================
def check_calendar():
    service = get_google_service("calendar", "v3")
    if not service: return "ไม่สามารถเช็คตารางงานได้"
    try:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        events = service.events().list(
            calendarId="primary", timeMin=now,
            maxResults=100, singleEvents=True, orderBy="startTime"
        ).execute().get("items", [])
        if not events: return "ว่างครับ (ยังไม่มีงานเร็วๆ นี้)"
        text = ""
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date"))
            text += f"- {start}: {e.get('summary','(ไม่มีชื่อ)')}\n"
        return text
    except Exception: return "เช็คตารางงานไม่ได้"

def get_packages():
    if not SPREADSHEET_ID: return "ไม่มีข้อมูลแพ็กเกจ"
    service = get_google_service("sheets", "v4")
    if not service: return "ดึงข้อมูลแพ็กเกจไม่ได้"
    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID, range="Services!A2:C20"
        ).execute()
        rows = result.get("values", [])
        text = ""
        for r in rows:
            if len(r) >= 2: text += f"- {r[0]}: {r[1]}\n"
        return text
    except Exception: return "ไม่พบข้อมูลแพ็กเกจ"

# ================== GEMINI AI (THE BRAIN) ==================
def ask_gemini(user_msg, sender_id):
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(model_name="gemini-2.5-flash") # ใช้รุ่น 2.5 ตามที่คุณมี

        calendar_info = check_calendar()
        packages_info = get_packages()
        custom_instruction = get_ai_instruction()

        # 1. ดึงประวัติเก่าของคนนี้มา (ถ้ามี)
        user_history = chat_history.get(sender_id, [])
        
        # แปลงเป็นข้อความเดียวเพื่อให้ AI อ่าน
        history_text = "\n".join(user_history)

        final_prompt = f"""
{custom_instruction}

[ข้อมูลประกอบ]
ตารางงาน: {calendar_info}
แพ็กเกจ: {packages_info}

[ประวัติการสนทนาก่อนหน้า] (สำคัญมาก! ให้อ่านบริบทจากตรงนี้ด้วย)
{history_text}

[ข้อความล่าสุดจากลูกค้า]
"{user_msg}"
"""
        response = model.generate_content(final_prompt)
        full_reply = response.text.strip()

        # 2. บันทึกบทสนทนาใหม่ลงความจำ
        # (เก็บแค่ส่วน "ตอบลูกค้า" ไม่เอาส่วนวิเคราะห์ เพื่อไม่ให้ AI งงตัวเอง)
        parts = full_reply.split("###")
        clean_reply = parts[1].strip() if len(parts) >= 2 else full_reply
        
        # เก็บแบบ: "User: ข้อความ" และ "Bot: ข้อความ"
        if sender_id not in chat_history:
            chat_history[sender_id] = []
        
        chat_history[sender_id].append(f"Customer: {user_msg}")
        chat_history[sender_id].append(f"Mos: {clean_reply}")

        # จำกัดความจำไว้แค่ 20 ประโยคล่าสุด (กันยาวเกิน)
        if len(chat_history[sender_id]) > 20:
            chat_history[sender_id] = chat_history[sender_id][-20:]

        return full_reply

    except Exception as e:
        return f"System Error ### ขออภัยครับ ระบบขัดข้อง ({str(e)})"

# ================== SERVER & LOGIC ==================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Verification failed", 403

    if request.method == "POST":
        data = request.json
        entries = data.get("entry", [])
        for entry in entries:
            for event in entry.get("messaging", []):
                if "message" in event and "text" in event["message"]:
                    user_msg = event["message"]["text"]
                    sender_id = event["sender"]["id"] # ดึง ID ลูกค้ามาใช้เป็นกุญแจความจำ
                    
                    # 1. ให้ AI คิด (ส่ง sender_id ไปด้วย)
                    full_response = ask_gemini(user_msg, sender_id)
                    
                    # 2. แยกส่วน
                    parts = full_response.split("###")
                    
                    if len(parts) >= 2:
                        analysis_part = parts[0].strip()
                        reply_part = parts[1].strip()
                    else:
                        analysis_part = "AI ไม่ได้วิเคราะห์แยกส่วนมาให้"
                        reply_part = full_response.strip()

                    # 3. ส่งเข้า Telegram (แยก 2 ข้อความ)
                    send_telegram(
                        f"🔔 ลูกค้า: {user_msg}\n"
                        f"--------------------\n"
                        f"🧠 AI วิเคราะห์:\n{analysis_part}"
                    )
                    send_telegram(reply_part)
                    
        return "OK", 200

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
