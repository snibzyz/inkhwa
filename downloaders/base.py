"""Base downloader + Chrome manager (undetected-chromedriver).

ใช้เป็นฐานสำหรับ downloader ของแต่ละเว็บไซต์
"""
from __future__ import annotations

import os
import re
import io
import time
import json
import base64
import shutil
import requests
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlparse

# ค่าที่ใช้บอกว่า "ตรวจสถานะ login ไม่ได้" (ต่างจาก True/False ที่ชัดเจน)
LOGIN_UNKNOWN = None

# ป้ายปุ่ม "เข้าสู่ระบบ" หลายภาษา (เจอ = ยังไม่ login)
LOGIN_LABELS = [
    "로그인", "로그인하기", "ログイン", "登录", "登入",
    "login", "log in", "sign in", "signin",
    "เข้าสู่ระบบ", "ล็อกอิน", "ล็อกอิน/สมัครสมาชิก",
]
# ป้ายที่จะโผล่ "เฉพาะตอน login แล้ว" (เจอ = login แล้ว)
# ใช้เฉพาะคำที่ "ชัดเจนว่า logout" เท่านั้น — ห้ามใส่คำเมนูทั่วไป (마이/마이페이지/보관함)
# เพราะคำพวกนั้นโผล่บนหน้า "ก่อน login" ได้ → จะทำให้เดาว่า login แล้วผิด ๆ แล้วข้าม gate
LOGGEDIN_LABELS = [
    "로그아웃", "로그 아웃", "ログアウト", "登出", "退出登录",
    "logout", "log out", "sign out", "signout",
    "ออกจากระบบ",
]

