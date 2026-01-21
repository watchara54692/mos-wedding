import os
import datetime
import json
from flask import Flask, request
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests

app = Flask(__name__)

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

# --- GOOGLE SERVICES SETUP ---
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'credentials.json'

def get_google_service(service_name, version):
    try:
        if os.path.exists(SERVICE_ACCOUNT_FILE):
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_FILE, scopes=SCOPES)
            return build(service_name, version, credentials=creds)
        return None
    except Exception as e:
        print(f"Google Service Error: {e}")
        return None

# --- 1. FUNCTION: เช็คตารางงาน (Calendar) ---
def check_calendar():
    service = get_google_service('calendar', 'v3')
    if not service: return "ไม่สามารถเช็คตารางงานได้"
    
    calendar_id = 'primary'
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    try:
        events_result = service.events().list(calendarId=calendar_id, timeMin=now,
                                              maxResults=3, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        if not events: return "ว่างครับ (ไม่พบตารางงานเร็วๆ นี้)"
        
        schedule_text = ""
        for event in events:
            start = event['start'].get('dateTime', event['start'].get('date'))
            schedule_text += f"- {start}: {event['summary']}\n"
        return schedule_text
    except Exception as e:
        return f"Error Calendar: {str(e)}"

# --- 2. FUNCTION: ดึงข้อมูลแพ็กเกจ (Sheets) ---
def get_packages():
    if not SPREADSHEET_ID: return "ไม่มีข้อมูลแพ็กเกจ"
    service = get_google_service('sheets', 'v4')
    if not service: return "ดึงข้อมูลแพ็กเกจไม่ได้"

    try:
        # ดึงข้อมูลจากแผ่นงานชื่อ 'Services' ช่วง A2 ถึง C10
        result = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range='Services!A2:C10').execute()
        rows = result.get('values', [])
        info = ""
        for row in rows:
            if len(row) >= 2:
                info += f"- {row[0]}: {row[1]}\n"
        return info
    except Exception as e:
        return "ไม่พบข้อมูลแพ็กเกจ (ตรวจสอบชื่อ Tab ใน Sheet)"

# --- 3. FUNCTION: AI Think (Direct API - Gemini 1.5 Flash) ---
def ask_gemini(user_msg):
    # ดึงข้อมูลประกอบ
    calendar_info = check_calendar()
    packages_info = get_packages()

    # สร้าง Prompt
    system_prompt = f"""
    Role: คุณคือผู้ช่วยของ "Mos Wedding พิษณุโลก" รับจัดงานแต่งและอีเวนต์
    
    [ข้อมูลปัจจุบัน]
    ตารางงานทีมงาน: {calendar_info}
    แพ็กเกจบริการ: {packages_info}
    
    Task: ตอบคำถามลูกค้าสั้นๆ กระชับ เป็นกันเอง
    User Message: "{user_msg}"
    """

    # ใช้ URL ของ Gemini 1.5 Flash (มาตรฐานใหม่)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{
            "parts": [{"text": system_prompt}]
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            result = response.json()
            return result['candidates'][0]['content']['parts'][0]['text']
        else:
            return f"AI Error ({response.status_code}): {response.text}"
    except Exception as e:
        return f"System Error: {str(e)}"

# --- 4. FUNCTION: ส่งเข้า Telegram ---
def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID: return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    requests.post(url, json=payload)

# --- WEBHOOK ---
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == 'GET':
        if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "Verification Failed", 403

    if request.method == 'POST':
        data = request.json
        events = data.get('entry', [])[0].get('messaging', [])
        for event in events:
            if 'message' in event and 'text' in event['message']:
                user_msg = event['message']['text']
                
                # ให้ AI คิด
                ai_reply = ask_gemini(user_msg)
                
                # ส่งเข้า Telegram
                send_telegram(f"🔔 ลูกค้าใหม่ Mos Wedding!\nUser: {user_msg}\n\n{ai_reply}")
                
        return "OK", 200

if __name__ == '__main__':
    app.run(port=5000)
