from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3, requests, os, json
from datetime import datetime

app = Flask(__name__, static_folder='.')
CORS(app)

PAGE_TOKEN = os.getenv("PAGE_TOKEN", "")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "moswedding")

DB = "db.sqlite3"


# =========================
# DATABASE
# =========================

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    db = get_db()
    c = db.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS customers(
        sender_id TEXT PRIMARY KEY,
        first_name TEXT,
        profile_pic TEXT,
        ai_tag TEXT DEFAULT 'new',
        ai_chance INTEGER DEFAULT 0,
        ai_budget TEXT DEFAULT '-',
        updated_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender_id TEXT,
        sender_type TEXT,
        message TEXT,
        created_at TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS ai_training(
        keyword TEXT,
        analysis TEXT,
        option_1 TEXT,
        option_2 TEXT
    )
    """)

    db.commit()
    db.close()


init_db()

# =========================
# FRONTEND
# =========================

@app.route("/")
def home():
    return send_from_directory(".", "index.html")


# =========================
# FACEBOOK WEBHOOK
# =========================

@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "Invalid token", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    for entry in data.get("entry", []):
        for msg in entry.get("messaging", []):
            sender = msg["sender"]["id"]

            if "message" not in msg:
                continue

            text = msg["message"].get("text", "")

            db = get_db()
            c = db.cursor()

            c.execute("""
                INSERT OR IGNORE INTO customers
                (sender_id, updated_at)
                VALUES (?,?)
            """, (sender, now()))

            c.execute("""
                INSERT INTO messages
                (sender_id, sender_type, message, created_at)
                VALUES (?,?,?,?)
            """, (sender, "user", text, now()))

            db.commit()
            db.close()

    return "ok", 200


# =========================
# API
# =========================

@app.route("/api/contacts")
def contacts():
    db = get_db()
    rows = db.execute("""
        SELECT * FROM customers
        ORDER BY updated_at DESC
    """).fetchall()
    db.close()

    return jsonify([dict(r) for r in rows])


@app.route("/api/messages/<sid>")
def messages(sid):
    db = get_db()
    rows = db.execute("""
        SELECT * FROM messages
        WHERE sender_id=?
        ORDER BY id ASC
    """, (sid,)).fetchall()
    db.close()

    return jsonify([dict(r) for r in rows])


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

    db = get_db()
    db.execute("""
        INSERT INTO messages(sender_id,sender_type,message,created_at)
        VALUES (?,?,?,?)
    """, (sid, "admin", msg, now()))
    db.commit()
    db.close()

    return jsonify({"status": "sent"})


@app.route("/api/analyze_now/<sid>")
def analyze(sid):
    db = get_db()
    db.execute("""
        UPDATE customers
        SET ai_tag='hot',
            ai_chance=75,
            ai_budget='300k+',
            updated_at=?
        WHERE sender_id=?
    """, (now(), sid))
    db.commit()
    db.close()

    return jsonify({"status": "ok"})


@app.route("/api/train", methods=["POST"])
def train():
    import csv
    f = request.files["file"]
    rows = csv.reader(f.stream.read().decode("utf-8").splitlines())

    db = get_db()
    db.execute("DELETE FROM ai_training")

    for r in rows:
        if len(r) < 4:
            continue
        db.execute("""
            INSERT INTO ai_training VALUES (?,?,?,?)
        """, r)

    db.commit()
    db.close()

    return jsonify({"status": "success"})


# =========================

def now():
    return datetime.now().isoformat()


if __name__ == "__main__":
    app.run(debug=True)
