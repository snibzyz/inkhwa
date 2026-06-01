"""Auto-detect project paths — ใช้ในทุก script ของ project"""
import os
import sys

# project root = parent ของ app/ (ไม่ขึ้นกับ cwd)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROFILES_DIR = os.path.join(PROJECT_ROOT, "profiles")
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Downloads")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

# Chrome profile เดียวใช้ร่วมกันทุกเว็บ — login ครั้งเดียวจำได้หมด ไม่ต้องแยก 4 โฟลเดอร์
SHARED_PROFILE_NAME = "Chrome_Shared"


def ensure_dirs():
    """สร้าง profiles/ และ Downloads/ ถ้ายังไม่มี"""
    os.makedirs(PROFILES_DIR, exist_ok=True)
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)


def profile_path(name: str) -> str:
    """คืน path สำหรับ Chrome profile"""
    return os.path.join(PROFILES_DIR, name)


def shared_profile_path() -> str:
    """Chrome profile กลางที่ทุกเว็บใช้ร่วมกัน (1 userdata for all)"""
    return os.path.join(PROFILES_DIR, SHARED_PROFILE_NAME)
