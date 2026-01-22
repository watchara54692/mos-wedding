import json, time
from openai import OpenAI
from config import GROQ_API_KEY
from db import get_db

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

def analyze_customer(sid, pid, msg, history):
    prompt = f"""
คุณคือ AI ฝ่ายขาย MoS Wedding
ตอบเป็น JSON เท่านั้น

รูปแบบ:
{{
 "keyword":"",
 "category":"",
 "budget":"ไม่ระบุ",
 "chance":0
}}

ประวัติแชท:
{history}

ข้อความล่าสุด:
{msg}
"""

    res = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role":"user","content":prompt}],
        response_format={"type":"json_object"}
    )

    ai = json.loads(res.choices[0].message.content)

    with get_db() as conn:
        know = conn.execute(
            "SELECT * FROM knowledge WHERE ? LIKE '%'||keyword||'%' LIMIT 1",
            (msg,)
        ).fetchone()

        analysis = know["analysis"] if know else "กำลังประเมินความต้องการลูกค้า..."
        o1 = know["option_1"] if know else "ขอทราบวันจัดงานเพื่อเช็คคิวครับ"
        o2 = know["option_2"] if know else "ต้องการให้เราประเมินงบให้ก่อนไหมครับ"

        conn.execute("""
        UPDATE users SET
            ai_tag=?,
            ai_budget=?,
            ai_chance=?,
            last_ai_check=CURRENT_TIMESTAMP
        WHERE sender_id=?
        """,(ai["category"],ai["budget"],ai["chance"],sid))

        content = f"{analysis} ### {o1} ### {o2} ### {ai['category']} ### {ai['budget']} ### {ai['chance']}"

        conn.execute(
            "INSERT INTO chats(sender_id,page_id,message,sender_type) VALUES(?,?,?,'ai_suggestion')",
            (sid,pid,content)
        )
