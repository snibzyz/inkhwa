"""Base downloader + Chrome manager (undetected-chromedriver).

ใช้เป็นฐานสำหรับ downloader ของแต่ละเว็บไซต์
"""
from __future__ import annotations

import os
import re
import time
import shutil
import requests
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

# undetected-chromedriver
try:
    import undetected_chromedriver as uc
    _UC_AVAILABLE = True
except Exception:
    _UC_AVAILABLE = False

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

# =========================================================================
# Registry
# =========================================================================
REGISTRY: dict[str, type["BaseDownloader"]] = {}


def register_downloader(cls):
    REGISTRY[cls.name] = cls
    return cls


# =========================================================================
# Context ที่ส่งให้ downloader (log/progress/cancel hooks)
# =========================================================================
@dataclass
class DownloaderContext:
    log: Callable[[str], None] = field(default=lambda m: print(m))
    progress: Callable[[int, int], None] = field(default=lambda c, t: None)
    is_running: Callable[[], bool] = field(default=lambda: True)


# =========================================================================
# Chrome Manager - undetected_chromedriver
# =========================================================================
class ChromeManager:
    """จัดการการเปิด Chrome ด้วย undetected-chromedriver พร้อม profile แยกตามเว็บ"""

    def __init__(
        self,
        profile_dir: str,
        log: Callable[[str], None] = print,
        headless: bool = False,
    ):
        self.profile_dir = os.path.abspath(profile_dir)
        self.log = log
        self.headless = headless
        self.driver = None

    def _detect_chrome_major(self) -> Optional[int]:
        """อ่าน Chrome major version จาก binary หรือ registry (Windows)"""
        # 1) จาก binary โดยตรง (PowerShell)
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
        ]
        for path in candidates:
            if os.path.exists(path):
                try:
                    import subprocess
                    out = subprocess.run(
                        ["powershell", "-NoProfile", "-Command",
                         f"(Get-Item '{path}').VersionInfo.ProductVersion"],
                        capture_output=True, text=True, timeout=5,
                    )
                    ver = (out.stdout or "").strip().split(".")[0]
                    if ver.isdigit():
                        return int(ver)
                except Exception:
                    pass
        return None

    def _build_options(self) -> "uc.ChromeOptions":
        options = uc.ChromeOptions()
        options.add_argument(f"--user-data-dir={self.profile_dir}")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-blink-features=AutomationControlled")
        # ช่วยเรื่องการดูด canvas/blob
        options.add_argument("--disable-web-security")
        options.add_argument("--disable-site-isolation-trials")
        options.add_argument("--allow-running-insecure-content")
        return options

    def launch(self, start_url: Optional[str] = None):
        if not _UC_AVAILABLE:
            raise RuntimeError(
                "ไม่พบ undetected-chromedriver — รันคำสั่ง:\n"
                "    pip install undetected-chromedriver"
            )

        self.log(f"🔧 กำลังเปิด Chrome (undetected) ...")
        if not os.path.exists(self.profile_dir):
            os.makedirs(self.profile_dir)
            self.log(f"📁 สร้าง Profile: {self.profile_dir}")

        version_main = self._detect_chrome_major()
        if version_main:
            self.log(f"🔎 ตรวจพบ Chrome version: {version_main}")

        try:
            self.driver = uc.Chrome(
                options=self._build_options(),
                headless=self.headless,
                use_subprocess=True,
                version_main=version_main,
            )
        except Exception as e:
            self.log(f"⚠️ เปิดด้วย undetected ครั้งแรกล้มเหลว ({e}) — ลองอีกครั้ง")
            # ใช้ options ใหม่ (uc ไม่ยอมให้ reuse)
            self.driver = uc.Chrome(
                options=self._build_options(),
                headless=self.headless,
                use_subprocess=True,
                version_main=version_main,
            )

        self.log("✅ เปิด Chrome สำเร็จ")

        if start_url:
            try:
                self.driver.get(start_url)
                self.log(f"🌐 เปิด URL: {start_url}")
            except Exception as e:
                self.log(f"⚠️ เปิด URL ไม่ได้: {e}")

        return self.driver

    def quit(self):
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None


# =========================================================================
# Helper
# =========================================================================
def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "", name).strip() or f"Untitled_{int(time.time())}"