# JS ตรวจสถานะ login แบบ passive (ไม่เปลี่ยนหน้า) — คืน flags ให้ฝั่ง Python ตัดสิน
_LOGIN_DETECT_JS_TMPL = r"""
() => {
  const LOGIN = %s;
  const OUT = %s;
  const norm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  // ไม่ใช้ offsetParent (จะ null สำหรับ position:fixed → พลาด header แบบ fixed)
  const visible = el => {
    try {
      const r = el.getBoundingClientRect();
      if (!(r.width > 0 && r.height > 0)) return false;
      const cs = getComputedStyle(el);
      return cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0';
    } catch (e) { return false; }
  };
  // มีช่อง password ที่มองเห็น = อยู่บนฟอร์ม login
  const hasPassword = Array.from(document.querySelectorAll("input[type='password']"))
      .some(visible);
  let hasLogin = false, hasLogout = false;
  const nodes = document.querySelectorAll("a,button,[role='button'],span,div,li");
  for (const el of nodes) {
    if (!visible(el)) continue;
    const t = norm(el.textContent);
    if (!t || t.length > 24) continue;
    // ตรงตัวเป๊ะเท่านั้น (ทั้ง logout/login) — กัน substring ของคำสั้น ๆ ทำให้เดาผิด
    if (OUT.some(x => t === x)) hasLogout = true;
    if (LOGIN.some(x => t === x)) hasLogin = true;
    if (hasLogin && hasLogout) break;
  }
  return { hasPassword, hasLogin, hasLogout };
}
"""

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

    # --- การตั้งชื่อโฟลเดอร์ตอน ---
    # ถ้า folder_start != None → ตั้งชื่อโฟลเดอร์เป็นเลขลำดับเริ่มจากค่านี้ (เช่น 01, 02, ...)
    # ถ้า None → ใช้ชื่อจาก get_chapter_name() (ชื่อจากหน้าเว็บ) เหมือนเดิม
    folder_start: Optional[int] = None
    folder_pad: int = 2

    # --- hook ที่ถูกเรียกหลังโหลดแต่ละตอนเสร็จ (ใช้ทำ auto-merge) ---
    # รับ (save_path, saved_count)
    after_chapter: Callable[[str, int], None] = field(default=lambda p, n: None)


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

        # บางโปรไฟล์ตั้ง "เปิดแท็บเดิมต่อ" (session restore) → Chrome เปิดหลายแท็บ/
        # หน้าต่าง แล้ว get() อาจวิ่งไปคนละแท็บกับที่โชว์ ทำให้ค้างหน้า New Tab
        # จึงรวมให้เหลือแท็บเดียวก่อน แล้วค่อย navigate แบบตรวจสอบ+ลองซ้ำ
        self._consolidate_windows()

        if start_url:
            self._navigate(start_url)

        return self.driver

    def _consolidate_windows(self):
        """ปิดแท็บ/หน้าต่างที่ restore มา เหลือไว้แท็บเดียว แล้วโฟกัสที่แท็บนั้น"""
        try:
            handles = self.driver.window_handles
            if len(handles) > 1:
                self.log(f"   🧹 พบ {len(handles)} แท็บ (session restore) — ปิดเหลือแท็บเดียว")
                for h in handles[:-1]:
                    try:
                        self.driver.switch_to.window(h)
                        self.driver.close()
                    except Exception:
                        pass
            self.driver.switch_to.window(self.driver.window_handles[-1])
        except Exception:
            pass

    @staticmethod
    def _is_blank(url: str) -> bool:
        """หน้า 'ว่าง' ที่ยังไม่ได้ไปไหน (New Tab / about:blank / data:)"""
        low = (url or "").strip().lower()
        if not low:
            return True
        return (
            low.startswith("chrome://")
            or low.startswith("about:")
            or low.startswith("data:")
            or low.startswith("edge://")
            or "newtab" in low
        )

    def _navigate(self, url: str, attempts: int = 3):
        """เปิด URL แล้วตรวจว่าออกจากหน้า New Tab ไปหน้าเว็บจริง ถ้ายังค้างให้ลองซ้ำ

        ถือว่าสำเร็จเมื่อไม่ได้อยู่หน้า chrome://newtab / about:blank แล้ว
        (รองรับ SSO ที่ redirect ข้าม host เช่น Kakao ด้วย)
        """
        for i in range(attempts):
            try:
                self.driver.get(url)
            except Exception as e:
                self.log(f"⚠️ เปิด URL ไม่ได้ (ครั้งที่ {i+1}): {e}")
                time.sleep(0.5)
                self._consolidate_windows()
                continue
            # poll สั้น ๆ — คืนทันทีที่หน้าเว็บจริงโหลด (ไม่ sleep ยาวคงที่)
            cur = ""
            deadline = time.time() + 1.5
            while time.time() < deadline:
                try:
                    cur = self.driver.current_url or ""
                except Exception:
                    cur = ""
                if not self._is_blank(cur):
                    self.log(f"🌐 เปิด URL: {url}")
                    return
                time.sleep(0.15)
            # ยังค้างหน้า New Tab → get() อาจวิ่งคนละแท็บ ลองรวมแท็บแล้วทำซ้ำ
            self.log(f"   ↻ ยังค้างหน้าว่าง (อยู่ที่ {cur or 'ว่าง'}) ลองใหม่...")
            self._consolidate_windows()
        self.log(f"⚠️ เปิด URL ไม่สำเร็จหลังลอง {attempts} ครั้ง — โปรดเปิดหน้า login เองในหน้าต่าง Chrome")

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


def write_bytes_safe(
    fpath: str, data: bytes, log: Optional[Callable[[str], None]] = None
) -> bool:
    """เขียนไฟล์รูปแบบ 'ทนทาน' — กันโฟลเดอร์หายกลางคัน (ไดรฟ์ network/VHD/sync)

    ถ้าเขียนไม่ได้เพราะ parent dir หาย (No such file or directory) → สร้าง dir
    ใหม่แล้วลองอีกครั้ง (ทำซ้ำได้ไม่กี่รอบ). คืน True เมื่อเขียนสำเร็จ
    """
    last = None
    for _ in range(3):
        try:
            with open(fpath, "wb") as f:
                f.write(data)
            return True
        except OSError as e:
            last = e
            try:
                os.makedirs(os.path.dirname(fpath) or ".", exist_ok=True)
            except Exception:
                pass
        except Exception as e:
            last = e
            break
    if log:
        log(f"      ❌ เขียนไฟล์ไม่ได้: {os.path.basename(fpath)} ({last})")
    return False


def download_url_to(session: requests.Session, url: str, dest: str, timeout: int = 20) -> bool:
    try:
        r = session.get(url, stream=True, timeout=timeout)
        if r.status_code == 200:
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as f:
                shutil.copyfileobj(r.raw, f)
            return os.path.getsize(dest) > 0
        return False
    except Exception:
        return False


