"""Headfull test: auto-login + Bomtoon canvas download"""
import os
import sys
import time

# ให้รันจาก root ของ project ได้ (python tools/test_bomtoon.py)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from downloaders.bomtoon import BomtoonDownloader
from downloaders.base import ChromeManager, DownloaderContext

LOGIN_URL = "https://www.bomtoon.com/user/login"
CHAPTER_URL = os.environ.get("INKHWA_TEST_URL", "https://www.bomtoon.com/viewer/Mon_Love/1")
LOGIN_ID = os.environ.get("INKHWA_USER", "")
LOGIN_PW = os.environ.get("INKHWA_PASS", "")
if not LOGIN_ID:
    try:
        from app.presets_local import LOGIN_PRESETS as _LP  # type: ignore
        first = next(iter(_LP.values()), None)
        if first:
            LOGIN_ID = first.get("user", "")
            LOGIN_PW = first.get("password", "")
    except Exception:
        pass

OUT_DIR = os.path.join(PROJECT_ROOT, "Test_Bomtoon")
os.makedirs(OUT_DIR, exist_ok=True)


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def auto_login(driver) -> bool:
    log(f"🌐 {LOGIN_URL}")
    driver.get(LOGIN_URL)
    time.sleep(5)
    if "user/login" not in driver.current_url:
        log("   ✅ login session อยู่แล้ว")
        return True

    id_input = None
    pw_input = None
    for sel in [
        "input[placeholder*='이메일']",
        "input[name='loginId']",
        "input[type='email']",
        "input[name='email']",
    ]:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            if el.is_displayed() and el.is_enabled():
                id_input = el
                break
        if id_input:
            break
    for sel in ["input[type='password']", "input[name='password']"]:
        for el in driver.find_elements(By.CSS_SELECTOR, sel):
            if el.is_displayed() and el.is_enabled():
                pw_input = el
                break
        if pw_input:
            break

    if not (id_input and pw_input):
        log("   ❌ form not found")
        return False

    id_input.clear()
    id_input.send_keys(LOGIN_ID)
    pw_input.clear()
    pw_input.send_keys(LOGIN_PW)
    log("   ✏️  filled credentials")

    # submit via Enter (button[type=submit] อาจถูกซ่อน — Enter ใช้ได้ผลในเทสก่อนหน้า)
    pw_input.send_keys(Keys.ENTER)

    # รอ redirect
    for _ in range(15):
        time.sleep(1)
        if "user/login" not in driver.current_url:
            log(f"   ✅ login ok → {driver.current_url}")
            return True
    log("   ❌ stuck on login")
    return False


def main():
    log("=" * 60)
    log("🚀 Bomtoon Headfull Test (auto-login + canvas)")
    log(f"📁 Output: {OUT_DIR}")
    log("=" * 60)

    dl = BomtoonDownloader()
    chrome = ChromeManager(
        profile_dir=os.path.join(PROJECT_ROOT, "profiles", dl.profile_dir),
        log=log, headless=False,
    )
    driver = chrome.launch(start_url="https://www.bomtoon.com/")
    time.sleep(3)

    if not auto_login(driver):
        log("❌ login fail — abort")
        chrome.quit()
        sys.exit(1)

    log(f"🌐 ไปยัง {CHAPTER_URL}")
    driver.get(CHAPTER_URL)
    time.sleep(8)

    ctx = DownloaderContext(log=log, progress=lambda c, t: None)
    name = dl.get_chapter_name(driver)
    log(f"📘 Chapter: {name}")
    save_path = os.path.join(OUT_DIR, name)
    os.makedirs(save_path, exist_ok=True)

    count = dl.download_chapter(driver, save_path, ctx)
    log(f"📊 ผล: {count} ภาพ")

    if os.path.exists(save_path):
        files = sorted(os.listdir(save_path))
        log(f"📂 ไฟล์ที่บันทึก: {len(files)}")
        for f in files[:5]:
            full = os.path.join(save_path, f)
            log(f"   {f} ({os.path.getsize(full)} bytes)")
        if len(files) > 5:
            log(f"   ... อีก {len(files)-5} ไฟล์")

    log("🏁 รอ 5s แล้วปิด")
    time.sleep(5)
    chrome.quit()
    log("✅ จบเทส")


if __name__ == "__main__":
    main()