def make_requests_session(driver) -> requests.Session:
    """สร้าง requests.Session ที่ inherit cookies + UA + Referer จาก driver"""
    session = requests.Session()
    try:
        cookies = driver.get_cookies()
        for c in cookies:
            try:
                session.cookies.set(c["name"], c["value"], domain=c.get("domain"))
            except Exception:
                session.cookies.set(c["name"], c["value"])
    except Exception:
        pass
    try:
        session.headers.update(
            {
                "User-Agent": driver.execute_script("return navigator.userAgent;"),
                "Referer": driver.current_url,
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            }
        )
    except Exception:
        pass
    return session


def guess_ext(url: str, default: str = ".jpg") -> str:
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return ext
    return default


def download_url_to(session: requests.Session, url: str, dest: str, timeout: int = 20) -> bool:
    try:
        r = session.get(url, stream=True, timeout=timeout)
        if r.status_code == 200:
            with open(dest, "wb") as f:
                shutil.copyfileobj(r.raw, f)
            return os.path.getsize(dest) > 0
        return False
    except Exception:
        return False


# =========================================================================
# Base Downloader
# =========================================================================
class BaseDownloader:
    """Interface สำหรับ downloader แต่ละเว็บ

    subclass ต้องตั้งค่า:
      - name        : ชื่อที่แสดงใน GUI
      - url         : หน้าแรกเริ่มต้น
      - profile_dir : โฟลเดอร์ Chrome profile
      - file_ext    : นามสกุลไฟล์ที่บันทึก (.jpg/.png/.webp)

    และ implement:
      - get_chapter_name(driver) -> str
      - download_chapter(driver, save_path, ctx) -> int   # คืน count
      - click_next(driver, ctx) -> bool
    """

    name: str = "Base"
    url: str = ""
    profile_dir: str = "Chrome_Profile"
    file_ext: str = ".jpg"

    # --------- ที่ต้อง override ---------
    def get_chapter_name(self, driver) -> str:
        return sanitize_filename(driver.title)

    def download_chapter(self, driver, save_path: str, ctx: DownloaderContext) -> int:
        raise NotImplementedError

    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        raise NotImplementedError

    # --------- optional override: auto-login ---------
    def login(self, driver, username: str, password: str, ctx: DownloaderContext) -> bool:
        """Default: ไม่ทำ auto-login (ผู้ใช้ login เองในหน้าต่าง browser)"""
        return True

    # --------- ลูปกลาง (เรียกจาก worker) ---------
    def run_loop(self, driver, base_save_path: str, ctx: DownloaderContext) -> None:
        last_folder = ""
        while ctx.is_running():
            chapter_name = self.get_chapter_name(driver)
            if chapter_name == last_folder:
                ctx.log(f"   ⚠️ ชื่อตอนซ้ำ ({chapter_name}) รอสักครู่...")
                time.sleep(2)
                chapter_name = self.get_chapter_name(driver)
                if chapter_name == last_folder:
                    ctx.log("   🛑 หน้าซ้ำเกินไป หรือจบเรื่อง")
                    break

            last_folder = chapter_name
            save_path = os.path.join(base_save_path, chapter_name)
            if not os.path.exists(save_path):
                os.makedirs(save_path)
                ctx.log(f"   📁 สร้างโฟลเดอร์: {save_path}")

            ctx.log(f"\n📘 --- กำลังโหลด: {chapter_name} ---")
            ctx.log(f"   💾 บันทึกที่: {save_path}")
            ctx.log(f"   🌐 URL: {driver.current_url}")

            try:
                saved = self.download_chapter(driver, save_path, ctx)
            except Exception as e:
                ctx.log(f"   ❌ โหลดล้มเหลว: {e}")
                saved = 0
            ctx.log(f"   📊 สรุป: {saved} ภาพ")

            if not ctx.is_running():
                break

            ctx.log("   - ▶️ กำลังไปตอนต่อไป...")
            current_url = driver.current_url
            try:
                ok = self.click_next(driver, ctx)
            except Exception as e:
                ctx.log(f"   ❌ คลิก Next ล้มเหลว: {e}")
                ok = False

            if not ok:
                ctx.log("\n🛑 หาปุ่มไปต่อไม่เจอ หรือจบเรื่องแล้ว")
                break

            try:
                WebDriverWait(driver, 15).until(EC.url_changes(current_url))
                ctx.log("   - 🔄 URL เปลี่ยนแล้ว รอโหลดเนื้อหา...")
                time.sleep(2)
            except TimeoutException:
                ctx.log("   ⚠️ URL ไม่เปลี่ยน (อาจเป็นตอนสุดท้าย หรือเน็ตหลุด)")
                break

        ctx.log("\n✅ จบการทำงาน")
