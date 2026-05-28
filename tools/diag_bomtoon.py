"""Bomtoon: auto-login + ไปหน้า viewer + dump DOM"""
import os
import sys
import time
import json

# ให้รันจาก project root ได้
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from downloaders.bomtoon import BomtoonDownloader
from downloaders.base import ChromeManager

LOGIN_URL = "https://www.bomtoon.com/user/login"
CHAPTER_URL = os.environ.get("INKHWA_TEST_URL", "https://www.bomtoon.com/viewer/Mon_Love/1")
LOGIN_ID = os.environ.get("INKHWA_USER", "")
LOGIN_PW = os.environ.get("INKHWA_PASS", "")

OUT_DIR = os.path.join(PROJECT_ROOT, "Diag_Bomtoon")
os.makedirs(OUT_DIR, exist_ok=True)


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


DIAG_JS = r"""
() => {
    const result = {
        title: document.title,
        url: location.href,
        bodyTextSample: (document.body && document.body.innerText || '').slice(0, 500),
        imgs: [],
        canvases: [],
        iframes: [],
        spansWithSize: [],
        priceOrBuy: [],
    };
    document.querySelectorAll('img').forEach((img, i) => {
        result.imgs.push({
            i, src: (img.src || '').slice(0, 200),
            dataSrc: (img.getAttribute('data-src') || '').slice(0, 200),
            naturalW: img.naturalWidth, naturalH: img.naturalHeight,
            w: img.width, h: img.height, cls: img.className,
            visible: !!(img.offsetWidth && img.offsetHeight),
        });
    });
    document.querySelectorAll('canvas').forEach((c, i) => {
        result.canvases.push({i, w: c.width, h: c.height, cls: c.className,
            visible: !!(c.offsetWidth && c.offsetHeight)});
    });
    document.querySelectorAll('iframe').forEach((f, i) => {
        result.iframes.push({i, src: (f.src || '').slice(0, 200)});
    });
    document.querySelectorAll('span[size]').forEach((s, i) => {
        result.spansWithSize.push({
            i, text: (s.textContent || '').slice(0, 50),
            size: s.getAttribute('size'), scale: s.getAttribute('scale'),
            color: s.getAttribute('color'),
        });
    });
    const buyKeywords = ['구매', '결제', '코인', 'ซื้อ', 'เหรียญ', 'Login', 'login', '로그인'];
    document.querySelectorAll('button, a, h1, h2, h3, p, span, div').forEach(el => {
        const t = (el.textContent || '').trim();
        if (t && t.length < 80) {
            for (const kw of buyKeywords) {
                if (t.includes(kw)) {
                    result.priceOrBuy.push({tag: el.tagName, text: t.slice(0,80)});
                    break;
                }
            }
        }
    });
    result.priceOrBuy = result.priceOrBuy.slice(0, 20);
    return result;
}
"""


def auto_login(driver) -> bool:
    """พยายาม login อัตโนมัติบน bomtoon"""
    log(f"🌐 เปิด {LOGIN_URL}")
    driver.get(LOGIN_URL)
    time.sleep(5)

    # เช็คก่อนว่า login อยู่แล้วหรือยัง (อาจ redirect ไป /)
    current = driver.current_url
    log(f"   หลังโหลด: {current}")
    if "user/login" not in current:
        log("   ✅ ดูเหมือน login อยู่แล้ว")
        return True

    # หา input ของ ID + Password
    id_input = None
    pw_input = None

    id_selectors = [
        "input[name='loginId']",
        "input[name='userId']",
        "input[name='email']",
        "input[type='email']",
        "input[placeholder*='이메일']",
        "input[placeholder*='아이디']",
        "input[placeholder*='Email']",
        "input[placeholder*='email']",
        "input[placeholder*='ID']",
        "input[placeholder*='อีเมล']",
    ]
    pw_selectors = [
        "input[name='password']",
        "input[name='userPassword']",
        "input[type='password']",
        "input[placeholder*='비밀번호']",
        "input[placeholder*='Password']",
        "input[placeholder*='รหัส']",
    ]

    for sel in id_selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    id_input = el
                    log(f"   🔍 ID input: {sel}")
                    break
            if id_input:
                break
        except Exception:
            continue

    for sel in pw_selectors:
        try:
            els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    pw_input = el
                    log(f"   🔍 PW input: {sel}")
                    break
            if pw_input:
                break
        except Exception:
            continue

    if not (id_input and pw_input):
        log("   ❌ หาฟอร์ม login ไม่เจอ — dump page source")
        with open(os.path.join(OUT_DIR, "login_page.html"), "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        driver.save_screenshot(os.path.join(OUT_DIR, "login_page.png"))
        return False

    # กรอก
    id_input.clear()
    id_input.send_keys(LOGIN_ID)
    pw_input.clear()
    pw_input.send_keys(LOGIN_PW)
    log("   ✏️  กรอกข้อมูลแล้ว")
    time.sleep(0.5)

    # หา submit button
    submit = None
    submit_selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:contains('로그인')",
        "button:contains('Login')",
        "button:contains('เข้าสู่ระบบ')",
    ]
    for sel in submit_selectors:
        try:
            if ":contains" in sel:
                # use XPath fallback
                text = sel.split("'")[1]
                els = driver.find_elements(
                    By.XPATH, f"//button[contains(., '{text}')]"
                )
            else:
                els = driver.find_elements(By.CSS_SELECTOR, sel)
            for el in els:
                if el.is_displayed() and el.is_enabled():
                    submit = el
                    log(f"   🔘 submit btn: {sel}")
                    break
            if submit:
                break
        except Exception:
            continue

    if submit:
        driver.execute_script("arguments[0].click();", submit)
    else:
        log("   ⚠️ ไม่เจอปุ่ม submit — ลอง Enter ที่ช่อง password")
        from selenium.webdriver.common.keys import Keys
        pw_input.send_keys(Keys.ENTER)

    log("   ⏳ รอ redirect 8s ...")
    time.sleep(8)
    log(f"   📍 URL หลัง login: {driver.current_url}")
    if "user/login" in driver.current_url:
        log("   ❌ ยัง stuck อยู่หน้า login")
        driver.save_screenshot(os.path.join(OUT_DIR, "after_login.png"))
        return False
    log("   ✅ Login สำเร็จ")
    return True


