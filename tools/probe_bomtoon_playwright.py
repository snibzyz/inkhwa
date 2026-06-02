"""Dev probe (Playwright) — ตรวจ/ออกแบบกลยุทธ์ดูดภาพ Bomtoon ให้ "ภาพครบ"

⚠️ เครื่องมือ dev เท่านั้น — production ใช้ undetected-chromedriver เหมือนเดิม
   (downloaders/bomtoon.py). สคริปต์นี้ขับ "Chrome จริง" ผ่าน channel="chrome"
   + โปรไฟล์ร่วม profiles/Chrome_Shared (login เดิม) เพื่อพิสูจน์กลยุทธ์ก่อนพอร์ต

กลยุทธ์ที่พิสูจน์แล้ว (scroll-and-capture + dedup):
  - หน้าการ์ตูน Bomtoon = <img src="blob:..."> โหลดแล้วอยู่ใน DOM ถาวร
  - เลื่อนจากบนลงล่าง แล้ว fetch(blobURL) เอา "bytes ต้นฉบับ" ของรูปที่ "ยังไม่เคยเก็บ"
    (กันได้ครบแม้จำนวนที่โหลด ณ ขณะหนึ่งจะไม่เท่ากัน), dedup ด้วย URL, เรียงด้วยตำแหน่ง Y
  - fetch = ได้ไฟล์เต็มใบ ไม่มี canvas เปล่า, ไม่เสียคุณภาพ (canvas เป็นแค่ fallback)

วิธีใช้ (ปิดแอป/Chrome ที่ใช้โปรไฟล์ร่วมก่อน ไม่งั้นโปรไฟล์ถูกล็อก):
    python tools/probe_bomtoon_playwright.py "https://www.bomtoon.com/viewer/<series>/<N>"
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from playwright.sync_api import sync_playwright

from app.paths import shared_profile_path
# ใช้ตัวตรวจ/แปลง JPEG + JS ลบ SN ตัวเดียวกับ production → ผลตรงกัน
from downloaders.bomtoon import BomtoonDownloader, SN_REMOVE_JS

# ล็อก SPA router ไม่ให้เด้งตอนอื่นระหว่าง scroll (มิเรอร์ _LOCK_NAV_JS)
LOCK_NAV_JS = r"""
() => {
  if (window.__navLocked) return;
  const lockPath = location.pathname;
  const p = history.pushState.bind(history);
  const r = history.replaceState.bind(history);
  history.pushState = function(s,t,u){ try { if (u && new URL(u, location.href).pathname !== lockPath) return; } catch(e){} return p(s,t,u); };
  history.replaceState = function(s,t,u){ try { if (u && new URL(u, location.href).pathname !== lockPath) return; } catch(e){} return r(s,t,u); };
  window.__navLocked = true;
}
"""

# ดูด "รูปการ์ตูนที่ยังไม่เคยเก็บ" รอบละไม่เกิน maxBatch ใบ (กัน return ก้อนใหญ่เกิน)
#   fetch(blobURL) → bytes ต้นฉบับ; ถ้าไม่ได้ → canvas สำรอง (decode ครบก่อน)
#   คืน [{url, y, dataUrl, via, size}] — y = ตำแหน่งแนวตั้งในเอกสาร (ไว้เรียงลำดับ)
BATCH_CAPTURE_JS = r"""
async ([seenUrls, maxBatch]) => {
  const seen = new Set(seenUrls);
  const isComic = (img) => {
    const s = img.currentSrc || img.src || '';
    if (!s || s.startsWith('data:')) return false;
    if (s.startsWith('blob:')) return true;
    const low = s.toLowerCase();
    if (low.includes('icon') || low.includes('logo') || low.includes('banner') ||
        low.includes('thumb') || low.includes('/sprite') || low.endsWith('.svg')) return false;
    return (img.naturalWidth >= 1000 && img.naturalHeight >= 600);
  };
  const imgs = Array.from(document.querySelectorAll('img')).filter(isComic);
  const out = [];
  for (const img of imgs) {
    const url = img.currentSrc || img.src;
    if (seen.has(url)) continue;
    const rect = img.getBoundingClientRect();
    const rec = { url, y: Math.round(rect.top + window.scrollY) };
    if (url.slice(0, 5) !== 'data:') {
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
            rec.via = 'fetch'; rec.size = blob.size;
          }
        } else { rec.fetchErr = 'http ' + resp.status; }
      } catch (e) { rec.fetchErr = String(e); }
    }
    if (!rec.dataUrl) {
      try { await img.decode(); } catch (e) {}
      if (img.complete && img.naturalWidth > 0) {
        const c = document.createElement('canvas');
        c.width = img.naturalWidth; c.height = img.naturalHeight;
        c.getContext('2d').drawImage(img, 0, 0);
        rec.dataUrl = c.toDataURL('image/jpeg', 0.95); rec.via = 'canvas';
      }
    }
    out.push(rec);
    if (out.length >= maxBatch) break;
  }
  return out;
}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="Bomtoon viewer URL เช่น https://www.bomtoon.com/viewer/Mon_Love/1")
    ap.add_argument("--out", default=os.path.join(_ROOT, "Diag_Playwright"))
    ap.add_argument("--keep-open", action="store_true")
    args = ap.parse_args()

    ep = args.url.rstrip("/").split("/")[-1]
    out_dir = os.path.join(args.out, ep)
    os.makedirs(out_dir, exist_ok=True)
    print(f"🔧 โปรไฟล์ร่วม: {shared_profile_path()}")
    print(f"📁 บันทึกรูปที่: {out_dir}")

    with sync_playwright() as p:
        try:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=shared_profile_path(),
                channel="chrome",
                headless=False,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-site-isolation-trials",
                    "--allow-running-insecure-content",
                ],
                no_viewport=True,
            )
        except Exception as e:
            print(f"❌ เปิด Chrome ไม่ได้ (โปรไฟล์อาจถูกล็อก — ปิดแอป/Chrome ก่อน): {e}")
            return 2

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.set_default_timeout(30000)
        print(f"🌐 ไปยัง: {args.url}")
        try:
            page.goto(args.url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print(f"⚠️ goto error: {e}")
        time.sleep(3)

        if "/viewer/" not in page.url:
            print(f"⚠️ ไม่ได้อยู่หน้า viewer (อาจยังไม่ login): {page.url}")
            if args.keep_open:
                input("กด Enter เพื่อปิด...")
            ctx.close()
            return 3

        page.evaluate(LOCK_NAV_JS)
        try:
            page.evaluate("() => (" + SN_REMOVE_JS + ")()")
        except Exception:
            pass

        # ===== scroll-and-capture + dedup =====
        print("⏬ เลื่อน + ดูดทันที (dedup ด้วย blob URL)...")
        captured = {}                 # url -> (y, jpg_bytes, via)
        no_new = 0
        page.evaluate("window.scrollTo(0,0)")
        time.sleep(0.4)
        y = 0
        t0 = time.time()
        for step in range(400):       # safety cap
            try:
                batch = page.evaluate(BATCH_CAPTURE_JS, [list(captured.keys()), 8])
            except Exception as e:
                print(f"   ⚠️ batch error: {e}")
                batch = []
            got = 0
            for rec in batch:
                url = rec.get("url")
                data_url = rec.get("dataUrl") or ""
                if "base64," not in data_url:
                    continue          # ดูดไม่ติดรอบนี้ → ไม่ mark, รอบหน้าลองใหม่
                try:
                    raw = base64.b64decode(data_url.split("base64,", 1)[1])
                except Exception:
                    continue
                via = rec.get("via")
                jpg, reason = BomtoonDownloader._normalize_to_jpeg(raw, check_blank=(via == "canvas"))
                if jpg is None:
                    continue          # เปล่า/ขาด → รอบหน้าลองใหม่
                if url not in captured:
                    got += 1
                captured[url] = (rec.get("y", 0), jpg, via)
            no_new = 0 if got else no_new + 1
            at_bottom = page.evaluate(
                "() => (window.scrollY + window.innerHeight) >= (document.body.scrollHeight - 4)"
            )
            if got:
                print(f"   +{got} (รวม {len(captured)}) y={y} bottom={at_bottom}")
            if at_bottom and no_new >= 5 and captured:
                break
            y += 1000
            page.evaluate(f"window.scrollTo(0,{y})")
            time.sleep(0.22)

        dt = time.time() - t0

        # เรียงตามตำแหน่งแนวตั้ง (บน→ล่าง) แล้วบันทึก 001.jpg, 002.jpg, ...
        items = sorted(captured.values(), key=lambda t: t[0])
        vias = {}
        sizes = []
        for i, (yy, jpg, via) in enumerate(items, start=1):
            with open(os.path.join(out_dir, f"{i:03d}.jpg"), "wb") as f:
                f.write(jpg)
            vias[via] = vias.get(via, 0) + 1
            sizes.append(len(jpg))

        # ตรวจ "หน้าเต็มที่เปล่า" = ปัญหาจริง (ต่างจากตัวคั่นบาง/หน้าสีเดียว)
        from PIL import Image
        blank_full = []
        for f in sorted(os.listdir(out_dir)):
            if not f.endswith(".jpg"):
                continue
            try:
                im = Image.open(os.path.join(out_dir, f))
                w, h = im.size
                ex = im.convert("RGB").getextrema()
                if h >= 1500 and all(lo == hi for lo, hi in ex):
                    blank_full.append(f)
            except Exception:
                blank_full.append(f + "(open-fail)")

        print("=" * 56)
        print(f"สรุป: เก็บได้ {len(items)} ใบ  ({vias})")
        if sizes:
            print(f"ขนาดไฟล์: เล็กสุด {min(sizes)}B / ใหญ่สุด {max(sizes)}B / เฉลี่ย {sum(sizes)//len(sizes)}B")
        print(f"หน้าเต็มที่เปล่า (ปัญหาจริง): {len(blank_full)} {blank_full if blank_full else ''}")
        print(f"เวลา: {dt:.1f}s")
        print("=" * 56)
        print("✅ ภาพครบ ไม่มีหน้าเปล่า!" if not blank_full else "⚠️ มีหน้าเปล่า — ดู log")

        if args.keep_open:
            input("กด Enter เพื่อปิด...")
        ctx.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
