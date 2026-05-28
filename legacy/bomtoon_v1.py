import os
import time
import re
import shutil
import requests
from urllib.parse import urlparse

# --- Playwright Imports ---
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# =========================================================================
# --- 1. ตั้งค่า (แก้ไข PATH ให้ถูกต้อง) ---
# =========================================================================

BASE_SAVE_PATH = r"D:\Mangaandnovel\manga\manhwa\Bomtoon_Download"
USER_DATA_DIR = os.path.join(os.getcwd(), "Chrome_Bomtoon_Profile")

URL_TO_OPEN = "https://www.bomtoon.com"

# =========================================================================
# --- 2. ตัวจัดการ SN (Serial Number Watermark) ---
# =========================================================================
# Bomtoon ฝัง SN เป็น <span> ที่มี attribute พิเศษอย่าง size/scale/color
# ตัวอย่าง:
#   <div class="sc-djvmMF oMjpT">
#     <span size="12" color="#343432" scale="1.0" class="sc-cUEIKg cmUyli">lcJ6D</span>
#   </div>
# เนื่องจาก class เป็น styled-components (สุ่มทุกครั้งที่ build)
# จึงต้องจับด้วย attribute pattern แทน

SN_REMOVE_SCRIPT = r"""
() => {
    let removed = 0;
    // จับ span ที่มี attribute size + scale (เป็น pattern เฉพาะของ SN)
    const spans = document.querySelectorAll('span[size][scale]');
    spans.forEach(span => {
        const text = (span.textContent || '').trim();
        // SN code มักยาว 3-12 ตัวอักษร เป็นตัวอักษร/ตัวเลข
        if (text.length >= 3 && text.length <= 12 && /^[A-Za-z0-9]+$/.test(text)) {
            // ลบทั้ง parent div ที่ครอบ SN
            const parent = span.closest('div');
            if (parent) {
                parent.remove();
            } else {
                span.remove();
            }
            removed++;
        }
    });
    return removed;
}
"""

# =========================================================================
# --- 3. ฟังก์ชันหลัก ---
# =========================================================================

def get_safe_name(page):
    try:
        full_title = page.title()
        # เอา " | BOMTOON" หรือชื่อท้ายๆ ของเว็ปออก
        full_title = re.sub(r'\s*[\|\-]\s*(BOMTOON|Bomtoon).*$', '', full_title, flags=re.IGNORECASE)
        clean_name = re.sub(r'[<>:"/\\|?*]', '', full_title).strip()
        if not clean_name:
            return f"Bomtoon_{int(time.time())}"
        return clean_name
    except Exception:
        return f"Bomtoon_{int(time.time())}"


def remove_sn(page):
    try:
        removed = page.evaluate(SN_REMOVE_SCRIPT)
        if removed:
            print(f"   - 🧽 ลบ SN watermark {removed} จุด")
        return removed
    except Exception as e:
        print(f"   ⚠️ ลบ SN ไม่ได้: {e}")
        return 0


def auto_scroll(page):
    # เลื่อนหน้าจอจากบนลงล่างเพื่อ trigger lazy loading
    try:
        page.evaluate(r"""
            async () => {
                await new Promise(resolve => {
                    let totalHeight = 0;
                    const distance = 600;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        if (totalHeight >= scrollHeight + 1000) {
                            clearInterval(timer);
                            window.scrollTo(0, 0);
                            resolve();
                        }
                    }, 150);
                });
            }
        """)
    except Exception:
        pass


def get_requests_session(page):
    session = requests.Session()
    cookies = page.context.cookies()
    for c in cookies:
        try:
            session.cookies.set(c['name'], c['value'], domain=c.get('domain'))
        except Exception:
            session.cookies.set(c['name'], c['value'])
    session.headers.update({
        "User-Agent": page.evaluate("navigator.userAgent"),
        "Referer": page.url,
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    })
    return session


def collect_image_urls(page):
    # เก็บ src ของรูปทั้งหมดในวิวเวอร์
    # กรองออกพวก icon/logo/banner/thumbnail
    return page.evaluate(r"""
        () => {
            const imgs = Array.from(document.querySelectorAll('img'));
            const urls = [];
            const seen = new Set();
            for (const img of imgs) {
                let src = img.src || img.getAttribute('data-src') || '';
                if (!src) continue;
                if (src.startsWith('data:')) continue;
                const low = src.toLowerCase();
                if (low.includes('icon')) continue;
                if (low.includes('logo')) continue;
                if (low.includes('banner')) continue;
                if (low.includes('thumbnail')) continue;
                if (low.includes('thumb_')) continue;
                if (low.includes('/sprite')) continue;
                if (low.includes('.svg')) continue;
                // ต้องมีขนาดพอประมาณ (รูปการ์ตูน)
                const w = img.naturalWidth || img.width || 0;
                const h = img.naturalHeight || img.height || 0;
                if (w > 0 && w < 250) continue;
                if (h > 0 && h < 250) continue;
                if (seen.has(src)) continue;
                seen.add(src);
                urls.push(src);
            }
            return urls;
        }
    """)


