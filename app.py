import os
import datetime
import requests
from flask import Flask, request

# ================== GOOGLE ==================
from google.oauth2 import service_account
from googleapiclient.discovery import build

# ================== GEMINI ==================
import google.generativeai as genai

# ================== FLASK ==================
app = Flask(__name__)

# ======================================================
# ENV CONFIG
# ======================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
FB_PAGE_TOKEN = os.environ.get("FB_PAGE_TOKEN")

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

SERVICE_ACCOUNT_FILE = "credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly"
]

# ======================================================
# GOOGLE SERVICE
# ======================================================
def get_google_service(service_name, version):
    try:
        if not os.path.exists(SERVICE_ACCOUNT_FILE):
            print("❌ credentials.json not found")
            return None

        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE,
            scopes=SCOPES
        )

        return build(service_name, version, credentials=creds)

    except Exception as e:
        print("Google Service Error:", e)
        return None


# ======================================================
# GOOGLE CALENDAR
# ======================================================
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
            return "📅 ยังไม่มีงานในช่วงนี้"

        text = ""
        for e in events:
            start = e["start"].get("dateTime", e["start"].get("date"))
            text += f"- {start} : {e.get('summary','(ไม่มีชื่อ)')}\n"

        return text

    except Exception as e:
        return f"Calendar error: {e}"


# ======================================================
# GOOGLE SHEETS
# ======================================================
def get_packages():
    if not SPREADSHEET_ID:
        return "ยังไม่ได้ตั้งค่าแพ็กเกจ"

    service = get_google_service("sheets", "v4")
    if not service:
        return "ไม่สามารถเชื่อม Google Sheets ได้"

    try:
        result = service.spreadsheets().values().get(
            spreadsheetId=SPREADSHEET_ID,
            range="Services!A2:C50"
        ).execute()

        rows = result.get("values", [])

        if not rows:
            return "ไม่พบข้อมูลแพ็กเกจ"

        text = ""
        for r in rows:
            if len(r) >= 2:
                service_name = r[0]
                price = r[1]
                desc = r[2] if len(r) > 2 else ""
                text += f"• {service_name}\n  ราคา: {price}\n  {desc}\n\n"

        return text.strip()

    except Exception as e:
        return f"Sheets error: {e}"


# ======================================================
# GEMINI AI
# ======================================================
def ask_gemini(user_msg):

    try:
        genai.configure(api_key=GEMINI_API_KEY)

        model = genai.GenerativeModel(
    model_name="gemini-2.5-flash"
)

        calendar_info = check_calendar()
        packages_info = get_packages()

        prompt = f"""
คุณคือแอดมินเพจ "Mos Wedding พิษณุโลก"
รับจัดงานแต่ง งานบวช งานอีเวนต์

ข้อมูลปัจจุบัน

📅 ตารางงาน:
{calendar_info}

💍 แพ็กเกจ:
{packages_info}

กติกาการตอบ:
- ใช้ภาษาไทย
- สุภาพ เป็นกันเอง
- ตอบสั้น กระชับ
- ถ้าลูกค้าทัก ให้ชวนคุยต่อ
- ถ้าถามราคา ให้แนะนำแพ็กเกจ
- ถ้าถามวันว่าง ให้ดูจากตารางงาน

ข้อความลูกค้า:
{user_msg}
"""

        response = model.generate_content(prompt)
        return response.text.strip()

    except Exception as e:
        return f"Gemini Error: {e}"


# ======================================================
# TELEGRAM NOTIFY
# ======================================================
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }

    try:
        requests.post(url, json=payload, timeout=10)
    except:
        pass


# ======================================================
# FACEBOOK SEND MESSAGE
# ======================================================
def send_fb_message(psid, text):
    url = f"https://graph.facebook.com/v19.0/me/messages"
    params = {"access_token": FB_PAGE_TOKEN}

    payload = {
        "recipient": {"id": psid},
        "message": {"text": text}
    }

    requests.post(url, params=params, json=payload, timeout=10)


# ======================================================
# WEBHOOK
# ======================================================
@app.route("/webhook", methods=["GET", "POST"])
def webhook():

    # ---------- Verify ----------
    if request.method == "GET":
        if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Verification failed", 403

    # ---------- Message ----------
    data = request.json
    entries = data.get("entry", [])

    for entry in entries:
        for event in entry.get("messaging", []):

            if "message" not in event:
                continue

            if "text" not in event["message"]:
                continue

            user_msg = event["message"]["text"]
            sender_id = event["sender"]["id"]

            ai_reply = ask_gemini(user_msg)

            # ส่งกลับลูกค้า
            send_fb_message(sender_id, ai_reply)

            # แจ้งแอดมิน
            send_telegram(
                f"🔔 ลูกค้าใหม่ Mos Wedding\n"
                f"💬 {user_msg}\n\n"
                f"🤖 AI ตอบ:\n{ai_reply}"
            )

    return "OK", 200


# ======================================================
# RUN
# ======================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
