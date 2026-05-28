"""Login presets — โครงเริ่มต้นเป็น empty

ถ้าต้องการเก็บ preset ส่วนตัว สร้างไฟล์ app/presets_local.py แบบนี้:

    LOGIN_PRESETS = {
        "myacct": {"user": "you@example.com", "password": "yourpw"},
    }

ไฟล์ presets_local.py อยู่ใน .gitignore (ไม่ถูก push ขึ้น git)
"""

LOGIN_PRESETS: dict[str, dict[str, str]] = {}

# โหลด preset ส่วนตัวจาก presets_local.py ถ้ามี
try:
    from .presets_local import LOGIN_PRESETS as _LOCAL  # type: ignore
    LOGIN_PRESETS = {**LOGIN_PRESETS, **_LOCAL}
except Exception:
    pass
