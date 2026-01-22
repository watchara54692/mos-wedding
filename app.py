from flask import Flask, request, jsonify
from flask_cors import CORS
from db import get_conn, release_conn, init_db

app = Flask(__name__)
CORS(app)

# init database once on startup
init_db()


@app.route("/")
def home():
    return "MoS Wedding API running"


# --------------------------------
# GET customers (pagination)
# --------------------------------
@app.route("/api/customers", methods=["GET"])
def get_customers():
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))

    offset = (page - 1) * limit

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, name, phone, note, created_at
        FROM customers
        ORDER BY id DESC
        LIMIT %s OFFSET %s
        """,
        (limit + 1, offset)
    )

    rows = cur.fetchall()

    cur.close()
    release_conn(conn)

    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [
        {
            "id": r[0],
            "name": r[1],
            "phone": r[2],
            "note": r[3],
            "created_at": r[4].isoformat()
        }
        for r in rows
    ]

    return jsonify({
        "page": page,
        "limit": limit,
        "has_more": has_more,
        "data": data
    })


# --------------------------------
# POST new customer
# --------------------------------
@app.route("/api/customers", methods=["POST"])
def create_customer():
    payload = request.json

    name = payload.get("name")
    phone = payload.get("phone")
    note = payload.get("note")

    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO customers (name, phone, note)
        VALUES (%s, %s, %s)
        """,
        (name, phone, note)
    )

    conn.commit()

    cur.close()
    release_conn(conn)

    return jsonify({"status": "ok"})
