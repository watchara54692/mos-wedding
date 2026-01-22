from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
import os
import requests
from datetime import datetime

# ===============================
# CONFIG
# ===============================

DATABASE_URL = os.getenv("DATABASE_URL")
PAGE_TOKEN = os.getenv("PAGE_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "moswedding")

app = Flask(__name__)
CORS(app)


# ===============================
# DATABASE
# ===============================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# ===============================
# STATIC HTML
# ===============================

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ===============================
# HEALTH CHECK
# ===============================

@app.route("/health")
def health():
    return "OK"


# ===============================
# FACEBOOK WEBHOOK
# ===============================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if token == VERIFY_TOKEN:
        return challenge
    return "Invalid token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):

            sender_id = event["sender"]["id"]

            if "message" in event and "text" in event["message"]:
                msg = event["message"]["text"]

                save_message(sender_id, msg)

    return "ok", 200


# ===============================
# SAVE MESSAGE
# ===============================

def save_message(sender_id, message):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages (
            sender_id,
            sender_type,
            message,
            created_at
        ) VALUES (%s, %s, %s, %s)
    """, (
        sender_id,
        "user",
        message,
        datetime.utcnow()
    ))

    conn.commit()
    cur.close()
    conn.close()


# ===============================
# API — CONTACT LIST
# ===============================

@app.route("/api/contacts")
def contacts():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT sender_id,
               MAX(message) AS message,
               MAX(created_at) AS last_time
        FROM messages
        GROUP BY sender_id
        ORDER BY last_time DESC
        LIMIT 50
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = []
    for r in rows:
        data.append({
            "sender_id": r[0],
            "first_name": "Facebook User",
            "profile_pic": "https://i.pravatar.cc/150?u=" + r[0],
            "message": r[1],
            "ai_tag": "new",
            "ai_chance": 30
        })

    return jsonify(data)


# ===============================
# API — MESSAGES
# ===============================

@app.route("/api/messages/<sid>")
def messages(sid):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT sender_type, message
        FROM messages
        WHERE sender_id=%s
        ORDER BY created_at ASC
        LIMIT 200
    """, (sid,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "sender_type": r[0],
            "message": r[1],
            "ai_tag": "lead",
            "ai_chance": 40,
            "ai_budget": "ไม่ระบุ"
        } for r in rows
    ])


# ===============================
# SEND MESSAGE BACK TO FB
# ===============================

@app.route("/api/send_reply", methods=["POST"])
def send_reply():
    data = request.json
    sid = data["sender_id"]
    msg = data["message"]

    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_TOKEN}"

    payload = {
        "recipient": {"id": sid},
        "message": {"text": msg}
    }

    requests.post(url, json=payload)

    save_admin_message(sid, msg)

    return jsonify({"status": "sent"})


def save_admin_message(sender_id, message):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages (
            sender_id,
            sender_type,
            message,
            created_at
        ) VALUES (%s, %s, %s, %s)
    """, (
        sender_id,
        "admin",
        message,
        datetime.utcnow()
    ))

    conn.commit()
    cur.close()
    conn.close()


# ===============================
# RUN LOCAL
# ===============================

if __name__ == "__main__":
    app.run(debug=True)
