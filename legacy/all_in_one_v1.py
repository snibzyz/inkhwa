import os
import time
import base64
import subprocess
import re
import shutil
import requests
import threading
import json
from tqdm import tqdm
from bs4 import BeautifulSoup
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

# --- Selenium Imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

# =========================================================================
# --- ตั้งค่าทั่วไป ---
# =========================================================================

BROWSER_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DEBUG_PORT = 9222
CONFIG_FILE = "config.json"

# Get script directory (โฟลเดอร์เดียวกับที่โค้ดอยู่)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Default save paths - บันทึกในโฟลเดอร์เดียวกับโค้ด
DEFAULT_SAVE_PATHS = {
    "lezhin": os.path.join(SCRIPT_DIR, "Lezhin_Download"),
    "ridi": os.path.join(SCRIPT_DIR, "Ridi_Download"),
    "toptoon": os.path.join(SCRIPT_DIR, "Toptoon_Download"),
    "kakao": os.path.join(SCRIPT_DIR, "Kakao_Download")
}

def load_config():
    """โหลด config จากไฟล์"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_config(config):
    """บันทึก config ลงไฟล์"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving config: {e}")

def get_save_path(platform):
    """ดึง save path สำหรับ platform"""
    config = load_config()
    if platform in config and 'save_path' in config[platform]:
        return config[platform]['save_path']
    return DEFAULT_SAVE_PATHS.get(platform, os.path.join(SCRIPT_DIR, f"{platform.capitalize()}_Download"))

# =========================================================================
# --- Base Class สำหรับทุกแพลตฟอร์ม ---
# =========================================================================

class ManhwaDownloader:
    def __init__(self, platform_name, base_save_path, url_to_open, profile_suffix, log_callback=None):
        self.platform_name = platform_name
        self.base_save_path = base_save_path
        self.url_to_open = url_to_open
        self.profile_dir = os.path.join(os.getcwd(), f"Chrome_{profile_suffix}_Profile")
        self.driver = None
        self.log_callback = log_callback
        self.is_running = True
        
    def log(self, message):
        """ส่ง log ไปยัง callback หรือ print"""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)
        
    def open_browser_manually(self):
        """เปิด Chrome ด้วย remote debugging"""
        self.log(f"🔧 กำลังเปิด Chrome ({self.platform_name})...")
        if not os.path.exists(BROWSER_PATH):
            self.log(f"❌ ไม่พบไฟล์ Chrome ที่: {BROWSER_PATH}")
            return False
        if not os.path.exists(self.profile_dir):
            os.makedirs(self.profile_dir)

        command = [
            BROWSER_PATH,
            f'--user-data-dir={self.profile_dir}',
            f'--remote-debugging-port={DEBUG_PORT}',
            '--disable-web-security',
            '--disable-site-isolation-trials',
            '--allow-running-insecure-content',
            '--no-first-run',
            '--no-default-browser-check',
            '--new-window',
            self.url_to_open
        ]
        subprocess.Popen(command)
        self.log("  -> เปิด Chrome แล้ว! รอสักครู่...")
        time.sleep(5)
        return True

    def connect_selenium(self):
        """เชื่อมต่อ Selenium กับ Chrome ที่เปิดอยู่"""
        self.log(f"🔌 กำลังเชื่อมต่อ Selenium...")
        try:
            options = webdriver.ChromeOptions()
            options.add_experimental_option("debuggerAddress", f"localhost:{DEBUG_PORT}")
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            self.log("✅ เชื่อมต่อสำเร็จ!")
            return self.driver
        except Exception as e:
            self.log(f"❌ เชื่อมต่อไม่ได้: {e}")
            return None

    def get_chapter_name(self, driver):
        """ดึงชื่อตอน (ต้อง override ใน subclass)"""
        return f"{self.platform_name}_{int(time.time())}"

    def download_images(self, driver, save_path):
        """โหลดรูปภาพ (ต้อง override ใน subclass)"""
        raise NotImplementedError("ต้อง override ฟังก์ชันนี้")

    def navigate_to_next(self, driver):
        """ไปตอนต่อไป (ต้อง override ใน subclass)"""
        raise NotImplementedError("ต้อง override ฟังก์ชันนี้")

    def run(self, gui_mode=False):
        """Main loop สำหรับโหลด"""
        # Kill Chrome ตัวเก่าก่อน
        try:
            os.system("taskkill /F /IM chrome.exe >nul 2>&1")
        except:
            pass

        self.log("=" * 60)
        self.log(f"      {self.platform_name.upper()} Auto Downloader")
        self.log("=" * 60)

        if not self.open_browser_manually():
            return

        driver = self.connect_selenium()
        if not driver:
            return

        self.log(f"\n[พร้อมทำงาน - {self.platform_name}]")
        self.log("1. Login ให้เรียบร้อย")
        self.log("2. ไปหน้าตอนแรกที่ต้องการโหลด")
        
        if not gui_mode:
            input("\n👉 กด Enter เพื่อเริ่ม... ")
        else:
            self.log("\n👉 รอให้คุณ Login และเปิดหน้าตอนแรก...")
            time.sleep(5)  # รอให้ user login

        last_folder_name = ""

        while self.is_running:
            # ดึงชื่อตอน
            current_folder_name = self.get_chapter_name(driver)
            
            # ตรวจสอบชื่อซ้ำ (สำหรับแพลตฟอร์มที่ไม่ได้ใช้ตัวเลข)
            if current_folder_name == last_folder_name:
                self.log(f"   ⚠️ ชื่อตอนซ้ำ ({current_folder_name}) รอสักครู่...")
                time.sleep(2)
                current_folder_name = self.get_chapter_name(driver)
                if current_folder_name == last_folder_name:
                    self.log("   🛑 หน้าเดิมซ้ำกันเกินไป หรือจบเรื่องแล้ว")
                    break

            last_folder_name = current_folder_name
            
            # สร้าง base save path ถ้ายังไม่มี
            if not os.path.exists(self.base_save_path):
                try:
                    os.makedirs(self.base_save_path, exist_ok=True)
                    self.log(f"📁 สร้างโฟลเดอร์หลัก: {self.base_save_path}")
                except Exception as e:
                    self.log(f"❌ ไม่สามารถสร้างโฟลเดอร์ได้: {self.base_save_path} - {e}")
                    break
            
            save_path = os.path.join(self.base_save_path, current_folder_name)
            if not os.path.exists(save_path):
                os.makedirs(save_path, exist_ok=True)

            self.log(f"\n📘 --- ตอน: {current_folder_name} ---")

            # โหลดรูปภาพ
            saved_count = self.download_images(driver, save_path)
            self.log(f"   📊 สรุป: บันทึกได้ {saved_count} ภาพ")

            # ไปตอนต่อไป
            if not self.navigate_to_next(driver):
                self.log("\n🛑 จบการโหลด (ไม่มีตอนต่อไป)")
                break

        self.log("\nจบการทำงาน")
        if not gui_mode:
            input("กด Enter เพื่อปิด...")

