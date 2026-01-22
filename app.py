import os
import sqlite3
import requests
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
import google.generativeai as genai
from openai import OpenAI 

app = Flask(__name__)

# ================== 1. CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
app.secret_key = "mos_wedding_failover_v3_8"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
# สำรองด้วย OpenThaiGPT (float16.cloud)
OPENTHAIGPT_CONFIG = {
    "api_key": "float16-AG0F8yNce5s1DiXm1ujcNrTaZquEdaikLwhZBRhyZQNeS7Dv0X",
    "base_url": "https://api.float16.cloud/dedicate/78y8fJLuzE/v1/",
    "model": "openthaigpt/openthaigpt1.5-7b-instruct"
}

PAGE_TOKENS = { 
    "336498580864850": "EAA36oXUv5vcBQp3t2Oh4MTS0ByxA0ndvSlLRX4A8BymU1nUzue02gaujziMZCfWrzjvnEjXmsG1VXY7urPLduyh9M7EZAlA487D4NPoTzZA92pzj8Bgcd7IVlgyIJVaWZBEm32GBXaqZCCJAK2MNkcjFlaIZBGp2s5fmEZBmZCFRmKDdu8DpwX0tlXAAlw1AT4m9Ip5kMcUIXwZDZD",
    "106344620734603": "EAA36oXUv5vcBQoHmOLSbFHieuH4WDrdzF0MSYC6Dw1DxZBQwyOQTboRYQCkGfK5Uq35ChF1dFEDDNF5ZBxc3naJpbT9lsI5Va7LiCzT6rZAsroBQWAv9aFywmeZCcF4Xvjw4BmWbKv2wIwMwhk1rFAuMLC3fPjEiqvrT7OqoneAIJKfgMaIBghnRs4hQTc1M1FIZCColQ"
}
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
DB_NAME = "mos_chat.db"

# ================== 2. AI SMART FAILOVER ==================

def ask_ai_expert(user_msg, history_context=""):
    prompt = f"""คุณคือผู้เชี่ยวชาญการขายของ 'มอธเวดดิ้ง' (Mos Wedding) 
เรารับจัด: งานแต่ง, งานบวช, อีเว้นท์, บายเนียร์, จัดเลี้ยง, ซุ้มดอกไม้
หน้าที่: ร่างคำตอบปิดการขาย สั้น กระชับ (ไม่เกิน 2 ประโยค)
ประวัติ: {history_context}
ลูกค้า: {user_msg}
Format: วิเคราะห์: ... ### คำตอบ: ... ### ประเภทงาน ### โอกาส(0-100) ### งบ"""

    # --- ลองใช้ Gemini (ตัวหลัก) ---
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-flash")
        res = model.generate_content(prompt)
        return res.text.strip()
    except Exception as e:
        # --- ถ้า Gemini ติดลิมิต (429) ให้สลับไป OpenThaiGPT ทันที ---
        if "429" in str(e):
            try:
                client = OpenAI(api_key=OPENTHAIGPT_CONFIG["api_key"], base_url=OPENTHAIGPT_CONFIG["base_url"])
                res = client.chat.completions.create(
                    model=OPENTHAIGPT_CONFIG["model"],
                    messages=[{"role": "user", "content": prompt}]
                )
                return "วิเคราะห์: (สลับใช้ OpenThaiGPT สำรอง) ### " + res.choices[0].message.content
            except:
                return "วิเคราะห์: AI พักเหนื่อยทั้งคู่ ### ขออภัยครับ ระบบหน่วงครู่หนึ่ง ### ยังไม่ชัดเจน ### 0 ### -"
        return f"วิเคราะห์: ระบบขัดข้อง ### ขออภัยครับ ({str(e)}) ### ยังไม่ชัดเจน ### 0 ### -"

# ================== 3. DATABASE & WEBHOOK ==================
# (ฟังก์ชัน init_db, get_facebook_profile, sync_chat_history, 
#  api_sync, get_contacts, get_messages, send_reply คงเดิมตามที่คุณสั่ง)

@app.route('/webhook', methods=['GET', 'POST'])
def webhook():
    if request.method == "GET": return request.args.get("hub.challenge") if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN else ("Failed", 403)
    data = request.json
    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            if "message" in event and "text" in event["message"]:
                msg, sid, pid = event["message"]["text"], str(event["sender"]["id"]), str(event["recipient"]["id"])
                with sqlite3.connect(DB_NAME) as conn:
                    # อัปเดตชื่อรูปโปรไฟล์
                    token = PAGE_TOKENS.get(pid, os.environ.get("FB_PAGE_ACCESS_TOKEN"))
                    r_prof = requests.get(f"https://graph.facebook.com/{sid}?fields=first_name,last_name,picture.type(large)&access_token={token}").json()
                    fn, ln, pic = r_prof.get('first_name', 'ลูกค้า'), r_prof.get('last_name', ''), r_prof.get('picture', {}).get('data', {}).get('url', '')
                    conn.execute("INSERT OR REPLACE INTO users (sender_id, first_name, last_name, profile_pic) VALUES (?, ?, ?, ?)", (sid, fn, ln, pic))
                    
                    # เรียก AI Expert (ตัวใหม่ที่มี Failover)
                    h = conn.execute("SELECT message FROM chats WHERE sender_id = ? ORDER BY id DESC LIMIT 5", (sid,)).fetchall()
                    ai = ask_ai_expert(msg, " | ".join([x[0] for x in h]))
                    p = ai.split('###')
                    if len(p) >= 5:
                        conn.execute("UPDATE users SET ai_tag = ?, ai_chance = ?, ai_budget = ? WHERE sender_id = ?", (p[2].strip(), p[3].strip(), p[4].strip(), sid))
                    
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, msg, 'user'))
                    conn.execute("INSERT INTO chats (sender_id, page_id, message, sender_type) VALUES (?, ?, ?, ?)", (sid, pid, ai, 'ai_suggestion'))
    return "OK", 200

# (Routes อื่นๆ คงเดิม)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
