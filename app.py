from flask import Flask, request, jsonify
from flask_cors import CORS
from db import get_conn, release_conn
import os
import requests

app = Flask(__name__)
CORS(app)


@app.route("/")
def home():
    return "MoS Wedding API running"


# ------------------------
# Customers Pagination
# ------------------------
@app.route("/api/customers")
def customers():

    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    offset = (page - 1) * limit

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            facebook_id,
            name,
            phone,
            intent,
            budget,
            wedding_date,
            note,
            created_at
        FROM customers
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, (limit + 1, offset))

    rows = cur.fetchall()
    cur.close()
    release_conn(conn)

    has_more = len(rows) > limit
    rows = rows[:limit]

    data = []
    for r in rows:
        data.append({
            "id": r[0],
            "facebook_id": r[1],
            "name": r[2],
            "phone": r[3],
            "intent": r[4],
            "budget": r[5],
            "wedding_date": str(r[6]) if r[6] else None,
            "note": r[7],
            "created_at": r[8].isoformat()
        })

    return jsonify({
        "page": page,
        "limit": limit,
        "has_more": has_more,
        "data": data
    })


# ------------------------
# Messenger Webhook
# ------------------------

PAGE_TOKEN_MAP = {
    os.getenv("PAGE_ID_1"): os.getenv("PAGE_TOKEN_1"),
    os.getenv("PAGE_ID_2"): os.getenv("PAGE_TOKEN_2"),
}


def reply(psid, page_id, text):
    token = PAGE_TOKEN_MAP.get(page_id)
    if not token:
        return

    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={token}"

    requests.post(url, json={
        "recipient": {"id": psid},
        "message": {"text": text}
    })


@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == os.getenv("VERIFY_TOKEN"):
        return request.args.get("hub.challenge")
    return "Invalid token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    for entry in data.get("entry", []):
        page_id = entry.get("id")

        for msg in entry.get("messaging", []):
            sender = msg["sender"]["id"]
            text = msg.get("message", {}).get("text")

            if text:
                reply(sender, page_id, "ระบบได้รับข้อความแล้วครับ ❤️")

    return "ok", 200
