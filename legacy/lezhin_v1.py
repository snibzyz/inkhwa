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

# =========================================================================
# --- 1. ตั้งค่า (แก้ไขให้ถูกต้อง) ---
# =========================================================================

BASE_SAVE_PATH = r"D:\Mangaandnovel\manga\manhwa\Lezhin_Download"
BROWSER_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# สร้าง Profile ในโฟลเดอร์ปัจจุบันเพื่อความง่าย
USER_DATA_DIR = os.path.join(os.getcwd(), "Chrome_Lezhin_Profile")

URL_TO_OPEN = "https://www.lezhin.com/ko"
DEBUG_PORT = 9222

# =========================================================================

def open_browser_manually():
    print(f"🔧 กำลังเปิด Chrome (โหมดพิเศษ ดูด Canvas)...")
    if not os.path.exists(BROWSER_PATH):
        print(f"❌ ไม่พบไฟล์ Chrome ที่: {BROWSER_PATH}")
        exit()
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)

    command = [
        BROWSER_PATH,
        f'--user-data-dir={USER_DATA_DIR}',
        f'--remote-debugging-port={DEBUG_PORT}',
        '--disable-web-security',           # <--- หัวใจสำคัญ
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
        print("✅ เชื่อมต่อสำเร็จ!")
        return driver
    except Exception as e:
        print(f"❌ เชื่อมต่อไม่ได้: {e}")
        exit()

def get_safe_name(driver):
    try:
        title = driver.title.split('-')[0].strip()
        url_part = driver.current_url.split('/')[-1]
        clean_name = re.sub(r'[<>:"/\\|?*]', '', f"{title}_EP{url_part}")
        return clean_name
    except:
        return f"Lezhin_{int(time.time())}"

# =========================================================================
#  CORE FUNCTION: โหลดแบบทีละกล่อง (Step-by-Step)
# =========================================================================
# =========================================================================
#  CORE FUNCTION: โหลดแบบทีละกล่อง (รองรับทั้ง IMG และ CANVAS)
# =========================================================================
def download_images_step_by_step(driver, save_path):
    print("   - 🎯 เริ่มกระบวนการโหลด (รองรับ IMG และ Canvas)")
    
    # 1. หา "กล่องใส่ภาพ" ทั้งหมด
    try:
        # หา div ที่ชื่อ class มีคำว่า scrollViewCut (คลาสของ Lezhin)
        containers = driver.find_elements(By.CSS_SELECTOR, "div[class*='scrollViewCut']")
    except:
        containers = []

    if not containers:
        print("   ❌ ไม่พบกล่องภาพเลย (หน้าเว็บอาจยังไม่โหลด)")
        return 0

    print(f"   - 📦 พบกล่องภาพทั้งหมด: {len(containers)} กล่อง")
    
    count = 0
    
    # วนลูปทีละกล่อง
    for index, container in enumerate(containers):
        filename = f"{str(index + 1).zfill(3)}.png"
        file_full_path = os.path.join(save_path, filename)
        
        # ถ้ามีไฟล์แล้วข้าม
        if os.path.exists(file_full_path):
            print(f"      -> {filename} มีแล้ว ข้าม")
            count += 1
            continue

        try:
            # 2. เลื่อนหน้าจอไปหากล่องนี้ (สำคัญมาก เพื่อให้รูปโหลด)
            driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", container)
            time.sleep(0.5) # รอโหลดนิดนึง

            target_element = None
            element_type = None

            # 3. ลูปค้นหาทั้ง IMG และ CANVAS (ลอง 15 ครั้ง = 3 วินาที)
            for _ in range(15): 
                try:
                    # A. ลองหา IMG ก่อน
                    imgs = container.find_elements(By.TAG_NAME, "img")
                    for img in imgs:
                        # เช็คว่ารูปโหลดเสร็จหรือยัง (naturalWidth > 0)
                        if img.get_attribute("src") and int(img.get_attribute("naturalWidth")) > 0:
                            target_element = img
                            element_type = "img"
                            break
                    
                    if target_element: break

                    # B. ถ้าไม่เจอ IMG ลองหา CANVAS
                    canvases = container.find_elements(By.TAG_NAME, "canvas")
                    for cvs in canvases:
                        if int(cvs.get_attribute("width")) > 0:
                            target_element = cvs
                            element_type = "canvas"
                            break
                    
                    if target_element: break

                except:
                    pass
                time.sleep(0.2)
            
            if not target_element:
                # บางกล่องอาจจะเป็นพื้นที่ว่างท้ายตอน (Footer) ข้ามไปได้
                # print(f"      ⚠️ กล่องที่ {index+1} ว่างเปล่า (อาจเป็น Footer หรือโหลดไม่ทัน)")
                continue

            # 4. ดูดข้อมูล (ใช้ JS แปลงเป็น Base64 ไม่ว่าจะเป็น IMG หรือ Canvas)
            script = ""
            if element_type == "canvas":
                script = "return arguments[0].toDataURL('image/png');"
            else: # img
                # เทคนิค: วาด IMG ลง Canvas ในเมมโมรี่ แล้วแปลงเป็น Base64
                # วิธีนี้แก้ปัญหาเรื่อง Download ติด 403 Forbidden ได้ดีที่สุด
                script = """
                    var img = arguments[0];
                    var canvas = document.createElement('canvas');
                    canvas.width = img.naturalWidth;
                    canvas.height = img.naturalHeight;
                    var ctx = canvas.getContext('2d');
                    ctx.drawImage(img, 0, 0);
                    return canvas.toDataURL('image/png');
                """

            base64_url = driver.execute_script(script, target_element)

            if base64_url and "base64," in base64_url:
                header, encoded = base64_url.split(",", 1)
                data = base64.b64decode(encoded)
                with open(file_full_path, "wb") as f:
                    f.write(data)
                count += 1
                print(f"      ✅ Save ({element_type}): {filename}")
            else:
                print(f"      ❌ Save Failed: {filename}")

        except Exception as e:
            print(f"      ❌ Error ภาพที่ {index+1}: {e}")

    return count

# =========================================================================
#  MAIN
# =========================================================================
def main():
    # Kill Chrome ตัวเก่าก่อน
    try:
        os.system("taskkill /F /IM chrome.exe >nul 2>&1")
    except: pass

    print("=" * 60)
    print("      LEZHIN Auto (Lazy Load Fixer)")
    print("=" * 60)

    open_browser_manually()
    driver = connect_selenium()
    
    print("\n[พร้อมทำงาน]")
    print("1. Login ให้เรียบร้อย")
    print("2. ไปหน้าตอนแรก")
    input("\n👉 กด Enter เพื่อเริ่ม... ")

    while True:
        # 1. สร้างโฟลเดอร์
        folder_name = get_safe_name(driver)
        save_path = os.path.join(BASE_SAVE_PATH, folder_name)
        if not os.path.exists(save_path): os.makedirs(save_path)

        print(f"\n📘 --- ตอน: {folder_name} ---")
        
        # 2. เรียกใช้ฟังก์ชันโหลดแบบใหม่
        saved_count = download_images_step_by_step(driver, save_path)
        print(f"   📊 สรุป: บันทึกได้ {saved_count} ภาพ")

        # 3. ไปตอนต่อไป
        print("   - ▶️ ไปตอนต่อไป...")
        try:
            current_url = driver.current_url
            # คลิกเปิดเมนู
            try: driver.find_element(By.TAG_NAME, "body").click()
            except: pass
            time.sleep(1)
            
            # หาปุ่ม Next
            next_btn = None
            btns = driver.find_elements(By.CSS_SELECTOR, ".viewerToolbar__navButton__5IMoJ")
            if len(btns) >= 2:
                 if btns[-1].is_enabled(): next_btn = btns[-1]
            
            if next_btn:
                driver.execute_script("arguments[0].click();", next_btn)
                print("   - 🖱️ คลิก Next แล้ว...")
                WebDriverWait(driver, 20).until(EC.url_changes(current_url))
                time.sleep(3)
            else:
                print("\n🛑 จบแล้ว (ไม่มีปุ่ม Next)")
                break
        except:
            print("   ❌ เปลี่ยนหน้าไม่ได้")
            break

    print("\nจบการทำงาน")
    input("กด Enter เพื่อปิด...")

if __name__ == "__main__":
    main()