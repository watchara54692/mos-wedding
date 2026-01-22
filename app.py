from flask import Flask, request, jsonify, render_template, redirect, session, url_for
from config import *
from db import init_db, get_db
from worker import run_bg
from ai_engine import analyze_customer
from fb_service import send_message, save_message
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = SESSION_LIFETIME

init_db()

# ---------- WEBHOOK ----------
@app.route("/webhook", methods=["GET","POST"])
def webhook():
    if request.method == "GET":
        if request.args.get("hub.verify_token") == FB_VERIFY_TOKEN:
            return request.args.get("hub.challenge")
        return "invalid"

    data = request.json
    for entry in data.get("entry",[]):
        pid = entry.get("id")
        for msg in entry.get("messaging",[]):
            if "message" in msg and "text" in msg["message"]:
                sid = msg["sender"]["id"]
                text = msg["message"]["text"]
                save_message(sid,pid,text,"user")
    return "ok"

# ---------- API ----------
@app.route("/api/analyze_now/<sid>")
def analyze_now(sid):
    with get_db() as conn:
        msgs = conn.execute("""
        SELECT message,sender_type FROM chats
        WHERE sender_id=?
        ORDER BY id DESC LIMIT 6
        """,(sid,)).fetchall()

        if not msgs: 
            return jsonify({"status":"no_data"})

        history = "\n".join(
            [f"{m['sender_type']}:{m['message']}" for m in reversed(msgs)]
        )

        last = msgs[0]["message"]
        pid = conn.execute(
            "SELECT page_id FROM chats WHERE sender_id=? ORDER BY id DESC LIMIT 1",
            (sid,)
        ).fetchone()["page_id"]

    run_bg(analyze_customer, sid, pid, last, history)
    return jsonify({"status":"processing"})

@app.route("/api/send_reply", methods=["POST"])
def reply():
    d = request.json
    ok = send_message(d["sender_id"], d["page_id"], d["message"])
    if ok:
        save_message(d["sender_id"], d["page_id"], d["message"], "admin")
        return jsonify({"status":"sent"})
    return jsonify({"status":"error"}),500

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST" and request.form["password"]==ADMIN_PASSWORD:
        session["logged_in"]=True
        return redirect("/")
    return render_template("login.html")

@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect("/login")
    return render_template("index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
