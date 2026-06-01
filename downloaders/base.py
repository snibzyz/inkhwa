"""Base downloader + Chrome manager (undetected-chromedriver).

ใช้เป็นฐานสำหรับ downloader ของแต่ละเว็บไซต์
"""
from __future__ import annotations

import os
import re
import time
import json
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
                time.sleep(1.0)
                self._consolidate_windows()
                continue
            time.sleep(1.5)
            try:
                cur = self.driver.current_url or ""
            except Exception:
                cur = ""
            if not self._is_blank(cur):
                self.log(f"🌐 เปิด URL: {url}")
                return
            # ยังค้างหน้า New Tab → get() อาจวิ่งคนละแท็บ ลองรวมแท็บแล้วทำซ้ำ
            self.log(f"   ↻ ยังค้างหน้าว่าง (อยู่ที่ {cur or 'ว่าง'}) ลองใหม่...")
            self._consolidate_windows()
            time.sleep(0.5)
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