def download_bomtoon(page, save_path):
    print("   - 🎯 เริ่มดาวน์โหลด...")

    # 1) รอ DOM พร้อมและรอรูปเริ่มโผล่
    try:
        page.wait_for_selector("img", timeout=15000)
    except PWTimeoutError:
        print("   ❌ ไม่พบ img element")
        return 0

    # 2) ลบ SN ครั้งแรก
    remove_sn(page)

    # 3) Scroll เพื่อโหลด lazy images
    auto_scroll(page)
    time.sleep(1.5)

    # 4) ลบ SN อีกรอบ เผื่อมี element ใหม่โผล่หลัง scroll
    remove_sn(page)

    # 5) เก็บ url รูป
    image_urls = collect_image_urls(page)

    if not image_urls:
        print("   ❌ ไม่พบรูปภาพ (อาจเป็นตอนที่ต้องซื้อ หรือรอโหลดไม่ทัน)")
        return 0

    print(f"   - 📦 พบ {len(image_urls)} รูป")

    session = get_requests_session(page)
    count = 0

    for index, url in enumerate(image_urls):
        # เดานามสกุลไฟล์จาก URL
        path = urlparse(url).path
        ext = os.path.splitext(path)[1].lower()
        if ext not in [".jpg", ".jpeg", ".png", ".webp", ".gif"]:
            ext = ".jpg"

        filename = f"{str(index + 1).zfill(3)}{ext}"
        file_full_path = os.path.join(save_path, filename)

        if os.path.exists(file_full_path) and os.path.getsize(file_full_path) > 0:
            count += 1
            continue

        try:
            response = session.get(url, stream=True, timeout=20)
            if response.status_code == 200:
                with open(file_full_path, "wb") as f:
                    shutil.copyfileobj(response.raw, f)
                count += 1
                print(f"      ✅ Save: {filename}")
            else:
                print(f"      ❌ HTTP {response.status_code} ({filename})")
        except Exception as e:
            print(f"      ❌ Error รูปที่ {index + 1}: {e}")

    return count


def click_next(page):
    # ลองหาปุ่ม "ตอนต่อไป" หลายแบบ
    candidates = [
        # ปุ่มภาษาไทย
        "button:has-text('ตอนต่อไป')",
        "a:has-text('ตอนต่อไป')",
        "button:has-text('ตอนถัดไป')",
        "a:has-text('ตอนถัดไป')",
        # ภาษาเกาหลี
        "button:has-text('다음화')",
        "a:has-text('다음화')",
        "button:has-text('다음')",
        "a:has-text('다음')",
        # ภาษาอังกฤษ
        "button:has-text('Next')",
        "a:has-text('Next')",
        # อิงจาก class
        "[class*='next' i]:not([disabled])",
    ]
    for sel in candidates:
        try:
            loc = page.locator(sel).last  # next มักอยู่ตำแหน่งท้ายๆ
            if loc.count() > 0 and loc.is_visible():
                loc.scroll_into_view_if_needed(timeout=2000)
                loc.click(timeout=3000)
                return True
        except Exception:
            continue
    return False


# =========================================================================
# --- 4. MAIN ---
# =========================================================================

def main():
    print("=" * 60)
    print("      BOMTOON Downloader (Playwright + SN Stripper)")
    print("=" * 60)

    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)
    if not os.path.exists(BASE_SAVE_PATH):
        os.makedirs(BASE_SAVE_PATH)

    with sync_playwright() as pw:
        # ใช้ persistent context เพื่อเก็บ login
        try:
            ctx = pw.chromium.launch_persistent_context(
                USER_DATA_DIR,
                headless=False,
                channel="chrome",  # ใช้ Chrome ที่ติดตั้งในเครื่อง
                viewport={"width": 1280, "height": 900},
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
        except Exception as e:
            print(f"⚠️ launch ด้วย Chrome ไม่ได้ ({e}) — ลองใช้ chromium ภายในของ Playwright")
            ctx = pw.chromium.launch_persistent_context(
                USER_DATA_DIR,
                headless=False,
                viewport={"width": 1280, "height": 900},
                args=[
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

        # ใช้ tab ที่มีอยู่ ไม่งั้นเปิดใหม่
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL_TO_OPEN, timeout=30000)
        except Exception:
            pass

        print("\n[พร้อมทำงาน]")
        print("1. Login Bomtoon ในหน้าต่างที่เปิดขึ้นมา")
        print("2. เปิดหน้าตอนแรกที่ต้องการดาวน์โหลด")
        input("\n👉 กด Enter เพื่อเริ่ม... ")

        last_folder_name = ""

        while True:
            current_folder_name = get_safe_name(page)

            if current_folder_name == last_folder_name:
                print(f"   ⚠️ ชื่อตอนซ้ำ ({current_folder_name}) รอสักครู่...")
                time.sleep(2)
                current_folder_name = get_safe_name(page)
                if current_folder_name == last_folder_name:
                    print("   🛑 หน้าซ้ำเกินไป หรือจบเรื่องแล้ว")
                    break

            last_folder_name = current_folder_name
            save_path = os.path.join(BASE_SAVE_PATH, current_folder_name)
            if not os.path.exists(save_path):
                os.makedirs(save_path)

            print(f"\n📘 --- กำลังโหลด: {current_folder_name} ---")
            saved_count = download_bomtoon(page, save_path)
            print(f"   📊 สรุป: {saved_count} ภาพ")

            # ไปตอนต่อไป
            print("   - ▶️ กำลังไปตอนต่อไป...")
            current_url = page.url
            if click_next(page):
                print("   - 🖱️ คลิก Next แล้ว...")
                try:
                    page.wait_for_url(
                        lambda url: url != current_url,
                        timeout=15000,
                    )
                    time.sleep(2)
                except PWTimeoutError:
                    print("   ⚠️ URL ไม่เปลี่ยน (อาจเป็นตอนสุดท้าย)")
                    break
            else:
                print("\n🛑 หาปุ่มไปต่อไม่เจอ (จบเรื่อง?)")
                break

        print("\nจบการทำงาน")
        input("กด Enter เพื่อปิด...")
        try:
            ctx.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
