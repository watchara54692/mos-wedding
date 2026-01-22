from flask import Flask, request, jsonify
from flask_cors import CORS
from db import get_conn, release_conn
import os

app = Flask(__name__)
CORS(app)

# ===============================
# HEALTH CHECK
# ===============================
@app.route("/")
def home():
    return "MoS Wedding API running"


# ===============================
# FACEBOOK WEBHOOK VERIFY
# ===============================
@app.route("/webhook", methods=["GET"])
def verify_webhook():
    VERIFY_TOKEN = os.getenv("VERIFY_TOKEN", "moswedding")

    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if token == VERIFY_TOKEN:
        return challenge
    return "Invalid token", 403


# ===============================
# RECEIVE MESSAGE FROM MESSENGER
# ===============================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    try:
        for entry in data.get("entry", []):
            for event in entry.get("messaging", []):

                sender_id = event["sender"]["id"]

                if "message" in event and "text" in event["message"]:
                    text = event["message"]["text"]

                    conn = get_conn()
                    cur = conn.cursor()

                    # save message
                    cur.execute("""
                        insert into messages (facebook_id, message, sender)
                        values (%s, %s, 'customer')
                    """, (sender_id, text))

                    # auto create customer if not exists
                    cur.execute("""
                        insert into customers (facebook_id)
                        values (%s)
                        on conflict (facebook_id) do nothing
                    """, (sender_id,))

                    conn.commit()
                    cur.close()
                    release_conn(conn)

    except Exception as e:
        print("WEBHOOK ERROR:", e)

    return "ok", 200


# ===============================
# PAGINATION API (FAST)
# ===============================
@app.route("/api/customers")
def customers():
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    offset = (page - 1) * limit

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        select id, facebook_id, name, phone, intent,
               budget, wedding_date, note, created_at
        from customers
        order by created_at desc
        limit %s offset %s
    """, (limit + 1, offset))

    rows = cur.fetchall()
    has_more = len(rows) > limit

    data = rows[:limit]

    cur.close()
    release_conn(conn)

    return jsonify({
        "page": page,
        "limit": limit,
        "has_more": has_more,
        "data": [
            {
                "id": r[0],
                "facebook_id": r[1],
                "name": r[2],
                "phone": r[3],
                "intent": r[4],
                "budget": r[5],
                "wedding_date": r[6],
                "note": r[7],
                "created_at": str(r[8])
            } for r in data
        ]
    })


# ===============================
# RUN
# ===============================
if __name__ == "__main__":
    app.run()
