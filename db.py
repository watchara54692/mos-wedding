import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL not set")

# =========================
# PostgreSQL connection pool
# =========================
pool = SimpleConnectionPool(
    minconn=1,
    maxconn=10,
    dsn=DATABASE_URL,
    sslmode="require"
)


def get_conn():
    return pool.getconn()


def release_conn(conn):
    pool.putconn(conn)


# =========================
# init database
# =========================
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id SERIAL PRIMARY KEY,
        facebook_id TEXT UNIQUE,
        name TEXT,
        phone TEXT,
        intent TEXT,
        last_message TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cur.execute("""
    CREATE INDEX IF NOT EXISTS idx_customers_created
    ON customers(created_at DESC);
    """)

    conn.commit()
    cur.close()
    release_conn(conn)
