"""Auto-update — เช็คเวอร์ชันใหม่จาก public repo แล้วอัปเดตให้

ตรรกะ:
  - เทียบไฟล์ VERSION ของเครื่องกับบน GitHub (raw)
  - ถ้ามีใหม่กว่า → แจ้งผู้ใช้
  - กดอัปเดต:
      * ถ้าเป็น git clone (.git อยู่)  → `git pull --ff-only`
      * ถ้าไม่ใช่ (โหลด zip มา)        → ดึง zip ล่าสุดจาก GitHub มาแตกทับ
"""
from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import zipfile
from typing import Callable, Optional, Tuple

import requests
from PyQt6.QtCore import QThread, pyqtSignal

from .paths import PROJECT_ROOT
from .version import (
    __version__,
    REMOTE_VERSION_URL,
    REPO_OWNER,
    REPO_NAME,
    REPO_BRANCH,
)

# โฟลเดอร์/ไฟล์ที่ห้ามทับตอนอัปเดตแบบ zip (ข้อมูลผู้ใช้)
_PRESERVE = {"profiles", "Downloads", "config.json", "VERSION"}


# =========================================================================
# version helpers
# =========================================================================
def _parse(v: str) -> tuple:
    parts = []
    for chunk in (v or "").strip().lstrip("v").split("."):
        num = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts) or (0,)


def is_newer(remote: str, local: str) -> bool:
    """remote ใหม่กว่า local ไหม"""
    r, l = _parse(remote), _parse(local)
    length = max(len(r), len(l))
    r += (0,) * (length - len(r))
    l += (0,) * (length - len(l))
    return r > l


def fetch_remote_version(timeout: int = 8) -> Optional[str]:
    """ดึงเวอร์ชันจาก repo — ตรวจให้แน่ใจว่าเป็นเลขเวอร์ชันจริง

    ป้องกัน captive-portal / proxy ที่ตอบ HTTP 200 เป็นหน้า HTML
    """
    try:
        r = requests.get(REMOTE_VERSION_URL, timeout=timeout)
        if r.status_code != 200:
            return None
        if "html" in r.headers.get("Content-Type", "").lower():
            return None
        body = (r.text or "").strip()
        if not body:
            return None
        line = body.splitlines()[0].strip()
        return line if re.fullmatch(r"v?\d+(\.\d+)*", line) else None
    except Exception:
        return None


# =========================================================================
# background checker
# =========================================================================
class UpdateChecker(QThread):
    """เช็คเวอร์ชันใหม่แบบ background ตอนเปิดโปรแกรม"""

    update_available = pyqtSignal(str, str)   # latest_version, notes
    up_to_date = pyqtSignal()
    check_failed = pyqtSignal(str)

    def run(self):
        remote = fetch_remote_version()
        if not remote:
            self.check_failed.emit("เช็คอัปเดตไม่ได้ (เน็ต/repo)")
            return
        if is_newer(remote, __version__):
            self.update_available.emit(remote, "")
        else:
            self.up_to_date.emit()


# =========================================================================
# apply update
# =========================================================================
def _is_git_repo() -> bool:
    return os.path.isdir(os.path.join(PROJECT_ROOT, ".git"))


def _git_pull(log: Callable[[str], None]) -> Tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        for line in out.strip().splitlines():
            log(f"   git: {line}")
        if proc.returncode == 0:
            return True, "อัปเดตผ่าน git สำเร็จ"
        return False, "git pull ไม่สำเร็จ (อาจมีไฟล์แก้ค้างไว้)"
    except FileNotFoundError:
        return False, "ไม่พบ git บนเครื่อง"
    except Exception as e:
        return False, f"git error: {e}"


def _safe_dest(rel: str, root_abs: str) -> Optional[str]:
    """แปลง rel path → absolute dest ที่ "อยู่ใน PROJECT_ROOT เท่านั้น"

    คืน None ถ้า path พยายามหลุดออกนอกโฟลเดอร์ (path traversal)
    """
    parts = rel.split("/")
    if any(p in ("", "..") for p in parts) or os.path.isabs(rel):
        return None
    dest = os.path.join(PROJECT_ROOT, *parts)
    dest_abs = os.path.realpath(dest)
    if dest_abs != root_abs and not dest_abs.startswith(root_abs + os.sep):
        return None
    return dest


_STAGING_DIR = ".update_staging"


