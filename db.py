import sqlite3
from config import DATABASE_PATH
import psycopg2
from psycopg2.extras import RealDictCursor
from config import DATABASE_URL

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )


def init_db():
    with get_db() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS chats(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id TEXT,
            page_id TEXT,
            message TEXT,
            sender_type TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS users(
            sender_id TEXT PRIMARY KEY,
            first_name TEXT,
            profile_pic TEXT,
            ai_tag TEXT DEFAULT 'ยังไม่ชัดเจน',
            ai_chance INTEGER DEFAULT 0,
            ai_budget TEXT DEFAULT 'ไม่ระบุ',
            last_ai_check DATETIME,
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS knowledge(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT,
            analysis TEXT,
            option_1 TEXT,
            option_2 TEXT
        )
        """)
