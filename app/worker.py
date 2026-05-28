"""Background worker that drives the chosen downloader inside a QThread."""
from __future__ import annotations

import os
import time

from PyQt6.QtCore import QThread, pyqtSignal

from downloaders import ChromeManager, DownloaderContext, get_downloader

from .paths import profile_path, ensure_dirs


class DownloadWorker(QThread):
    """รัน downloader ใน background thread เพื่อไม่ block GUI"""

    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int, int)        # current, total
    finished_signal = pyqtSignal(bool, str)       # success, message

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

    # ------ control ------
    def stop(self):
        self.is_running = False
        if self.chrome:
            self.chrome.quit()

    def log(self, msg: str):
        self.log_signal.emit(msg)

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

            self.chrome = ChromeManager(
                profile_dir=profile_path(downloader.profile_dir),
                log=self.log,
            )
            initial_url = self.start_url.strip() if self.start_url else downloader.url
            driver = self.chrome.launch(start_url=initial_url)

            ctx = DownloaderContext(
                log=self.log,
                progress=lambda c, t: self.progress_signal.emit(c, t),
                is_running=lambda: self.is_running,
            )

            # auto-login ถ้ามี credentials + downloader รองรับ
            if self.username and self.password:
                self.log(f"🔐 ลอง auto-login ด้วย {self.username}")
                if not downloader.login(driver, self.username, self.password, ctx):
                    self.log("⚠️ auto-login ไม่สำเร็จ — ดำเนินต่อ (อาจต้อง login ในหน้าต่างเอง)")
            else:
                self.log("\n[พร้อมทำงาน]")
                self.log("1. Login ในหน้าต่าง Chrome ที่เปิดขึ้น")
                self.log("2. เปิดหน้าตอนแรกที่ต้องการ")
                self.log("⏳ รอ 12 วินาที ก่อนเริ่มสแกน...")
                for _ in range(12):
                    if not self.is_running:
                        return
                    time.sleep(1)

            if not self.is_running:
                return

            # ถ้ามี start URL ให้ไปหน้านั้นหลัง login เสร็จ
            if self.start_url and self.start_url.strip():
                self.log(f"🌐 ไปยัง URL: {self.start_url}")
                try:
                    driver.get(self.start_url.strip())
                    time.sleep(5)
                except Exception as e:
                    self.log(f"⚠️ เปิด URL ไม่ได้: {e}")

            downloader.run_loop(driver, self.output_path, ctx)
            self.finished_signal.emit(True, "ดาวน์โหลดเสร็จสิ้น")

        except Exception as e:
            self.log(f"❌ เกิดข้อผิดพลาด: {e}")
            self.finished_signal.emit(False, f"เกิดข้อผิดพลาด: {e}")
        finally:
            if self.chrome:
                self.chrome.quit()
