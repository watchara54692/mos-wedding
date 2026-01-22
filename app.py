from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import psycopg2
from psycopg2.extras import RealDictCursor
import requests
import json

app = Flask(__name__)
CORS(app)

# ======================
# CONFIG
# ======================

DATABASE_URL = os.getenv("DATABASE_URL")

PAGE_TOKEN = os.getenv("PAGE_TOKEN")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "moswedding")

# ======================
# DATABASE
# ======================

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id SERIAL PRIMARY KEY,
        sender TEXT,
        message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()

# ======================
# ROOT + HTML
# ======================

@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ======================
# MESSENGER WEBHOOK
# ======================

@app.route("/webhook", methods=["GET"])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if token == VERIFY_TOKEN:
        return challenge
    return "Invalid token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    if "entry" not in data:
        return "ok"

    for entry in data["entry"]:
        for event in entry.get("messaging", []):
            sender_id = event["sender"]["id"]

            if "message" in event and "text" in event["message"]:
                text = event["message"]["text"]

                save_message(sender_id, text)
                send_message(sender_id, "รับข้อความแล้วครับ 🙏")

    return "ok"


def save_message(sender, text):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO messages (sender, message) VALUES (%s, %s)",
        (sender, text)
    )
    conn.commit()
    cur.close()
    conn.close()


def send_message(psid, text):
    url = f"https://graph.facebook.com/v18.0/me/messages?access_token={PAGE_TOKEN}"
    payload = {
        "recipient": {"id": psid},
        "message": {"text": text}
    }
    requests.post(url, json=payload)


# ======================
# API สำหรับ HTML
# ======================

@app.route("/api/contacts")
def contacts():
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT sender,
               MAX(created_at) AS last_time
        FROM messages
        GROUP BY sender
        ORDER BY last_time DESC
        LIMIT 50
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(rows)


@app.route("/api/messages/<sender>")
def messages(sender):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute("""
        SELECT sender, message, created_at
        FROM messages
        WHERE sender = %s
        ORDER BY created_at ASC
        LIMIT 200
    """, (sender,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify(rows)


# ======================
# START
# ======================

if __name__ == "__main__":
    app.run(debug=True)
