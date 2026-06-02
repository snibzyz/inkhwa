"""Bomtoon downloader (fetch blob ต้นฉบับ + scroll-and-capture)

Bomtoon เรนเดอร์หน้าการ์ตูนเป็น <img src="blob:..."> (decode ฝั่ง client) ซึ่ง
requests ดึง blob: ไม่ได้ จึงต้องดูดในหน้าเว็บ วิธีที่ใช้:
  - เลื่อนบน→ล่าง แล้ว fetch(blobURL) เอา "bytes ต้นฉบับ" ของหน้าที่ยังไม่เคยเก็บ
    (dedup ด้วย URL) → ได้ไฟล์เต็มใบ ไม่มี canvas เปล่า ไม่เสียคุณภาพ ครบทุกใบ
  - canvas.toDataURL() เป็นแค่ fallback เมื่อ fetch ไม่ได้
  - เรียงหน้าด้วยตำแหน่งแนวตั้ง (Y) = ลำดับการอ่าน

SN (serial number) เป็น <span size/scale> overlay ซ้อนบนรูป — ไม่ได้ฝังในไฟล์ blob
จึงไม่ติดมากับ fetch (ยังลบ spans ทิ้งไว้กัน DOM รก)
"""
from __future__ import annotations

import os
import re
import time

from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .base import (
    BaseDownloader,
    DownloaderContext,
    register_downloader,
    sanitize_filename,
    write_bytes_safe,
)

LOGIN_URL = "https://www.bomtoon.com/user/login"


SN_REMOVE_JS = r"""
() => {
    let removed = 0;
    const spans = document.querySelectorAll('span[size][scale]');
    spans.forEach(span => {
        const text = (span.textContent || '').trim();
        if (text.length >= 3 && text.length <= 12 && /^[A-Za-z0-9]+$/.test(text)) {
            const parent = span.closest('div');
            if (parent) parent.remove();
            else span.remove();
            removed++;
        }
    });
    return removed;
}
"""


