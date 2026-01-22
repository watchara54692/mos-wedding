import os, json
from datetime import timedelta

DATABASE_URL = os.getenv("DATABASE_URL")

SECRET_KEY = os.environ.get("SECRET_KEY", "mos_secret")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "mos1234")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

FB_VERIFY_TOKEN = os.environ.get("FB_VERIFY_TOKEN")

PAGE_TOKENS = json.loads(os.environ.get("PAGE_TOKENS", "{}"))

DATABASE_PATH = os.environ.get("DATABASE_PATH", "mos_chat.db")

SESSION_LIFETIME = timedelta(days=365)
