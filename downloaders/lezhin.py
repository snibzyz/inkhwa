"""Lezhin downloader (IMG/Canvas hybrid)"""
from __future__ import annotations

import os
import time
import base64

from selenium.webdriver.common.by import By

from .base import (
    BaseDownloader,
    DownloaderContext,
    register_downloader,
    sanitize_filename,
)


@register_downloader
class LezhinDownloader(BaseDownloader):
    name = "Lezhin"
    url = "https://www.lezhin.com/ko"
    login_url = "https://www.lezhin.com/ko/login"
    profile_dir = "Chrome_Lezhin_Profile"
    file_ext = ".png"

    def get_chapter_name(self, driver) -> str:
        try:
            title = driver.title.split("-")[0].strip()
            url_part = driver.current_url.split("/")[-1]
            return sanitize_filename(f"{title}_EP{url_part}")
        except Exception:
            return f"Lezhin_{int(time.time())}"

    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (Canvas/IMG hybrid)")
        time.sleep(2)

        containers = []
        for sel in [
            "div[class*='scrollViewCut']",
            "div[class*='viewer']",
            "div[class*='comic']",
        ]:
            found = driver.find_elements(By.CSS_SELECTOR, sel)
            if found:
                containers = found
                ctx.log(f"   🔍 เจอด้วย {sel}: {len(found)} กล่อง")
                break

        if not containers:
            ctx.log("   ❌ ไม่พบกล่องภาพ")
            return 0

        total = len(containers)
        count = 0
        for index, container in enumerate(containers):
            if not ctx.is_running():
                break
            filename = f"{str(index + 1).zfill(3)}.png"
            fpath = os.path.join(save_path, filename)
            if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                count += 1
                continue
            try:
                driver.execute_script(
                    "arguments[0].scrollIntoView({behavior:'auto', block:'center'});",
                    container,
                )
                time.sleep(0.5)
                target = None
                kind = None
                for _ in range(15):
                    if not ctx.is_running():
                        break
                    imgs = container.find_elements(By.TAG_NAME, "img")
                    for img in imgs:
                        if img.get_attribute("src") and int(img.get_attribute("naturalWidth") or 0) > 0:
                            target, kind = img, "img"
                            break
                    if target:
                        break
                    canvases = container.find_elements(By.TAG_NAME, "canvas")
                    for cvs in canvases:
                        if int(cvs.get_attribute("width") or 0) > 0:
                            target, kind = cvs, "canvas"
                            break
                    if target:
                        break
                    time.sleep(0.2)

                if not target:
                    continue

                if kind == "canvas":
                    script = "return arguments[0].toDataURL('image/png');"
                else:
                    script = """
                        var img=arguments[0];
                        var c=document.createElement('canvas');
                        c.width=img.naturalWidth; c.height=img.naturalHeight;
                        c.getContext('2d').drawImage(img,0,0);
                        return c.toDataURL('image/png');
                    """
                b64 = driver.execute_script(script, target)
                if b64 and "base64," in b64:
                    _, enc = b64.split(",", 1)
                    with open(fpath, "wb") as f:
                        f.write(base64.b64decode(enc))
                    count += 1
                    size = os.path.getsize(fpath)
                    ctx.log(f"      ✅ Save ({kind}): {filename} ({size}B) [{count}/{total}]")
                    ctx.progress(count, total)
                else:
                    ctx.log(f"      ❌ Save Failed: {filename}")
            except Exception as e:
                ctx.log(f"      ❌ Error #{index+1}: {e}")
        return count

    def click_next(self, driver, ctx: DownloaderContext) -> bool:
        try:
            driver.find_element(By.TAG_NAME, "body").click()
        except Exception:
            pass
        time.sleep(1)
        try:
            btns = driver.find_elements(By.CSS_SELECTOR, ".viewerToolbar__navButton__5IMoJ")
            if len(btns) >= 2 and btns[-1].is_enabled():
                driver.execute_script("arguments[0].click();", btns[-1])
                return True
        except Exception:
            pass
        return False
