import os
import datetime
from flask import Flask, request
import google.generativeai as genai
from google.oauth2 import service_account
from googleapiclient.discovery import build
import requests

app = Flask(__name__)

# --- CONFIGURATION (ดึงค่าจาก Render) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234") # ตั้งรหัสผ่านตรงนี้

# ตั้งค่า Google API Scopes
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'credentials.json'

# --- 1. FUNCTION: เชื่อมต่อ Google Services ---
def get_google_service(service_name, version):
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES)
        return build(service_name, version, credentials=creds)
    except Exception as e:
        print(f"Error connecting to Google: {e}")
        return None

# --- 2. FUNCTION: เช็คตารางงาน (Calendar) ---
def check_calendar(date_text):
    # (ในเวอร์ชัน MVP นี้ เราจะเช็คคร่าวๆ ของวันปัจจุบันหรือวันที่ระบุ)
    # เพื่อความง่าย ถ้า AI ส่งวันที่มา เราจะลองเช็คช่วงนั้น
    service = get_google_service('calendar', 'v3')
    if not service: return "ไม่สามารถเช็คตารางงานได้ (ระบบขัดข้อง)"
    
    # ดึง ID ปฏิทิน (สมมติว่าเป็น Primary ของ Service Account ที่แชร์มา)
    # *สำคัญ* คุณต้องแชร์ปฏิทินให้ Service Account email ด้วย
    calendar_id = 'primary' 
    
    now = datetime.datetime.utcnow().isoformat() + 'Z' # 'Z' indicates UTC time
    
    events_result = service.events().list(calendarId=calendar_id, timeMin=now,
                                          maxResults=5, singleEvents=True,
                                          orderBy='startTime').execute()
    events = events_result.get('items', [])

    if not events:
        return "ว่างครับ (ไม่พบตารางงานในระบบช่วงเร็วๆ นี้)"
    
    schedule_text = "📅 ตารางงานที่พบ:\n"
    for event in events:
        start = event['start'].get('dateTime', event['start'].get('date'))
        schedule_text += f"- {start}: {event['summary']}\n"
    return schedule_text

# --- 3. FUNCTION: ดึงข้อมูลแพ็กเกจ (Sheets) ---
def get_packages():
    # สมมติว่าข้อมูลอยู่ใน Sheet ชื่อ MosWedding_Data, Range A2:C10
    # ID ของ Spreadsheet ดูได้จาก URL ของ Google Sheet (อยู่หลัง /d/...)
    SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID") 
    RANGE_NAME = 'Services!A2:C10' # ชื่อ Tab!Range
    
    service = get_google_service('sheets', 'v4')
    if not service or not SPREADSHEET_ID: return "ข้อมูลแพ็กเกจ: (ระบบขัดข้อง หรือยังไม่ได้ตั้งค่า Sheet ID)"

    try:
        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=SPREADSHEET_ID,
                                    range=RANGE_NAME).execute()
        rows = result.get('values', [])
        info = ""
        for row in rows:
            # สมมติ Col A=ชื่อ, Col B=ราคา
            if len(row) >= 2:
                info += f"- {row[0]}: {row[1]}\n"
        return info
    except Exception as e:
        return f"Error reading sheet: {e}"

# --- 4. FUNCTION: AI Think (Gemini) ---
def ask_gemini(user_msg):
    genai.configure(api_key=GEMINI_API_KEY)
    
    # ดึงข้อมูลจริงมาประกอบ
    calendar_info = check_calendar("today") # MVP: เช็คคิวเร็วๆนี้ให้ก่อน
    packages_info = get_packages()

    system_prompt = f"""
    Role: คุณคือผู้ช่วยของ "Mos Wedding พิษณุโลก" รับจัดงานแต่งและอีเวนต์
    
    [ข้อมูลปัจจุบัน]
    ตารางงานทีมงาน: {calendar_info}
    แพ็กเกจบริการ: {packages_info}
    
    Task: วิเคราะห์ข้อความลูกค้าและแนะนำแอดมิน (สั้นๆ กระชับ)
    User Message: "{user_msg}"
    
    Format Output:
    🔥 วิเคราะห์: ...
    📊 โอกาสปิดการขาย: ...%
    💡 แนะนำตอบ:
    1. ...
    2. ...
    """
    
    try:
        model = genai.GenerativeModel('gemini-pro')
        response = model.generate_content(system_prompt)
        return response.text
    except Exception as e:
        return f"AI Error: {e}"

# --- 5. FUNCTION: ส่งเข้า Telegram ---
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}
    requests.post(url, json=payload)

# --- WEBHOOK (หัวใจสำคัญที่ Facebook จะมาเคาะประตู) ---
@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    # ส่วนที่ 1: Facebook Verify (แก้ปัญหา Failed ของคุณตรงนี้!)
    if request.method == 'GET':
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode and token:
            if mode == "subscribe" and token == FB_VERIFY_TOKEN:
                print("WEBHOOK_VERIFIED")
                return challenge, 200
            else:
                return "Verification Token ไม่ถูกต้อง", 403
    
    # ส่วนที่ 2: รับข้อความจริง
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
                
        return "EVENT_RECEIVED", 200

if __name__ == '__main__':
    app.run(port=5000)
