"""Bomtoon downloader (blob: URL → Canvas method + SN watermark stripper)

Bomtoon ใช้ <img src="blob:..."> ที่ browser ดึงผ่าน FileReader/MediaSource
ดังนั้นต้องดูดผ่าน canvas.toDataURL() เหมือน Ridi (requests ดึง blob: ไม่ได้)

นอกจากนี้ยังฝัง SN (serial number) เป็น <span> ที่มี attribute size/scale พิเศษ
เช่น <span size="12" color="#343432" scale="1.0" class="sc-cUEIKg cmUyli">lcJ6D</span>
script นี้จะลบ SN spans ออกก่อนเริ่มดูด
"""
from __future__ import annotations

import os
import re
import time
import base64

from typing import Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

from .base import (
    BaseDownloader,
    DownloaderContext,
    register_downloader,
    sanitize_filename,
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

    def is_logged_in(self, driver) -> Optional[bool]:
        """ตรวจสถานะ login แบบ passive (ไม่เปลี่ยนหน้า)

        ใช้ตัวตรวจกลางก่อน (ปุ่ม 로그인/로그아웃/마이페이지) ถ้าไม่ชัดเจน
        ค่อย fallback ดูจากช่อง password / การหลุดจากหน้า login
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
        # นอกนั้นไม่ชัวร์ → คืน None ให้ผู้ใช้ยืนยันเอง
        # (ห้ามเดาว่า "หลุดจากหน้า login = login แล้ว" เพราะ login fail ก็ redirect ได้)
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

    def _scroll_to_load(self, driver, ctx: DownloaderContext):
        """ค่อย ๆ scroll ลงจนถึงล่างเพื่อปลุก lazy-load ทุกรูป"""
        try:
            driver.execute_script(
                "return (async()=>{"
                "await new Promise(r=>{let t=0;const d=600;const id=setInterval(()=>{"
                "const sh=document.body.scrollHeight;window.scrollBy(0,d);t+=d;"
                "if(t>=sh+1000){clearInterval(id);window.scrollTo(0,0);r();}},150);});"
                "})();"
            )
            time.sleep(1.5)
        except Exception as e:
            ctx.log(f"   ⚠️ scroll error: {e}")

    def _collect_comic_imgs(self, driver):
        """คืน list<WebElement> เฉพาะ <img> ที่เป็นรูปการ์ตูน (กรอง UI/thumbnail ออก)"""
        return driver.execute_script(
            r"""
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs.filter(img => {
                const src = img.src || '';
                // ยอมแค่ blob: URL หรือ url ที่ดูเหมือนรูปการ์ตูน
                if (!src) return false;
                if (src.startsWith('data:')) return false;
                const low = src.toLowerCase();
                if (low.includes('icon') || low.includes('logo')) return false;
                if (low.includes('banner') || low.includes('thumb')) return false;
                if (low.includes('/sprite') || low.endsWith('.svg')) return false;
                const w = img.naturalWidth || img.width || 0;
                const h = img.naturalHeight || img.height || 0;
                // รูปการ์ตูน Bomtoon ปกติกว้าง >= 1000px
                if (w < 600 || h < 200) return false;
                return true;
            });
            """
        )

    # ----- download -----
    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (blob → canvas + SN strip)")

        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "img"))
            )
        except TimeoutException:
            ctx.log("   ❌ ไม่พบ img element")
            return 0

        # ลบ SN ครั้งแรก
        self._strip_sn(driver, ctx)

        # scroll ปลุก lazy load
        self._scroll_to_load(driver, ctx)

        # ลบ SN อีกรอบ (กรณีมี element ใหม่หลัง scroll)
        self._strip_sn(driver, ctx)

        images = self._collect_comic_imgs(driver)
        if not images:
            ctx.log("   ❌ ไม่พบรูปภาพ (ต้องซื้อตอน?)")
            return 0

        total = len(images)
        ctx.log(f"   - 📦 พบ {total} รูป (canvas mode)")

        count = 0
        for index, img in enumerate(images):
            if not ctx.is_running():
                break
            filename = f"{str(index + 1).zfill(3)}.jpg"
            fpath = os.path.join(save_path, filename)
            if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                count += 1
                continue
            try:
                # 1) scroll element into view เพื่อให้ browser โหลด blob เสร็จจริง
                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'auto',block:'center'});",
                    img,
                )
                time.sleep(0.25)

                # 2) เช็คความพร้อม (naturalWidth > 0)
                ready = driver.execute_script(
                    "var i=arguments[0]; return i.complete && i.naturalWidth>0;", img,
                )
                if not ready:
                    # กระตุ้นด้วย jiggle
                    driver.execute_script(
                        "window.scrollBy(0,-50);"
                        "setTimeout(()=>window.scrollBy(0,50),100);"
                    )
                    start = time.time()
                    while time.time() - start < 4:
                        if not ctx.is_running():
                            break
                        time.sleep(0.4)
                        ready = driver.execute_script(
                            "var i=arguments[0]; return i.complete && i.naturalWidth>0;",
                            img,
                        )
                        if ready:
                            break
                if not ready:
                    ctx.log(f"      ❌ ข้าม #{index+1} (โหลดไม่ทัน)")
                    continue

                # 3) วาดลง canvas → toDataURL → save
                b64 = driver.execute_script(
                    """
                    var img=arguments[0];
                    try{
                      var c=document.createElement('canvas');
                      c.width=img.naturalWidth; c.height=img.naturalHeight;
                      c.getContext('2d').drawImage(img,0,0);
                      return c.toDataURL('image/jpeg',0.92);
                    }catch(e){return null;}
                    """,
                    img,
                )
                if b64 and "base64," in b64:
                    _, enc = b64.split("base64,", 1)
                    with open(fpath, "wb") as f:
                        f.write(base64.b64decode(enc))
                    count += 1
                    size = os.path.getsize(fpath)
                    ctx.log(f"      ✅ Save: {filename} ({size}B) [{count}/{total}]")
                    ctx.progress(count, total)
                else:
                    ctx.log(f"      ❌ Save Failed: {filename}")
            except StaleElementReferenceException:
                ctx.log(f"      ⚠️ Element หลุด (Stale)")
            except Exception as e:
                ctx.log(f"      ⚠️ Error #{index+1}: {e}")

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

    def click_next(self, driver, ctx: DownloaderContext) -> bool:
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
