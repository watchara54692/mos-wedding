import os
import datetime
import requests
from flask import Flask, request

# Google
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Gemini SDK (วิธีที่ถูกต้อง)
import google.generativeai as genai

app = Flask(__name__)

# ================== CONFIG ==================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# Google Service Account
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]
SERVICE_ACCOUNT_FILE = "credentials.json"

# ================== GOOGLE SERVICE ==================
def get_google_service(service_name, version):
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            return None

        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )
        return build(service_name, version, credentials=creds)

    except Exception as e:
        print("Google service error:", e)
        return None

# ================== CALENDAR ==================
def check_calendar():
    service = get_google_service("calendar", "v3")
    if not service:
        return "ไม่สามารถเช็คตารางงานได้"

    try:
        now = datetime.datetime.utcnow().isoformat() + "Z"
        events = service.events().list(
            calendarId="primary",
            timeMin=now,
            maxResults=3,
            singleEvents=True,
            orderBy="startTime"
        ).execute().get("items", [])

        if not events:
            return "ว่างครับ (ยังไม่มีงานเร็ว ๆ นี้)"

        text = ""
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date"))
            text += f"- {start}: {e.get('summary','(ไม่มีชื่อ)')}\n"

        return text

    except Exception as e:
        return f"Calendar error: {e}"

# ================== PACKAGES (SHEETS) ==================
def get_packages():
    if not SPREADSHEET_ID:
        return "ยังไม่ได้ตั้งค่าแพ็กเกจ"

    service = get_google_service("sheets", "v4")
    if not service:
        return "ไม่สามารถดึงแพ็กเกจได้"

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Services!A2:C20"
        ).execute()

        rows = result.get("values", [])
        if not rows:
            return "ไม่พบข้อมูลแพ็กเกจ"

        text = ""
        for r in rows:
            if len(r) >= 2:
                text += f"- {r[0]}: {r[1]}\n"

        return text

    except Exception as e:
        return f"Sheets error: {e}"

# ================== GEMINI ==================
def ask_gemini(user_msg):
    try:
        genai.configure(api_key=GEMINI_API_KEY)

        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash"
        )

        calendar_info = check_calendar()
        packages_info = get_packages()

        prompt = f"""
คุณคือแอดมินของ "Mos Wedding พิษณุโลก"
รับจัดงานแต่งและอีเวนต์

ข้อมูลปัจจุบัน:
ตารางงานทีม:
{calendar_info}

แพ็กเกจ:
{packages_info}

กติกา:
- ตอบสุภาพ เป็นกันเอง
- สั้น กระชับ
- ถ้าลูกค้าทักทาย ให้ชวนคุยต่อ

ข้อความลูกค้า:
{user_msg}
"""

        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        return f"Gemini Error: {e}"

# ================== TELEGRAM ==================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    requests.post(url, json=payload, timeout=10)

# ================== WEBHOOK ==================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    # Facebook Verify
    if request.method == "GET":
        if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Verification failed", 403

    # Facebook Message
    data = request.json
    entries = data.get("entry", [])

    for entry in entries:
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                user_msg = event["message"]["text"]

                ai_reply = ask_gemini(user_msg)

                send_telegram(
                    f"🔔 ลูกค้าใหม่ Mos Wedding\n"
                    f"💬 ข้อความ: {user_msg}\n\n"
                    f"🤖 AI ตอบ:\n{ai_reply}"
                )

    return "OK", 200

# ================== RUN ==================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
