"""RidiBooks downloader (Canvas blob method)"""
from __future__ import annotations

import os
import time
import base64

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

from .base import (
    BaseDownloader,
    DownloaderContext,
    register_downloader,
    sanitize_filename,
)


@register_downloader
class RidiDownloader(BaseDownloader):
    name = "RidiBooks"
    url = "https://ridibooks.com/"
    profile_dir = "Chrome_Ridi_Profile"
    file_ext = ".jpg"

    # -------- info --------
    def get_chapter_name(self, driver) -> str:
        try:
            el = driver.find_element(By.CSS_SELECTOR, "h2.wv-1xn0gxv")
            name = el.text.strip()
            if name:
                return sanitize_filename(name)
        except Exception:
            pass
        try:
            url_parts = driver.current_url.split("/")
            book_id = url_parts[-2] if url_parts[-1] == "view" else url_parts[-1]
            main_title = driver.find_element(By.CSS_SELECTOR, "h1.wv-1n9wbqe").text.strip()
            return sanitize_filename(f"{main_title}_{book_id}")
        except Exception:
            return f"Ridi_Unknown_{int(time.time())}"

    # -------- download --------
    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (Canvas mode)...")
        time.sleep(2)

        images = []
        selectors = [
            "img.wv-1ago99h",
            "img[class*='wv-1ago99h']",
            "img[src*='blob:']",
        ]
        for sel in selectors:
            try:
                WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, sel))
                )
                found = driver.find_elements(By.CSS_SELECTOR, sel)
                if found:
                    images = found
                    ctx.log(f"   🔍 เจอด้วย selector: {sel} ({len(found)} รูป)")
                    break
            except Exception:
                continue

        if not images:
            ctx.log("   ❌ ไม่พบรูปภาพ (Login แล้ว / เปิดหน้าตอนแล้ว?)")
            return 0

        total = len(images)
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
                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'auto', block:'center'});",
                    img,
                )
                time.sleep(0.3)
                ready = driver.execute_script(
                    "var i=arguments[0]; return i.complete && i.naturalWidth>0 && "
                    "(i.src.startsWith('blob:')||i.src.startsWith('data:'));",
                    img,
                )
                if not ready:
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
                            "var i=arguments[0]; return i.complete && i.naturalWidth>0 && "
                            "(i.src.startsWith('blob:')||i.src.startsWith('data:'));",
                            img,
                        )
                        if ready:
                            break
                if not ready:
                    ctx.log(f"      ❌ ข้าม #{index+1} (โหลดไม่ทัน)")
                    continue

                b64 = driver.execute_script(
                    """
                    var img=arguments[0];
                    try{
                      var c=document.createElement('canvas');
                      c.width=img.naturalWidth; c.height=img.naturalHeight;
                      c.getContext('2d').drawImage(img,0,0);
                      return c.toDataURL('image/jpeg',0.90);
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
                ctx.log(f"      ⚠️ Element หลุด")
            except Exception as e:
                ctx.log(f"      ⚠️ Error: {e}")
        return count

    # -------- next --------
    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        try:
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            links = driver.find_elements(By.CSS_SELECTOR, "a.wv-18b9wav")
            for link in links:
                if "다음화" in link.text or "보기" in link.text:
                    driver.execute_script("arguments[0].click();", link)
                    return True
        except Exception:
            pass
        try:
            driver.find_element(By.TAG_NAME, "body").click()
        except Exception:
            pass
        time.sleep(1)
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, "button.wv-j6u8or")
            if btns:
                driver.execute_script("arguments[0].click();", btns[-1])
                return True
        except Exception:
            pass
        return False
