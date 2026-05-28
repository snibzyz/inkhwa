"""Login history — เก็บ user เคยใช้แล้ว (ไม่เก็บ password)

password ไม่ถูก save ใส่ใหม่ทุกครั้ง (security)
history เก็บที่ ~/.inkhwa/login_history.json (ไม่อยู่ใน repo)
"""
import json
import os

from .paths import PROJECT_ROOT

HISTORY_PATH = os.path.join(PROJECT_ROOT, ".login_history.json")


def load_history() -> list[str]:
    """คืน list ของ user/email ที่เคย login (เรียงล่าสุดก่อน)"""
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        users = data.get("users", [])
        return [u for u in users if isinstance(u, str)]
    except Exception:
        return []


def add_to_history(username: str) -> None:
    """เพิ่ม user ใน history (deduped + cap ที่ 5 อันล่าสุด)"""
    if not username or not username.strip():
        return
    username = username.strip()
    users = load_history()
    if username in users:
        users.remove(username)
    users.insert(0, username)
    users = users[:5]
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump({"users": users}, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# Backward compat: LOGIN_PRESETS ยังถูก import จากที่อื่น — คืน empty
LOGIN_PRESETS: dict[str, dict[str, str]] = {}
