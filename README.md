# Inkhwa — Manhwa Downloader

GUI downloader สำหรับเว็บการ์ตูนเกาหลี — รองรับ 5 เว็บใน app เดียว ใช้ undetected-chromedriver เพื่อหลบ bot detection พร้อม SN watermark stripper สำหรับ Bomtoon

![python](https://img.shields.io/badge/python-3.10%2B-blue) ![pyqt6](https://img.shields.io/badge/PyQt6-6.6%2B-green) ![license](https://img.shields.io/badge/license-MIT-lightgrey)

## เว็บที่รองรับ

| เว็บ | วิธีโหลด | หมายเหตุ |
|---|---|---|
| **Bomtoon** | Canvas + SN strip | ลบ SN watermark อัตโนมัติ |
| **Lezhin** | Canvas + IMG hybrid | รองรับทั้ง img/canvas |
| **RidiBooks** | Canvas blob | ดึงผ่าน toDataURL |
| **Toptoon** | URL + cookies | จัดการ coin popup |
| **Kakao** | URL + cookies | ใช้ page-edge URL |

## ติดตั้ง (Windows)

1. ติดตั้ง Python 3.10+ จาก https://www.python.org/
2. ติดตั้ง Google Chrome
3. ดับเบิลคลิก **`install.bat`** เพื่อติดตั้ง dependencies
4. ดับเบิลคลิก **`run.bat`** เพื่อเปิดโปรแกรม

### หรือใช้ command line

```cmd
pip install -r requirements.txt
python manhwa_dl.py
```

## โครงสร้างโปรเจกต์

```
inkhwa/
├── manhwa_dl.py          ← entry point
├── app/                  ← GUI (PyQt6 dark theme)
│   ├── gui.py
│   ├── worker.py         ← QThread runner
│   ├── presets.py        ← login presets (empty by default)
│   ├── paths.py          ← auto-detect project root
│   └── styles.py         ← dark theme QSS
├── downloaders/          ← per-site logic
│   ├── base.py           ← BaseDownloader + ChromeManager
│   ├── ridi.py
│   ├── lezhin.py
│   ├── toptoon.py
│   ├── kakao.py
│   └── bomtoon.py        ← Bomtoon + SN stripper
├── tools/                ← dev/test utilities
│   ├── test_bomtoon.py
│   ├── diag_bomtoon.py
│   ├── test_all_sites.py
│   ├── discover_links.py
│   └── merge_images.py
├── legacy/               ← scripts ดั้งเดิม (อ้างอิง)
├── profiles/             ← Chrome profile per site (gitignored)
├── Downloads/            ← default output (gitignored)
├── install.bat
├── run.bat
└── requirements.txt
```

## ใช้งาน

1. **เลือกเว็บ** ใน dropdown
2. (Optional) **URL ตอน** — ถ้าใส่ จะเปิดหน้านี้หลัง login
3. **โฟลเดอร์บันทึก** — default `./Downloads`
4. (Optional) **Login** — ใส่ user/password จะ auto-login (ปัจจุบันรองรับ Bomtoon)
5. กด **เริ่มดาวน์โหลด** — Chrome window จะเปิดขึ้น

โปรแกรมจะลูปไปทุกตอน คลิก Next อัตโนมัติจนจบเรื่อง

### Login Presets

เก็บ preset ส่วนตัวที่ไม่ถูก commit ใน `app/presets_local.py`:

```python
LOGIN_PRESETS = {
    "myacct": {"user": "you@example.com", "password": "yourpw"},
}
```

ไฟล์ `app/presets_local.py` อยู่ใน `.gitignore`

## พัฒนาเว็บใหม่

สร้างไฟล์ใน `downloaders/<site>.py`:

```python
from .base import BaseDownloader, DownloaderContext, register_downloader

@register_downloader
class MySiteDownloader(BaseDownloader):
    name = "MySite"
    url = "https://example.com"
    profile_dir = "Chrome_MySite_Profile"
    file_ext = ".jpg"

    def get_chapter_name(self, driver) -> str: ...
    def download_chapter(self, driver, save_path, ctx) -> int: ...
    def click_next(self, driver, ctx) -> bool: ...
    # (optional) def login(self, driver, user, pw, ctx) -> bool: ...
```

แล้ว import ใน `downloaders/__init__.py` — GUI จะเจออัตโนมัติ

## Portable

โปรเจกต์ใช้ path detection อัตโนมัติ (`app/paths.py`) — รัน `manhwa_dl.py` จากที่ไหนก็ได้ profile + downloads อยู่ข้าง ๆ ตัวโปรแกรม zip ทั้งโฟลเดอร์แล้ว copy ไปเครื่องอื่นได้

## License

MIT
