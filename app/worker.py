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
    # ขอให้ GUI ถาม URL ตอนแรกจากผู้ใช้ (login แล้วแต่ไม่มี start_url)
    ask_url_signal = pyqtSignal(str)              # current_url (เป็น hint)

    def __init__(
        self,
        site: str,
        output_path: str,
        start_url: str = "",
        username: str = "",
        password: str = "",
        *,
        number_folders: bool = True,
        start_number: int = 1,
        pad: int = 2,
        merge_enabled: bool = False,
        merge_group: int = 5,
        merge_keep_original: bool = False,
    ):
        super().__init__()
        self.site = site
        self.output_path = output_path
        self.start_url = start_url
        self.username = username
        self.password = password
        # ตัวเลือกตั้งชื่อโฟลเดอร์เป็นเลขลำดับ
        self.number_folders = number_folders
        self.start_number = start_number
        self.pad = pad
        # ตัวเลือก auto-merge หลังโหลดแต่ละตอน
        self.merge_enabled = merge_enabled
        self.merge_group = merge_group
        self.merge_keep_original = merge_keep_original
        self.is_running = True
        self.chrome: ChromeManager | None = None
        # event ที่ตั้งเมื่อผู้ใช้กด OK ใน popup login
        self._login_confirmed = threading.Event()
        # event + ผลลัพธ์ ตอนถาม URL ตอนแรกจากผู้ใช้
        self._url_event = threading.Event()
        self._provided_url: str = ""
        self._url_cancelled = False

    # ------ control ------
    def stop(self):
        # ห้ามแตะ driver จาก GUI thread — worker thread เป็นเจ้าของ driver
        # และจะ quit เองใน finally ของ run() (กัน race สอง thread ใช้ driver พร้อมกัน)
        self.is_running = False
        # ปลด lock ถ้ากำลังรอ login / รอ URL อยู่
        self._login_confirmed.set()
        self._url_event.set()

    def confirm_login(self):
        """เรียกจาก GUI เมื่อผู้ใช้กด OK ใน popup — ปลดล็อกให้ worker ไปต่อ"""
        self._login_confirmed.set()

    def provide_url(self, url: str):
        """เรียกจาก GUI เมื่อผู้ใช้ใส่ URL ตอนแรกในกล่องถาม (เว้นว่าง = ใช้หน้าปัจจุบัน)"""
        self._provided_url = url or ""
        self._url_cancelled = False
        self._url_event.set()

    def cancel_url_prompt(self):
        """เรียกจาก GUI เมื่อผู้ใช้กดยกเลิกในกล่องถาม URL"""
        self._url_cancelled = True
        self._url_event.set()

    def log(self, msg: str):
        self.log_signal.emit(msg)

    # ------ ติดตามสถานะ (หน้า + cookie) ------
    _AUTH_HINTS = (
        "token", "session", "sess", "auth", "access", "refresh",
        "login", "member", "uid", "sid", "passport",
    )

    def _track_page(self, driver, tag: str = ""):
        try:
            url = driver.current_url or "?"
        except Exception:
            url = "?"
        self.log(f"📍 {tag}: {url}")

    def _log_cookies(self, driver):
        """log cookie ที่ "ดูเหมือน session/auth" เพื่อติดตามสถานะ login"""
        try:
            cks = driver.get_cookies()
        except Exception:
            return
        hits = []
        for c in cks:
            name = c.get("name") or ""
            val = c.get("value") or ""
            if not val:
                continue
            ln = name.lower()
            is_jwt = val.count(".") == 2 and len(val) > 40
            if (any(h in ln for h in self._AUTH_HINTS) and len(val) >= 12) or is_jwt:
                hits.append(f"{name}({len(val)}{'·JWT' if is_jwt else ''})")
        self.log(f"🍪 cookies ทั้งหมด {len(cks)} ตัว | คล้าย session: "
                 f"{', '.join(hits) if hits else 'ไม่พบ'}")

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

        def _state():
            try:
                return downloader.is_logged_in(driver)
            except Exception:
                return None

        # 2) ตรวจสถานะ login ณ หน้าปัจจุบัน (พร้อมติดตามหน้า + cookie)
        self._track_page(driver, "หน้าหลัง launch")
        self._log_cookies(driver)
        state = _state()
        if state is True:
            self.log("✅ ตรวจพบว่า login อยู่แล้ว — ไปต่อได้เลย")
            return True

        # 2.5) หน้า login อาจ "ว่าง" เพราะ login ไปแล้ว (bomtoon ไม่โชว์ฟอร์มให้คนที่
        #      login แล้ว) → ลองเปิดหน้าหลักของเว็บ ซึ่งดูสถานะ login ได้ชัดกว่า
        if state is None and downloader.url:
            self.log("🔎 หน้า login ตรวจไม่ชัด (อาจว่างเพราะ login แล้ว) — เปิดหน้าหลักเช็คซ้ำ")
            try:
                driver.get(downloader.url)
                time.sleep(2)
            except Exception as e:
                self.log(f"⚠️ เปิดหน้าหลักไม่ได้: {e}")
            self._track_page(driver, "หน้าหลัก")
            self._log_cookies(driver)
            state = _state()
            if state is True:
                self.log("✅ ตรวจพบว่า login อยู่แล้ว (จากหน้าหลัก) — ไปต่อได้เลย")
                return True

        # 3) ยังไม่ login → พาไปหน้า login แล้วรอผู้ใช้
        try:
            login_path = urlparse(login_url).path if login_url else ""
            cur = driver.current_url or ""
            if login_url and login_path and login_path not in cur:
                self.log(f"🌐 เปิดหน้า login: {login_url}")
                driver.get(login_url)
                time.sleep(2)
                self._track_page(driver, "หน้า login")
        except Exception as e:
            self.log(f"⚠️ เปิดหน้า login ไม่ได้: {e}")

        # เผื่อเพิ่งโหลดหน้า login เสร็จ session อาจมีอยู่แล้ว
        if _state() is True:
            self.log("✅ ตรวจพบว่า login อยู่แล้ว — ไปต่อได้เลย")
            return True

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

    # ------ หา URL ตอนแรก (หลัง login) ------
    def _resolve_start_url(self, downloader, driver, ctx):
        """หา URL ตอนแรกที่จะเริ่มดาวน์โหลด หลัง login เสร็จแล้ว

        ลำดับ:
          1) มี start_url จากช่องกรอก → ใช้เลย
          2) หน้าที่เปิดอยู่ใน Chrome เป็นหน้าอ่าน/ตอนอยู่แล้ว → เริ่มจากนี่
          3) นอกนั้น → ถาม user (กล่อง input) ให้วาง URL หรือเว้นว่างใช้หน้าปัจจุบัน

        คืน:
          "<url>" = ให้ไป (driver.get) URL นี้
          ""      = ใช้หน้าที่เปิดอยู่ตอนนี้ (ไม่ต้อง navigate)
          None    = ผู้ใช้ยกเลิก / ถูกสั่งหยุด
        """
        target = (self.start_url or "").strip()
        if target:
            return target

        try:
            cur = driver.current_url or ""
        except Exception:
            cur = ""

        # หน้าปัจจุบันเป็นหน้าอ่านอยู่แล้ว → เริ่มจากนี่เลย ไม่ต้องถาม
        if downloader.is_chapter_url(cur):
            ctx.log(f"   ✅ หน้าปัจจุบันเป็นหน้าอ่านอยู่แล้ว — เริ่มจากนี่")
            return ""

        # ไม่มี URL และไม่ใช่หน้าอ่าน → ถามผู้ใช้
        self.log("❓ ยังไม่มี URL ตอนแรก — กรุณาเปิดตอนที่ต้องการใน Chrome หรือวาง URL ในกล่องที่เด้งขึ้น")
        self._url_cancelled = False
        self._provided_url = ""
        self._url_event.clear()
        self.ask_url_signal.emit(cur)
        self._url_event.wait()

        if not self.is_running or self._url_cancelled:
            return None

        answer = (self._provided_url or "").strip()
        if answer:
            return answer
        # เว้นว่าง = ใช้หน้าที่เปิดอยู่ตอนนี้ (run_loop จะเริ่มจากหน้าปัจจุบันเอง)
        return ""

    # ------ hook หลังโหลดแต่ละตอน: auto-merge ------
    def _after_chapter(self, save_path: str, saved: int):
        if not self.merge_enabled or saved < 2:
            return
        # import แบบ lazy เผื่อ Pillow ไม่ได้ติดตั้ง
        try:
            from .merge import merge_folder
        except Exception as e:
            self.log(f"   ⚠️ รวมไฟล์อัตโนมัติไม่ได้ (import error): {e}")
            return
        keep = self.merge_keep_original
        self.log(f"   🧩 รวมไฟล์อัตโนมัติ (ทีละ {self.merge_group} รูป, "
                 f"{'เก็บต้นฉบับ' if keep else 'ลบต้นฉบับ'})...")
        try:
            made, src = merge_folder(save_path, self.merge_group, keep, self.log)
            if made:
                self.log(f"   ✅ รวมเสร็จ: {src} รูป → {made} ไฟล์")
        except Exception as e:
            self.log(f"   ⚠️ รวมไฟล์ผิดพลาด: {e}")

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
                folder_start=(self.start_number if self.number_folders else None),
                folder_pad=self.pad,
                after_chapter=self._after_chapter,
            )

            # ---- รับประกัน login เสร็จ "ก่อน" ไปหน้าตอน ----
            if not self._ensure_logged_in(downloader, driver, ctx):
                self.log("⏹ ยกเลิกก่อนเริ่มดาวน์โหลด")
                self.finished_signal.emit(False, "ยกเลิกก่อนเริ่มดาวน์โหลด")
                return

            if not self.is_running:
                self.finished_signal.emit(False, "หยุดการทำงาน")
                return

            # ---- login เสร็จแล้วค่อยหา URL ตอนที่ 1 (ถาม user ถ้าจำเป็น) ----
            target = self._resolve_start_url(downloader, driver, ctx)
            if target is None:
                self.log("⏹ ยกเลิกตอนถาม URL ตอนแรก")
                self.finished_signal.emit(False, "ยกเลิกก่อนเริ่มดาวน์โหลด")
                return

            if not self.is_running:
                self.finished_signal.emit(False, "หยุดการทำงาน")
                return

            if target:
                self.log(f"🌐 ไปยังตอนแรก: {target}")
                try:
                    driver.get(target)
                    time.sleep(5)
                except Exception as e:
                    self.log(f"⚠️ เปิด URL ตอนแรกไม่ได้: {e}")
            else:
                self.log("ℹ️ เริ่มจากหน้าที่เปิดอยู่ใน Chrome")

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


