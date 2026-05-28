"""Auto-detect project paths — ใช้ในทุก script ของ project"""
import os
import sys

# project root = parent ของ app/ (ไม่ขึ้นกับ cwd)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROFILES_DIR = os.path.join(PROJECT_ROOT, "profiles")
DEFAULT_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "Downloads")
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")


def ensure_dirs():
    """สร้าง profiles/ และ Downloads/ ถ้ายังไม่มี"""
    os.makedirs(PROFILES_DIR, exist_ok=True)
    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)


def profile_path(name: str) -> str:
    """คืน path สำหรับ Chrome profile"""
    return os.path.join(PROFILES_DIR, name)
