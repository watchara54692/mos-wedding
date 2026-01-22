import os
import json
import threading
import requests
import pandas as pd
from datetime import timedelta
from flask import Flask, request, render_template, jsonify, session, redirect, url_for
from openai import OpenAI

from db import get_db, init_db

# ================== APP ==================
app = Flask(__name__)
app.secret_key = "mos_wedding_v10_transparent"
app.permanent_session_lifetime = timedelta(days=365)

# ================== CONFIG ==================
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")
FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN", "moswedding1234")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

# ================== FACEBOOK PAGE TOKENS ==================
PAGE_TOKENS = {
    "336498580864850": os.environ.get("PAGE_TOKEN_1"),
    "106344620734603": os.environ.get("PAGE_TOKEN_2"),
}

# ================== INIT DB ==================
init_db()

# ================== DB HELPERS ==================
def fetchall(sql, params=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows

def fetchone(sql, params=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def execute(sql, params=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(sql, params or ())
    conn.commit()
    cur.close()
    conn.close()

# ================== RECOVERY ==================
def recover_fb_data():
    for pid, token in PAGE_TOKENS.items():
        if not token:
            continue

        try:
            r = requests.get(
                f"https://graph.facebook.com/v12.0/me/conversations",
                params={
                    "fields": "participants,updated_time,snippet",
                    "limit": 50,
                    "access_token": token
                }
            ).json()

            for conv in r.get("data", []):
                sid = next(
                    (p["id"] for p in conv["participants"]["data"] if p["id"] != pid),
                    None
                )

                if not sid:
                    continue

                execute("""
                    INSERT INTO users (sender_id, first_name, last_active)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (sender_id) DO NOTHING
                """, (sid, "กำลังซิงค์...", conv["updated_time"]))

                def sync_detail(uid=sid, conv_id=conv["id"], tk=token):
                    try:
                        profile = requests.get(
                            f"https://graph.facebook.com/{uid}",
                            params={
                                "fields": "first_name,picture.type(large)",
                                "access_token": tk
                            }
                        ).json()

                        msgs = requests.get(
                            f"https://graph.facebook.com/v12.0/{conv_id}/messages",
                            params={
                                "fields": "message,from,created_time",
                                "limit": 30,
                                "access_token": tk
                            }
                        ).json()

                        execute("""
                            UPDATE users
                            SET first_name=%s, profile_pic=%s
                            WHERE sender_id=%s
                        """, (
                            profile.get("first_name", "ลูกค้าเก่า"),
                            profile.get("picture", {}).get("data", {}).get("url", ""),
                            uid
                        ))

                        for m in reversed(msgs.get("data", [])):
                            sender_type = "user" if m["from"]["id"] == uid else "admin"
                            execute("""
                                INSERT INTO chats
                                (sender_id, page_id, message, sender_type, timestamp)
                                VALUES (%s,%s,%s,%s,%s)
                                ON CONFLICT DO NOTHING
                            """, (
                                uid, pid, m.get("message", ""),
                                sender_type, m["created_time"]
                            ))
                    except:
                        pass

                threading.Thread(target=sync_detail).start()

        except:
            pass

# ================== AI ANALYZER ==================
def analyze_for_closer(sid, pid, msg):
    try:
        client = OpenAI(
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1"
        )

        prompt = f"""
ตอบเป็น JSON เท่านั้น:
{{
 "keyword": "",
 "category": "",
 "budget": "",
 "chance": 0
}}

ข้อความลูกค้า:
{msg}
"""

        res = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        ai = json.loads(res.choices[0].message.content)

        know = fetchone(
            "SELECT * FROM knowledge WHERE %s ILIKE '%' || keyword || '%' LIMIT 1",
            (msg,)
        )

        analysis = know["analysis"] if know else "กำลังประเมินความต้องการลูกค้า..."
        opt1 = know["option_1"] if know else "ขอทราบวันและสถานที่จัดงานหน่อยครับ"
        opt2 = know["option_2"] if know else "ต้องการดูแนวตกแต่งเบื้องต้นไหมครับ"

        if ai.get("budget"):
            execute("UPDATE users SET ai_budget=%s WHERE sender_id=%s",
                    (ai["budget"], sid))

        if ai.get("category"):
            execute("UPDATE users SET ai_tag=%s WHERE sender_id=%s",
                    (ai["category"], sid))

        execute("""
            UPDATE users
            SET ai_chance=%s, last_active=NOW()
            WHERE sender_id=%s
        """, (ai.get("chance", 0), sid))

        content = f"{analysis} ### {opt1} ### {opt2}"

        execute("""
            INSERT INTO chats
            (sender_id, page_id, message, sender_type)
            VALUES (%s,%s,%s,'ai_suggestion')
        """, (sid, pid, content))

    except:
        pass

# ================== ROUTES ==================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session.permanent = True
            session["logged_in"] = True
            threading.Thread(target=recover_fb_data).start()
            return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    return render_template("index.html")


@app.route("/api/contacts")
def contacts():
    return jsonify(fetchall("""
        SELECT DISTINCT ON (u.sender_id)
        c.*, u.*
        FROM users u
        LEFT JOIN chats c ON u.sender_id = c.sender_id
        ORDER BY u.sender_id, c.timestamp DESC
    """))


@app.route("/api/messages/<sid>")
def messages(sid):
    return jsonify(fetchall("""
        SELECT c.*, u.*
        FROM chats c
        LEFT JOIN users u ON c.sender_id = u.sender_id
        WHERE c.sender_id=%s
        ORDER BY c.timestamp
    """, (sid,)))


@app.route("/api/analyze_now/<sid>")
def analyze_now(sid):
    row = fetchone("""
        SELECT page_id, message
        FROM chats
        WHERE sender_id=%s AND sender_type='user'
        ORDER BY timestamp DESC
        LIMIT 1
    """, (sid,))

    if row:
        threading.Thread(
            target=analyze_for_closer,
            args=(sid, row["page_id"], row["message"])
        ).start()
        return jsonify({"status": "processing"})

    return jsonify({"status": "no_data"})


@app.route("/api/train", methods=["POST"])
def train():
    file = request.files.get("file")
    if not file:
        return jsonify({"error": "no file"}), 400

    df = pd.read_csv(file)

    for _, r in df.iterrows():
        execute("""
            INSERT INTO knowledge (keyword, analysis, option_1, option_2)
            VALUES (%s,%s,%s,%s)
        """, (r.keyword, r.analysis, r.option_1, r.option_2))

    return jsonify({"status": "success"})


@app.route("/api/send_reply", methods=["POST"])
def send_reply():
    data = request.json
    sid = str(data["sender_id"])
    msg = data["message"]

    row = fetchone("""
        SELECT page_id FROM chats
        WHERE sender_id=%s
        ORDER BY timestamp DESC LIMIT 1
    """, (sid,))

    token = PAGE_TOKENS.get(str(row["page_id"]))

    r = requests.post(
        "https://graph.facebook.com/v12.0/me/messages",
        params={"access_token": token},
        json={"recipient": {"id": sid}, "message": {"text": msg}}
    )

    if r.status_code == 200:
        execute("""
            INSERT INTO chats (sender_id, message, sender_type)
            VALUES (%s,%s,'admin')
        """, (sid, msg))
        return jsonify({"status": "sent"})

    return jsonify({"status": "error"}), 500
