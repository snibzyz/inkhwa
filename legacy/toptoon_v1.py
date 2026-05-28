import os
import time
import requests
import subprocess
import re
import shutil

# --- Selenium Imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

# =========================================================================
# --- 1. ตั้งค่า (แก้ไข PATH ให้ถูกต้อง) ---
# =========================================================================

BASE_SAVE_PATH = r"D:\Mangaandnovel\manga\manhwa\Toptoon_Download"
BROWSER_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = os.path.join(os.getcwd(), "Chrome_Toptoon_Profile")

URL_TO_OPEN = "https://toptoon.com"
DEBUG_PORT = 9222

# =========================================================================

def open_browser_manually():
    print(f"🔧 กำลังเปิด Chrome...")
    if not os.path.exists(BROWSER_PATH):
        print(f"❌ ไม่พบไฟล์ Chrome ที่: {BROWSER_PATH}")
        exit()
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)

    command = [
        BROWSER_PATH,
        f'--user-data-dir={USER_DATA_DIR}',
        f'--remote-debugging-port={DEBUG_PORT}',
        '--disable-web-security',
        '--no-first-run',
        '--new-window',
        URL_TO_OPEN
    ]
    subprocess.Popen(command)
    print("  -> เปิด Chrome แล้ว! กรุณา Login และเลือกการ์ตูน...")
    time.sleep(3)

def connect_selenium():
    print(f"🔌 กำลังเชื่อมต่อ Selenium...")
    try:
        options = webdriver.ChromeOptions()
        options.add_experimental_option("debuggerAddress", f"localhost:{DEBUG_PORT}")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        return driver
    except Exception as e:
        print(f"❌ เชื่อมต่อไม่ได้: {e}")
        exit()

def get_safe_name(driver):
    try:
        full_title = driver.title
        clean_name = re.sub(r'[<>:"/\\|?*]', '', full_title).strip()
        return clean_name
    except:
        return f"Toptoon_{int(time.time())}"

def get_requests_session(driver):
    session = requests.Session()
    selenium_cookies = driver.get_cookies()
    for cookie in selenium_cookies:
        session.cookies.set(cookie['name'], cookie['value'])
    session.headers.update({
        "User-Agent": driver.execute_script("return navigator.userAgent;"),
        "Referer": driver.current_url
    })
    return session

# =========================================================================
#  FAST DOWNLOAD FUNCTION
# =========================================================================
def download_toptoon_fast(driver, save_path):
    print("   - 🎯 เริ่มดาวน์โหลด (Fast Mode)...")
    
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".document_img")))
        images = driver.find_elements(By.CSS_SELECTOR, ".document_img")
    except:
        images = []

    if not images:
        print("   ❌ ไม่พบรูปภาพ (อาจต้องซื้อตอน หรือเน็ตช้า)")
        return 0

    print(f"   - 📦 พบ {len(images)} รูป")
    
    session = get_requests_session(driver)
    count = 0
    
    for index, img_elem in enumerate(images):
        filename = f"{str(index + 1).zfill(3)}.jpg"
        file_full_path = os.path.join(save_path, filename)
        
        if os.path.exists(file_full_path):
            count += 1
            continue

        try:
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", img_elem)
            
            img_url = img_elem.get_attribute("data-src")
            if not img_url:
                img_url = img_elem.get_attribute("src")

            if not img_url:
                continue

            response = session.get(img_url, stream=True, timeout=10)
            if response.status_code == 200:
                with open(file_full_path, "wb") as f:
                    shutil.copyfileobj(response.raw, f)
                count += 1
                print(f"      ✅ Save: {filename}")
            else:
                print(f"      ❌ Load Failed: {response.status_code}")

        except Exception as e:
            print(f"      ❌ Error รูปที่ {index+1}: {e}")

    return count

# =========================================================================
#  MAIN
# =========================================================================
def main():
    try: os.system("taskkill /F /IM chrome.exe >nul 2>&1")
    except: pass

    print("=" * 60)
    print("      TOPTOON Auto (Popup Fix)")
    print("=" * 60)

    open_browser_manually()
    driver = connect_selenium()
    
    print("\n[พร้อมทำงาน]")
    print("1. Login Toptoon")
    print("2. เปิดหน้าตอนแรกที่ต้องการ")
    input("\n👉 กด Enter เพื่อเริ่ม... ")

    last_folder_name = ""

    while True:
        current_folder_name = get_safe_name(driver)
        
        if current_folder_name == last_folder_name:
            print(f"   ⚠️ ชื่อตอนซ้ำ ({current_folder_name}) รอสักครู่...")
            time.sleep(2)
            current_folder_name = get_safe_name(driver)
            if current_folder_name == last_folder_name:
                print("   🛑 หน้าเดิมซ้ำกันเกินไป หรือจบเรื่องแล้ว")
                break

        last_folder_name = current_folder_name
        save_path = os.path.join(BASE_SAVE_PATH, current_folder_name)
        if not os.path.exists(save_path): os.makedirs(save_path)

        print(f"\n📘 --- กำลังโหลด: {current_folder_name} ---")
        
        saved_count = download_toptoon_fast(driver, save_path)
        print(f"   📊 สรุป: {saved_count} ภาพ")

        # --- ส่วนจัดการเปลี่ยนตอน ---
        print("   - ▶️ กำลังไปตอนต่อไป...")
        try:
            current_url = driver.current_url
            next_btn = None
            
            # หาปุ่ม Next
            btns = driver.find_elements(By.CSS_SELECTOR, ".btnOtherEpisode.next")
            if btns:
                next_btn = btns[0]

            if next_btn:
                # คลิกปุ่ม Next
                driver.execute_script("arguments[0].click();", next_btn)
                print("   - 🖱️ คลิก Next แล้ว...")
                
                # ====================================================
                # [NEW] ดักจับ Popup (เช่น Free Event หรือ Confirm)
                # ====================================================
                try:
                    # รอเช็ค popup แป๊บนึง (3 วินาที)
                    popup_btn = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "button.btn_coin_confirm"))
                    )
                    print("   ⚠️ เจอ Popup (Free Event/Coin) -> กำลังกดตกลง...")
                    
                    # กดปุ่มใน Popup
                    driver.execute_script("arguments[0].click();", popup_btn)
                    time.sleep(1) # รอให้ popup หายไปและระบบประมวลผล

                except TimeoutException:
                    # ไม่มี Popup เด้งมา ก็ข้ามไป
                    pass
                # ====================================================

                # รอ URL เปลี่ยน
                try:
                    WebDriverWait(driver, 15).until(EC.url_changes(current_url))
                    time.sleep(2) 
                except TimeoutException:
                    print("   ⚠️ URL ไม่เปลี่ยน (อาจเป็นตอนสุดท้าย หรือเน็ตหลุด)")
                    break
            else:
                print("\n🛑 หาปุ่มไปต่อไม่เจอ (จบเรื่อง?)")
                break

        except Exception as e:
            print(f"   ❌ Error เปลี่ยนหน้า: {e}")
            break

    print("\nจบการทำงาน")
    input("กด Enter เพื่อปิด...")

if __name__ == "__main__":
    main()