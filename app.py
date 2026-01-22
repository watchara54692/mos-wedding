from flask import Flask, request, jsonify
from flask_cors import CORS
from db import get_conn, release_conn, init_db

app = Flask(__name__)
CORS(app)


# -------------------------
# INIT DB (ตอน start server)
# -------------------------
init_db()


@app.route("/")
def health():
    return "MoS Wedding API running"


# -------------------------
# CREATE CUSTOMER
# -------------------------
@app.post("/customers")
def create_customer():
    data = request.json

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO customers (name, phone, note)
        VALUES (%s, %s, %s)
        RETURNING id
    """, (
        data.get("name"),
        data.get("phone"),
        data.get("note")
    ))

    customer_id = cur.fetchone()[0]
    conn.commit()

    cur.close()
    release_conn(conn)

    return jsonify({"id": customer_id})


# -------------------------
# PAGINATION
# -------------------------
@app.get("/customers")
def get_customers():
    limit = int(request.args.get("limit", 20))
    page = int(request.args.get("page", 1))
    offset = (page - 1) * limit

    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM customers")
    total = cur.fetchone()[0]

    cur.execute("""
        SELECT id, name, phone, note, created_at
        FROM customers
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """, (limit, offset))

    rows = cur.fetchall()

    cur.close()
    release_conn(conn)

    return jsonify({
        "data": [
            {
                "id": r[0],
                "name": r[1],
                "phone": r[2],
                "note": r[3],
                "created_at": r[4].isoformat()
            } for r in rows
        ],
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": (total + limit - 1) // limit
    })


# -------------------------
# SINGLE CUSTOMER
# -------------------------
@app.get("/customers/<int:id>")
def get_customer(id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT id, name, phone, note, created_at
        FROM customers WHERE id=%s
    """, (id,))

    r = cur.fetchone()

    cur.close()
    release_conn(conn)

    if not r:
        return jsonify({"error": "not found"}), 404

    return jsonify({
        "id": r[0],
        "name": r[1],
        "phone": r[2],
        "note": r[3],
        "created_at": r[4].isoformat()
    })


# -------------------------
# DELETE
# -------------------------
@app.delete("/customers/<int:id>")
def delete_customer(id):
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("DELETE FROM customers WHERE id=%s", (id,))
    conn.commit()

    cur.close()
    release_conn(conn)

    return jsonify({"status": "deleted"})
