import os
import json
import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from db import get_conn

app = Flask(__name__)
CORS(app)

PAGE_TOKEN = os.environ.get("PAGE_TOKEN")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")


# =========================
# Facebook verify webhook
# =========================
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


# =========================
# Receive message
# =========================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):

            sender_id = event["sender"]["id"]

            if "message" in event:
                text = event["message"].get("text", "")

                save_customer(sender_id, text)

                reply(sender_id, "ขอบคุณที่ติดต่อ Mos Wedding 💍\nทีมงานจะรีบตอบกลับค่ะ")

    return "ok", 200


# =========================
# Save to database
# =========================
def save_customer(facebook_id, text):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO customers (facebook_id, intent)
        VALUES (%s, %s)
        ON CONFLICT (facebook_id) DO NOTHING
    """, (facebook_id, text))

    conn.commit()
    cur.close()
    conn.close()


# =========================
# Send message back
# =========================
def reply(psid, text):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_TOKEN}"

    payload = {
        "recipient": {"id": psid},
        "message": {"text": text}
    }

    requests.post(url, json=payload)


# =========================
# Admin API
# =========================
@app.route("/api/customers")
def customers():
    page = int(request.args.get("page", 1))
    limit = 20
    offset = (page - 1) * limit

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, facebook_id, intent, created_at
        FROM customers
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, (limit + 1, offset))

    rows = cur.fetchall()

    has_more = len(rows) > limit
    rows = rows[:limit]

    cur.close()
    conn.close()

    return jsonify({
        "data": [
            {
                "id": r[0],
                "facebook_id": r[1],
                "intent": r[2],
                "created_at": r[3].isoformat()
            } for r in rows
        ],
        "page": page,
        "limit": limit,
        "has_more": has_more
    })


if __name__ == "__main__":
    app.run(debug=True)
