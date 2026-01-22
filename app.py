from flask import Flask, request, jsonify
from flask_cors import CORS
from db import get_conn, release_conn
import os
import requests
from openai import OpenAI

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PAGE_TOKEN_MAP = {
    os.getenv("PAGE_ID_1"): os.getenv("PAGE_TOKEN_1"),
    os.getenv("PAGE_ID_2"): os.getenv("PAGE_TOKEN_2")
}


# -----------------------
# AI วิเคราะห์ intent
# -----------------------
def analyze_intent(text):

    prompt = f"""
คุณคือผู้ช่วยร้าน wedding planner

จำแนก intent ลูกค้าเป็น 1 คำจากนี้เท่านั้น:

- สนใจแพ็กเกจ
- ขอราคา
- ขอเบอร์ติดต่อ
- เช็คราคาสถานที่
- ยังดูเฉยๆ
- อื่นๆ

ข้อความ:
{text}

ตอบเป็นคำเดียวเท่านั้น
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0
    )

    return res.choices[0].message.content.strip()


# -----------------------
# Reply Messenger
# -----------------------
def reply(psid, page_id, text):

    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        return

    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={token}"

    requests.post(url, json={
        "recipient": {"id": psid},
        "message": {"text": text}
    })


# -----------------------
# Webhook verify
# -----------------------
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return request.args.get("hub.challenge")
    return "invalid", 403


# -----------------------
# Webhook receive
# -----------------------
@app.route("/webhook", methods=["POST"])
def webhook():

    data = request.json

    for entry in data.get("entry", []):
        page_id = entry.get("id")

        for m in entry.get("messaging", []):
            sender = m["sender"]["id"]
            text = m.get("message", {}).get("text")

            if not text:
                continue

            intent = analyze_intent(text)

            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                insert into customers
                (facebook_id, page_id, intent, last_message)
                values (%s,%s,%s,%s)
                on conflict (facebook_id)
                do update set
                    intent = excluded.intent,
                    last_message = excluded.last_message,
                    created_at = now()
            """, (sender, page_id, intent, text))

            conn.commit()
            cur.close()
            release_conn(conn)

            reply(
                sender,
                page_id,
                f"รับข้อความแล้วครับ ❤️\nสถานะ: {intent}"
            )

    return "ok", 200


# -----------------------
# Admin API
# -----------------------
@app.route("/api/customers")
def customers():

    page = int(request.args.get("page", 1))
    limit = 20
    offset = (page - 1) * limit

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        select
            id, facebook_id, page_id,
            intent, last_message, created_at
        from customers
        order by created_at desc
        limit %s offset %s
    """, (limit, offset))

    rows = cur.fetchall()
    cur.close()
    release_conn(conn)

    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "facebook_id": r[1],
            "page_id": r[2],
            "intent": r[3],
            "message": r[4],
            "created_at": r[5].isoformat()
        })

    return jsonify(data)


@app.route("/")
def home():
    return "MoS Wedding AI running"
