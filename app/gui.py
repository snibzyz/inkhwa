"""Modern PyQt6 GUI — dark theme, card-based layout"""
from __future__ import annotations

import os
import sys
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QTextEdit, QFileDialog,
    QGroupBox, QMessageBox, QProgressBar, QFrame,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QIcon

from downloaders import list_sites

from .paths import DEFAULT_OUTPUT_DIR
from .presets import LOGIN_PRESETS
from .styles import (
    APP_QSS, COLOR_TEXT, COLOR_TEXT_DIM, COLOR_ACCENT, COLOR_SUCCESS,
    log_style, primary_button_style, danger_button_style, secondary_button_style,
)
from .worker import DownloadWorker


class ManhwaDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: DownloadWorker | None = None
        self._init_ui()

    # ----------------- UI -----------------
    def _init_ui(self):
        self.setWindowTitle("Inkhwa — Manhwa Downloader")
        self.setMinimumSize(QSize(900, 780))
        self.resize(1080, 880)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        outer.addWidget(self._build_header())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(14)
        body_layout.setContentsMargins(28, 20, 28, 20)

        # row 1: site + url
        row1 = QHBoxLayout()
        row1.setSpacing(14)
        row1.addWidget(self._build_site_card(), stretch=1)
        row1.addWidget(self._build_url_card(), stretch=2)
        body_layout.addLayout(row1)

        # row 2: output + login
        body_layout.addWidget(self._build_output_card())
        body_layout.addWidget(self._build_login_card())

        # row 3: actions
        body_layout.addWidget(self._build_actions())

        # row 4: log
        body_layout.addWidget(self._build_log_card(), stretch=1)

        outer.addWidget(body)

        self.statusBar().showMessage("✨ พร้อมใช้งาน")

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
            f"color: {COLOR_TEXT}; font-size: 20pt; font-weight: 700;"
        )
        lay.addWidget(title)

        subtitle = QLabel("Manhwa Downloader")
        subtitle.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 11pt; font-weight: 500;"
            "padding-left: 4px;"
        )
        lay.addWidget(subtitle)

        lay.addStretch()

        sites_badge = QLabel("·".join(list_sites()))
        sites_badge.setStyleSheet(
            f"color: {COLOR_TEXT_DIM}; font-size: 10pt;"
            f"background: #1A2028; border: 1px solid #2A3441;"
            "padding: 6px 12px; border-radius: 12px;"
        )
        lay.addWidget(sites_badge)
        return h

    # -- cards
    def _build_site_card(self) -> QGroupBox:
        box = QGroupBox("🌐  เว็บไซต์")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        self.site_combo = QComboBox()
        self.site_combo.setMinimumHeight(40)
        for s in list_sites():
            self.site_combo.addItem(s)
        v.addWidget(self.site_combo)
        return box

    def _build_url_card(self) -> QGroupBox:
        box = QGroupBox("🔗  URL ตอน (ไม่บังคับ)")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        self.url_edit = QLineEdit()
        self.url_edit.setMinimumHeight(40)
        self.url_edit.setPlaceholderText("ว่าง = เปิดหน้าแรกของเว็บที่เลือก")
        v.addWidget(self.url_edit)
        return box

    def _build_output_card(self) -> QGroupBox:
        box = QGroupBox("📁  โฟลเดอร์บันทึก")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.output_edit = QLineEdit()
        self.output_edit.setMinimumHeight(40)
        self.output_edit.setText(DEFAULT_OUTPUT_DIR)
        browse = QPushButton("เลือก…")
        browse.setStyleSheet(secondary_button_style())
        browse.clicked.connect(self._browse_output)
        row.addWidget(self.output_edit)
        row.addWidget(browse)
        v.addLayout(row)
        return box

    def _build_login_card(self) -> QGroupBox:
        box = QGroupBox("🔐  Login (auto-fill ตอน start)")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        v.setSpacing(10)

        # preset row
        prow = QHBoxLayout()
        prow.setSpacing(10)
        prow.addWidget(self._make_label("Preset", 70))
        self.preset_combo = QComboBox()
        self.preset_combo.setMinimumHeight(38)
        self.preset_combo.addItems(["ไม่มี"] + list(LOGIN_PRESETS.keys()))
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        prow.addWidget(self.preset_combo, stretch=1)
        v.addLayout(prow)

        # user
        urow = QHBoxLayout()
        urow.setSpacing(10)
        urow.addWidget(self._make_label("User", 70))
        self.user_edit = QLineEdit()
        self.user_edit.setMinimumHeight(38)
        urow.addWidget(self.user_edit, stretch=1)
        v.addLayout(urow)

        # password
        pwrow = QHBoxLayout()
        pwrow.setSpacing(10)
        pwrow.addWidget(self._make_label("Password", 70))
        self.pw_edit = QLineEdit()
        self.pw_edit.setMinimumHeight(38)
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pwrow.addWidget(self.pw_edit, stretch=1)
        v.addLayout(pwrow)
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
        box = QGroupBox("📋  Log")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setStyleSheet(log_style())
        v.addWidget(self.log_text)
        return box

    # ----------------- handlers -----------------
    def _on_preset_changed(self, preset: str):
        if preset in LOGIN_PRESETS:
            self.user_edit.setText(LOGIN_PRESETS[preset]["user"])
            self.pw_edit.setText(LOGIN_PRESETS[preset]["password"])
            self._log(f"โหลด preset: {preset}")
        else:
            self.user_edit.clear()
            self.pw_edit.clear()

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "เลือกโฟลเดอร์บันทึก")
        if folder:
            self.output_edit.setText(folder)
            self._log(f"เลือกโฟลเดอร์: {folder}")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.append(f"<span style='color:#8B96A6'>[{ts}]</span> {msg}")
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _start_download(self):
        site = self.site_combo.currentText()
        output = self.output_edit.text().strip()
        start_url = self.url_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "คำเตือน", "กรุณาเลือกโฟลเดอร์บันทึก")
            return
        try:
            os.makedirs(output, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "ผิดพลาด", f"สร้างโฟลเดอร์ไม่ได้: {e}")
            return
        if start_url and not (start_url.startswith("http://") or start_url.startswith("https://")):
            QMessageBox.warning(self, "คำเตือน", "URL ต้องขึ้นต้นด้วย http:// หรือ https://")
            return

        username = self.user_edit.text().strip()
        password = self.pw_edit.text().strip()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.log_text.clear()

        self.worker = DownloadWorker(site, output, start_url, username, password)
        self.worker.log_signal.connect(self._log)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.start()
        self.statusBar().showMessage(f"🚀 กำลังดาวน์โหลดจาก {site}...")

    def _stop_download(self):
        if self.worker:
            self.worker.stop()
            self._log("⏹ กำลังหยุด...")
            self.statusBar().showMessage("⏸ กำลังหยุด...")

    def _on_progress(self, cur: int, total: int):
        if total > 0:
            self.progress_bar.setValue(int(cur / total * 100))
            self.progress_bar.setFormat(f"{cur}/{total} ภาพ — %p%")
            self.statusBar().showMessage(f"📥 {cur}/{total} ภาพ")

    def _on_finished(self, ok: bool, msg: str):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage(("✅ " if ok else "❌ ") + msg)
        if ok:
            QMessageBox.information(self, "สำเร็จ", msg)
        else:
            QMessageBox.warning(self, "ผิดพลาด", msg)
        self.worker = None


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
