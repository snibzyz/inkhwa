"""Modern dark theme stylesheets — เปลี่ยน theme ที่เดียวจบ"""

# =========================================================================
# Color palette
# =========================================================================
COLOR_BG = "#0F1419"          # main bg (เกือบดำ)
COLOR_SURFACE = "#1A2028"     # card / surface
COLOR_SURFACE_HI = "#232A35"  # hover / elevated
COLOR_BORDER = "#2A3441"      # subtle border
COLOR_TEXT = "#E6EDF3"        # primary text
COLOR_TEXT_DIM = "#8B96A6"    # secondary text
COLOR_ACCENT = "#7C5CFF"      # primary action (purple)
COLOR_ACCENT_HOV = "#8E72FF"
COLOR_SUCCESS = "#3DD68C"
COLOR_DANGER = "#FF5C5C"
COLOR_DANGER_HOV = "#FF7575"

FONT_FAMILY = "'Segoe UI', 'Inter', 'Tahoma', sans-serif"


# =========================================================================
# Global stylesheet (applied to QApplication)
# =========================================================================
APP_QSS = f"""
* {{
    font-family: {FONT_FAMILY};
    color: {COLOR_TEXT};
}}
QMainWindow, QWidget {{
    background-color: {COLOR_BG};
}}
QGroupBox {{
    background-color: {COLOR_SURFACE};
    border: 1px solid {COLOR_BORDER};
    border-radius: 12px;
    margin-top: 18px;
    padding: 16px;
    font-size: 12pt;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: {COLOR_TEXT};
    background-color: {COLOR_BG};
}}
QLabel {{
    background-color: transparent;
    color: {COLOR_TEXT};
}}
QLineEdit, QComboBox, QTextEdit {{
    background-color: {COLOR_SURFACE_HI};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 10px 12px;
    font-size: 11pt;
    selection-background-color: {COLOR_ACCENT};
}}
QLineEdit:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {COLOR_ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {COLOR_TEXT_DIM};
    margin-right: 10px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLOR_SURFACE_HI};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {COLOR_ACCENT};
    outline: 0;
}}
QPushButton {{
    border-radius: 8px;
    padding: 11px 22px;
    font-weight: 600;
    font-size: 11pt;
    border: none;
}}
QProgressBar {{
    background-color: {COLOR_SURFACE_HI};
    border: 1px solid {COLOR_BORDER};
    border-radius: 8px;
    text-align: center;
    color: {COLOR_TEXT};
    font-weight: 600;
    height: 22px;
}}
QProgressBar::chunk {{
    background-color: {COLOR_ACCENT};
    border-radius: 7px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: {COLOR_BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLOR_TEXT_DIM};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QStatusBar {{
    background-color: {COLOR_SURFACE};
    color: {COLOR_TEXT_DIM};
    border-top: 1px solid {COLOR_BORDER};
    padding: 6px 12px;
    font-size: 10pt;
}}
"""


# =========================================================================
# Per-widget helpers (เผื่อใช้สำหรับ override จุดเฉพาะ)
# =========================================================================
def combo_style() -> str:
    return ""  # ใช้ global APP_QSS


def edit_style() -> str:
    return ""


def progress_style() -> str:
    return ""


def log_style() -> str:
    return f"""
        QTextEdit {{
            background-color: {COLOR_BG};
            border: 1px solid {COLOR_BORDER};
            border-radius: 8px;
            padding: 12px;
            font-family: 'JetBrains Mono', 'Consolas', monospace;
            font-size: 10pt;
            color: {COLOR_TEXT};
        }}
    """


def button_style(bg: str, hover: str) -> str:
    return f"""
        QPushButton {{
            background-color: {bg};
            color: white;
            border-radius: 8px;
            padding: 12px 28px;
            font-weight: 600;
            font-size: 11pt;
            min-width: 160px;
        }}
        QPushButton:hover {{ background-color: {hover}; }}
        QPushButton:disabled {{
            background-color: {COLOR_SURFACE_HI};
            color: {COLOR_TEXT_DIM};
        }}
    """


def primary_button_style() -> str:
    return button_style(COLOR_ACCENT, COLOR_ACCENT_HOV)


def danger_button_style() -> str:
    return button_style(COLOR_DANGER, COLOR_DANGER_HOV)


def secondary_button_style() -> str:
    return f"""
        QPushButton {{
            background-color: {COLOR_SURFACE_HI};
            color: {COLOR_TEXT};
            border: 1px solid {COLOR_BORDER};
            border-radius: 8px;
            padding: 11px 22px;
            font-weight: 500;
            font-size: 11pt;
        }}
        QPushButton:hover {{ background-color: {COLOR_BORDER}; }}
    """