class MergeWorker(QThread):
    """รวมไฟล์เองใน background thread (ไม่ block GUI)

    รับโฟลเดอร์ที่ผู้ใช้เลือก แล้วรวมรูปในโฟลเดอร์นั้น + โฟลเดอร์ย่อยทั้งหมด
    """

    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)

    def __init__(
        self,
        folder: str,
        group_size: int = 5,
        keep_original: bool = False,
    ):
        super().__init__()
        self.folder = folder
        self.group_size = group_size
        self.keep_original = keep_original
        self.is_running = True

    def stop(self):
        self.is_running = False

    def log(self, msg: str):
        self.log_signal.emit(msg)

    def run(self):
        try:
            from .merge import merge_tree, _PIL_AVAILABLE
            if not _PIL_AVAILABLE:
                self.finished_signal.emit(False, "ไม่พบ Pillow — pip install Pillow")
                return
            if not os.path.isdir(self.folder):
                self.finished_signal.emit(False, "ไม่พบโฟลเดอร์ที่เลือก")
                return

            self.log("=" * 60)
            self.log(f"🧩 เริ่มรวมไฟล์: {self.folder}")
            self.log(f"   ทีละ {self.group_size} รูป · "
                     f"{'เก็บต้นฉบับไว้ใน _merged/' if self.keep_original else 'ลบต้นฉบับ เหลือแค่ไฟล์รวม'}")
            self.log("=" * 60)

            folders, files = merge_tree(
                self.folder,
                self.group_size,
                self.keep_original,
                log=self.log,
                is_running=lambda: self.is_running,
            )
            if not self.is_running:
                self.finished_signal.emit(False, "หยุดการรวมไฟล์")
                return
            if folders == 0:
                self.finished_signal.emit(False, "ไม่พบรูปที่จะรวม (หรือมีน้อยกว่า 2 รูป)")
            else:
                self.finished_signal.emit(
                    True, f"รวมเสร็จ {folders} โฟลเดอร์ → {files} ไฟล์"
                )
        except Exception as e:
            self.log(f"❌ รวมไฟล์ผิดพลาด: {e}")
            self.finished_signal.emit(False, f"รวมไฟล์ผิดพลาด: {e}")