@register_downloader
class BomtoonDownloader(BaseDownloader):
    name = "Bomtoon"
    url = "https://www.bomtoon.com"
    login_url = LOGIN_URL
    profile_dir = "Chrome_Bomtoon_Profile"
    file_ext = ".jpg"

    # (prefix, เลขตอน) ที่จับไว้ "ตอนเริ่มโหลด" ก่อน scroll — ใช้คำนวณตอนถัดไป
    # กัน viewer auto-advance ทำ current_url ดริฟต์ (ดู download_chapter/click_next)
    _episode_at_start = None

    # ----- login helpers -----
    @staticmethod
    def _find_password_input(driver):
        for sel in ["input[type='password']", "input[name='password']"]:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if el.is_displayed() and el.is_enabled():
                        return el
                except Exception:
                    continue
        return None

    @staticmethod
    def _find_id_input(driver):
        for sel in [
            "input[placeholder*='이메일']",
            "input[name='loginId']",
            "input[type='email']",
            "input[name='email']",
        ]:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                try:
                    if el.is_displayed() and el.is_enabled():
                        return el
                except Exception:
                    continue
        return None

    # ชื่อ cookie ที่บ่งบอกว่า "มี session/ล็อกอินแล้ว" (เดาจากคำในชื่อ)
    _AUTH_COOKIE_HINTS = (
        "token", "session", "sess", "auth", "access", "refresh",
        "login", "member", "user", "uid", "sid", "passport",
    )

    def auth_cookies(self, driver) -> list[dict]:
        """คืน cookie ของ bomtoon ที่ "ดูเหมือน session/auth" (ไว้ตรวจ + log)"""
        found = []
        try:
            for c in driver.get_cookies():
                dom = (c.get("domain") or "").lower()
                if "bomtoon" not in dom:
                    continue
                name = (c.get("name") or "")
                val = c.get("value") or ""
                if not val:
                    continue
                lname = name.lower()
                is_jwt = val.count(".") == 2 and len(val) > 40
                if (any(h in lname for h in self._AUTH_COOKIE_HINTS) and len(val) >= 16) or is_jwt:
                    found.append({"name": name, "len": len(val), "jwt": is_jwt})
        except Exception:
            pass
        return found

    def is_logged_in(self, driver) -> Optional[bool]:
        """ตรวจสถานะ login แบบ passive (ไม่เปลี่ยนหน้า) — smart detect

        ลำดับ (เรียงตามความน่าเชื่อถือ):
          1) ตัวตรวจกลาง: เจอปุ่ม 로그인 ชัด ๆ = ยังไม่ login / เจอ 로그아웃 = login แล้ว
          2) เห็นช่อง password = ยังไม่ login (อยู่บนฟอร์ม login)
          3) หน้า login "ว่าง" (login แล้ว bomtoon ไม่โชว์ฟอร์ม) → ดูจาก session cookie
        """
        base = super().is_logged_in(driver)
        if base is not None:
            return base
        try:
            # เห็นช่อง password = ยังไม่ login (อยู่บนฟอร์ม login)
            if self._find_password_input(driver) is not None:
                return False
        except Exception:
            pass
        # มาถึงนี่ = ไม่เจอปุ่ม login ชัด ๆ และไม่มีฟอร์ม (เช่นหน้า login ว่างเพราะ
        # login ไปแล้ว) → ใช้ session cookie เป็นสัญญาณบวก
        if self.auth_cookies(driver):
            return True
        return None

    # ----- login -----
    def login(self, driver, username: str, password: str, ctx: DownloaderContext) -> bool:
        """Auto-login บน bomtoon. คืน True ถ้า login สำเร็จ/มี session อยู่แล้ว"""
        if not username or not password:
            ctx.log("   ⚠️ ไม่มี credentials — ข้าม auto-login (ให้ผู้ใช้ login เอง)")
            return False
        try:
            driver.get(LOGIN_URL)
        except Exception as e:
            ctx.log(f"   ❌ เปิดหน้า login ไม่ได้: {e}")
            return False
        time.sleep(4)

        if "user/login" not in driver.current_url:
            ctx.log("   ✅ session อยู่แล้ว ไม่ต้อง login")
            return True

        id_input = self._find_id_input(driver)
        pw_input = self._find_password_input(driver)

        if not (id_input and pw_input):
            ctx.log("   ❌ หาฟอร์ม login ไม่เจอ")
            return False

        id_input.clear()
        id_input.send_keys(username)
        pw_input.clear()
        pw_input.send_keys(password)
        ctx.log("   ✏️  กรอก credentials แล้ว")
        pw_input.send_keys(Keys.ENTER)

        for _ in range(15):
            if not ctx.is_running():
                return False
            time.sleep(1)
            if "user/login" not in driver.current_url:
                ctx.log(f"   ✅ Login สำเร็จ → {driver.current_url}")
                return True
        ctx.log("   ❌ Login timeout (ยังอยู่หน้า login)")
        return False

    # ----- info -----
    def get_chapter_name(self, driver) -> str:
        try:
            title = driver.title or ""
            # ตัด " - 봄툰" หรือ " | BOMTOON" ที่ท้าย
            title = re.sub(
                r"\s*[\-\|]\s*(봄툰|BOMTOON|Bomtoon).*$",
                "",
                title,
                flags=re.IGNORECASE,
            )
            return sanitize_filename(title) if title.strip() else f"Bomtoon_{int(time.time())}"
        except Exception:
            return f"Bomtoon_{int(time.time())}"

    def _strip_sn(self, driver, ctx: DownloaderContext) -> int:
        try:
            n = driver.execute_script("return (" + SN_REMOVE_JS + ")();")
            if n:
                ctx.log(f"   - 🧽 ลบ SN watermark {n} จุด")
            return n or 0
        except Exception as e:
            ctx.log(f"   ⚠️ ลบ SN ไม่ได้: {e}")
            return 0

    # ล็อก SPA router ไม่ให้เด้งไปตอนอื่นระหว่าง scroll
    # Bomtoon เป็น Next.js: auto-advance ตอนถัดไปด้วย history.pushState เมื่อ scroll
    # ลงลึก → override ให้ปฏิเสธการเปลี่ยน path (อยู่ตอนเดิม เก็บรูปครบทั้งตอน)
    _LOCK_NAV_JS = r"""
(() => {
  if (window.__navLocked) return;
  const lockPath = location.pathname;
  const p = history.pushState.bind(history);
  const r = history.replaceState.bind(history);
  history.pushState = function(s,t,u){
    try { if (u && new URL(u, location.href).pathname !== lockPath) return; } catch(e){}
    return p(s,t,u);
  };
  history.replaceState = function(s,t,u){
    try { if (u && new URL(u, location.href).pathname !== lockPath) return; } catch(e){}
    return r(s,t,u);
  };
  window.__navLocked = true;
})();
"""

    # body ของ isComic(img) สำหรับ engine กลาง scroll_and_capture_blobs (ใน base.py):
    #   หน้าการ์ตูน Bomtoon = blob เสมอ; เผื่อหน้า http ใหญ่ ๆ (เช่น copyright)
    _COMIC_FILTER_JS = r"""
    const s = img.currentSrc || img.src || '';
    if (!s || s.startsWith('data:')) return false;
    if (s.startsWith('blob:')) return true;
    const low = s.toLowerCase();
    if (low.includes('icon') || low.includes('logo') || low.includes('banner') ||
        low.includes('thumb') || low.includes('/sprite') || low.endsWith('.svg')) return false;
    return (img.naturalWidth >= 1000 && img.naturalHeight >= 600);
    """

    # ----- download -----
    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (fetch blob ต้นฉบับ + canvas สำรอง)")

        # จับเลขตอน "ก่อน" scroll — กัน viewer auto-advance ทำ current_url ดริฟต์
        # แล้วไปตอนถัดไปผิด (ข้ามตอน) หรือเก็บรูปผิดตอน
        self._episode_at_start = self._episode_url_parts(driver.current_url)
        ep = self._episode_at_start
        try:
            cur = driver.current_url or ""
        except Exception:
            cur = ""
        ctx.log(f"   - 📍 เช็ค URL: {cur}" + (f"  (ตอน {ep[1]})" if ep else "  (ไม่ใช่เลขตอน)"))

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "img"))
            )
        except TimeoutException:
            ctx.log("   ❌ ไม่พบ img element")
            return 0

        # ล็อก SPA ไม่ให้เด้งไปตอนอื่นตอน scroll (กันเก็บรูปผิดตอน/ไม่ครบ)
        try:
            driver.execute_script(self._LOCK_NAV_JS)
        except Exception:
            pass

        # ลบ SN overlay (ไม่ติดมากับ fetch อยู่แล้ว แต่ลบไว้กัน DOM รก)
        self._strip_sn(driver, ctx)

        # ดูดแบบ scroll + dedup ผ่าน engine กลาง (fetch blob ต้นฉบับ + canvas สำรอง)
        # กันภาพไม่ครบทุกกรณี ไม่ขึ้นกับว่าโหลดมากี่ใบ ณ ขณะหนึ่ง
        captured = self.scroll_and_capture_blobs(
            driver, ctx, self._COMIC_FILTER_JS, to_jpeg=True
        )

        # กันเก็บรูปผิดตอน: ถ้า viewer ดริฟต์ไปตอนอื่นระหว่างโหลด (lock-nav ควรกันได้แล้ว)
        if ep:
            now = self._episode_url_parts(driver.current_url)
            if now is not None and now != ep:
                ctx.log(f"   ⚠️ ตอนเปลี่ยนระหว่างโหลด ({ep[1]} → {now[1]}) — รูปอาจปนตอน")

        if not captured:
            ctx.log("   ❌ ไม่พบรูปภาพ (ต้องซื้อตอน? หรือยังไม่ได้ login)")
            return 0

        # เรียงตามตำแหน่งแนวตั้ง (บน→ล่าง = ลำดับการอ่าน) แล้วบันทึก 001.jpg, 002.jpg, ...
        items = sorted(captured.values(), key=lambda t: t[0])
        count = 0
        for index, (_y, jpg) in enumerate(items, start=1):
            if not ctx.is_running():
                break
            fpath = os.path.join(save_path, f"{str(index).zfill(3)}.jpg")
            if write_bytes_safe(fpath, jpg, ctx.log):   # กันโฟลเดอร์หาย → สร้างใหม่+ลองซ้ำ
                count += 1
        ctx.progress(count, count)
        ctx.log(f"   - ✅ ดูดครบ {count} ใบ (fetch blob ต้นฉบับ คุณภาพเต็ม)")
        return count

    # ----- next -----
    #
    # ปุ่ม "다음화" (ตอนถัดไป) ของ Bomtoon เป็น React <div> ไม่ใช่ <button>/<a>
    # โครงสร้างจริง (จากหน้า viewer):
    #   <div class="sc-eVQfli kvLyqP">            ← ตัว control (มี onClick)
    #     <div class="sc-eFWqGp kTJXXc"><svg/></div>
    #     <div class="sc-kTvvXX fscKCH">다음화</div>  ← text node (leaf)
    #   </div>
    # วิธีที่ชัวร์สุดคือคลิกที่ "leaf" ที่มี text ตรงป้าย แล้วปล่อยให้ event
    # bubble ขึ้นไปหา onClick ของ React (อยู่ที่ตัว control หรือสูงกว่า)
    _NEXT_JS = r"""
    () => {
      const NEXT = ['다음화','다음 화','다음','ตอนต่อไป','ตอนถัดไป','ถัดไป','Next','NEXT','next'];
      const norm = s => (s || '').replace(/\s+/g, ' ').trim();
      const nodes = Array.from(document.querySelectorAll('div,button,a,span'));
      const matches = nodes.filter(el => NEXT.includes(norm(el.textContent)));
      // เก็บเฉพาะ node ที่ "ลึกสุด" (ไม่มี match ซ้อนข้างใน) = ตัว text node จริง
      const leaves = matches.filter(el => !matches.some(o => o !== el && el.contains(o)));
      if (!leaves.length) return null;
      const leaf = leaves[0];
      // ปุ่มถูกปิด? เช็คตัวเอง+ทุก ancestor (closest) เพราะ aria-disabled/disabled
      // มักอยู่ที่ตัว wrapper ไม่ใช่ leaf — และ pointerEvents เช็คที่ leaf ได้เลย
      // (เป็น inherited property) ห้ามใช้ cursor:pointer มาเดา wrapper เพราะ
      // cursor ก็ inherit ลงมาที่ leaf เหมือนกัน
      if (leaf.closest('[aria-disabled="true"], [disabled]') ||
          getComputedStyle(leaf).pointerEvents === 'none') {
        return 'disabled';
      }
      leaf.scrollIntoView({block: 'center'});
      leaf.click();                 // ปล่อยให้ bubble ขึ้นไปหา onClick ของ React
      return 'clicked';
    }
    """

    # URL ตอนของ Bomtoon เป็นเลขจำนวนเต็มเรียงตรง: /viewer/<series>/<N>
    # (เลข >= 10000 ถือว่าเป็น ID ไม่ใช่เลขตอน → ไม่บวก URL, ใช้ปุ่มแทน)
    _VIEWER_NUM_RE = re.compile(r"^(.*/viewer/[^/]+/)(\d+)/?$")

    def _episode_url_parts(self, url: str):
        """คืน (prefix, number) ถ้า url เป็นรูปแบบ /viewer/<series>/<เลขตอน>"""
        base = (url or "").split("#")[0].split("?")[0]
        m = self._VIEWER_NUM_RE.match(base)
        if not m:
            return None
        n = int(m.group(2))
        if n >= 10000:        # น่าจะเป็น ID ไม่ใช่เลขตอน
            return None
        return (m.group(1), n)

    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        """ไปตอนถัดไป — ใช้การบวกเลข URL เป็นหลัก (ชัวร์ ไม่ข้ามตอน)

        ปุ่ม React '다음화' ของ Bomtoon คลิกแล้วบางครั้งกระโดดข้ามตอน
        แต่ URL เป็นเลขเรียงตรง ๆ จึงเด้งไปตอน N+1 ตรง ๆ แทน
        ใช้ "เลขตอนที่จับไว้ตอนเริ่มโหลด" (ก่อน scroll) เป็นหลัก เพราะ current_url
        อาจดริฟต์จาก viewer auto-advance ถ้าไม่มีค่อยใช้ current_url
        ถ้า URL ไม่ใช่รูปแบบเลขตอน (เช่นเป็น ID) ค่อย fallback ไปใช้ปุ่ม
        """
        parts = self._episode_at_start or self._episode_url_parts(driver.current_url)
        self._episode_at_start = None   # ใช้แล้วเคลียร์ กันค้างไปตอนหน้า
        if parts:
            prefix, n = parts
            next_url = f"{prefix}{n + 1}"
            ctx.log(f"   - ▶️ ไปตอนถัดไป (URL): {next_url}")
            try:
                driver.get(next_url)
            except Exception as e:
                ctx.log(f"   ⚠️ เปิดตอนถัดไปไม่ได้: {e}")
                return False
            time.sleep(2)
            new_url = driver.current_url or ""
            ctx.log(f"   - 📍 เช็ค URL หลังไปต่อ: {new_url}")
            want = n + 1
            # ถูก redirect ออกจาก viewer (เช่นกลับหน้า main) = จบเรื่องแล้ว
            if "/viewer/" not in new_url:
                ctx.log("   🛑 ไม่มีตอนถัดไป (ออกจากหน้า viewer = จบเรื่อง)")
                return False
            np = self._episode_url_parts(new_url)
            if np is None:
                ctx.log("   ✅ ถึงตอนถัดไปแล้ว")
                return True
            if np[1] == want:
                ctx.log(f"   ✅ ยืนยัน: อยู่ตอน {want} ถูกต้อง")
                return True
            if np[1] == n:
                ctx.log("   🛑 ยังเป็นตอนเดิม (ไม่ขยับ) = จบเรื่อง")
                return False
            # ไปไม่ตรงตอนที่ตั้งใจ (viewer เด้ง?) → บังคับกลับไปตอนที่ถูก
            ctx.log(f"   ⚠️ ควรไปตอน {want} แต่ไปตอน {np[1]} — บังคับกลับ {next_url}")
            try:
                driver.get(next_url)
                time.sleep(2)
                fix = self._episode_url_parts(driver.current_url or "")
                ctx.log(f"   - 📍 เช็ค URL หลังแก้: {driver.current_url}")
                if fix and fix[1] == want:
                    ctx.log(f"   ✅ แก้แล้ว อยู่ตอน {want}")
            except Exception:
                pass
            return True
        # URL ไม่ใช่เลขตอน → ใช้ปุ่ม 다음화 เดิม
        return self._click_next_button(driver, ctx)

    def _click_next_button(self, driver, ctx: DownloaderContext) -> bool:
        # 1) วิธีหลัก: หา <div> ปุ่ม next ด้วย JS (รองรับ React div-button)
        try:
            result = driver.execute_script("return (" + self._NEXT_JS + ")();")
        except Exception as e:
            ctx.log(f"   ⚠️ next(JS) error: {e}")
            result = None
        if result == "clicked":
            ctx.log("   - 🖱️ คลิก Next (다음화)")
            return True
        if result == "disabled":
            ctx.log("   - 🛑 ปุ่ม Next ถูกปิด (น่าจะเป็นตอนสุดท้าย)")
            return False

        # 2) fallback: <button>/<a> แบบเดิม (เผื่อ layout เปลี่ยน)
        candidates = [
            "//button[contains(., '다음화')]",
            "//a[contains(., '다음화')]",
            "//button[contains(., '다음')]",
            "//a[contains(., '다음')]",
            "//button[contains(., 'ตอนต่อไป')]",
            "//a[contains(., 'ตอนต่อไป')]",
            "//button[contains(., 'ตอนถัดไป')]",
            "//a[contains(., 'ตอนถัดไป')]",
            "//button[contains(., 'Next')]",
            "//a[contains(., 'Next')]",
        ]
        for xp in candidates:
            try:
                els = driver.find_elements(By.XPATH, xp)
                if not els:
                    continue
                btn = els[-1]
                driver.execute_script(
                    "arguments[0].scrollIntoView({block:'center'});", btn
                )
                time.sleep(0.3)
                driver.execute_script("arguments[0].click();", btn)
                ctx.log("   - 🖱️ คลิก Next (fallback)")
                return True
            except Exception:
                continue
        return False