def image_is_complete(path: str) -> bool:
    """ตรวจ 'ท้ายไฟล์ภาพ' ว่าโหลดมาครบจริงไหม (กันภาพขาดครึ่งตอนเน็ตช้า/หลุด)

    JPEG ต้องลงท้าย FFD9, PNG ต้องมี IEND, GIF ลงท้าย 0x3B
    ชนิดที่ตรวจไม่เป็น (เช่น WebP) → ถือว่าผ่านถ้ามีขนาดพอควร (ไม่ฟันธงว่าเสีย)
    """
    try:
        size = os.path.getsize(path)
        if size < 100:
            return False
        with open(path, "rb") as f:
            head = f.read(8)
            f.seek(-16, os.SEEK_END)
            tail = f.read(16)
        if head[:2] == b"\xff\xd8":                         # JPEG
            return tail.rstrip(b"\x00")[-2:] == b"\xff\xd9"
        if head[:8] == b"\x89PNG\r\n\x1a\n":                 # PNG
            return b"IEND" in tail
        if head[:3] == b"GIF":                               # GIF
            return tail.rstrip(b"\x00")[-1:] == b"\x3b"
        return True                                          # WebP/อื่น ๆ — ตรวจไม่เป็น
    except Exception:
        return True


def download_url_verified(
    session: requests.Session,
    url: str,
    dest: str,
    timeout: int = 30,
    retries: int = 3,
    log: Optional[Callable[[str], None]] = None,
) -> bool:
    """ดาวน์โหลดรูป + 'ยืนยันว่าได้ครบ' (เทียบ Content-Length + ตรวจท้ายไฟล์)

    ถ้าไม่ครบ/พังกลางคัน จะลบไฟล์เสียทิ้งแล้วลองใหม่ (เน็ตช้าได้บ่อย)
    คืน True เฉพาะเมื่อได้ไฟล์ภาพครบสมบูรณ์จริง ๆ เท่านั้น
    """
    last_err = ""
    for attempt in range(1, retries + 1):
        try:
            r = session.get(url, stream=True, timeout=timeout)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
            else:
                clen = r.headers.get("Content-Length")
                expected = int(clen) if (clen and clen.isdigit()) else None
                written = 0
                os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)  # กันโฟลเดอร์หาย
                with open(dest, "wb") as f:
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            written += len(chunk)
                if written == 0:
                    last_err = "ได้ 0 ไบต์"
                elif expected is not None and written < expected:
                    last_err = f"ไม่ครบ {written}/{expected}B"
                elif not image_is_complete(dest):
                    last_err = "ภาพไม่สมบูรณ์ (ขาดท้ายไฟล์)"
                else:
                    return True
        except Exception as e:
            last_err = str(e)
        if log and attempt < retries:
            log(f"      ↻ โหลดไม่ครบ ลองใหม่ ({attempt}/{retries}) — {last_err}")
        time.sleep(min(3.0, 0.8 * attempt))
    # ลบไฟล์เสียทิ้ง กันเข้าใจผิดว่าโหลดสำเร็จ (มี size > 0 แต่ภาพขาด)
    try:
        if os.path.exists(dest):
            os.remove(dest)
    except Exception:
        pass
    if log:
        log(f"      ❌ โหลดไม่สำเร็จหลังลอง {retries} ครั้ง — {last_err}")
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

    # หน้าที่ควรเปิดให้ผู้ใช้ login (default = หน้าแรกของเว็บ)
    # subclass ที่มีหน้า login เฉพาะให้ override เป็น URL หน้า login ตรง ๆ
    login_url: str = ""

    # ชื่อ cookie ที่จะมี "หลัง login" (ใช้เป็นสัญญาณ login แล้วแบบ positive)
    login_cookies: tuple[str, ...] = ()
    # ป้ายเพิ่มเติมเฉพาะเว็บ (เสริมจากค่ากลาง) — login button / logged-in marker
    extra_login_labels: tuple[str, ...] = ()
    extra_loggedin_labels: tuple[str, ...] = ()

    # --------- ที่ต้อง override ---------
    def get_chapter_name(self, driver) -> str:
        return sanitize_filename(driver.title)

    def download_chapter(self, driver, save_path: str, ctx: DownloaderContext) -> int:
        raise NotImplementedError

    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        raise NotImplementedError

    # --------- หน้า login ที่ควรเปิดให้ผู้ใช้ ---------
    def get_login_url(self) -> str:
        """URL ที่จะเปิดให้ผู้ใช้ login (default = หน้าแรกของเว็บ)"""
        return self.login_url or self.url

    # --------- ตรวจว่า URL นี้เป็น "หน้าอ่าน/ตอน" หรือไม่ ---------
    def is_chapter_url(self, url: str) -> bool:
        """หน้านี้เป็นหน้าอ่าน/ตอน ที่เริ่มดาวน์โหลดได้เลยไหม

        ใช้หลัง login: ถ้า user ไม่ได้กรอก URL ตอนแรก แต่หน้าที่เปิดอยู่
        เป็นหน้าอ่านอยู่แล้ว → เริ่มจากนี่ได้เลย ไม่ต้องถาม
        ถ้าไม่ใช่ (เช่นหน้า main/home/login) → worker จะถาม URL จากผู้ใช้

        default: เดาจาก keyword ใน path (subclass override ได้ถ้ามี pattern เฉพาะ)
        """
        low = (url or "").lower()
        if not low:
            return False
        # หน้าที่ "ไม่ใช่หน้าอ่าน" แน่ ๆ
        if any(k in low for k in (
            "/login", "/account", "/main", "/home", "/ranking",
            "/genre", "/search", "/event", "/notice",
        )):
            return False
        # คำที่บ่งว่าเป็นหน้าอ่าน/ตอน
        return any(k in low for k in (
            "/viewer", "/episode", "/chapter", "/ep/", "/content",
        ))

    # --------- optional override: auto-login ---------
    def login(self, driver, username: str, password: str, ctx: DownloaderContext) -> bool:
        """Default: ไม่ทำ auto-login (ผู้ใช้ login เองในหน้าต่าง browser)"""
        return True

    # --------- ตรวจสถานะ login (generic — ทุกเว็บใช้ได้) ---------
    def _login_cookie_present(self, driver) -> bool:
        if not self.login_cookies:
            return False
        try:
            names = {c.get("name") for c in driver.get_cookies() if c.get("value")}
            return any(n in names for n in self.login_cookies)
        except Exception:
            return False

    def _detect_login_flags(self, driver) -> Optional[dict]:
        """รัน JS ตรวจ flags: hasPassword / hasLogin / hasLogout"""
        login_labels = [s.lower() for s in (list(LOGIN_LABELS) + list(self.extra_login_labels))]
        out_labels = [s.lower() for s in (list(LOGGEDIN_LABELS) + list(self.extra_loggedin_labels))]
        js = _LOGIN_DETECT_JS_TMPL % (json.dumps(login_labels), json.dumps(out_labels))
        try:
            return driver.execute_script("return (" + js + ")();")
        except Exception:
            return None

    def is_logged_in(self, driver) -> Optional[bool]:
        """ตรวจว่า login แล้วหรือยัง (passive — ไม่เปลี่ยนหน้า)

        คืน:
          True  = login แล้วแน่นอน
          False = ยังไม่ login แน่นอน
          None  = ตรวจไม่ได้ (ให้ worker รอผู้ใช้กด OK เอง)

        หลักการ (เรียงตามความน่าเชื่อถือ):
          1) มี cookie login → True
          2) มีช่อง password โผล่ → False (อยู่บนฟอร์ม login)
          3) เจอปุ่ม logout/มายเพจ และไม่เจอปุ่ม login → True
          4) เจอปุ่ม login และไม่เจอ logout → False
          5) อื่น ๆ → None
        """
        if self._login_cookie_present(driver):
            return True
        flags = self._detect_login_flags(driver)
        if not flags:
            # JS ใช้ไม่ได้ — ลองดูจาก host ของหน้า login เป็นทางสุดท้าย
            # เทียบ host (ไม่ใช่ substring) เพราะ SSO เช่น Kakao จะ rewrite query
            try:
                lu = self.get_login_url()
                if lu:
                    cur_host = urlparse(driver.current_url or "").netloc
                    if cur_host and cur_host == urlparse(lu).netloc:
                        return False
            except Exception:
                pass
            return LOGIN_UNKNOWN
        if flags.get("hasPassword"):
            return False
        has_login = bool(flags.get("hasLogin"))
        has_logout = bool(flags.get("hasLogout"))
        if has_logout and not has_login:
            return True
        if has_login and not has_logout:
            return False
        return LOGIN_UNKNOWN

    # --------- ยืนยันภาพโหลดครบ (shared — เว็บแบบ canvas/blob ใช้ร่วมกัน) ---------
    # JS: รับ list<img> แล้วคืน array ว่าแต่ละใบ 'โหลดเสร็จจริง' ไหม
    # (complete && naturalWidth>0 = ภาพถูก decode เต็มใบแล้ว วาดลง canvas ได้ครบ)
    _IMG_READY_STATES_JS = r"""
const imgs = arguments[0] || [];
return imgs.map(i => {
  try { return !!(i && i.complete && i.naturalWidth > 0); }
  catch (e) { return false; }
});
"""

    @staticmethod
    def _img_ready_states(driver, images):
        """คืน list<bool> สถานะโหลดเสร็จของแต่ละ img — None ถ้า element หลุด (stale)"""
        if not images:
            return []
        try:
            return driver.execute_script(BaseDownloader._IMG_READY_STATES_JS, images)
        except Exception:
            return None

    def wait_images_loaded(
        self,
        driver,
        ctx: "DownloaderContext",
        collect,
        *,
        min_count: int = 1,
        overall_timeout: float = 180.0,
        zero_grace: float = 12.0,
    ):
        """รอ + ยืนยันว่า <img> การ์ตูน 'โหลดครบทุกใบ' ก่อนเริ่มดูด (กันเน็ตช้า)

        เน็ตช้าทำให้ <img> บางใบยังโหลดไม่เสร็จ (naturalWidth=0) → ถ้าดูดเลยจะ
        ได้ภาพไม่ครบ/canvas เปล่า บางเว็บยังถูกกรองทิ้งตอน 'นับ' ด้วย จึงต้องรอ
        ให้ครบก่อน

        collect: callable(driver) -> list<WebElement>  (รูปการ์ตูนล่าสุดบนหน้า)
        เงื่อนไข 'ครบ' = จำนวนรูปนิ่ง (lazy ไม่เพิ่มแล้ว) + ทุกใบโหลดเสร็จ
        คืน list<WebElement> ล่าสุด (เอาไปดูดต่อได้เลย) — [] ถ้าไม่เจอรูปเลย
        """
        deadline = time.time() + overall_timeout
        zero_deadline = time.time() + zero_grace
        prev_total = -1
        stable = 0
        last: list = []
        while time.time() < deadline:
            if not ctx.is_running():
                break
            images = collect(driver) or []
            last = images
            total = len(images)
            if total == 0:
                # ยังไม่เจอรูปเลย — ให้เวลา grace แล้วเลื่อนปลุก lazy load
                if time.time() > zero_deadline:
                    return []
                try:
                    driver.execute_script(
                        "window.scrollBy(0, Math.max(800, window.innerHeight));"
                    )
                except Exception:
                    pass
                time.sleep(1.0)
                continue
            states = self._img_ready_states(driver, images)
            if states is None:          # element หลุด (stale) → ลองใหม่
                time.sleep(0.5)
                continue
            ready = sum(1 for s in states if s)
            ctx.progress(ready, total)
            not_ready = [i for i, ok in enumerate(states) if not ok]
            # ครบเมื่อ: ทุกใบโหลดเสร็จ + จำนวนนิ่งเท่ารอบก่อน (ยืนยัน 2 รอบกัน lazy เพิ่ม)
            if not not_ready and total == prev_total and total >= min_count:
                stable += 1
                if stable >= 2:
                    ctx.log(f"   - ✅ ยืนยันภาพครบ: {ready}/{total} ใบ พร้อมดูด")
                    return images
            else:
                stable = 0
            prev_total = total
            if not_ready:
                ctx.log(f"   - ⏳ รอภาพโหลด: พร้อม {ready}/{total} (เหลือ {len(not_ready)})")
                # กระตุ้นโหลดรูปที่ยังไม่เสร็จ: เลื่อนไปหาทีละใบ
                for idx in not_ready[:16]:
                    try:
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block:'center'});",
                            images[idx],
                        )
                        time.sleep(0.1)
                    except Exception:
                        pass
            else:
                # โหลดครบที่เห็น แต่จำนวนยังไม่นิ่ง → เลื่อนลงหารูปเพิ่ม
                try:
                    driver.execute_script(
                        "window.scrollBy(0, Math.max(800, window.innerHeight));"
                    )
                except Exception:
                    pass
            time.sleep(1.0)
        # หมดเวลา — ดูดเท่าที่พร้อม + แจ้งเตือนชัด ๆ ว่าอาจไม่ครบ
        states = self._img_ready_states(driver, last) or []
        ready = sum(1 for s in states if s)
        ctx.log(
            f"   - ⚠️ โหลดไม่ครบในเวลาที่กำหนด: พร้อม {ready}/{len(last)} ใบ "
            f"(เน็ตช้า) — จะดูดเท่าที่พร้อม"
        )
        return last

    def wait_count_stable(
        self,
        driver,
        ctx: "DownloaderContext",
        collect,
        *,
        label: str = "รูป",
        min_count: int = 1,
        overall_timeout: float = 120.0,
        zero_grace: float = 12.0,
        stable_rounds: int = 3,
    ):
        """เลื่อนหน้าโหลด lazy + รอจน 'จำนวนที่เจอนิ่ง' (lazy โหลดมาครบไม่เพิ่มแล้ว)

        ใช้กับเว็บที่นับจาก element/URL ใน DOM (ไม่ใช่ canvas) เช่น Kakao/Toptoon/
        Lezhin — กันเน็ตช้าแล้วเก็บ <img> มาไม่ครบเพราะ lazy ยังโหลดไม่หมด
        คืน list ล่าสุดที่ collect ได้
        """
        deadline = time.time() + overall_timeout
        zero_deadline = time.time() + zero_grace
        prev = -1
        stable = 0
        last: list = []
        while time.time() < deadline:
            if not ctx.is_running():
                break
            items = collect(driver) or []
            last = items
            n = len(items)
            if n == 0 and time.time() > zero_deadline:
                return []
            if n >= min_count and n == prev:
                stable += 1
                if stable >= stable_rounds:
                    ctx.log(f"   - ✅ จำนวน{label}นิ่งแล้ว (โหลดครบ): {n}")
                    return items
            else:
                stable = 0
                if n != prev and n > 0:
                    ctx.log(f"   - ⏳ กำลังโหลด{label}... พบ {n} (รอให้นิ่ง)")
            prev = n
            try:
                driver.execute_script(
                    "window.scrollBy(0, Math.max(1000, window.innerHeight));"
                )
            except Exception:
                pass
            time.sleep(0.8)
        ctx.log(f"   - ⚠️ จำนวน{label}อาจยังไม่ครบ (เน็ตช้า): {len(last)}")
        return last

    # =====================================================================
    # Engine กลางสำหรับ "ดูดภาพให้ครบ" (ใช้ร่วมกันทุกเว็บ)
    # =====================================================================
    @staticmethod
    def verify_image_bytes(raw: bytes, *, to_jpeg: bool = True, check_blank: bool = True):
        """ยืนยันภาพ 'ไม่ขาด/ไม่เปล่า' ด้วย PIL — คืน bytes (อาจแปลง JPEG) หรือ None

        - เปิด + load() = บังคับ decode (ภาพขาด/เสียจะ error ตรงนี้)
        - check_blank: สีเดียวทั้งใบ = ดูดไม่ติด → None (ใช้กับ canvas)
        - to_jpeg=True คืน JPEG (ของเดิมถ้าเป็น JPEG/RGB อยู่แล้ว ไม่ re-encode)
          to_jpeg=False คืน bytes เดิม (เก็บ PNG/format เดิม)
        """
        if not raw or len(raw) < 100:
            return None
        try:
            from PIL import Image
        except Exception:
            # ไม่มี PIL: เชื่อ raw ถ้าเป็น JPEG/PNG
            if raw[:2] == b"\xff\xd8" or raw[:8] == b"\x89PNG\r\n\x1a\n":
                return raw
            return None
        try:
            im = Image.open(io.BytesIO(raw))
            im.load()
        except Exception:
            return None
        if check_blank:
            try:
                ex = im.convert("RGB").getextrema()
                if all(lo == hi for (lo, hi) in ex):
                    return None
            except Exception:
                pass
        if not to_jpeg:
            return raw
        if im.format == "JPEG" and im.mode == "RGB":
            return raw
        try:
            buf = io.BytesIO()
            (im if im.mode == "RGB" else im.convert("RGB")).save(buf, "JPEG", quality=95)
            return buf.getvalue()
        except Exception:
            return None

    # JS: ดูด "รูป blob ที่ยังไม่เคยเก็บ" รอบละไม่เกิน maxBatch ใบ (%s = body ของ isComic)
    #  fetch(blobURL) เอา bytes ต้นฉบับ → ไม่มี canvas เปล่า ไม่เสียคุณภาพ; canvas = fallback
    _BLOB_BATCH_JS_TMPL = r"""
const seenUrls = arguments[0];
const maxBatch = arguments[1];
const done = arguments[arguments.length - 1];
(async () => {
  const seen = new Set(seenUrls);
  const isComic = (img) => { %s };
  const imgs = Array.from(document.querySelectorAll('img')).filter(isComic);
  const out = [];
  try {
    for (const img of imgs) {
      const url = img.currentSrc || img.src;
      if (!url || seen.has(url)) continue;
      const rect = img.getBoundingClientRect();
      const rec = { url, y: Math.round(rect.top + window.scrollY) };
      if (url.slice(0, 5) !== 'data:') {
        try {
          const resp = await fetch(url, { cache: 'force-cache' });
          if (resp.ok) {
            const blob = await resp.blob();
            if (blob && blob.size > 0) {
              rec.dataUrl = await new Promise((res, rej) => {
                const r = new FileReader();
                r.onload = () => res(r.result); r.onerror = () => rej(new Error('reader'));
                r.readAsDataURL(blob);
              });
              rec.via = 'fetch'; rec.size = blob.size;
            }
          } else { rec.fetchErr = 'http ' + resp.status; }
        } catch (e) { rec.fetchErr = String(e); }
      }
      if (!rec.dataUrl) {
        try { await img.decode(); } catch (e) {}
        if (img.complete && img.naturalWidth > 0) {
          const c = document.createElement('canvas');
          c.width = img.naturalWidth; c.height = img.naturalHeight;
          c.getContext('2d').drawImage(img, 0, 0);
          rec.dataUrl = c.toDataURL('image/jpeg', 0.95); rec.via = 'canvas';
        }
      }
      out.push(rec);
      if (out.length >= maxBatch) break;
    }
  } catch (e) {}
  done(out);
})();
"""

    def scroll_and_capture_blobs(
        self, driver, ctx: "DownloaderContext", filter_js: str,
        *, to_jpeg: bool = True, max_batch: int = 8,
    ) -> dict:
        """เลื่อนบน→ล่าง + fetch ดูดรูป blob ที่ "ยังไม่เคยเก็บ" (dedup) — engine กลาง

        ใช้กับเว็บที่หน้าการ์ตูนเป็น <img> (blob:/http) เช่น Bomtoon/Ridi:
        วนเลื่อน+เก็บเพิ่มจน "ถึงล่าง + ไม่มีใหม่ 5 รอบ" → ครบแน่นอนแม้จำนวนที่โหลด
        ณ ขณะหนึ่งจะแกว่ง. filter_js = body ของ isComic(img) (JS, return true/false)
        คืน dict: url -> (y, bytes)  เรียงด้วย y ได้เป็นลำดับการอ่าน
        """
        js = self._BLOB_BATCH_JS_TMPL % filter_js
        captured: dict = {}
        try:
            driver.execute_script("window.scrollTo(0,0);")
        except Exception:
            pass
        time.sleep(0.4)
        no_new = 0
        y = 0
        for _ in range(600):          # safety cap
            if not ctx.is_running():
                break
            try:
                driver.set_script_timeout(45)
                batch = driver.execute_async_script(js, list(captured.keys()), max_batch)
            except Exception as e:
                ctx.log(f"   ⚠️ ดูดรอบนี้ error: {e}")
                batch = []
            got = 0
            for rec in batch or []:
                if not isinstance(rec, dict):
                    continue
                url = rec.get("url")
                data_url = rec.get("dataUrl") or ""
                if not url or "base64," not in data_url:
                    continue
                try:
                    raw = base64.b64decode(data_url.split("base64,", 1)[1])
                except Exception:
                    continue
                out = self.verify_image_bytes(
                    raw, to_jpeg=to_jpeg, check_blank=(rec.get("via") == "canvas")
                )
                if out is None:
                    continue          # เปล่า/ขาด → รอบหน้าลองใหม่
                if url not in captured:
                    got += 1
                captured[url] = (rec.get("y", 0), out)
            if got:
                ctx.progress(len(captured), len(captured))
                ctx.log(f"   - 📥 ดูดแล้ว {len(captured)} ใบ...")
            no_new = 0 if got else no_new + 1
            try:
                at_bottom = bool(driver.execute_script(
                    "return (window.scrollY + window.innerHeight) >= "
                    "(document.body.scrollHeight - 4);"
                ))
            except Exception:
                at_bottom = True
            if at_bottom and no_new >= 5 and captured:
                break
            y += 1000
            try:
                driver.execute_script(f"window.scrollTo(0,{y});")
            except Exception:
                pass
            time.sleep(0.2)
        return captured

    def collect_urls_scrolling(
        self, driver, ctx: "DownloaderContext", collect_urls,
        *, label: str = "รูป", overall_timeout: float = 120.0, stable_rounds: int = 3,
    ) -> list:
        """เลื่อนหน้า + เก็บ 'URL รูปสะสม' (dedup) จนไม่มีใหม่ติดกัน stable_rounds รอบ

        ใช้กับเว็บที่รูปเป็น http URL (Kakao/Toptoon) — เก็บสะสมกัน viewer virtualize
        ถอด <img> เก่าทิ้ง. collect_urls: callable(driver) -> list[str] (URL ที่เห็นตอนนี้)
        คืน list URL ตามลำดับที่พบครั้งแรก
        """
        urls: list = []
        seen: set = set()
        stable = 0
        deadline = time.time() + overall_timeout
        while time.time() < deadline and ctx.is_running():
            new = 0
            try:
                for u in collect_urls(driver) or []:
                    if u and u not in seen:
                        seen.add(u)
                        urls.append(u)
                        new += 1
            except Exception:
                pass
            if new == 0 and urls:
                stable += 1
                if stable >= stable_rounds:
                    break
            else:
                stable = 0
                if new:
                    ctx.log(f"   - ⏳ เก็บ{label}แล้ว {len(urls)} ใบ (เลื่อนหาเพิ่ม...)")
            try:
                driver.execute_script(
                    "window.scrollBy(0, Math.max(1000, window.innerHeight));"
                )
            except Exception:
                pass
            time.sleep(0.8)
        if urls:
            ctx.log(f"   - ✅ รวบรวม URL {label}ครบ: {len(urls)} ใบ")
        return urls

    # --------- ลูปกลาง (เรียกจาก worker) ---------
    def run_loop(self, driver, base_save_path: str, ctx: DownloaderContext) -> None:
        # last_real = ชื่อจริงจากหน้าเว็บ (ใช้ตรวจ "หน้าซ้ำ = จบเรื่อง")
        # counter   = เลขลำดับสำหรับตั้งชื่อโฟลเดอร์ (ถ้าเปิดโหมดเลขลำดับ)
        last_real = ""
        counter = ctx.folder_start  # None = ใช้ชื่อจากหน้าเว็บ
        while ctx.is_running():
            real_name = self.get_chapter_name(driver)
            if real_name == last_real:
                ctx.log(f"   ⚠️ ชื่อตอนซ้ำ ({real_name}) รอสักครู่...")
                time.sleep(2)
                real_name = self.get_chapter_name(driver)
                if real_name == last_real:
                    ctx.log("   🛑 หน้าซ้ำเกินไป หรือจบเรื่อง")
                    break
            last_real = real_name

            # ชื่อโฟลเดอร์: เลขลำดับ (เช่น 01) หรือชื่อจากหน้าเว็บ
            if counter is not None:
                folder_name = str(counter).zfill(max(1, ctx.folder_pad))
            else:
                folder_name = real_name

            save_path = os.path.join(base_save_path, folder_name)
            if not os.path.exists(save_path):
                os.makedirs(save_path)
                ctx.log(f"   📁 สร้างโฟลเดอร์: {save_path}")

            ctx.log(f"\n📘 --- กำลังโหลด: ตอน {folder_name}  ({real_name}) ---")
            ctx.log(f"   💾 บันทึกที่: {save_path}")
            ctx.log(f"   🌐 URL: {driver.current_url}")

            try:
                saved = self.download_chapter(driver, save_path, ctx)
            except Exception as e:
                ctx.log(f"   ❌ โหลดล้มเหลว: {e}")
                saved = 0
            ctx.log(f"   📊 สรุป: {saved} ภาพ")

            # hook หลังโหลดตอน (auto-merge ฯลฯ)
            if saved > 0:
                try:
                    ctx.after_chapter(save_path, saved)
                except Exception as e:
                    ctx.log(f"   ⚠️ ทำงานหลังโหลดตอนผิดพลาด: {e}")

            if counter is not None:
                counter += 1

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
