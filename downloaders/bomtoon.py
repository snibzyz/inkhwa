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
    profile_dir = "Chrome_Bomtoon_Profile"
    file_ext = ".jpg"

    # ----- login -----
    def login(self, driver, username: str, password: str, ctx: DownloaderContext) -> bool:
        """Auto-login บน bomtoon. คืน True ถ้า login สำเร็จ/มี session อยู่แล้ว"""
        if not username or not password:
            ctx.log("   ⚠️ ไม่มี credentials — ข้าม login")
            return True
        try:
            driver.get(LOGIN_URL)
        except Exception as e:
            ctx.log(f"   ❌ เปิดหน้า login ไม่ได้: {e}")
            return False
        time.sleep(4)

        if "user/login" not in driver.current_url:
            ctx.log("   ✅ session อยู่แล้ว ไม่ต้อง login")
            return True

        id_input = None
        pw_input = None
        for sel in [
            "input[placeholder*='이메일']",
            "input[name='loginId']",
            "input[type='email']",
            "input[name='email']",
        ]:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed() and el.is_enabled():
                    id_input = el
                    break
            if id_input:
                break
        for sel in ["input[type='password']", "input[name='password']"]:
            for el in driver.find_elements(By.CSS_SELECTOR, sel):
                if el.is_displayed() and el.is_enabled():
                    pw_input = el
                    break
            if pw_input:
                break

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
    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        candidates = [
            # เกาหลี (เว็บใช้ภาษาเกาหลี)
            "//button[contains(., '다음화')]",
            "//a[contains(., '다음화')]",
            "//button[contains(., '다음')]",
            "//a[contains(., '다음')]",
            # ไทย
            "//button[contains(., 'ตอนต่อไป')]",
            "//a[contains(., 'ตอนต่อไป')]",
            "//button[contains(., 'ตอนถัดไป')]",
            "//a[contains(., 'ตอนถัดไป')]",
            # อังกฤษ
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
                ctx.log("   - 🖱️ คลิก Next")
                return True
            except Exception:
                continue
        return False
