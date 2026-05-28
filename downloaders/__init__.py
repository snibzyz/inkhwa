"""Manhwa downloaders package.

แต่ละโมดูลใน package นี้ขึ้น class ที่สืบทอดจาก BaseDownloader
และลงทะเบียนเข้าไปใน REGISTRY ผ่าน @register_downloader decorator
"""
from .base import (
    BaseDownloader,
    ChromeManager,
    DownloaderContext,
    register_downloader,
    REGISTRY,
)

# import เพื่อ trigger การ register
from . import ridi          # noqa: F401
from . import lezhin        # noqa: F401
from . import toptoon       # noqa: F401
from . import kakao         # noqa: F401
from . import bomtoon       # noqa: F401


def get_downloader(name: str) -> BaseDownloader:
    if name not in REGISTRY:
        raise ValueError(f"ไม่รู้จักเว็บไซต์: {name}")
    return REGISTRY[name]()


def list_sites():
    return list(REGISTRY.keys())


__all__ = [
    "BaseDownloader",
    "ChromeManager",
    "DownloaderContext",
    "register_downloader",
    "REGISTRY",
    "get_downloader",
    "list_sites",
]
