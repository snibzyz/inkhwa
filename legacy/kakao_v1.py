import os
import time
import requests
import subprocess
import shutil
from tqdm import tqdm
from bs4 import BeautifulSoup

# --- Selenium Imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException

# =========================================================================
# --- 1. ตั้งค่า (ส่วนนี้เอามาจาก Lezhin Style) ---
# =========================================================================

BASE_SAVE_PATH = r"D:\Mangaandnovel\manga\manhwa\Kakao_Download"
START_CHAPTER = 26

# Path ของ Chrome (แก้ให้ตรงกับเครื่องคุณ)
BROWSER_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# สร้าง Profile ในโฟลเดอร์ปัจจุบัน (แบบเดียวกับ Lezhin เพื่อความง่าย)
USER_DATA_DIR = os.path.join(os.getcwd(), "Chrome_Kakao_Profile")

URL_TO_OPEN = "https://page.kakao.com"
DEBUG_PORT = 9222

# =========================================================================
#  ส่วนเชื่อมต่อ (เอามาจาก Lezhin แบบเป๊ะๆ)
# =========================================================================

def open_browser_manually():
    print(f"🔧 กำลังเปิด Chrome (โหมดพิเศษ Lezhin Style)...")
    if not os.path.exists(BROWSER_PATH):
        print(f"❌ ไม่พบไฟล์ Chrome ที่: {BROWSER_PATH}")
        exit()
    
    # สร้างโฟลเดอร์ Profile ถ้ายังไม่มี
    if not os.path.exists(USER_DATA_DIR):
        os.makedirs(USER_DATA_DIR)

    command = [
        BROWSER_PATH,
        f'--user-data-dir={USER_DATA_DIR}',
        f'--remote-debugging-port={DEBUG_PORT}',
        '--disable-web-security',           # <--- จุดสำคัญที่ช่วยให้โหลดลื่น
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

# =========================================================================
#  ส่วนโหลด (เอามาจาก Kakao ตัวเดิมเป๊ะๆ)
# =========================================================================

def download_chapter_images(driver, save_path):
    try:
        print("   - 📄 กำลังวิเคราะห์ข้อมูลรูปภาพ...")
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        
        # ค้นหารูปภาพทั้งหมดทันที
        image_tags = soup.find_all('img', src=lambda s: s and 'page-edge.kakao.com' in s)
        
        if not image_tags:
            print("\n   - ⚠️ ไม่พบรูปภาพในตอนนี้ อาจเป็นตอนที่ต้องซื้อ หรือมีปัญหาในการโหลด")
            return False
            
        image_urls = [img['src'] for img in image_tags]
        total_images_found = len(image_urls)
        print(f"   - ✅ พบรูปภาพทั้งหมด {total_images_found} รูป")
        
        print("   - 🔑 กำลังเตรียมข้อมูลยืนยันตัวตน (Cookies & Headers) สำหรับการดาวน์โหลด...")
        session = requests.Session()
        headers = {'User-Agent': driver.execute_script("return navigator.userAgent;"), 'Referer': driver.current_url}
        session.headers.update(headers)
        cookies = driver.get_cookies()
        for cookie in cookies: 
            session.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])
            
        print("   - 📥 กำลังเริ่มดาวน์โหลด...")
        for i, url in enumerate(tqdm(image_urls, desc="   Downloading", unit="img", ncols=100)):
            try:
                filename = f"{i+1:03d}.jpeg"
                file_path = os.path.join(save_path, filename)
                
                if os.path.exists(file_path): 
                    continue
                    
                response = session.get(url, stream=True, timeout=30)
                response.raise_for_status()
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192): 
                        f.write(chunk)
            except requests.exceptions.RequestException as e:
                print(f"\n      - ❌ เกิดข้อผิดพลาดในการดาวน์โหลดรูปภาพที่ {i+1}: {e}")
                
        print(f"\n   - 🎉 ดาวน์โหลดตอนที่ {os.path.basename(save_path)} เรียบร้อย!")
        return True
    except Exception as e:
        print(f"\n   - ❌ เกิดข้อผิดพลาดร้ายแรงในฟังก์ชันดาวน์โหลด: {e}")
        return False

# =========================================================================
#  MAIN
# =========================================================================
def main():
    # Kill Chrome ตัวเก่าก่อน
    try: os.system("taskkill /F /IM chrome.exe >nul 2>&1")
    except: pass

    print("=" * 60)
    print("      KAKAOPAGE Auto (Lezhin Connection Style)")
    print("=" * 60)
    
    # 1. ใช้การเปิดแบบใหม่
    open_browser_manually()
    driver = connect_selenium()
    wait = WebDriverWait(driver, 15)

    print("\n[ขั้นตอนที่ 1: เตรียมเบราว์เซอร์]")
    print("1. Chrome ที่เปิดขึ้นมาเป็น Profile แยก (สร้างในโฟลเดอร์นี้)")
    print("2. Login Kakao ให้เรียบร้อย")
    print("3. **เข้าไปยังหน้าการ์ตูนตอนแรกที่คุณต้องการจะเริ่มโหลด**")
    
    input("4. เมื่อเปิดหน้า 'ตอนแรก' แล้ว -> กลับมาที่จอดำกด 'Enter' เพื่อเริ่ม... ")
    
    chapter_counter = START_CHAPTER

    while True:
        print(f"\n📘 --- กำลังประมวลผลตอนที่ {chapter_counter} ---")
        current_url = driver.current_url 
        chapter_path = os.path.join(BASE_SAVE_PATH, str(chapter_counter))
        if not os.path.exists(chapter_path): os.makedirs(chapter_path)

        try:
            # รอให้รูปขึ้น
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "img[src*='page-edge.kakao.com']")))
            print("   - 🌐 หน้าเว็บโหลดรูปภาพแล้ว")
        except TimeoutException:
            print("   - ⚠️ ไม่สามารถโหลดหน้าเว็บของตอนนี้ได้")
            break

        # เรียกใช้ฟังก์ชันโหลดตัวเดิม
        success = download_chapter_images(driver, chapter_path)
        
        if not success:
            print("   - 🛑 หยุดการทำงานเนื่องจากดาวน์โหลดไม่สำเร็จ")
            break

        # ========================[ ระบบเปลี่ยนตอน (Kakao เดิม) ]========================
        try:
            print("   - ▶️ กำลังไปตอนต่อไป...")
            
            # Step 1: คลิกเพื่อปลุก UI
            viewer_area = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "img[src*='page-edge.kakao.com']")))
            ActionChains(driver).move_to_element(viewer_area).click().perform()
            time.sleep(1) 

            # Step 2: กดปุ่ม Next
            next_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[data-test="viewer-navbar-next-button"]'))
            )
            
            driver.execute_script("arguments[0].click();", next_button)
            chapter_counter += 1
            
            WebDriverWait(driver, 20).until(EC.url_changes(current_url))
            time.sleep(2) 
        
        except TimeoutException:
            print("\n👍 ไม่พบปุ่ม 'ตอนถัดไป' หรือจบเรื่องแล้ว")
            break
        except Exception as e:
            print(f"\n   - ❌ เกิดข้อผิดพลาดในการเปลี่ยนตอน: {e}")
            break

    print("\nจบการทำงาน")
    input("กด Enter เพื่อปิดโปรแกรม...")

if __name__ == "__main__":
    main()