# =========================================================================
# --- Lezhin Downloader ---
# =========================================================================

class LezhinDownloader(ManhwaDownloader):
    def __init__(self, log_callback=None, save_path=None):
        super().__init__(
            "Lezhin",
            save_path or get_save_path("lezhin"),
            "https://www.lezhin.com/ko",
            "Lezhin",
            log_callback
        )

    def get_chapter_name(self, driver):
        try:
            title = driver.title.split('-')[0].strip()
            url_part = driver.current_url.split('/')[-1]
            clean_name = re.sub(r'[<>:"/\\|?*]', '', f"{title}_EP{url_part}")
            return clean_name
        except:
            return f"Lezhin_{int(time.time())}"

    def download_images(self, driver, save_path):
        self.log("   - 🎯 เริ่มกระบวนการโหลด (รองรับ IMG และ Canvas)")
        
        try:
            containers = driver.find_elements(By.CSS_SELECTOR, "div[class*='scrollViewCut']")
        except:
            containers = []

        if not containers:
            self.log("   ❌ ไม่พบกล่องภาพเลย (หน้าเว็บอาจยังไม่โหลด)")
            return 0

        self.log(f"   - 📦 พบกล่องภาพทั้งหมด: {len(containers)} กล่อง")
        count = 0

        for index, container in enumerate(containers):
            filename = f"{str(index + 1).zfill(3)}.png"
            file_full_path = os.path.join(save_path, filename)

            if os.path.exists(file_full_path):
                self.log(f"      -> {filename} มีแล้ว ข้าม")
                count += 1
                continue

            try:
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", container)
                time.sleep(0.5)

                target_element = None
                element_type = None

                for _ in range(15):
                    try:
                        imgs = container.find_elements(By.TAG_NAME, "img")
                        for img in imgs:
                            if img.get_attribute("src") and int(img.get_attribute("naturalWidth") or 0) > 0:
                                target_element = img
                                element_type = "img"
                                break
                        if target_element:
                            break

                        canvases = container.find_elements(By.TAG_NAME, "canvas")
                        for cvs in canvases:
                            if int(cvs.get_attribute("width") or 0) > 0:
                                target_element = cvs
                                element_type = "canvas"
                                break
                        if target_element:
                            break
                    except:
                        pass
                    time.sleep(0.2)

                if not target_element:
                    continue

                if element_type == "canvas":
                    script = "return arguments[0].toDataURL('image/png');"
                else:
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
                    self.log(f"      ✅ Save ({element_type}): {filename}")
                else:
                    self.log(f"      ❌ Save Failed: {filename}")

            except Exception as e:
                self.log(f"      ❌ Error ภาพที่ {index+1}: {e}")

        return count

    def navigate_to_next(self, driver):
        try:
            current_url = driver.current_url
            try:
                driver.find_element(By.TAG_NAME, "body").click()
            except:
                pass
            time.sleep(1)

            next_btn = None
            btns = driver.find_elements(By.CSS_SELECTOR, ".viewerToolbar__navButton__5IMoJ")
            if len(btns) >= 2:
                if btns[-1].is_enabled():
                    next_btn = btns[-1]

            if next_btn:
                driver.execute_script("arguments[0].click();", next_btn)
                self.log("   - 🖱️ คลิก Next แล้ว...")
                WebDriverWait(driver, 20).until(EC.url_changes(current_url))
                time.sleep(3)
                return True
            else:
                return False
        except:
            self.log("   ❌ เปลี่ยนหน้าไม่ได้")
            return False

# =========================================================================
# --- Ridi Downloader ---
# =========================================================================

