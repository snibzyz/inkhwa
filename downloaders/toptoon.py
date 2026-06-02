"""Toptoon downloader (URL + cookies, fast mode)"""
from __future__ import annotations

import os
import re
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from .base import (
    BaseDownloader,
    DownloaderContext,
    register_downloader,
    sanitize_filename,
    make_requests_session,
    download_url_verified,
)


@register_downloader
class ToptoonDownloader(BaseDownloader):
    name = "Toptoon"
    url = "https://toptoon.com"
    login_url = "https://toptoon.com/alert/auth/login"
    profile_dir = "Chrome_Toptoon_Profile"
    file_ext = ".jpg"

    def get_chapter_name(self, driver) -> str:
        try:
            return sanitize_filename(driver.title)
        except Exception:
            return f"Toptoon_{int(time.time())}"

    @staticmethod
    def _collect_urls(driver):
        """คืน URL รูป (.document_img) ที่เห็นตอนนี้ — เอา data-src (URL จริง) ก่อน src"""
        urls = []
        try:
            for el in driver.find_elements(By.CSS_SELECTOR, ".document_img"):
                try:
                    u = el.get_attribute("data-src") or el.get_attribute("src")
                except Exception:
                    u = None
                if u:
                    urls.append(u)
        except Exception:
            pass
        return urls

    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (URL mode)")
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".document_img"))
            )
        except TimeoutException:
            ctx.log("   ❌ ไม่พบรูปภาพ (ต้องซื้อตอน?)")
            return 0

        # ✅ เก็บ URL สะสม (dedup) ระหว่างเลื่อน — กัน lazy/virtualize ทำให้ได้ไม่ครบ
        urls = self.collect_urls_scrolling(driver, ctx, self._collect_urls)
        if not urls:
            ctx.log("   ❌ ไม่พบรูปภาพ (ต้องซื้อตอน?)")
            return 0

        total = len(urls)
        ctx.log(f"   - 📦 พบ {total} รูป (ยืนยันโหลดครบแล้ว)")
        session = make_requests_session(driver)
        count = 0
        for i, url in enumerate(urls, start=1):
            if not ctx.is_running():
                break
            fpath = os.path.join(save_path, f"{str(i).zfill(3)}.jpg")
            # โหลดแบบ verified: เช็คครบ (Content-Length + ท้ายไฟล์) + ลองซ้ำ + กันโฟลเดอร์หาย
            if download_url_verified(session, url, fpath, log=ctx.log):
                count += 1
                ctx.log(f"      ✅ Save: {i:03d}.jpg [{count}/{total}]")
                ctx.progress(count, total)
            else:
                ctx.log(f"      ❌ Load Failed: {i:03d}.jpg")

        if count < total:
            ctx.log(
                f"   - ⚠️ ได้ภาพไม่ครบ: {count}/{total} ใบ (เน็ตช้า) — แนะนำโหลดตอนนี้ซ้ำ"
            )
        else:
            ctx.log(f"   - ✅ ครบทุกใบ: {count}/{total}")
        return count

    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, ".btnOtherEpisode.next")
            if btns:
                driver.execute_script("arguments[0].click();", btns[0])
                ctx.log("   - 🖱️ คลิก Next")
                # จัดการ popup confirm
                try:
                    popup = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "button.btn_coin_confirm")
                        )
                    )
                    ctx.log("   ⚠️ เจอ popup -> กดตกลง")
                    driver.execute_script("arguments[0].click();", popup)
                    time.sleep(1)
                except TimeoutException:
                    pass
                return True
        except Exception as e:
            ctx.log(f"   ⚠️ click next error: {e}")
        return False
