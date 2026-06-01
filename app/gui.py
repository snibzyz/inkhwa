"""Modern PyQt6 GUI — dark theme, card layout, copyable log"""
from __future__ import annotations

import os
import sys
import time
import webbrowser

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QLineEdit, QPlainTextEdit, QFileDialog,
    QGroupBox, QMessageBox, QProgressBar, QFrame,
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QFont, QGuiApplication

from downloaders import list_sites

from .paths import DEFAULT_OUTPUT_DIR, PROJECT_ROOT
from .presets import add_to_history, load_history
from .styles import (
    APP_QSS, COLOR_TEXT, COLOR_TEXT_DIM, COLOR_ACCENT, COLOR_SURFACE,
    COLOR_SURFACE_HI, COLOR_BORDER, COLOR_BG,
    log_style, primary_button_style, danger_button_style, secondary_button_style,
)
from .worker import DownloadWorker
from .version import __version__, REPO_URL
from .updater import UpdateChecker, apply_update


class ManhwaDownloaderGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.worker: DownloadWorker | None = None
        self._login_box: QMessageBox | None = None
        self._login_cancel_btn = None
        self.update_checker: UpdateChecker | None = None
        self._init_ui()
        self._start_update_check()

    # ----------------- UI -----------------
    def _init_ui(self):
        self.setWindowTitle("Inkhwa — Manhwa Downloader")
        self.setMinimumSize(QSize(960, 800))
        self.resize(1120, 900)

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        outer.addWidget(self._build_header())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setSpacing(14)
        body_layout.setContentsMargins(28, 18, 28, 18)

        # row 1: site + url
        row1 = QHBoxLayout()
        row1.setSpacing(14)
        row1.addWidget(self._build_site_card(), stretch=1)
        row1.addWidget(self._build_url_card(), stretch=2)
        body_layout.addLayout(row1)

        # row 2: output
        body_layout.addWidget(self._build_output_card())

        # row 3: login
        body_layout.addWidget(self._build_login_card())

        # row 4: actions
        body_layout.addWidget(self._build_actions())

        # row 5: log
        body_layout.addWidget(self._build_log_card(), stretch=1)

        outer.addWidget(body)

        self.statusBar().showMessage("Ready")

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

        subtitle = QLabel("Manhwa Downloader")
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
        box = QGroupBox("🌐  Website")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        self.site_combo = QComboBox()
        self.site_combo.setMinimumHeight(42)
        for s in list_sites():
            self.site_combo.addItem(s)
        v.addWidget(self.site_combo)
        return box

    def _build_url_card(self) -> QGroupBox:
        box = QGroupBox("🔗  Starting chapter URL")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        v.setSpacing(6)

        hint = QLabel("URL ของตอนที่ต้องการเริ่มดาวน์โหลด — โปรแกรมจะลูปต่อจากตอนนี้ไปจนจบเรื่อง")
        hint.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 9pt;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self.url_edit = QLineEdit()
        self.url_edit.setMinimumHeight(42)
        self.url_edit.setPlaceholderText("https://www.bomtoon.com/viewer/<series>/<episode>")
        v.addWidget(self.url_edit)
        return box

    def _build_output_card(self) -> QGroupBox:
        box = QGroupBox("📁  Save folder")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.output_edit = QLineEdit()
        self.output_edit.setMinimumHeight(42)
        self.output_edit.setText(DEFAULT_OUTPUT_DIR)
        browse = QPushButton("Browse…")
        browse.setStyleSheet(secondary_button_style())
        browse.clicked.connect(self._browse_output)
        open_btn = QPushButton("Open")
        open_btn.setStyleSheet(secondary_button_style())
        open_btn.clicked.connect(self._open_output)
        row.addWidget(self.output_edit)
        row.addWidget(browse)
        row.addWidget(open_btn)
        v.addLayout(row)
        return box

    def _build_login_card(self) -> QGroupBox:
        box = QGroupBox("🔐  Login (optional — auto-fill when supported)")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        v.setSpacing(10)

        # user (combobox editable — แสดง history)
        urow = QHBoxLayout()
        urow.setSpacing(10)
        urow.addWidget(self._make_label("User", 72))
        self.user_edit = QComboBox()
        self.user_edit.setEditable(True)
        self.user_edit.setMinimumHeight(40)
        history = load_history()
        if history:
            self.user_edit.addItems(history)
            self.user_edit.setCurrentText("")
        urow.addWidget(self.user_edit, stretch=1)
        v.addLayout(urow)

        # password (always blank — ไม่ save)
        pwrow = QHBoxLayout()
        pwrow.setSpacing(10)
        pwrow.addWidget(self._make_label("Password", 72))
        self.pw_edit = QLineEdit()
        self.pw_edit.setMinimumHeight(40)
        self.pw_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw_edit.setPlaceholderText("ไม่บันทึก password — ต้องใส่ใหม่ทุกครั้ง")
        pwrow.addWidget(self.pw_edit, stretch=1)
        # show/hide toggle
        self.pw_show_btn = QPushButton("Show")
        self.pw_show_btn.setCheckable(True)
        self.pw_show_btn.setStyleSheet(secondary_button_style())
        self.pw_show_btn.setMaximumWidth(80)
        self.pw_show_btn.toggled.connect(self._toggle_pw_visibility)
        pwrow.addWidget(self.pw_show_btn)
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

        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setStyleSheet(danger_button_style())
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_download)
        row.addWidget(self.stop_btn)

        self.start_btn = QPushButton("▶  Start download")
        self.start_btn.setStyleSheet(primary_button_style())
        self.start_btn.clicked.connect(self._start_download)
        row.addWidget(self.start_btn)
        return w

    def _build_log_card(self) -> QGroupBox:
        box = QGroupBox("📋  Log")
        v = QVBoxLayout(box)
        v.setContentsMargins(16, 22, 16, 14)
        v.setSpacing(8)

        # log actions row
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        copy_btn = QPushButton("Copy")
        copy_btn.setStyleSheet(secondary_button_style())
        copy_btn.setMaximumWidth(90)
        copy_btn.clicked.connect(self._copy_log)
        save_btn = QPushButton("Save…")
        save_btn.setStyleSheet(secondary_button_style())
        save_btn.setMaximumWidth(90)
        save_btn.clicked.connect(self._save_log)
        clear_btn = QPushButton("Clear")
        clear_btn.setStyleSheet(secondary_button_style())
        clear_btn.setMaximumWidth(90)
        clear_btn.clicked.connect(self._clear_log)
        actions.addWidget(copy_btn)
        actions.addWidget(save_btn)
        actions.addWidget(clear_btn)
        v.addLayout(actions)

        # log text (QPlainTextEdit = read-only แต่ select+copy ได้)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
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
        self.pw_show_btn.setText("Hide" if checked else "Show")

    def _browse_output(self):
        folder = QFileDialog.getExistingDirectory(self, "Select save folder")
        if folder:
            self.output_edit.setText(folder)
            self._log(f"Save folder: {folder}")

    def _open_output(self):
        path = self.output_edit.text().strip()
        if not path:
            return
        os.makedirs(path, exist_ok=True)
        try:
            os.startfile(path)  # Windows only
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Open folder failed: {e}")

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.appendPlainText(f"[{ts}] {msg}")
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _copy_log(self):
        text = self.log_text.toPlainText()
        QGuiApplication.clipboard().setText(text)
        self.statusBar().showMessage(f"📋 Copied {len(text)} chars to clipboard", 3000)

    def _save_log(self):
        default = os.path.join(
            PROJECT_ROOT, f"inkhwa-log-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Save log", default, "Text files (*.txt);;All files (*.*)"
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.log_text.toPlainText())
                self.statusBar().showMessage(f"💾 Saved log → {path}", 4000)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Save log failed: {e}")

    def _clear_log(self):
        self.log_text.clear()

    def _start_download(self):
        site = self.site_combo.currentText()
        output = self.output_edit.text().strip()
        start_url = self.url_edit.text().strip()
        if not output:
            QMessageBox.warning(self, "Warning", "Please select save folder")
            return
        try:
            os.makedirs(output, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot create folder: {e}")
            return
        if start_url and not (start_url.startswith("http://") or start_url.startswith("https://")):
            QMessageBox.warning(self, "Warning", "URL must start with http:// or https://")
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

        self.worker = DownloadWorker(site, output, start_url, username, password)
        self.worker.log_signal.connect(self._log)
        self.worker.progress_signal.connect(self._on_progress)
        self.worker.finished_signal.connect(self._on_finished)
        self.worker.login_prompt_signal.connect(self._on_login_prompt)
        self.worker.login_close_signal.connect(self._on_login_close)
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
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.statusBar().showMessage(("✅ " if ok else "❌ ") + msg)
        if ok:
            QMessageBox.information(self, "Done", msg)
        else:
            QMessageBox.warning(self, "Error", msg)
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