class RidiDownloader(ManhwaDownloader):
    def __init__(self, log_callback=None, save_path=None):
        super().__init__(
            "Ridi",
            save_path or get_save_path("ridi"),
            "https://ridibooks.com/",
            "Ridi",
            log_callback
        )

    def get_chapter_name(self, driver):
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

    def download_images(self, driver, save_path):
        self.log("   - 🎯 เริ่มดาวน์โหลด (โหมดเร็ว + ซ่อมเฉพาะจุด)...")
        
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "img.wv-1ago99h")))
            images = driver.find_elements(By.CSS_SELECTOR, "img.wv-1ago99h")
        except:
            self.log("   ❌ ไม่พบรูปภาพ")
            return 0

        total_images = len(images)
        self.log(f"   - 📦 พบ {total_images} รูป")
        count = 0

        for index, img_elem in enumerate(images):
            filename = f"{str(index + 1).zfill(3)}.jpg"
            file_full_path = os.path.join(save_path, filename)

            if os.path.exists(file_full_path):
                count += 1
                continue

            try:
                driver.execute_script("arguments[0].scrollIntoView({behavior: 'auto', block: 'center'});", img_elem)

                is_ready = driver.execute_script("""
                    var img = arguments[0];
                    return img.complete && img.naturalWidth > 0 && img.src.startsWith('blob:');
                """, img_elem)

                if not is_ready:
                    driver.execute_script("window.scrollBy(0, -50); setTimeout(() => window.scrollBy(0, 50), 100);")
                    start_wait = time.time()
                    while time.time() - start_wait < 4:
                        time.sleep(0.5)
                        is_ready = driver.execute_script("""
                            var img = arguments[0];
                            return img.complete && img.naturalWidth > 0 && img.src.startsWith('blob:');
                        """, img_elem)
                        if is_ready:
                            break

                if not is_ready:
                    self.log(f"      ❌ ข้ามภาพที่ {index+1} (โหลดไม่ทัน/ไฟล์เสีย)")
                    continue

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
                    self.log(f"      ✅ Save: {filename}")
                else:
                    self.log(f"      ❌ Save Failed: {filename}")

            except StaleElementReferenceException:
                self.log(f"      ⚠️ Element หลุด (Stale)")
            except Exception as e:
                self.log(f"      ⚠️ Error: {e}")

        return count

    def navigate_to_next(self, driver):
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
            except:
                pass

            if not next_btn:
                try:
                    driver.find_element(By.TAG_NAME, "body").click()
                except:
                    pass
                time.sleep(1)
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, "button.wv-j6u8or")
                    if len(btns) > 0:
                        next_btn = btns[-1]
                except:
                    pass

            if next_btn:
                driver.execute_script("arguments[0].click();", next_btn)
                self.log("   - 🖱️ คลิก Next แล้ว...")
                try:
                    WebDriverWait(driver, 15).until(EC.url_changes(current_url))
                    self.log("   - 🔄 URL เปลี่ยนแล้ว รอโหลดเนื้อหา...")
                    time.sleep(3)
                    return True
                except TimeoutException:
                    self.log("   ⚠️ URL ไม่เปลี่ยน (อาจเป็นตอนสุดท้าย หรือเน็ตหลุด)")
                    return False
            else:
                return False
        except Exception as e:
            self.log(f"   ❌ Error เปลี่ยนหน้า: {e}")
            return False

# =========================================================================
# --- Toptoon Downloader ---
# =========================================================================

class ToptoonDownloader(ManhwaDownloader):
    def __init__(self, log_callback=None, save_path=None):
        super().__init__(
            "Toptoon",
            save_path or get_save_path("toptoon"),
            "https://toptoon.com",
            "Toptoon",
            log_callback
        )

    def get_chapter_name(self, driver):
        try:
            full_title = driver.title
            clean_name = re.sub(r'[<>:"/\\|?*]', '', full_title).strip()
            return clean_name
        except:
            return f"Toptoon_{int(time.time())}"

    def get_requests_session(self, driver):
        session = requests.Session()
        selenium_cookies = driver.get_cookies()
        for cookie in selenium_cookies:
            session.cookies.set(cookie['name'], cookie['value'])
        session.headers.update({
            "User-Agent": driver.execute_script("return navigator.userAgent;"),
            "Referer": driver.current_url
        })
        return session

    def download_images(self, driver, save_path):
        self.log("   - 🎯 เริ่มดาวน์โหลด (Fast Mode)...")
        
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".document_img")))
            images = driver.find_elements(By.CSS_SELECTOR, ".document_img")
        except:
            images = []

        if not images:
            self.log("   ❌ ไม่พบรูปภาพ (อาจต้องซื้อตอน หรือเน็ตช้า)")
            return 0

        self.log(f"   - 📦 พบ {len(images)} รูป")
        
        session = self.get_requests_session(driver)
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
                    self.log(f"      ✅ Save: {filename}")
                else:
                    self.log(f"      ❌ Load Failed: {response.status_code}")

            except Exception as e:
                self.log(f"      ❌ Error รูปที่ {index+1}: {e}")

        return count

    def navigate_to_next(self, driver):
        try:
            current_url = driver.current_url
            next_btn = None

            btns = driver.find_elements(By.CSS_SELECTOR, ".btnOtherEpisode.next")
            if btns:
                next_btn = btns[0]

            if next_btn:
                driver.execute_script("arguments[0].click();", next_btn)
                self.log("   - 🖱️ คลิก Next แล้ว...")

                # ดักจับ Popup
                try:
                    popup_btn = WebDriverWait(driver, 3).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "button.btn_coin_confirm"))
                    )
                    self.log("   ⚠️ เจอ Popup (Free Event/Coin) -> กำลังกดตกลง...")
                    driver.execute_script("arguments[0].click();", popup_btn)
                    time.sleep(1)
                except TimeoutException:
                    pass

                try:
                    WebDriverWait(driver, 15).until(EC.url_changes(current_url))
                    time.sleep(2)
                    return True
                except TimeoutException:
                    self.log("   ⚠️ URL ไม่เปลี่ยน (อาจเป็นตอนสุดท้าย หรือเน็ตหลุด)")
                    return False
            else:
                return False
        except Exception as e:
            self.log(f"   ❌ Error เปลี่ยนหน้า: {e}")
            return False

