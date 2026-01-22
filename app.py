from flask import Flask, request, jsonify
from flask_cors import CORS
from db import get_db

app = Flask(__name__)
CORS(app)


@app.route("/")
def home():
    return "MoS Wedding API running"


# -------------------------------
# GET messages (pagination)
# -------------------------------
@app.route("/api/messages", methods=["GET"])
def get_messages():
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))

    offset = (page - 1) * limit

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, sender, message, created_at
        FROM messages
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """,
        (limit + 1, offset)
    )

    rows = cur.fetchall()
    cur.close()
    conn.close()

    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [
        {
            "id": r[0],
            "sender": r[1],
            "message": r[2],
            "created_at": r[3].isoformat()
        }
        for r in rows
    ]

    return jsonify({
        "page": page,
        "limit": limit,
        "has_more": has_more,
        "data": data
    })


# -------------------------------
# POST new message
# -------------------------------
@app.route("/api/messages", methods=["POST"])
def create_message():
    payload = request.json

    sender = payload.get("sender")
    message = payload.get("message")

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO messages (sender, message)
        VALUES (%s, %s)
        """,
        (sender, message)
    )

    conn.commit()
    cur.close()
    conn.close()

    return jsonify({"status": "ok"})
