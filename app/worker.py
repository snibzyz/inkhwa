"""Background worker that drives the chosen downloader inside a QThread."""
from __future__ import annotations

import os
import threading
import time
from urllib.parse import urlparse

from PyQt6.QtCore import QThread, pyqtSignal

from downloaders import (
    BaseDownloader,
    ChromeManager,
    DownloaderContext,
    get_downloader,
)

from .paths import shared_profile_path, ensure_dirs


class DownloadWorker(QThread):
    """รัน downloader ใน background thread เพื่อไม่ block GUI"""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)        # current, total
    finished_signal = pyqtSignal(bool, str)       # success, message

    # ขอให้ GUI โชว์ popup ให้ผู้ใช้ login แล้วกด OK
    login_prompt_signal = pyqtSignal(str)         # message
    # บอก GUI ให้ปิด popup login (กรณีตรวจพบว่า login แล้วเอง)
    login_close_signal = pyqtSignal()

    def __init__(
        self,
        site: str,
        output_path: str,
        start_url: str = "",
        username: str = "",
        password: str = "",
    ):
        super().__init__()
        self.site = site
        self.output_path = output_path
        self.start_url = start_url
        self.username = username
        self.password = password
        self.is_running = True
        self.chrome: ChromeManager | None = None
        # event ที่ตั้งเมื่อผู้ใช้กด OK ใน popup login
        self._login_confirmed = threading.Event()

    # ------ control ------
    def stop(self):
        # ห้ามแตะ driver จาก GUI thread — worker thread เป็นเจ้าของ driver
        # และจะ quit เองใน finally ของ run() (กัน race สอง thread ใช้ driver พร้อมกัน)
        self.is_running = False
        # ปลด lock ถ้ากำลังรอ login อยู่
        self._login_confirmed.set()

    def confirm_login(self):
        """เรียกจาก GUI เมื่อผู้ใช้กด OK ใน popup — ปลดล็อกให้ worker ไปต่อ"""
        self._login_confirmed.set()

    def log(self, msg: str):
        self.log_signal.emit(msg)

    # ------ login gate ------
    def _ensure_logged_in(self, downloader, driver, ctx) -> bool:
        """รับประกันว่า user login เสร็จก่อนไปโหลดตอน

        ลำดับ:
          1) ลอง auto-login ถ้ามี credentials + เว็บรองรับ
          2) ตรวจสถานะ login (is_logged_in)
          3) ถ้ายังไม่ login → เปิดหน้า login + เด้ง popup ให้ผู้ใช้ login แล้วกด OK
             ระหว่างรอ ถ้าตรวจพบว่า login แล้วจะปิด popup ให้อัตโนมัติ
        คืน True เมื่อพร้อมไปต่อ, False เมื่อถูกสั่งหยุด
        """
        login_url = downloader.get_login_url()
        supports_autologin = type(downloader).login is not BaseDownloader.login

        # 1) auto-login (เฉพาะเว็บที่รองรับ เช่น Bomtoon)
        if self.username and self.password and supports_autologin:
            self.log(f"🔐 ลอง auto-login ด้วย {self.username}")
            try:
                if downloader.login(driver, self.username, self.password, ctx):
                    self.log("   ✅ auto-login สำเร็จ")
                else:
                    self.log("   ⚠️ auto-login ไม่สำเร็จ — ให้ login เองในหน้าต่าง Chrome")
            except Exception as e:
                self.log(f"   ⚠️ auto-login error: {e}")
        elif self.username and self.password:
            self.log("ℹ️ เว็บนี้ยังไม่รองรับ auto-login — กรุณา login เองในหน้าต่าง Chrome")

        if not self.is_running:
            return False

        # 2) ตรวจสถานะ login ตอนนี้
        try:
            state = downloader.is_logged_in(driver)
        except Exception:
            state = None
        if state is True:
            self.log("✅ ตรวจพบว่า login อยู่แล้ว — ไปต่อได้เลย")
            return True

        # 3) ยังไม่ login → พาไปหน้า login แล้วรอผู้ใช้
        # เทียบด้วย host (ไม่ใช่ substring) เพราะ SSO เช่น Kakao จะ rewrite query string
        try:
            want_host = urlparse(login_url).netloc if login_url else ""
            cur_host = urlparse(driver.current_url or "").netloc
            if login_url and want_host and want_host != cur_host:
                self.log(f"🌐 เปิดหน้า login: {login_url}")
                driver.get(login_url)
                time.sleep(2)
        except Exception as e:
            self.log(f"⚠️ เปิดหน้า login ไม่ได้: {e}")

        # เผื่อเพิ่งโหลดหน้า login เสร็จ session อาจมีอยู่แล้ว
        try:
            if downloader.is_logged_in(driver) is True:
                self.log("✅ ตรวจพบว่า login อยู่แล้ว — ไปต่อได้เลย")
                return True
        except Exception:
            pass

        self.log("⏳ กรุณา login ในหน้าต่าง Chrome ที่เปิดขึ้น แล้วกด OK ใน popup")
        self._login_confirmed.clear()
        self.login_prompt_signal.emit(
            "กรุณา Login ในหน้าต่าง Chrome ที่เปิดขึ้นมา\n\n"
            "เมื่อ Login เสร็จแล้ว ให้กด OK เพื่อเริ่มดาวน์โหลด\n"
            "(ระบบจะตรวจจับให้อัตโนมัติด้วย ถ้า login สำเร็จ)"
        )

        # รอจนกว่า: ผู้ใช้กด OK / ตรวจพบว่า login แล้ว / ถูกสั่งหยุด
        auto_detected = False
        while self.is_running and not self._login_confirmed.is_set():
            try:
                if downloader.is_logged_in(driver) is True:
                    auto_detected = True
                    self.log("✅ ตรวจพบว่า login สำเร็จแล้ว — เริ่มดาวน์โหลดอัตโนมัติ")
                    self.login_close_signal.emit()   # ปิด popup ให้
                    break
            except Exception:
                pass
            time.sleep(1.0)

        if not self.is_running:
            return False

        # ผู้ใช้กด OK เอง — เช็คซ้ำอีกที (เตือนแต่ไม่บล็อก)
        if not auto_detected:
            try:
                if downloader.is_logged_in(driver) is False:
                    self.log("   ⚠️ ยังตรวจไม่พบสถานะ login — จะลองโหลดต่อให้")
            except Exception:
                pass
            self.log("   ▶️ ผู้ใช้ยืนยัน login แล้ว — ไปต่อ")
        return True

    # ------ main ------
    def run(self):
        try:
            self.log("=" * 60)
            self.log(f"🚀 เริ่มดาวน์โหลดจาก {self.site}")
            self.log("=" * 60)
            self.log(f"📁 Output: {self.output_path}")
            os.makedirs(self.output_path, exist_ok=True)

            downloader = get_downloader(self.site)
            ensure_dirs()

            # ใช้ Chrome profile เดียวร่วมกันทุกเว็บ → login ครั้งเดียวจำได้หมด
            self.chrome = ChromeManager(
                profile_dir=shared_profile_path(),
                log=self.log,
            )

            # เปิด Chrome ที่ "หน้า login" ก่อนเสมอ (ไม่ใช่วิ่งไปตอน 1 ทันที)
            login_url = downloader.get_login_url()
            driver = self.chrome.launch(start_url=login_url)

            ctx = DownloaderContext(
                log=self.log,
                progress=lambda c, t: self.progress_signal.emit(c, t),
                is_running=lambda: self.is_running,
            )

            # ---- รับประกัน login เสร็จ "ก่อน" ไปหน้าตอน ----
            if not self._ensure_logged_in(downloader, driver, ctx):
                self.log("⏹ ยกเลิกก่อนเริ่มดาวน์โหลด")
                self.finished_signal.emit(False, "ยกเลิกก่อนเริ่มดาวน์โหลด")
                return

            if not self.is_running:
                self.finished_signal.emit(False, "หยุดการทำงาน")
                return

            # ---- login เสร็จแล้วค่อยไป URL ตอนที่ 1 ----
            if self.start_url and self.start_url.strip():
                target = self.start_url.strip()
                self.log(f"🌐 ไปยังตอนแรก: {target}")
                try:
                    driver.get(target)
                    time.sleep(5)
                except Exception as e:
                    self.log(f"⚠️ เปิด URL ตอนแรกไม่ได้: {e}")
            else:
                self.log("ℹ️ ไม่ได้ใส่ URL ตอนแรก — จะเริ่มจากหน้าที่เปิดอยู่ใน Chrome")

            if not self.is_running:
                self.finished_signal.emit(False, "หยุดการทำงาน")
                return

            downloader.run_loop(driver, self.output_path, ctx)
            if self.is_running:
                self.finished_signal.emit(True, "ดาวน์โหลดเสร็จสิ้น")
            else:
                self.finished_signal.emit(False, "หยุดการทำงาน")

        except Exception as e:
            self.log(f"❌ เกิดข้อผิดพลาด: {e}")
            self.finished_signal.emit(False, f"เกิดข้อผิดพลาด: {e}")
        finally:
            if self.chrome:
                self.chrome.quit()