def main():
    log("=" * 60)
    log("🔬 Bomtoon Auto-Login + DOM Diagnostic")
    log("=" * 60)

    dl = BomtoonDownloader()
    chrome = ChromeManager(
        profile_dir=os.path.join(PROJECT_ROOT, "profiles", dl.profile_dir),
        log=log, headless=False,
    )
    driver = chrome.launch(start_url="https://www.bomtoon.com/")
    time.sleep(3)

    # ลอง auto-login
    auto_login(driver)

    # ไปหน้า viewer
    log(f"🌐 ไปยัง {CHAPTER_URL}")
    driver.get(CHAPTER_URL)
    log("⏳ รอ 12s + scroll ให้ลาน lazy load")
    time.sleep(8)
    try:
        for y in [0.3, 0.6, 0.9, 0.0]:
            driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight*{y});")
            time.sleep(1.5)
    except Exception:
        pass

    info = driver.execute_script("return (" + DIAG_JS + ")();")
    log(f"📄 Title: {info['title']!r}")
    log(f"🔗 URL: {info['url']}")
    log(f"📝 Body: {info['bodyTextSample'][:200]!r}")
    log(f"🖼️  IMG: {len(info['imgs'])}")
    log(f"🎨 Canvas: {len(info['canvases'])}")
    log(f"📦 IFrame: {len(info['iframes'])}")
    log(f"🔖 span[size]: {len(info['spansWithSize'])}")
    log(f"💰 Buy/Login keywords: {len(info['priceOrBuy'])}")
    for x in info['priceOrBuy'][:10]:
        log(f"   [{x['tag']}] {x['text']!r}")

    log("--- Sample imgs (top 20) ---")
    for x in info['imgs'][:20]:
        log(f"  #{x['i']} nat={x['naturalW']}x{x['naturalH']} vis={x['visible']} cls='{x['cls'][:40]}'")
        log(f"     src={x['src']}")
        if x['dataSrc']:
            log(f"     dataSrc={x['dataSrc']}")

    log("--- Canvases ---")
    for x in info['canvases'][:10]:
        log(f"  #{x['i']} {x['w']}x{x['h']} vis={x['visible']} cls='{x['cls'][:40]}'")

    json_path = os.path.join(OUT_DIR, "dom_info.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
    log(f"💾 JSON: {json_path}")

    html_path = os.path.join(OUT_DIR, "viewer_page.html")
    try:
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        log(f"💾 HTML: {html_path} ({os.path.getsize(html_path)} bytes)")
    except Exception as e:
        log(f"⚠️ HTML dump fail: {e}")

    png_path = os.path.join(OUT_DIR, "viewer_screen.png")
    try:
        driver.save_screenshot(png_path)
        log(f"📸 Screenshot: {png_path}")
    except Exception as e:
        log(f"⚠️ screenshot fail: {e}")

    log("🏁 รอ 6s แล้วปิด")
    time.sleep(6)
    chrome.quit()


if __name__ == "__main__":
    main()