def _zip_update(log: Callable[[str], None]) -> Tuple[bool, str]:
    """ดึง zip ของ branch ล่าสุดมาอัปเดต — แบบ all-or-nothing

    2 เฟส:
      1) แตกทุกไฟล์ลงโฟลเดอร์ staging ก่อน (ถ้าพังช่วงนี้ ของจริงไม่โดนแตะเลย)
      2) ย้ายเข้าที่จริงทีละไฟล์แบบ atomic (os.replace) + สำรองของเดิมเป็น .bak
    กันไม่ให้ install เหลือไฟล์ครึ่งเก่าครึ่งใหม่/ไฟล์เสีย
    """
    url = (
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}/archive/refs/heads/"
        f"{REPO_BRANCH}.zip"
    )
    root_abs = os.path.realpath(PROJECT_ROOT)
    staging = os.path.join(PROJECT_ROOT, _STAGING_DIR)
    shutil.rmtree(staging, ignore_errors=True)
    try:
        log("   กำลังดาวน์โหลด zip ล่าสุด...")
        r = requests.get(url, timeout=120)
        if r.status_code != 200:
            return False, f"ดาวน์โหลด zip ไม่ได้ (HTTP {r.status_code})"
        zf = zipfile.ZipFile(io.BytesIO(r.content))

        names = [n for n in zf.namelist() if n]
        if not names:
            return False, "zip ว่างเปล่า (ไม่มีไฟล์)"
        tops = {n.split("/", 1)[0] for n in names}
        if len(tops) != 1:
            return False, "โครงสร้าง zip ไม่ถูกต้อง (unexpected layout)"
        root = next(iter(tops)) + "/"   # เช่น "inkhwa-main/"

        # ---- เฟส 1: แตกทั้งหมดลง staging ----
        plan = []           # (staged_path, dest_path)
        skipped_unsafe = 0
        for member in names:
            if member.endswith("/"):
                continue
            rel = member[len(root):] if member.startswith(root) else member
            if not rel:
                continue
            top = rel.split("/")[0]
            # ข้ามข้อมูลผู้ใช้ + ข้าม VERSION ไว้ทำทีหลัง (จะ update แยก)
            if top in _PRESERVE:
                continue
            dest = _safe_dest(rel, root_abs)
            if dest is None:
                skipped_unsafe += 1
                log(f"   ⚠️ ข้าม member ที่อยู่นอกโฟลเดอร์: {member}")
                continue
            staged = os.path.join(staging, *rel.split("/"))
            os.makedirs(os.path.dirname(staged), exist_ok=True)
            with zf.open(member) as src, open(staged, "wb") as out:
                shutil.copyfileobj(src, out)
            plan.append((staged, dest))

        # VERSION (อัปเดตด้วยแต่ไม่ถือเป็นข้อมูลผู้ใช้)
        vmember = root + "VERSION"
        if vmember in zf.namelist():
            vstaged = os.path.join(staging, "VERSION")
            with zf.open(vmember) as src, open(vstaged, "wb") as out:
                shutil.copyfileobj(src, out)
            plan.append((vstaged, os.path.join(PROJECT_ROOT, "VERSION")))

        if not plan:
            return False, "ไม่มีไฟล์ให้อัปเดต"

        # ---- เฟส 2: ย้ายเข้าที่จริง (atomic ต่อไฟล์ + สำรอง .bak) ----
        moved = 0
        for staged, dest in plan:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            if os.path.exists(dest):
                try:
                    shutil.copy2(dest, dest + ".bak")
                except Exception:
                    pass
            os.replace(staged, dest)
            moved += 1

        log(f"   อัปเดต {moved} ไฟล์" + (f" (ข้ามไม่ปลอดภัย {skipped_unsafe})" if skipped_unsafe else ""))
        return True, f"อัปเดตผ่าน zip สำเร็จ ({moved} ไฟล์)"
    except Exception as e:
        return False, f"zip update error: {e}"
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def apply_update(log: Callable[[str], None] = print) -> Tuple[bool, str]:
    """อัปเดตโปรแกรม — เลือกวิธีตาม environment

    - เป็น git checkout → git pull เท่านั้น (ถ้าพังให้ผู้ใช้แก้เอง
      *ห้าม* zip ทับ git tree เพราะจะทำให้ของที่แก้ไว้/repo เสีย)
    - ไม่ใช่ git (โหลด zip มา) → ดึง zip ล่าสุดมาแตกทับแบบ atomic
    """
    if _is_git_repo():
        log("   ใช้วิธี git pull")
        ok, msg = _git_pull(log)
        if ok:
            return ok, msg
        return False, (
            msg + " — เป็น git repo จึงไม่เขียนทับด้วย zip\n"
            "ลองแก้เอง: git stash แล้ว git pull (หรือ clone ใหม่)"
        )
    return _zip_update(log)
