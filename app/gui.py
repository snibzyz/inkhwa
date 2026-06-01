"""Modern PyQt6 GUI — dark theme, card layout, copyable log"""
from __future__ import annotations

import os
import sys
import time
import webbrowser

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QFileDialog,
    QGroupBox, QMessageBox, QProgressBar, QFrame, QInputDialog, QDialog,
    QCheckBox, QSpinBox,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QGuiApplication

from downloaders import list_sites

from .paths import DEFAULT_OUTPUT_DIR, PROJECT_ROOT
from .presets import add_to_history, load_history
from .config import load_config, save_config
from .styles import (
    APP_QSS, COLOR_TEXT, COLOR_TEXT_DIM, COLOR_ACCENT, COLOR_SURFACE,
    COLOR_SURFACE_HI, COLOR_BORDER, COLOR_BG,
    log_style, primary_button_style, danger_button_style, secondary_button_style,
)
from .worker import DownloadWorker, MergeWorker
from .version import __version__, REPO_URL
from .updater import UpdateChecker, apply_update


class ManhwaDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: DownloadWorker | None = None
        self.merge_worker: MergeWorker | None = None
        self._login_box: QMessageBox | None = None
        self._login_cancel_btn = None
        self._url_box: QInputDialog | None = None
        self.update_checker: UpdateChecker | None = None
        self._init_ui()
        self._apply_config(load_config())   # คืนค่าตั้งล่าสุด
        self._start_update_check()

    # ----------------- UI -----------------
    def _init_ui(self):
        self.setWindowTitle("Inkhwa — ตัวโหลดมันฮวา")
        # min สูงพอให้ทุกการ์ดกางเต็ม (กันแถวทับกันโดยไม่ต้องมี scroll)
        self.setMinimumSize(QSize(900, 880))
        self.resize(1100, 950)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        outer.addWidget(self._build_header())

        body = QWidget()
        b = QVBoxLayout(body)
        b.setSpacing(12)
        b.setContentsMargins(24, 14, 24, 16)

        # 1) เลือกเว็บ + URL ตอนเริ่ม
        row1 = QHBoxLayout()
        row1.setSpacing(12)
        row1.addWidget(self._build_site_card(), stretch=1)
        row1.addWidget(self._build_url_card(), stretch=2)
        b.addLayout(row1)

        # 2) บันทึกไฟล์ (โฟลเดอร์ + ตั้งชื่อ + รวมอัตโนมัติ) รวมเป็นการ์ดเดียว
        b.addWidget(self._build_save_card())

        # 3) เข้าสู่ระบบ + รวมไฟล์เอง วางเคียงกัน
        row3 = QHBoxLayout()
        row3.setSpacing(12)
        row3.addWidget(self._build_login_card(), stretch=1)
        row3.addWidget(self._build_merge_card(), stretch=1)
        b.addLayout(row3)

        # 4) ปุ่มเริ่ม/หยุด
        b.addWidget(self._build_actions())

        # 5) บันทึกการทำงาน (ยืดเต็มที่เหลือ)
        b.addWidget(self._build_log_card(), stretch=1)

        outer.addWidget(body, stretch=1)
        self.statusBar().showMessage("พร้อมใช้งาน")

    # -- header
    def _build_header(self) -> QWidget:
        h = QFrame()
        h.setStyleSheet(
            "QFrame { background-color: #131922; border-bottom: 1px solid #2A3441; }"
        )
        lay = QHBoxLayout(h)
        lay.setContentsMargins(28, 18, 28, 18)
        lay.setSpacing(14)

        title = QLabel("📚  Inkhwa")
        title.setStyleSheet(
            f"color: {COLOR_TEXT}; font-size: 22pt; font-weight: 700;"
        )
        lay.addWidget(title)

        subtitle = QLabel("ตัวโหลดมันฮวา")
        subtitle.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11pt;"
            "padding-left: 4px;"
        )
        lay.addWidget(subtitle)

        lay.addStretch()

        self.version_label = QLabel(f"v{__version__}")
        self.version_label.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 9pt;"
            f"background: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER};"
            "padding: 6px 12px; border-radius: 12px;"
        )
        self.version_label.setToolTip(f"Inkhwa v{__version__}\n{REPO_URL}")
        lay.addWidget(self.version_label)

        sites_badge = QLabel(" · ".join(list_sites()))
        sites_badge.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 10pt;"
            f"background: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER};"
            "padding: 7px 14px; border-radius: 14px;"
        )
        lay.addWidget(sites_badge)
        return h

    # -- cards
    def _build_site_card(self) -> QGroupBox:
        box = QGroupBox("🌐  เว็บไซต์")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)
        self.site_combo = QComboBox()
        self.site_combo.setMinimumHeight(42)
        for s in list_sites():
            self.site_combo.addItem(s)
        v.addWidget(self.site_combo)
        v.addStretch()
        return box

    def _build_url_card(self) -> QGroupBox:
        box = QGroupBox("🔗  URL ตอนที่เริ่ม")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(6)

        self.url_edit = QLineEdit()
        self.url_edit.setMinimumHeight(42)
        self.url_edit.setPlaceholderText("https://www.bomtoon.com/viewer/<ชื่อเรื่อง>/<ตอน>")
        v.addWidget(self.url_edit)

        hint = QLabel("วาง URL ตอนเริ่ม แล้วไล่โหลดจนจบ (เว้นว่างได้ เดี๋ยวถามทีหลัง)")
        hint.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 9pt;")
        hint.setWordWrap(True)
        v.addWidget(hint)
        return box

    def _spin(self, lo: int, hi: int, val: int, width: int = 90) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(val)
        s.setFixedHeight(36)
        s.setFixedWidth(width)
        return s

    def _build_save_card(self) -> QGroupBox:
        box = QGroupBox("💾  บันทึกไฟล์")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(9)

        # --- แถวโฟลเดอร์บันทึก ---
        frow = QHBoxLayout()
        frow.setSpacing(8)
        frow.addWidget(self._make_label("โฟลเดอร์", 64))
        self.output_edit = QLineEdit()
        self.output_edit.setMinimumHeight(40)
        self.output_edit.setText(DEFAULT_OUTPUT_DIR)
        frow.addWidget(self.output_edit, stretch=1)
        browse = QPushButton("เลือก")
        browse.setStyleSheet(secondary_button_style())
        browse.setFixedHeight(40)
        browse.clicked.connect(self._browse_output)
        open_btn = QPushButton("เปิด")
        open_btn.setStyleSheet(secondary_button_style())
        open_btn.setFixedHeight(40)
        open_btn.clicked.connect(self._open_output)
        frow.addWidget(browse)
        frow.addWidget(open_btn)
        v.addLayout(frow)

        # --- แถวตั้งชื่อโฟลเดอร์เป็นเลขลำดับ ---
        nrow = QHBoxLayout()
        nrow.setSpacing(8)
        self.number_chk = QCheckBox("ตั้งชื่อเป็นเลขลำดับ")
        self.number_chk.setChecked(True)
        self.number_chk.setMinimumHeight(32)
        nrow.addWidget(self.number_chk)
        nrow.addSpacing(14)
        nrow.addWidget(self._make_label("เริ่มที่ตอน", 66))
        self.start_num_spin = self._spin(0, 99999, 1, 84)
        nrow.addWidget(self.start_num_spin)
        nrow.addSpacing(14)
        nrow.addWidget(self._make_label("จำนวนหลัก", 74))
        self.pad_spin = self._spin(1, 6, 2, 64)
        nrow.addWidget(self.pad_spin)
        nrow.addStretch()
        v.addLayout(nrow)

        # --- แถวรวมไฟล์อัตโนมัติ ---
        mrow = QHBoxLayout()
        mrow.setSpacing(8)
        self.merge_chk = QCheckBox("รวมไฟล์อัตโนมัติ")
        self.merge_chk.setChecked(True)          # เปิดเป็นค่าเริ่มต้น (รวมทีละ 5)
        self.merge_chk.setMinimumHeight(32)
        mrow.addWidget(self.merge_chk)
        mrow.addSpacing(14)
        mrow.addWidget(self._make_label("ทีละ", 38))
        self.merge_group_spin = self._spin(2, 50, 5, 72)
        mrow.addWidget(self.merge_group_spin)
        mrow.addWidget(self._make_label("รูป", 30))
        mrow.addSpacing(16)
        self.merge_keep_chk = QCheckBox("เก็บไฟล์ต้นฉบับ")
        self.merge_keep_chk.setMinimumHeight(32)
        self.merge_keep_chk.setToolTip("ไม่ติ๊ก = ลบไฟล์ต้นฉบับ เหลือแค่ไฟล์รวม")
        mrow.addWidget(self.merge_keep_chk)
        mrow.addStretch()
        v.addLayout(mrow)

        # คำแนะนำย่อ (เก็บไว้ใน tooltip กันการ์ดสูงไม่เท่ากันเมื่อข้อความตัดบรรทัด)
        self.number_chk.setToolTip("เช่น เริ่มที่ตอน 5 + จำนวนหลัก 2 → โฟลเดอร์ 05, 06, 07 …")

        # เปิด/ปิดช่องตามสถานะ checkbox
        self.number_chk.toggled.connect(self._sync_number_enabled)
        self.merge_chk.toggled.connect(self._sync_merge_enabled)
        self._sync_number_enabled(self.number_chk.isChecked())
        self._sync_merge_enabled(self.merge_chk.isChecked())
        return box

    def _build_login_card(self) -> QGroupBox:
        box = QGroupBox("🔐  เข้าสู่ระบบ (ไม่บังคับ)")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        # user (combobox editable — แสดงรายชื่อที่เคยใช้)
        urow = QHBoxLayout()
        urow.setSpacing(10)
        urow.addWidget(self._make_label("ผู้ใช้", 70))
        self.user_edit = QComboBox()
        self.user_edit.setEditable(True)
        self.user_edit.setMinimumHeight(40)
        history = load_history()
        if history:
            self.user_edit.addItems(history)
            self.user_edit.setCurrentText("")
        urow.addWidget(self.user_edit, stretch=1)
        v.addLayout(urow)

        # password (ไม่บันทึก — ต้องใส่ใหม่ทุกครั้ง)
        pwrow = QHBoxLayout()
        pwrow.setSpacing(10)
        pwrow.addWidget(self._make_label("รหัสผ่าน", 70))
        self.pw_edit = QLineEdit()
        self.pw_edit.setMinimumHeight(40)
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setPlaceholderText("ไม่บันทึกรหัสผ่าน — ใส่ใหม่ทุกครั้ง")
        pwrow.addWidget(self.pw_edit, stretch=1)
        self.pw_show_btn = QPushButton("แสดง")
        self.pw_show_btn.setCheckable(True)
        self.pw_show_btn.setStyleSheet(secondary_button_style())
        self.pw_show_btn.setFixedSize(86, 40)
        self.pw_show_btn.toggled.connect(self._toggle_pw_visibility)
        pwrow.addWidget(self.pw_show_btn)
        v.addLayout(pwrow)
        box.setToolTip("ปกติล็อกอินในหน้าต่าง Chrome ได้เลย ไม่ต้องกรอกที่นี่")
        v.addStretch()
        box.setMinimumHeight(132)
        return box

    def _build_merge_card(self) -> QGroupBox:
        box = QGroupBox("🧩  รวมไฟล์เอง")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.merge_path_edit = QLineEdit()
        self.merge_path_edit.setMinimumHeight(40)
        self.merge_path_edit.setText(DEFAULT_OUTPUT_DIR)
        browse = QPushButton("เลือก")
        browse.setStyleSheet(secondary_button_style())
        browse.setFixedHeight(40)
        browse.clicked.connect(self._browse_merge)
        row.addWidget(self.merge_path_edit, stretch=1)
        row.addWidget(browse)
        v.addLayout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(self._make_label("ทีละ", 38))
        self.merge_manual_group = self._spin(2, 50, 5, 72)
        row2.addWidget(self.merge_manual_group)
        row2.addWidget(self._make_label("รูป", 30))
        row2.addSpacing(12)
        self.merge_manual_keep = QCheckBox("เก็บต้นฉบับ")
        self.merge_manual_keep.setMinimumHeight(32)
        row2.addWidget(self.merge_manual_keep)
        row2.addStretch()
        self.merge_btn = QPushButton("รวมไฟล์เลย")
        self.merge_btn.setStyleSheet(primary_button_style())
        self.merge_btn.setMaximumWidth(160)
        self.merge_btn.clicked.connect(self._start_merge)
        row2.addWidget(self.merge_btn)
        v.addLayout(row2)
        box.setToolTip("เลือกโฟลเดอร์ตอน หรือโฟลเดอร์ใหญ่ที่มีหลายตอน — รวมรูปในทุกโฟลเดอร์ย่อยให้")
        v.addStretch()
        box.setMinimumHeight(132)
        return box

    def _make_label(self, text: str, min_w: int = 80) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11pt; font-weight: 500;"
        )
        lbl.setMinimumWidth(min_w)
        return lbl

    def _build_actions(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 4, 0, 4)
        row.setSpacing(12)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        row.addWidget(self.progress_bar, stretch=1)

        self.stop_btn = QPushButton("⏹  หยุด")
        self.stop_btn.setStyleSheet(danger_button_style())
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_download)
        row.addWidget(self.stop_btn)

        self.start_btn = QPushButton("▶  เริ่มดาวน์โหลด")
        self.start_btn.setStyleSheet(primary_button_style())
        self.start_btn.clicked.connect(self._start_download)
        row.addWidget(self.start_btn)
        return w

    def _build_log_card(self) -> QGroupBox:
        box = QGroupBox("📋  บันทึกการทำงาน")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(8)

        # log actions row
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        copy_btn = QPushButton("คัดลอก")
        copy_btn.setStyleSheet(secondary_button_style())
        copy_btn.setMaximumWidth(96)
        copy_btn.clicked.connect(self._copy_log)
        save_btn = QPushButton("บันทึก…")
        save_btn.setStyleSheet(secondary_button_style())
        save_btn.setMaximumWidth(96)
        save_btn.clicked.connect(self._save_log)
        clear_btn = QPushButton("ล้าง")
        clear_btn.setStyleSheet(secondary_button_style())
        clear_btn.setMaximumWidth(96)
        clear_btn.clicked.connect(self._clear_log)
        actions.addWidget(copy_btn)
        actions.addWidget(save_btn)
        actions.addWidget(clear_btn)
        v.addLayout(actions)

        # log text (QPlainTextEdit = read-only แต่ select+copy ได้)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(140)
        self.log_text.setStyleSheet(log_style())
        self.log_text.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        v.addWidget(self.log_text)
        return box

    # ----------------- handlers -----------------
    def _toggle_pw_visibility(self, checked: bool):
        self.pw_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        self.pw_show_btn.setText("ซ่อน" if checked else "แสดง")

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์บันทึก")
        if folder:
            self.output_edit.setText(folder)
            self._log(f"โฟลเดอร์บันทึก: {folder}")

    def _open_output(self):
        path = self.output_edit.text().strip()
        if not path:
            return
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)  # Windows only
        except Exception as e:
            QMessageBox.warning(self, "ผิดพลาด", f"เปิดโฟลเดอร์ไม่ได้: {e}")

    # ----- options enable/disable -----
    def _sync_number_enabled(self, on: bool):
        self.start_num_spin.setEnabled(on)
        self.pad_spin.setEnabled(on)

    def _sync_merge_enabled(self, on: bool):
        self.merge_group_spin.setEnabled(on)
        self.merge_keep_chk.setEnabled(on)

    # ----- manual merge -----
    def _browse_merge(self):
        start = self.merge_path_edit.text().strip() or DEFAULT_OUTPUT_DIR
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์ที่จะรวมไฟล์", start)
        if folder:
            self.merge_path_edit.setText(folder)

    def _start_merge(self):
        if self.merge_worker is not None:
            return
        folder = self.merge_path_edit.text().strip()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "แจ้งเตือน", "กรุณาเลือกโฟลเดอร์ที่มีรูปก่อน")
            return
        group = self.merge_manual_group.value()
        keep = self.merge_manual_keep.isChecked()
        if not keep:
            reply = QMessageBox.question(
                self, "ยืนยันการรวมไฟล์",
                f"จะรวมรูปในโฟลเดอร์:\n{folder}\n\n"
                f"ทีละ {group} รูป และ ลบรูปต้นฉบับ เหลือแค่ไฟล์รวม\n\nดำเนินการต่อไหม?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.merge_btn.setEnabled(False)
        self.merge_worker = MergeWorker(folder, group, keep)
        self.merge_worker.log_signal.connect(self._log)
        self.merge_worker.finished_signal.connect(self._on_merge_finished)
        self.merge_worker.start()
        self.statusBar().showMessage("🧩 กำลังรวมไฟล์...")

    def _on_merge_finished(self, ok: bool, msg: str):
        self.merge_btn.setEnabled(True)
        self.merge_worker = None
        self.statusBar().showMessage(("✅ " if ok else "❌ ") + msg, 6000)
        if ok:
            QMessageBox.information(self, "รวมไฟล์เสร็จ", msg)
        else:
            QMessageBox.warning(self, "รวมไฟล์", msg)

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{ts}] {msg}")
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_log(self):
        text = self.log_text.toPlainText()
        QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"📋 คัดลอกแล้ว {len(text)} ตัวอักษร", 3000)

    def _save_log(self):
        default = os.path.join(
            PROJECT_ROOT, f"inkhwa-log-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "บันทึก log", default, "ไฟล์ข้อความ (*.txt);;ทุกไฟล์ (*.*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.log_text.toPlainText())
                self.statusBar().showMessage(f"💾 บันทึก log → {path}", 4000)
            except Exception as e:
                QMessageBox.warning(self, "ผิดพลาด", f"บันทึก log ไม่ได้: {e}")

    def _clear_log(self):
        self.log_text.clear()

    def _start_download(self):
        site = self.site_combo.currentText()
        output = self.output_edit.text().strip()
        start_url = self.url_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "แจ้งเตือน", "กรุณาเลือกโฟลเดอร์บันทึกก่อน")
            return
        try:
            os.makedirs(output, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "ผิดพลาด", f"สร้างโฟลเดอร์ไม่ได้: {e}")
            return
        if start_url and not (start_url.startswith("http://") or start_url.startswith("https://")):
            QMessageBox.warning(self, "แจ้งเตือน", "URL ต้องขึ้นต้นด้วย http:// หรือ https://")
            return

        username = self.user_edit.currentText().strip()
        password = self.pw_edit.text().strip()

        if username:
            add_to_history(username)

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("0%")

        self.worker = DownloadWorker(
            site, output, start_url, username, password,
            number_folders=self.number_chk.isChecked(),
            start_number=self.start_num_spin.value(),
            pad=self.pad_spin.value(),
            merge_enabled=self.merge_chk.isChecked(),
            merge_group=self.merge_group_spin.value(),
            merge_keep_original=self.merge_keep_chk.isChecked(),
        )
        self.worker.log_signal.connect(self._log)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.login_prompt_signal.connect(self._on_login_prompt)
        self.worker.login_close_signal.connect(self._on_login_close)
        self.worker.ask_url_signal.connect(self._on_ask_url)
        self.worker.start()
        self.statusBar().showMessage(f"🚀 Downloading from {site}...")

    def _stop_download(self):
        if self.worker:
            self.worker.stop()
            self._log("⏹ Stopping...")
            self.statusBar().showMessage("⏸ Stopping...")

    def _on_progress(self, cur: int, total: int):
        if total > 0:
            self.progress_bar.setValue(int(cur / total * 100))
            self.progress_bar.setFormat(f"{cur}/{total} — %p%")
            self.statusBar().showMessage(f"📥 {cur}/{total} images")

    def _on_finished(self, ok: bool, msg: str):
        # ปิด popup login ถ้ายังค้างอยู่
        if self._login_box is not None:
            self._login_box.done(0)
            self._login_box = None
        # ปิดกล่องถาม URL ถ้ายังค้างอยู่
        if self._url_box is not None:
            self._url_box.done(0)
            self._url_box = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage(("✅ " if ok else "❌ ") + msg)
        if ok:
            QMessageBox.information(self, "เสร็จสิ้น", msg)
        else:
            QMessageBox.warning(self, "ผิดพลาด", msg)
        self.worker = None

    # ----------------- login popup -----------------
    def _on_login_prompt(self, message: str):
        """worker ขอให้ผู้ใช้ login แล้วกด OK"""
        if self._login_box is not None:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("รอ Login — Inkhwa")
        box.setText(message)
        ok_btn = box.addButton("OK — เริ่มดาวน์โหลด", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("ยกเลิก", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(ok_btn)
        self._login_box = box
        self._login_cancel_btn = cancel_btn
        box.finished.connect(self._on_login_finished)
        # ไม่บล็อก GUI — ผู้ใช้ยังสลับไปหน้าต่าง Chrome เพื่อ login ได้
        box.open()
        self.statusBar().showMessage("⏳ รอ Login ในหน้าต่าง Chrome...")

    def _on_login_finished(self, _result: int):
        box = self._login_box
        self._login_box = None
        if box is None or self.worker is None:
            return
        clicked = box.clickedButton()
        if clicked is not None and clicked is self._login_cancel_btn:
            # ผู้ใช้กดยกเลิก → หยุดงาน
            self.worker.stop()
            self._log("⏹ ยกเลิกตอนรอ login")
        else:
            # กด OK หรือถูกปิดอัตโนมัติ (ตรวจพบว่า login แล้ว) → ไปต่อ
            self.worker.confirm_login()

    def _on_login_close(self):
        """worker ตรวจพบว่า login สำเร็จเอง → ปิด popup ให้อัตโนมัติ"""
        if self._login_box is not None:
            self._login_box.done(0)

    # ----------------- ask-URL popup -----------------
    def _on_ask_url(self, current_url: str):
        """worker ขอ URL ตอนแรก (login แล้ว แต่ยังไม่มี URL)"""
        if self.worker is None or self._url_box is not None:
            return
        label = (
            "Login สำเร็จแล้ว ✅\n\n"
            "ไปที่ 'ตอนแรก' ที่ต้องการดาวน์โหลดในหน้าต่าง Chrome\n"
            "แล้ววาง URL ของตอนนั้นที่ช่องด้านล่าง\n"
            "(เว้นว่างไว้ = เริ่มจากหน้าที่เปิดอยู่ใน Chrome ตอนนี้)"
        )
        if current_url:
            label += f"\n\nหน้าที่เปิดอยู่ตอนนี้:\n{current_url}"

        dlg = QInputDialog(self)
        dlg.setWindowTitle("ใส่ URL ตอนแรก — Inkhwa")
        dlg.setLabelText(label)
        dlg.setTextValue("")
        dlg.setOkButtonText("OK — เริ่มดาวน์โหลด")
        dlg.setCancelButtonText("ยกเลิก")
        dlg.resize(560, dlg.sizeHint().height())
        self._url_box = dlg
        dlg.finished.connect(self._on_ask_url_finished)
        # ไม่บล็อก GUI — ผู้ใช้ยังสลับไปหน้าต่าง Chrome เพื่อหา/คัดลอก URL ได้
        dlg.open()
        self.statusBar().showMessage("⏳ รอใส่ URL ตอนแรก...")

    def _on_ask_url_finished(self, result: int):
        dlg = self._url_box
        self._url_box = None
        if dlg is None or self.worker is None:
            return
        if result == QDialog.DialogCode.Accepted:
            self.worker.provide_url(dlg.textValue().strip())
        else:
            self.worker.cancel_url_prompt()
            self._log("⏹ ยกเลิกตอนถาม URL")

    # ----------------- last config (จำค่าตั้งล่าสุด) -----------------
    def _collect_config(self) -> dict:
        """รวบรวมค่าตั้งปัจจุบัน (ไม่เก็บ password)"""
        return {
            "site": self.site_combo.currentText(),
            "output": self.output_edit.text().strip(),
            "start_url": self.url_edit.text().strip(),
            "number_folders": self.number_chk.isChecked(),
            "start_number": self.start_num_spin.value(),
            "pad": self.pad_spin.value(),
            "merge_enabled": self.merge_chk.isChecked(),
            "merge_group": self.merge_group_spin.value(),
            "merge_keep_original": self.merge_keep_chk.isChecked(),
            "merge_path": self.merge_path_edit.text().strip(),
            "merge_manual_group": self.merge_manual_group.value(),
            "merge_manual_keep": self.merge_manual_keep.isChecked(),
            "username": self.user_edit.currentText().strip(),
            "win_w": self.width(),
            "win_h": self.height(),
        }

    def _apply_config(self, cfg: dict):
        """คืนค่าตั้งล่าสุดกลับเข้า UI (ถ้าไม่มี config ใช้ค่าเริ่มต้นใน UI)"""
        if not cfg:
            return
        try:
            site = cfg.get("site")
            if site:
                idx = self.site_combo.findText(site)
                if idx >= 0:
                    self.site_combo.setCurrentIndex(idx)
            if cfg.get("output"):
                self.output_edit.setText(cfg["output"])
            if "start_url" in cfg:
                self.url_edit.setText(cfg.get("start_url") or "")
            if "username" in cfg and cfg["username"]:
                self.user_edit.setCurrentText(cfg["username"])

            if "number_folders" in cfg:
                self.number_chk.setChecked(bool(cfg["number_folders"]))
            if "start_number" in cfg:
                self.start_num_spin.setValue(int(cfg["start_number"]))
            if "pad" in cfg:
                self.pad_spin.setValue(int(cfg["pad"]))

            if "merge_enabled" in cfg:
                self.merge_chk.setChecked(bool(cfg["merge_enabled"]))
            if "merge_group" in cfg:
                self.merge_group_spin.setValue(int(cfg["merge_group"]))
            if "merge_keep_original" in cfg:
                self.merge_keep_chk.setChecked(bool(cfg["merge_keep_original"]))

            if cfg.get("merge_path"):
                self.merge_path_edit.setText(cfg["merge_path"])
            if "merge_manual_group" in cfg:
                self.merge_manual_group.setValue(int(cfg["merge_manual_group"]))
            if "merge_manual_keep" in cfg:
                self.merge_manual_keep.setChecked(bool(cfg["merge_manual_keep"]))

            w, h = cfg.get("win_w"), cfg.get("win_h")
            if isinstance(w, int) and isinstance(h, int) and w >= 900 and h >= 880:
                self.resize(w, h)
        except Exception:
            # config เสีย/ไม่ครบ → ข้ามไป ใช้ค่าเริ่มต้น
            pass

    def closeEvent(self, event):
        """ปิดแอป → เซฟค่าตั้งล่าสุด + หยุดงานที่ค้างอยู่"""
        try:
            save_config(self._collect_config())
        except Exception:
            pass
        for wk in (self.worker, self.merge_worker):
            if wk is not None:
                try:
                    wk.stop()
                except Exception:
                    pass
        super().closeEvent(event)

    # ----------------- auto-update -----------------
    def _start_update_check(self):
        try:
            self.update_checker = UpdateChecker()
            self.update_checker.update_available.connect(self._on_update_available)
            self.update_checker.up_to_date.connect(
                lambda: self.statusBar().showMessage(
                    f"✅ Inkhwa v{__version__} (ล่าสุดแล้ว)", 5000
                )
            )
            self.update_checker.check_failed.connect(
                lambda m: self.statusBar().showMessage(f"ℹ️ {m}", 5000)
            )
            self.update_checker.start()
        except Exception:
            # อัปเดตเป็นฟีเจอร์เสริม — พังก็ไม่กระทบการใช้งาน
            pass

    def _on_update_available(self, latest: str, notes: str):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("มีเวอร์ชันใหม่ — Inkhwa")
        body = (
            f"พบเวอร์ชันใหม่: v{latest}\n"
            f"เวอร์ชันปัจจุบัน: v{__version__}\n\n"
        )
        if notes:
            body += f"{notes}\n\n"
        body += "ต้องการอัปเดตเดี๋ยวนี้ไหม?"
        box.setText(body)
        update_btn = box.addButton("อัปเดต", QMessageBox.ButtonRole.AcceptRole)
        later_btn = box.addButton("ไว้ทีหลัง", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(update_btn)
        box.exec()
        if box.clickedButton() is update_btn:
            self._run_update()
        else:
            self.version_label.setText(f"v{__version__} ⬆")
            self.version_label.setToolTip(f"มีเวอร์ชันใหม่ v{latest} — คลิกที่ {REPO_URL}")

    def _run_update(self):
        self._log("⬇️ กำลังอัปเดต...")
        ok, message = apply_update(self._log)
        if ok:
            QMessageBox.information(
                self, "อัปเดตสำเร็จ",
                message + "\n\nกรุณาปิดแล้วเปิดโปรแกรมใหม่เพื่อใช้เวอร์ชันล่าสุด",
            )
        else:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("อัปเดตไม่สำเร็จ")
            box.setText(message + f"\n\nดาวน์โหลดเองได้ที่:\n{REPO_URL}")
            open_btn = box.addButton("เปิดหน้าเว็บ", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("ปิด", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is open_btn:
                webbrowser.open(REPO_URL)


# =========================================================================
# Entry point
# =========================================================================
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    app.setFont(QFont("Segoe UI", 10))
    win = ManhwaDownloaderGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
