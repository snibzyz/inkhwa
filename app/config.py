"""จำค่าตั้งล่าสุด (last config) — เซฟตอนปิดแอป โหลดคืนตอนเปิด

เก็บที่ config.json (PROJECT_ROOT) — auto-updater ถนอมไฟล์นี้ไว้อยู่แล้ว
ไม่เก็บ password เด็ดขาด (security)
"""
from __future__ import annotations

import json

from .paths import CONFIG_PATH


def load_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
