import os
import time
import base64
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
# --- 1. ตั้งค่า (แก้ไขให้ถูกต้อง) ---
# =========================================================================

BASE_SAVE_PATH = r"D:\Mangaandnovel\manga\manhwa\ridibookcomic"
BROWSER_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
USER_DATA_DIR = os.path.join(os.getcwd(), "Chrome_Ridi_Profile")
URL_TO_OPEN = "https://ridibooks.com/"
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
        '--disable-site-isolation-trials',
        '--allow-running-insecure-content',
        '--no-first-run',
        '--no-default-browser-check',
        '--new-window',
        URL_TO_OPEN
    ]
    subprocess.Popen(command)
    print("  -> เปิด Chrome แล้ว! รอสักครู่...")
    time.sleep(5)

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

def get_chapter_info(driver):
    try:
        chapter_title_elem = driver.find_element(By.CSS_SELECTOR, "h2.wv-1xn0gxv")
        full_name = chapter_title_elem.text.strip()
        if full_name:
            return re.sub(r'[<>:"/\\|?*]', '', full_name)
    except:
        pass

    try:
        url_parts = driver.current_url.split('/')
        book_id = url_parts[-2] if url_parts[-1] == 'view' else url_parts[-1]
        main_title = driver.find_element(By.CSS_SELECTOR, "h1.wv-1n9wbqe").text.strip()
        full_name = f"{main_title}_{book_id}"
        return re.sub(r'[<>:"/\\|?*]', '', full_name)
    except:
        return f"Ridi_Unknown_{int(time.time())}"

# =========================================================================
# [แก้ไขใหม่] Fast Mode + Smart Recovery
# =========================================================================
def download_images_ridi(driver, save_path):
    print("   - 🎯 เริ่มดาวน์โหลด (โหมดเร็ว + ซ่อมเฉพาะจุด)...")
    
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "img.wv-1ago99h")))
        images = driver.find_elements(By.CSS_SELECTOR, "img.wv-1ago99h")
    except:
        print("   ❌ ไม่พบรูปภาพ")
        return 0

    total_images = len(images)
    print(f"   - 📦 พบ {total_images} รูป")
    count = 0
    
    for index, img_elem in enumerate(images):
        filename = f"{str(index + 1).zfill(3)}.jpg"
        file_full_path = os.path.join(save_path, filename)
        
        if os.path.exists(file_full_path):
            count += 1
            continue

        try:
            # 1. เลื่อนหน้าจอไปทันที (Fast Scroll)
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", img_elem)
            
            # เช็คสถานะทันที (Fast Check)
            is_ready = driver.execute_script("""
                var img = arguments[0];
                return img.complete && img.naturalWidth > 0 && img.src.startsWith('blob:');
            """, img_elem)

            # 2. ถ้ายังไม่พร้อม (Slow Path: Recovery)
            if not is_ready:
                # print(f"      ⚠️ ภาพที่ {index+1} ยังไม่มา.. กำลังกระตุ้น..")
                
                # กระตุ้น Jiggle (ขึ้น-ลง)
                driver.execute_script("window.scrollBy(0, -50); setTimeout(() => window.scrollBy(0, 50), 100);")
                
                # รอ Loop สั้นๆ (สูงสุด 4 วินาที)
                start_wait = time.time()
                while time.time() - start_wait < 4:
                    time.sleep(0.5) # รอทีละนิด
                    is_ready = driver.execute_script("""
                        var img = arguments[0];
                        return img.complete && img.naturalWidth > 0 && img.src.startsWith('blob:');
                    """, img_elem)
                    if is_ready:
                        break
            
            # 3. ถ้าสุดท้ายยังไม่ได้จริงๆ ก็ข้าม
            if not is_ready:
                print(f"      ❌ ข้ามภาพที่ {index+1} (โหลดไม่ทัน/ไฟล์เสีย)")
                continue

            # 4. บันทึก (Canvas)
            base64_url = driver.execute_script("""
                var img = arguments[0];
                try {
                    var canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    var ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    return canvas.toDataURL('image/jpeg', 0.90);
                } catch(e) { return null; }
            """, img_elem)

            if base64_url and "base64," in base64_url:
                header, encoded = base64_url.split("base64,", 1)
                data = base64.b64decode(encoded)
                with open(file_full_path, "wb") as f:
                    f.write(data)
                count += 1
                print(f"      ✅ Save: {filename}")
            else:
                print(f"      ❌ Save Failed: {filename}")

        except StaleElementReferenceException:
            print(f"      ⚠️ Element หลุด (Stale)")
        except Exception as e:
            print(f"      ⚠️ Error: {e}")

    return count

def main():
    try: os.system("taskkill /F /IM chrome.exe >nul 2>&1")
    except: pass

    open_browser_manually()
    driver = connect_selenium()
    
    print("\n[พร้อมทำงาน]")
    print("1. Login Ridi")
    print("2. เปิดหน้าอ่านการ์ตูนตอนแรก")
    input("\n👉 กด Enter เพื่อเริ่ม... ")

    last_folder_name = ""

    while True:
        print("\n⏳ กำลังตรวจสอบข้อมูลตอน...")
        current_folder_name = ""
        
        for _ in range(10):
            temp_name = get_chapter_info(driver)
            if temp_name != last_folder_name:
                current_folder_name = temp_name
                break
            time.sleep(1)
        
        if current_folder_name == last_folder_name:
            print(f"   ⚠️ ชื่อตอนซ้ำ ({current_folder_name}) อาจจะโหลดไม่เสร็จหรือสุดทางแล้ว")
            current_folder_name = f"{current_folder_name}_{int(time.time())}" 
        
        last_folder_name = current_folder_name
        save_path = os.path.join(BASE_SAVE_PATH, current_folder_name)
        if not os.path.exists(save_path): os.makedirs(save_path)

        print(f"📘 --- กำลังโหลด: {current_folder_name} ---")
        
        # เรียกฟังก์ชันโหลดแบบใหม่
        saved_count = download_images_ridi(driver, save_path)
        print(f"   📊 สรุป: {saved_count} ภาพ")

        # ไปตอนต่อไป
        print("   - ▶️ กำลังไปตอนต่อไป...")
        try:
            current_url = driver.current_url
            next_btn = None

            try:
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1)
                links = driver.find_elements(By.CSS_SELECTOR, "a.wv-18b9wav")
                for link in links:
                    if "다음화" in link.text or "보기" in link.text:
                        next_btn = link
                        break
            except: pass

            if not next_btn:
                try: driver.find_element(By.TAG_NAME, "body").click()
                except: pass
                time.sleep(1)
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, "button.wv-j6u8or")
                    if len(btns) > 0:
                        next_btn = btns[-1] 
                except: pass

            if next_btn:
                driver.execute_script("arguments[0].click();", next_btn)
                print("   - 🖱️ คลิก Next แล้ว...")
                try:
                    WebDriverWait(driver, 15).until(EC.url_changes(current_url))
                    print("   - 🔄 URL เปลี่ยนแล้ว รอโหลดเนื้อหา...")
                    time.sleep(3) 
                except TimeoutException:
                    print("   ⚠️ URL ไม่เปลี่ยน (อาจเป็นตอนสุดท้าย หรือเน็ตหลุด)")
                    break
            else:
                print("\n🛑 หาปุ่มไปต่อไม่เจอ หรือจบเรื่องแล้ว")
                break
        except Exception as e:
            print(f"   ❌ Error เปลี่ยนหน้า: {e}")
            break

    print("\nจบการทำงาน")
    input("กด Enter เพื่อปิด...")

if __name__ == "__main__":
    main()