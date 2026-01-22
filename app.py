from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
import psycopg2
import os

app = Flask(__name__, static_folder=".")
CORS(app)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_conn():
    return psycopg2.connect(DATABASE_URL, sslmode="require")


# ===============================
# ✅ SERVE HTML
# ===============================
@app.route("/")
def index():
    return send_from_directory(".", "index.html")


# ===============================
# ✅ CONTACT LIST
# ===============================
@app.route("/api/contacts")
def contacts():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            facebook_id,
            name,
            last_message,
            COALESCE(ai_chance, 0),
            COALESCE(ai_tag, 'new'),
            COALESCE(ai_budget, 'ไม่ระบุ')
        FROM customers
        ORDER BY updated_at DESC
        LIMIT 50
    """)

    rows = cur.fetchall()
    cur.close()
    conn.close()

    data = []
    for r in rows:
        data.append({
            "sender_id": r[0],
            "first_name": r[1],
            "profile_pic": "",
            "message": r[2],
            "ai_chance": r[3],
            "ai_tag": r[4],
            "ai_budget": r[5]
        })

    return jsonify(data)


# ===============================
# ✅ MESSAGE HISTORY
# ===============================
@app.route("/api/messages/<sid>")
def messages(sid):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT sender_type, message
        FROM messages
        WHERE sender_id = %s
        ORDER BY created_at ASC
    """, (sid,))

    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {"sender_type": r[0], "message": r[1]}
        for r in rows
    ])


# ===============================
# ✅ SEND MESSAGE
# ===============================
@app.route("/api/send_reply", methods=["POST"])
def send_reply():
    data = request.json
    sid = data.get("sender_id")
    msg = data.get("message")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages (sender_id, sender_type, message)
        VALUES (%s, 'admin', %s)
    """, (sid, msg))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "ok"})


# ===============================
# ✅ AI ANALYZE (mock)
# ===============================
@app.route("/api/analyze_now/<sid>")
def analyze(sid):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO messages (sender_id, sender_type, message)
        VALUES (
            %s,
            'ai_suggestion',
            'ลูกค้าสนใจงานแต่ง###ตอบสุภาพพร้อมราคา###ปิดการขายด้วยโปรโมชั่น'
        )
    """, (sid,))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "analyzed"})


# ===============================
# ✅ CSV TRAIN (dummy)
# ===============================
@app.route("/api/train", methods=["POST"])
def train():
    return jsonify({"status": "success"})
