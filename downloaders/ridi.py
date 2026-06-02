"""RidiBooks downloader (Canvas blob method)"""
from __future__ import annotations

import os
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .base import (
    BaseDownloader,
    DownloaderContext,
    register_downloader,
    sanitize_filename,
    write_bytes_safe,
)


@register_downloader
class RidiDownloader(BaseDownloader):
    name = "RidiBooks"
    url = "https://ridibooks.com/"
    login_url = "https://ridibooks.com/account/login"
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

    # body ของ isComic(img) สำหรับ engine กลาง scroll_and_capture_blobs (ใน base.py):
    #   หน้าการ์ตูน Ridi = <img src="blob:..."> (decode ฝั่ง client เหมือน Bomtoon)
    _COMIC_FILTER_JS = r"""
    const s = img.currentSrc || img.src || '';
    if (!s) return false;
    if (s.startsWith('blob:')) return true;
    return false;
    """

    # -------- download --------
    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (fetch blob ต้นฉบับ + canvas สำรอง)")
        time.sleep(1)

        # รอให้มีรูป blob โผล่ก่อน (อย่างน้อย 1 ใบ)
        try:
            WebDriverWait(driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "img[src*='blob:']"))
            )
        except Exception:
            pass

        # ดูดแบบ scroll + dedup ผ่าน engine กลาง (กันภาพไม่ครบ + canvas เปล่า)
        captured = self.scroll_and_capture_blobs(
            driver, ctx, self._COMIC_FILTER_JS, to_jpeg=True
        )
        if not captured:
            ctx.log("   ❌ ไม่พบรูปภาพ (Login แล้ว / เปิดหน้าตอนแล้ว?)")
            return 0

        # เรียงตามตำแหน่งแนวตั้ง (บน→ล่าง) แล้วบันทึก 001.jpg, 002.jpg, ...
        items = sorted(captured.values(), key=lambda t: t[0])
        count = 0
        for index, (_y, jpg) in enumerate(items, start=1):
            if not ctx.is_running():
                break
            fpath = os.path.join(save_path, f"{str(index).zfill(3)}.jpg")
            if write_bytes_safe(fpath, jpg, ctx.log):
                count += 1
        ctx.progress(count, count)
        ctx.log(f"   - ✅ ดูดครบ {count} ใบ (fetch blob ต้นฉบับ)")
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