# =========================================================================
# --- Kakao Downloader ---
# =========================================================================

class KakaoDownloader(ManhwaDownloader):
    def __init__(self, start_chapter=1, log_callback=None, save_path=None):
        super().__init__(
            "Kakao",
            save_path or get_save_path("kakao"),
            "https://page.kakao.com",
            "Kakao",
            log_callback
        )
        self.START_CHAPTER = start_chapter

    def get_chapter_name(self, driver):
        # สำหรับ Kakao ใช้ตัวเลขแทน
        return str(self.START_CHAPTER)

    def download_images(self, driver, save_path):
        try:
            self.log("   - 📄 กำลังวิเคราะห์ข้อมูลรูปภาพ...")
            html = driver.page_source
            soup = BeautifulSoup(html, 'html.parser')

            image_tags = soup.find_all('img', src=lambda s: s and 'page-edge.kakao.com' in s)

            if not image_tags:
                self.log("\n   - ⚠️ ไม่พบรูปภาพในตอนนี้ อาจเป็นตอนที่ต้องซื้อ หรือมีปัญหาในการโหลด")
                return 0

            image_urls = [img['src'] for img in image_tags]
            total_images_found = len(image_urls)
            self.log(f"   - ✅ พบรูปภาพทั้งหมด {total_images_found} รูป")

            self.log("   - 🔑 กำลังเตรียมข้อมูลยืนยันตัวตน (Cookies & Headers) สำหรับการดาวน์โหลด...")
            session = requests.Session()
            headers = {
                'User-Agent': driver.execute_script("return navigator.userAgent;"),
                'Referer': driver.current_url
            }
            session.headers.update(headers)
            cookies = driver.get_cookies()
            for cookie in cookies:
                session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain', ''))

            self.log("   - 📥 กำลังเริ่มดาวน์โหลด...")
            count = 0
            # สำหรับ GUI mode ไม่ใช้ tqdm
            if self.log_callback:
                for i, url in enumerate(image_urls):
                    try:
                        filename = f"{i+1:03d}.jpeg"
                        file_path = os.path.join(save_path, filename)

                        if os.path.exists(file_path):
                            count += 1
                            continue

                        response = session.get(url, stream=True, timeout=30)
                        response.raise_for_status()
                        with open(file_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        count += 1
                        self.log(f"      ✅ ดาวน์โหลด: {filename} ({i+1}/{total_images_found})")
                    except requests.exceptions.RequestException as e:
                        self.log(f"\n      - ❌ เกิดข้อผิดพลาดในการดาวน์โหลดรูปภาพที่ {i+1}: {e}")
            else:
                for i, url in enumerate(tqdm(image_urls, desc="   Downloading", unit="img", ncols=100)):
                    try:
                        filename = f"{i+1:03d}.jpeg"
                        file_path = os.path.join(save_path, filename)

                        if os.path.exists(file_path):
                            count += 1
                            continue

                        response = session.get(url, stream=True, timeout=30)
                        response.raise_for_status()
                        with open(file_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                f.write(chunk)
                        count += 1
                    except requests.exceptions.RequestException as e:
                        print(f"\n      - ❌ เกิดข้อผิดพลาดในการดาวน์โหลดรูปภาพที่ {i+1}: {e}")

            self.log(f"\n   - 🎉 ดาวน์โหลดตอนที่ {os.path.basename(save_path)} เรียบร้อย!")
            return count
        except Exception as e:
            self.log(f"\n   - ❌ เกิดข้อผิดพลาดร้ายแรงในฟังก์ชันดาวน์โหลด: {e}")
            return 0

    def navigate_to_next(self, driver):
        try:
            self.log("   - ▶️ กำลังไปตอนต่อไป...")
            current_url = driver.current_url
            wait = WebDriverWait(driver, 15)

            viewer_area = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "img[src*='page-edge.kakao.com']")))
            ActionChains(driver).move_to_element(viewer_area).click().perform()
            time.sleep(1)

            next_button = wait.until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[data-test="viewer-navbar-next-button"]'))
            )

            driver.execute_script("arguments[0].click();", next_button)
            self.START_CHAPTER += 1

            WebDriverWait(driver, 20).until(EC.url_changes(current_url))
            time.sleep(2)
            return True

        except TimeoutException:
            self.log("\n👍 ไม่พบปุ่ม 'ตอนถัดไป' หรือจบเรื่องแล้ว")
            return False
        except Exception as e:
            self.log(f"\n   - ❌ เกิดข้อผิดพลาดในการเปลี่ยนตอน: {e}")
            return False

    def run(self, gui_mode=False):
        """Override run เพื่อเพิ่มการรอให้รูปขึ้น"""
        try:
            os.system("taskkill /F /IM chrome.exe >nul 2>&1")
        except:
            pass

        self.log("=" * 60)
        self.log(f"      {self.platform_name.upper()} Auto Downloader")
        self.log("=" * 60)

        if not self.open_browser_manually():
            return

        driver = self.connect_selenium()
        if not driver:
            return

        wait = WebDriverWait(driver, 15)

        self.log(f"\n[พร้อมทำงาน - {self.platform_name}]")
        self.log("1. Login Kakao ให้เรียบร้อย")
        self.log("2. **เข้าไปยังหน้าการ์ตูนตอนแรกที่คุณต้องการจะเริ่มโหลด**")
        
        if not gui_mode:
            input("3. เมื่อเปิดหน้า 'ตอนแรก' แล้ว -> กลับมาที่จอดำกด 'Enter' เพื่อเริ่ม... ")
        else:
            self.log("3. รอให้คุณ Login และเปิดหน้าตอนแรก...")
            time.sleep(5)

        # สร้าง base save path ถ้ายังไม่มี
        if not os.path.exists(self.base_save_path):
            try:
                os.makedirs(self.base_save_path, exist_ok=True)
                self.log(f"📁 สร้างโฟลเดอร์หลัก: {self.base_save_path}")
            except Exception as e:
                self.log(f"❌ ไม่สามารถสร้างโฟลเดอร์ได้: {self.base_save_path} - {e}")
                return
        
        while self.is_running:
            current_url = driver.current_url
            chapter_path = os.path.join(self.base_save_path, str(self.START_CHAPTER))
            if not os.path.exists(chapter_path):
                os.makedirs(chapter_path, exist_ok=True)

            self.log(f"\n📘 --- กำลังประมวลผลตอนที่ {self.START_CHAPTER} ---")

            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "img[src*='page-edge.kakao.com']")))
                self.log("   - 🌐 หน้าเว็บโหลดรูปภาพแล้ว")
            except TimeoutException:
                self.log("   - ⚠️ ไม่สามารถโหลดหน้าเว็บของตอนนี้ได้")
                break

            saved_count = self.download_images(driver, chapter_path)
            self.log(f"   📊 สรุป: บันทึกได้ {saved_count} ภาพ")

            if saved_count == 0:
                self.log("   - 🛑 หยุดการทำงานเนื่องจากดาวน์โหลดไม่สำเร็จ")
                break

            if not self.navigate_to_next(driver):
                break

        self.log("\nจบการทำงาน")
        if not gui_mode:
            input("กด Enter เพื่อปิด...")

