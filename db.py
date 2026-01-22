import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL")

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
        name TEXT,
        phone TEXT,
        note TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    cur.close()
    release_conn(conn)
