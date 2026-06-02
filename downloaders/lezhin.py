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
    write_bytes_safe,
)


@register_downloader
class LezhinDownloader(BaseDownloader):
    name = "Lezhin"
    url = "https://www.lezhin.com/ko"
    login_url = "https://www.lezhin.com/ko/login"
    profile_dir = "Chrome_Lezhin_Profile"
    file_ext = ".jpg"

    def get_chapter_name(self, driver) -> str:
        try:
            title = driver.title.split("-")[0].strip()
            url_part = driver.current_url.split("/")[-1]
            return sanitize_filename(f"{title}_EP{url_part}")
        except Exception:
            return f"Lezhin_{int(time.time())}"

    # JS: ดูดหน้าการ์ตูนที่ "ยังไม่ถูก mark" รอบละไม่เกิน maxBatch (Lezhin = img/canvas ผสม)
    #  - <img>  : fetch(URL) เอา bytes ต้นฉบับ → ถ้าไม่ได้ค่อย canvas
    #  - <canvas>: toDataURL ตรง ๆ (ไม่มี URL ให้ fetch)
    #  dedup ด้วยการ mark element ที่เก็บแล้ว (data-lzCaptured) → เลื่อนเก็บเพิ่มได้เรื่อย ๆ
    _CAPTURE_HYBRID_JS = r"""
const maxBatch = arguments[0];
const done = arguments[arguments.length - 1];
(async () => {
  const out = [];
  try {
    const els = Array.from(document.querySelectorAll('img, canvas')).filter(el => {
      if (el.dataset.lzCaptured) return false;
      if (el.tagName === 'IMG') {
        const s = el.currentSrc || el.src || '';
        if (!s || s.startsWith('data:')) return false;
        return ((el.naturalWidth || 0) >= 300 && (el.naturalHeight || 0) >= 300);
      }
      return (el.width >= 300 && el.height >= 300);   // CANVAS
    });
    for (const el of els) {
      const rec = {};
      try {
        if (el.tagName === 'IMG') {
          const url = el.currentSrc || el.src;
          try {
            const resp = await fetch(url, { cache: 'force-cache' });
            if (resp.ok) {
              const blob = await resp.blob();
              if (blob && blob.size > 0) {
                rec.dataUrl = await new Promise((res, rej) => {
                  const r = new FileReader();
                  r.onload = () => res(r.result); r.onerror = () => rej(new Error('reader'));
                  r.readAsDataURL(blob);
                });
                rec.via = 'fetch';
              }
            }
          } catch (e) {}
          if (!rec.dataUrl) {
            try { await el.decode(); } catch (e) {}
            if (el.complete && el.naturalWidth > 0) {
              const c = document.createElement('canvas');
              c.width = el.naturalWidth; c.height = el.naturalHeight;
              c.getContext('2d').drawImage(el, 0, 0);
              rec.dataUrl = c.toDataURL('image/jpeg', 0.95); rec.via = 'canvas-img';
            }
          }
        } else {
          rec.dataUrl = el.toDataURL('image/jpeg', 0.95); rec.via = 'canvas';
        }
      } catch (e) {}
      if (rec.dataUrl) { el.dataset.lzCaptured = '1'; out.push(rec); }
      if (out.length >= maxBatch) break;
    }
  } catch (e) {}
  done(out);
})();
"""

    def download_chapter(self, driver, save_path, ctx: DownloaderContext) -> int:
        ctx.log("   - 🎯 เริ่มดาวน์โหลด (img/canvas hybrid + scroll dedup)")
        time.sleep(1)

        # เลื่อนบน→ล่าง + เก็บหน้าที่ยังไม่ถูก mark (dedup ด้วย DOM mark) จนครบ
        captured: list = []        # bytes ตามลำดับเอกสาร (บน→ล่าง)
        try:
            driver.execute_script("window.scrollTo(0,0);")
        except Exception:
            pass
        time.sleep(0.4)
        no_new = 0
        y = 0
        for _ in range(600):
            if not ctx.is_running():
                break
            try:
                driver.set_script_timeout(45)
                batch = driver.execute_async_script(self._CAPTURE_HYBRID_JS, 6)
            except Exception as e:
                ctx.log(f"   ⚠️ ดูดรอบนี้ error: {e}")
                batch = []
            got = 0
            for rec in batch or []:
                if not isinstance(rec, dict):
                    continue
                data_url = rec.get("dataUrl") or ""
                if "base64," not in data_url:
                    continue
                try:
                    raw = base64.b64decode(data_url.split("base64,", 1)[1])
                except Exception:
                    continue
                # canvas อาจเปล่าถ้ายังไม่ render → check_blank; fetch เชื่อได้
                out = self.verify_image_bytes(
                    raw, to_jpeg=True, check_blank=(rec.get("via") != "fetch")
                )
                if out is None:
                    continue
                captured.append(out)
                got += 1
            if got:
                ctx.progress(len(captured), len(captured))
                ctx.log(f"   - 📥 ดูดแล้ว {len(captured)} ใบ...")
            no_new = 0 if got else no_new + 1
            try:
                at_bottom = bool(driver.execute_script(
                    "return (window.scrollY + window.innerHeight) >= "
                    "(document.body.scrollHeight - 4);"
                ))
            except Exception:
                at_bottom = True
            if at_bottom and no_new >= 5 and captured:
                break
            y += 1000
            try:
                driver.execute_script(f"window.scrollTo(0,{y});")
            except Exception:
                pass
            time.sleep(0.25)

        if not captured:
            ctx.log("   ❌ ไม่พบกล่องภาพ")
            return 0

        count = 0
        for i, jpg in enumerate(captured, start=1):
            if not ctx.is_running():
                break
            fpath = os.path.join(save_path, f"{str(i).zfill(3)}.jpg")
            if write_bytes_safe(fpath, jpg, ctx.log):
                count += 1
        ctx.progress(count, count)
        ctx.log(f"   - ✅ ดูดครบ {count} ใบ")
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