# =========================================================================
# --- GUI Application ---
# =========================================================================

class ManhwaDownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Manhwa Downloader - All in One")
        self.root.geometry("900x700")
        self.root.resizable(True, True)
        self.root.configure(bg="#f5f5f5")
        
        # ตั้งค่า style
        self.setup_styles()
        
        self.downloader_thread = None
        self.current_downloader = None
        self.is_running = False
        
        self.setup_ui()
        
    def setup_styles(self):
        """ตั้งค่า styles และ colors"""
        self.colors = {
            'primary': '#3498db',
            'success': '#2ecc71',
            'danger': '#e74c3c',
            'warning': '#f39c12',
            'dark': '#2c3e50',
            'light': '#ecf0f1',
            'bg': '#ffffff',
            'bg_dark': '#34495e',
            'text': '#2c3e50',
            'text_light': '#7f8c8d',
            'border': '#bdc3c7'
        }
        
    def setup_ui(self):
        # Header with gradient effect
        header_frame = tk.Frame(self.root, bg="#2c3e50", height=80)
        header_frame.pack(fill=tk.X)
        header_frame.pack_propagate(False)
        
        # Title with icon
        title_container = tk.Frame(header_frame, bg="#2c3e50")
        title_container.pack(expand=True, fill=tk.BOTH)
        
        title_label = tk.Label(
            title_container,
            text="📚 Manhwa Downloader",
            font=("Tahoma", 20, "bold"),
            bg="#2c3e50",
            fg="#ffffff"
        )
        title_label.pack(pady=(15, 5))
        
        subtitle_label = tk.Label(
            title_container,
            text="All in One - Lezhin | Ridi | Toptoon | Kakao",
            font=("Tahoma", 10),
            bg="#2c3e50",
            fg="#bdc3c7"
        )
        subtitle_label.pack(pady=(0, 15))
        
        # Main container with padding
        main_frame = tk.Frame(self.root, bg="#f5f5f5", padx=25, pady=25)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Platform selection - Card style
        platform_card = tk.Frame(main_frame, bg="#ffffff", relief=tk.FLAT, bd=0)
        platform_card.pack(fill=tk.X, pady=(0, 15))
        
        # Card header
        card_header = tk.Frame(platform_card, bg="#3498db", height=40)
        card_header.pack(fill=tk.X)
        card_header.pack_propagate(False)
        
        header_label = tk.Label(
            card_header,
            text="เลือกแพลตฟอร์ม",
            font=("Tahoma", 12, "bold"),
            bg="#3498db",
            fg="#ffffff"
        )
        header_label.pack(side=tk.LEFT, padx=15, pady=10)
        
        # Card content
        card_content = tk.Frame(platform_card, bg="#ffffff", padx=20, pady=20)
        card_content.pack(fill=tk.X)
        
        self.platform_var = tk.StringVar(value="lezhin")
        
        platforms = [
            ("Lezhin", "lezhin", "#00a8ff"),
            ("Ridi", "ridi", "#9b59b6"),
            ("Toptoon", "toptoon", "#e67e22"),
            ("Kakao", "kakao", "#f1c40f")
        ]
        
        platform_inner = tk.Frame(card_content, bg="#ffffff")
        platform_inner.pack(pady=10)
        
        self.radio_buttons = {}
        for i, (text, value, color) in enumerate(platforms):
            rb_frame = tk.Frame(platform_inner, bg="#ffffff")
            rb_frame.pack(side=tk.LEFT, padx=12)
            
            rb = tk.Radiobutton(
                rb_frame,
                text=text,
                variable=self.platform_var,
                value=value,
                font=("Tahoma", 11, "bold"),
                bg="#ffffff",
                fg=self.colors['text'],
                selectcolor=color,
                activebackground="#ffffff",
                activeforeground=color,
                cursor="hand2",
                indicatoron=0,
                width=14,
                height=2,
                relief=tk.RAISED,
                bd=2,
                highlightthickness=0
            )
            rb.pack()
            self.radio_buttons[value] = rb
            
            # Bind hover effect
            def make_hover(rb=rb, color=color, val=value):
                def on_enter(e):
                    if self.platform_var.get() != val:
                        rb.config(bg="#f0f0f0", relief=tk.RAISED, bd=2)
                def on_leave(e):
                    if self.platform_var.get() != val:
                        rb.config(bg="#ffffff", relief=tk.RAISED, bd=2)
                
                rb.bind("<Enter>", on_enter)
                rb.bind("<Leave>", on_leave)
            make_hover()
        
        # Set initial selection
        self.update_radio_buttons()
        
        # Kakao start chapter input - ใช้ pack() เพราะ card_content ใช้ pack()
        self.kakao_frame = tk.Frame(card_content, bg="#ffffff")
        self.kakao_frame.pack(fill=tk.X, padx=20, pady=(5, 10), anchor=tk.W)
        
        kakao_label = tk.Label(
            self.kakao_frame,
            text="เลขตอนเริ่มต้น:",
            font=("Tahoma", 10),
            bg="#ffffff",
            fg=self.colors['text']
        )
        kakao_label.pack(side=tk.LEFT, padx=(0, 10))
        
        self.kakao_entry = tk.Entry(
            self.kakao_frame,
            width=12,
            font=("Tahoma", 10),
            relief=tk.SOLID,
            bd=1,
            highlightthickness=1,
            highlightcolor="#3498db",
            highlightbackground="#bdc3c7"
        )
        self.kakao_entry.insert(0, "1")
        self.kakao_entry.pack(side=tk.LEFT)
        
        # Save path selection - Card style
        save_path_card = tk.Frame(main_frame, bg="#ffffff", relief=tk.FLAT, bd=0)
        save_path_card.pack(fill=tk.X, pady=(0, 15))
        
        # Card header
        save_path_header = tk.Frame(save_path_card, bg="#27ae60", height=40)
        save_path_header.pack(fill=tk.X)
        save_path_header.pack_propagate(False)
        
        save_path_header_label = tk.Label(
            save_path_header,
            text="📁 โฟลเดอร์บันทึกภาพ",
            font=("Tahoma", 12, "bold"),
            bg="#27ae60",
            fg="#ffffff"
        )
        save_path_header_label.pack(side=tk.LEFT, padx=15, pady=10)
        
        # Card content
        save_path_content = tk.Frame(save_path_card, bg="#ffffff", padx=20, pady=15)
        save_path_content.pack(fill=tk.X)
        
        # Load saved paths
        config = load_config()
        self.save_paths = {}
        for platform in ["lezhin", "ridi", "toptoon", "kakao"]:
            if platform in config and 'save_path' in config[platform]:
                self.save_paths[platform] = config[platform]['save_path']
            else:
                self.save_paths[platform] = DEFAULT_SAVE_PATHS.get(platform, "")
        
        # Path display and browse button
        path_frame = tk.Frame(save_path_content, bg="#ffffff")
        path_frame.pack(fill=tk.X)
        
        path_label = tk.Label(
            path_frame,
            text="โฟลเดอร์:",
            font=("Tahoma", 10),
            bg="#ffffff",
            fg=self.colors['text']
        )
        path_label.pack(side=tk.LEFT, padx=(0, 10))
        
        self.path_var = tk.StringVar(value=self.save_paths.get("lezhin", ""))
        self.path_entry = tk.Entry(
            path_frame,
            textvariable=self.path_var,
            font=("Tahoma", 9),
            relief=tk.SOLID,
            bd=1,
            highlightthickness=1,
            highlightcolor="#3498db",
            highlightbackground="#bdc3c7"
        )
        self.path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # Bind event เพื่อบันทึก path เมื่อแก้ไข
        def on_path_change(*args):
            platform = self.platform_var.get()
            new_path = self.path_var.get()
            if new_path and os.path.exists(new_path):
                self.save_paths[platform] = new_path
                config = load_config()
                if platform not in config:
                    config[platform] = {}
                config[platform]['save_path'] = new_path
                save_config(config)
        
        self.path_var.trace('w', on_path_change)
        
        browse_button = tk.Button(
            path_frame,
            text="📂 เลือกโฟลเดอร์",
            command=self.browse_folder,
            bg="#3498db",
            fg="#ffffff",
            font=("Tahoma", 10, "bold"),
            padx=15,
            pady=5,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            activebackground="#2980b9",
            activeforeground="#ffffff"
        )
        browse_button.pack(side=tk.LEFT)
        
        # Update path when platform changes
        self.platform_var.trace('w', self.on_platform_change)
        # Set initial state
        self.update_radio_buttons()
        self.on_platform_change()
        
        # Control buttons - Modern style
        button_frame = tk.Frame(main_frame, bg="#f5f5f5")
        button_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.start_button = tk.Button(
            button_frame,
            text="▶ เริ่มโหลด",
            command=self.start_download,
            bg=self.colors['success'],
            fg="#ffffff",
            font=("Tahoma", 12, "bold"),
            padx=30,
            pady=12,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            activebackground="#27ae60",
            activeforeground="#ffffff"
        )
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # Hover effect for start button
        def start_hover_enter(e):
            self.start_button.config(bg="#27ae60")
        def start_hover_leave(e):
            self.start_button.config(bg=self.colors['success'])
        self.start_button.bind("<Enter>", start_hover_enter)
        self.start_button.bind("<Leave>", start_hover_leave)
        
        self.stop_button = tk.Button(
            button_frame,
            text="⏹ หยุด",
            command=self.stop_download,
            bg=self.colors['danger'],
            fg="#ffffff",
            font=("Tahoma", 12, "bold"),
            padx=30,
            pady=12,
            state=tk.DISABLED,
            cursor="hand2",
            relief=tk.FLAT,
            bd=0,
            activebackground="#c0392b",
            activeforeground="#ffffff"
        )
        self.stop_button.pack(side=tk.LEFT)
        
        # Hover effect for stop button
        def stop_hover_enter(e):
            if self.stop_button['state'] == 'normal':
                self.stop_button.config(bg="#c0392b")
        def stop_hover_leave(e):
            if self.stop_button['state'] == 'normal':
                self.stop_button.config(bg=self.colors['danger'])
        self.stop_button.bind("<Enter>", stop_hover_enter)
        self.stop_button.bind("<Leave>", stop_hover_leave)
        
        # Log area - Card style
        log_card = tk.Frame(main_frame, bg="#ffffff", relief=tk.FLAT, bd=0)
        log_card.pack(fill=tk.BOTH, expand=True)
        
        # Log header
        log_header = tk.Frame(log_card, bg="#34495e", height=35)
        log_header.pack(fill=tk.X)
        log_header.pack_propagate(False)
        
        log_title = tk.Label(
            log_header,
            text="📋 Log",
            font=("Tahoma", 11, "bold"),
            bg="#34495e",
            fg="#ffffff"
        )
        log_title.pack(side=tk.LEFT, padx=15, pady=8)
        
        # Log content
        log_content = tk.Frame(log_card, bg="#ffffff")
        log_content.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        
        self.log_text = scrolledtext.ScrolledText(
            log_content,
            wrap=tk.WORD,
            font=("Tahoma", 9),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#ffffff",
            relief=tk.FLAT,
            bd=0,
            padx=10,
            pady=10,
            selectbackground="#3498db",
            selectforeground="#ffffff"
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Status bar - Modern style
        self.status_var = tk.StringVar(value="พร้อมใช้งาน")
        status_bar = tk.Frame(self.root, bg="#34495e", height=30)
        status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        status_bar.pack_propagate(False)
        
        status_label = tk.Label(
            status_bar,
            textvariable=self.status_var,
            font=("Tahoma", 9),
            bg="#34495e",
            fg="#ecf0f1",
            anchor=tk.W
        )
        status_label.pack(side=tk.LEFT, padx=15, pady=6)
        
    def update_radio_buttons(self):
        """อัพเดทสีของ radio buttons ตามการเลือก"""
        for value, rb in self.radio_buttons.items():
            if self.platform_var.get() == value:
                colors = {"lezhin": "#00a8ff", "ridi": "#9b59b6", "toptoon": "#e67e22", "kakao": "#f1c40f"}
                rb.config(bg=colors.get(value, "#3498db"), fg="#ffffff", relief=tk.SUNKEN)
            else:
                rb.config(bg="#ffffff", fg=self.colors['text'], relief=tk.RAISED)
    
    def browse_folder(self):
        """เปิด dialog เลือกโฟลเดอร์"""
        current_path = self.path_var.get()
        if not current_path or not os.path.exists(current_path):
            current_path = os.path.expanduser("~")
        
        folder = filedialog.askdirectory(
            title="เลือกโฟลเดอร์บันทึกภาพ",
            initialdir=current_path
        )
        
        if folder:
            platform = self.platform_var.get()
            self.save_paths[platform] = folder
            self.path_var.set(folder)
            
            # บันทึก config
            config = load_config()
            if platform not in config:
                config[platform] = {}
            config[platform]['save_path'] = folder
            save_config(config)
    
    def on_platform_change(self, *args):
        """แสดง/ซ่อน input สำหรับ Kakao และอัพเดท radio buttons และ path"""
        self.update_radio_buttons()
        
        # อัพเดท path display
        platform = self.platform_var.get()
        if platform in self.save_paths:
            self.path_var.set(self.save_paths[platform])
        else:
            self.path_var.set(DEFAULT_SAVE_PATHS.get(platform, ""))
        
        # แสดง/ซ่อน Kakao input
        if self.platform_var.get() == "kakao":
            self.kakao_frame.pack(fill=tk.X, padx=20, pady=(5, 10), anchor=tk.W)
        else:
            self.kakao_frame.pack_forget()
    
    def log(self, message):
        """เพิ่ม log ลงใน text widget"""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def start_download(self):
        """เริ่มการดาวน์โหลด"""
        if self.is_running:
            return
        
        self.is_running = True
        self.start_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        
        platform = self.platform_var.get()
        save_path = self.path_var.get()
        
        # ตรวจสอบและสร้างโฟลเดอร์ถ้ายังไม่มี
        if not save_path:
            save_path = DEFAULT_SAVE_PATHS.get(platform, os.path.join(SCRIPT_DIR, f"{platform.capitalize()}_Download"))
            self.path_var.set(save_path)
            self.save_paths[platform] = save_path
        
        # สร้างโฟลเดอร์ถ้ายังไม่มี
        if not os.path.exists(save_path):
            try:
                os.makedirs(save_path, exist_ok=True)
                self.log(f"📁 สร้างโฟลเดอร์: {save_path}")
                
                # บันทึก config
                config = load_config()
                if platform not in config:
                    config[platform] = {}
                config[platform]['save_path'] = save_path
                save_config(config)
            except Exception as e:
                messagebox.showerror("Error", f"ไม่สามารถสร้างโฟลเดอร์ได้:\n{save_path}\n\n{str(e)}")
                self.is_running = False
                self.start_button.config(state=tk.NORMAL)
                self.stop_button.config(state=tk.DISABLED)
                return
        
        # สร้าง downloader
        if platform == "lezhin":
            self.current_downloader = LezhinDownloader(log_callback=self.log, save_path=save_path)
        elif platform == "ridi":
            self.current_downloader = RidiDownloader(log_callback=self.log, save_path=save_path)
        elif platform == "toptoon":
            self.current_downloader = ToptoonDownloader(log_callback=self.log, save_path=save_path)
        elif platform == "kakao":
            try:
                start_chapter = int(self.kakao_entry.get() or "1")
            except ValueError:
                start_chapter = 1
            self.current_downloader = KakaoDownloader(start_chapter=start_chapter, log_callback=self.log, save_path=save_path)
        
        # รันใน thread แยก
        self.downloader_thread = threading.Thread(target=self.run_downloader, daemon=True)
        self.downloader_thread.start()
        
        self.status_var.set("กำลังทำงาน...")
    
    def run_downloader(self):
        """รัน downloader ใน thread แยก"""
        try:
            self.current_downloader.run(gui_mode=True)
        except Exception as e:
            self.log(f"\n❌ เกิดข้อผิดพลาด: {e}")
        finally:
            self.is_running = False
            self.root.after(0, self.on_download_finished)
    
    def stop_download(self):
        """หยุดการดาวน์โหลด"""
        if self.current_downloader:
            self.current_downloader.is_running = False
        self.is_running = False
        self.log("\n⏹ หยุดการทำงาน...")
        self.on_download_finished()
    
    def on_download_finished(self):
        """เมื่อการดาวน์โหลดเสร็จสิ้น"""
        self.start_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.status_var.set("พร้อมใช้งาน")

# =========================================================================
# --- Main Menu (Console Mode) ---
# =========================================================================

def show_menu():
    print("\n" + "=" * 60)
    print("      MANHWA DOWNLOADER - ALL IN ONE")
    print("=" * 60)
    print("\nเลือกแพลตฟอร์ม:")
    print("  1. Lezhin")
    print("  2. Ridi")
    print("  3. Toptoon")
    print("  4. Kakao")
    print("  0. ออกจากโปรแกรม")
    print("=" * 60)

def main_console():
    while True:
        show_menu()
        choice = input("\n👉 กรุณาเลือก (0-4): ").strip()

        if choice == "0":
            print("\n👋 ขอบคุณที่ใช้งาน!")
            break
        elif choice == "1":
            downloader = LezhinDownloader()
            downloader.run()
        elif choice == "2":
            downloader = RidiDownloader()
            downloader.run()
        elif choice == "3":
            downloader = ToptoonDownloader()
            downloader.run()
        elif choice == "4":
            try:
                start_chapter = int(input("👉 ใส่เลขตอนเริ่มต้น (default: 1): ").strip() or "1")
            except ValueError:
                start_chapter = 1
            downloader = KakaoDownloader(start_chapter=start_chapter)
            downloader.run()
        else:
            print("\n❌ กรุณาเลือกตัวเลข 0-4 เท่านั้น\n")
            time.sleep(1)

def main():
    """Main function - เปิด GUI หรือ Console ตามที่เลือก"""
    import sys
    
    # ถ้ามี argument --console ให้ใช้ console mode
    if "--console" in sys.argv or "-c" in sys.argv:
        main_console()
    else:
        # เปิด GUI
        root = tk.Tk()
        app = ManhwaDownloaderGUI(root)
        root.mainloop()

if __name__ == "__main__":
    main()

