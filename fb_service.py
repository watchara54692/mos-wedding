import requests
from config import PAGE_TOKENS
from db import get_db

GRAPH = "https://graph.facebook.com/v18.0"

def send_message(sender_id, page_id, text):
    token = PAGE_TOKENS.get(str(page_id))
    if not token:
        return False

    r = requests.post(
        f"{GRAPH}/me/messages?access_token={token}",
        json={
            "recipient":{"id":sender_id},
            "message":{"text":text}
        }
    )
    return r.status_code == 200


def save_message(sender_id, page_id, text, sender_type):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO chats(sender_id,page_id,message,sender_type) VALUES(?,?,?,?)",
            (sender_id,page_id,text,sender_type)
        )
        conn.execute(
            "INSERT OR IGNORE INTO users(sender_id) VALUES(?)",
            (sender_id,)
        )
