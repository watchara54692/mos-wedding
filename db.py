import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# รองรับทั้ง DATABASE_URL และ SUPABASE_DB_URL
DATABASE_URL = (
    os.getenv("DATABASE_URL")
    or os.getenv("SUPABASE_DB_URL")
)

if not DATABASE_URL:
    raise Exception("DATABASE_URL or SUPABASE_DB_URL not set")

pool = SimpleConnectionPool(
    minconn=1,
    maxconn=5,
    dsn=DATABASE_URL,
    sslmode="require"
)


def get_conn():
    return pool.getconn()


def release_conn(conn):
    pool.putconn(conn)


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
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    release_conn(conn)
