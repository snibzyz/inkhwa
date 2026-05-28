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
    download_url_to,
)


@register_downloader
class ToptoonDownloader(BaseDownloader):
    name = "Toptoon"
    url = "https://toptoon.com"
    profile_dir = "Chrome_Toptoon_Profile"
    file_ext = ".jpg"

    def get_chapter_name(self, driver) -> str:
        try:
            return sanitize_filename(driver.title)
        except Exception:
            return f"Toptoon_{int(time.time())}"

    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (Fast URL mode)")
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".document_img"))
            )
            images = driver.find_elements(By.CSS_SELECTOR, ".document_img")
        except TimeoutException:
            images = []

        if not images:
            ctx.log("   ❌ ไม่พบรูปภาพ (ต้องซื้อตอน?)")
            return 0

        total = len(images)
        ctx.log(f"   - 📦 พบ {total} รูป")
        session = make_requests_session(driver)
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
                url = img.get_attribute("data-src") or img.get_attribute("src")
                if not url:
                    continue
                if download_url_to(session, url, fpath):
                    count += 1
                    ctx.log(f"      ✅ Save: {filename} [{count}/{total}]")
                    ctx.progress(count, total)
                else:
                    ctx.log(f"      ❌ Load Failed: {filename}")
            except Exception as e:
                ctx.log(f"      ❌ Error #{index+1}: {e}")
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
