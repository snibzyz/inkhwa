"""KakaoPage downloader (URL + page-edge.kakao.com)"""
from __future__ import annotations

import os
import time

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
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
class KakaoDownloader(BaseDownloader):
    name = "Kakao"
    url = "https://page.kakao.com"
    # Kakao ใช้ SSO ที่ accounts.kakao.com แล้ว redirect กลับ page.kakao.com
    login_url = "https://accounts.kakao.com/login/?continue=https%3A%2F%2Fpage.kakao.com"
    profile_dir = "Chrome_Kakao_Profile"
    file_ext = ".jpeg"
    # cookie token ของ Kakao web login (มีเมื่อ login บัญชี Kakao แล้วเท่านั้น)
    # ใช้เป็นสัญญาณ positive เพื่อให้ตรวจ login ได้แม้หน้าเป็น SPA
    login_cookies = ("_kawlt", "_kawltea")

    def get_chapter_name(self, driver) -> str:
        # ใช้ส่วนท้าย URL เป็นชื่อตอน
        try:
            url_part = driver.current_url.rstrip("/").split("/")[-1]
            title = driver.title.split("|")[0].strip()
            return sanitize_filename(f"{title}_{url_part}") if title else sanitize_filename(url_part)
        except Exception:
            return f"Kakao_{int(time.time())}"

    def _collect_all_image_urls(
        self, driver, ctx: DownloaderContext, overall_timeout: float = 120.0
    ) -> list:
        """เลื่อนหน้าทีละช่วง + เก็บ URL รูปสะสม จน 'ไม่มี URL ใหม่' ติดกัน 3 รอบ

        เก็บแบบสะสม (set) กัน viewer virtualize ถอด <img> เก่าทิ้ง → ได้รูปครบทุกใบ
        คืน list URL ตามลำดับที่พบ
        """
        urls: list = []
        seen: set = set()
        deadline = time.time() + overall_timeout
        stable = 0

        def grab():
            new = 0
            try:
                els = driver.find_elements(
                    By.CSS_SELECTOR, "img[src*='page-edge.kakao.com']"
                )
            except Exception:
                els = []
            for el in els:
                try:
                    src = el.get_attribute("src")
                except Exception:
                    continue
                if src and "page-edge.kakao.com" in src and src not in seen:
                    seen.add(src)
                    urls.append(src)
                    new += 1
            return new

        while time.time() < deadline and ctx.is_running():
            new = grab()
            if new == 0 and urls:
                stable += 1
                if stable >= 3:          # ไม่มีรูปใหม่ติดกัน 3 รอบ = ครบแล้ว
                    break
            else:
                stable = 0
                if new:
                    ctx.log(f"   - ⏳ เก็บรูปแล้ว {len(urls)} ใบ (เลื่อนหาเพิ่ม...)")
            try:
                driver.execute_script(
                    "window.scrollBy(0, Math.max(1000, window.innerHeight));"
                )
            except Exception:
                pass
            time.sleep(0.8)

        if urls:
            ctx.log(f"   - ✅ รวบรวม URL รูปครบ: {len(urls)} ใบ")
        return urls

    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (URL mode)")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "img[src*='page-edge.kakao.com']")
                )
            )
        except TimeoutException:
            ctx.log("   ❌ ไม่พบรูปภาพ (อาจต้องซื้อตอน)")
            return 0

        # ✅ verify: เลื่อนหน้าโหลด lazy + 'เก็บ URL สะสม' จนไม่มีรูปใหม่ (กันเน็ตช้า)
        #    viewer Kakao อาจ virtualize (ถอด <img> ที่เลื่อนผ่านออกจาก DOM) จึงต้อง
        #    เก็บสะสมระหว่างเลื่อน ไม่ใช่อ่าน DOM ครั้งเดียว เดี๋ยวได้รูปไม่ครบ
        urls = self._collect_all_image_urls(driver, ctx)
        if not urls:
            ctx.log("   ❌ ไม่พบรูปภาพ")
            return 0

        total = len(urls)
        ctx.log(f"   - 📦 พบ {total} รูป (ยืนยันโหลดครบแล้ว)")
        session = make_requests_session(driver)

        count = 0
        for i, url in enumerate(urls):
            if not ctx.is_running():
                break
            filename = f"{i+1:03d}.jpeg"
            fpath = os.path.join(save_path, filename)
            if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                count += 1
                continue
            # โหลดแบบ verified: เช็คครบ (Content-Length + ท้ายไฟล์) + ลองใหม่ถ้าขาด
            if download_url_verified(session, url, fpath, timeout=30, log=ctx.log):
                count += 1
                ctx.log(f"      ✅ Save: {filename} [{count}/{total}]")
                ctx.progress(count, total)
            else:
                ctx.log(f"      ❌ Failed: {filename}")

        if count < total:
            ctx.log(
                f"   - ⚠️ ได้ภาพไม่ครบ: {count}/{total} ใบ (เน็ตช้า) — แนะนำโหลดตอนนี้ซ้ำ"
            )
        else:
            ctx.log(f"   - ✅ ครบทุกใบ: {count}/{total}")
        return count

    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        wait = WebDriverWait(driver, 15)
        try:
            # ปลุก UI
            viewer = wait.until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "img[src*='page-edge.kakao.com']")
                )
            )
            ActionChains(driver).move_to_element(viewer).click().perform()
            time.sleep(1)
            btn = wait.until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, 'div[data-test="viewer-navbar-next-button"]')
                )
            )
            driver.execute_script("arguments[0].click();", btn)
            ctx.log("   - 🖱️ คลิก Next")
            return True
        except TimeoutException:
            return False
        except Exception as e:
            ctx.log(f"   ⚠️ click next error: {e}")
            return False
