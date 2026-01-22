from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from db import get_conn
import csv, io

app = Flask(__name__, static_folder="static")
CORS(app)


@app.route("/")
def home():
    return send_from_directory("static", "index.html")


# =========================
# CONTACT LIST
# =========================
@app.route("/api/contacts")
def contacts():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        select sender_id, first_name, profile_pic,
               ai_tag, ai_chance, last_message
        from customers
        order by updated_at desc
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "sender_id": r[0],
            "first_name": r[1],
            "profile_pic": r[2],
            "ai_tag": r[3],
            "ai_chance": r[4],
            "message": r[5]
        } for r in rows
    ])


# =========================
# MESSAGE LIST
# =========================
@app.route("/api/messages/<sid>")
def messages(sid):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        select sender_type, message,
               coalesce(c.ai_tag,''),
               coalesce(c.ai_chance,0),
               coalesce(c.ai_budget,'-')
        from messages m
        left join customers c on c.sender_id=m.sender_id
        where m.sender_id=%s
        order by m.created_at
    """, (sid,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify([
        {
            "sender_type": r[0],
            "message": r[1],
            "ai_tag": r[2],
            "ai_chance": r[3],
            "ai_budget": r[4]
        } for r in rows
    ])


# =========================
# SEND REPLY
# =========================
@app.route("/api/send_reply", methods=["POST"])
def send_reply():
    data = request.json
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        insert into messages(sender_id, sender_type, message)
        values(%s,'admin',%s)
    """, (data["sender_id"], data["message"]))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "sent"})


# =========================
# AI TRAIN CSV
# =========================
@app.route("/api/train", methods=["POST"])
def train():
    f = request.files["file"]
    text = io.StringIO(f.stream.read().decode("utf-8"))
    reader = csv.DictReader(text)

    conn = get_conn()
    cur = conn.cursor()

    for r in reader:
        cur.execute("""
            insert into ai_training(keyword,analysis,option_1,option_2)
            values(%s,%s,%s,%s)
        """, (
            r["keyword"],
            r["analysis"],
            r["option_1"],
            r["option_2"]
        ))

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "success"})


# =========================
# SIMPLE AI ANALYSIS
# =========================
@app.route("/api/analyze_now/<sid>")
def analyze(sid):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        select message from messages
        where sender_id=%s
        order by created_at desc limit 1
    """, (sid,))
    msg = cur.fetchone()

    if not msg:
        return jsonify({"status": "no message"})

    text = msg[0].lower()

    cur.execute("select * from ai_training")
    rows = cur.fetchall()

    for r in rows:
        if r[1].lower() in text:
            ai_msg = f"{r[2]}###${r[3]}###${r[4]}"
            cur.execute("""
                insert into messages(sender_id,sender_type,message)
                values(%s,'ai_suggestion',%s)
            """, (sid, ai_msg))
            conn.commit()
            break

    cur.close()
    conn.close()
    return jsonify({"status": "ok"})


# =========================
# MESSENGER WEBHOOK
# =========================
@app.route("/webhook", methods=["GET","POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == "mos_wedding":
            return request.args.get("hub.challenge")
        return "invalid"

    data = request.json

    for e in data.get("entry", []):
        for m in e.get("messaging", []):
            sid = m["sender"]["id"]
            text = m.get("message", {}).get("text")

            if not text:
                continue

            conn = get_conn()
            cur = conn.cursor()

            cur.execute("""
                insert into customers(sender_id,last_message)
                values(%s,%s)
                on conflict(sender_id)
                do update set
                    last_message=excluded.last_message,
                    updated_at=now()
            """, (sid, text))

            cur.execute("""
                insert into messages(sender_id,sender_type,message)
                values(%s,'user',%s)
            """, (sid, text))

            conn.commit()
            cur.close()
            conn.close()

    return "ok"


if __name__ == "__main__":
    app.run()
