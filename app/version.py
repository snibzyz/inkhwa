"""เวอร์ชันของแอป + ข้อมูล repo สำหรับ auto-update"""
import os

from .paths import PROJECT_ROOT

# --- GitHub public repo (ใช้เช็ค/ดึงอัปเดต) ---
REPO_OWNER = "snibzyz"
REPO_NAME = "inkhwa"
REPO_BRANCH = "main"
REPO_URL = f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
# ไฟล์ VERSION บน repo (raw) — เทียบกับของเครื่องเพื่อรู้ว่ามีของใหม่ไหม
REMOTE_VERSION_URL = (
    f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{REPO_BRANCH}/VERSION"
)


def _read_version() -> str:
    """อ่านเวอร์ชันจากไฟล์ VERSION ที่ root ของโปรเจกต์"""
    path = os.path.join(PROJECT_ROOT, "VERSION")
    try:
        with open(path, "r", encoding="utf-8") as f:
            v = f.read().strip()
            return v or "0.0.0"
    except Exception:
        return "0.0.0"


__version__ = _read_version()
