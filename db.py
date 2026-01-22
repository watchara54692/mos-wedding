import os
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require",
        cursor_factory=RealDictCursor
    )


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id SERIAL PRIMARY KEY,
            sender_id TEXT,
            page_id TEXT,
            message TEXT,
            sender_type TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            sender_id TEXT PRIMARY KEY,
            first_name TEXT,
            profile_pic TEXT,
            ai_tag TEXT DEFAULT 'ยังไม่ชัดเจน',
            ai_chance INTEGER DEFAULT 0,
            ai_budget TEXT DEFAULT 'ไม่ระบุ',
            last_active TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS knowledge (
            id SERIAL PRIMARY KEY,
            keyword TEXT,
            analysis TEXT,
            option_1 TEXT,
            option_2 TEXT
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
