"""รวมรูปในโฟลเดอร์เป็นภาพยาว (ต่อแนวตั้ง) ทีละ N รูป

ใช้ได้ทั้ง:
  - auto-merge หลังโหลดแต่ละตอน (เรียกจาก worker)
  - manual-merge เลือกโฟลเดอร์เอง (เรียกจาก GUI ผ่าน MergeWorker)

โหมดเริ่มต้น = "แทนที่" (เก็บเฉพาะไฟล์รวม):
  - เปลี่ยนชื่อไฟล์ต้นฉบับเป็น tmp_* ก่อน เพื่อกันชนชื่อกับไฟล์ผลลัพธ์
  - เขียนไฟล์รวม 01.jpg, 02.jpg, ... แล้วลบ tmp_* เมื่อรวมกลุ่มนั้นสำเร็จ
ถ้า keep_original=True → ไฟล์รวมไปอยู่ใน <folder>/_merged/ และไม่ลบต้นฉบับ
"""
from __future__ import annotations

import io
import os
from typing import Callable

try:
    from PIL import Image
    _PIL_AVAILABLE = True
except Exception:
    _PIL_AVAILABLE = False

VALID_EXT = (".png", ".jpg", ".jpeg", ".webp")
MERGED_SUBDIR = "_merged"

_MAX_DIMENSION = 65500          # ความสูงสูงสุดที่ JPEG รองรับ
_MAX_FILE_SIZE = 30 * 1024 * 1024  # 30MB


def _numeric_key(filename: str):
    """sort ชื่อไฟล์เชิงตัวเลข (รองรับ 1.jpg, 01.jpg, tmp_2.jpg, 010.jpg)"""
    stem = os.path.splitext(filename)[0]
    digits = "".join(ch for ch in stem if ch.isdigit())
    return (int(digits) if digits else 0, filename)


def _list_images(folder: str) -> list[str]:
    try:
        files = [
            f for f in os.listdir(folder)
            if f.lower().endswith(VALID_EXT)
            and os.path.isfile(os.path.join(folder, f))
        ]
    except Exception:
        return []
    files.sort(key=_numeric_key)
    return files


def _combine(image_paths: list[str], save_path: str, log: Callable[[str], None]) -> bool:
    """ต่อรูปแนวตั้งเป็นภาพเดียว แล้วบันทึกที่ save_path (คุมขนาด/ไฟล์อัตโนมัติ)"""
    imgs = []
    try:
        for p in image_paths:
            try:
                im = Image.open(p)
                if im.mode != "RGB":
                    im = im.convert("RGB")
                imgs.append(im)
            except Exception as e:
                log(f"      ⚠️ โหลดรูปไม่ได้: {os.path.basename(p)} ({e})")
        if not imgs:
            return False

        base_width = max(im.width for im in imgs)

        def _render(scale: float = 1.0):
            w = max(1, int(base_width * scale))
            tiles = []
            for im in imgs:
                nh = max(1, int(im.height * w / im.width))
                tiles.append(im.resize((w, nh), Image.LANCZOS) if (im.width != w or scale != 1.0) else im)
            total_h = sum(t.height for t in tiles)
            canvas = Image.new("RGB", (w, total_h), (255, 255, 255))
            y = 0
            for t in tiles:
                canvas.paste(t, (0, y))
                y += t.height
            return canvas, total_h

        # คุมความสูงไม่ให้เกินที่ JPEG/PNG รับได้
        canvas, total_h = _render(1.0)
        if total_h > _MAX_DIMENSION:
            scale = _MAX_DIMENSION / total_h
            log(f"      💡 สูงเกิน {_MAX_DIMENSION}px — ย่อเหลือ {int(total_h*scale)}px")
            canvas, total_h = _render(scale)

        use_png = total_h > 30000
        final_path = save_path[:-4] + ".png" if (use_png and save_path.lower().endswith(".jpg")) else save_path

        quality = 95
        scale = 1.0
        while True:
            buf = io.BytesIO()
            if use_png:
                canvas.save(buf, "PNG", optimize=True)
            else:
                canvas.save(buf, "JPEG", quality=quality, optimize=True)
            size = buf.tell()
            if size < _MAX_FILE_SIZE:
                with open(final_path, "wb") as f:
                    f.write(buf.getvalue())
                buf.close()
                return True
            buf.close()
            # ไฟล์ใหญ่ไป — ลด quality ก่อน แล้วค่อยย่อขนาด
            if not use_png and quality > 55:
                quality -= 5
            else:
                scale *= 0.9
                if scale < 0.3:
                    canvas.save(final_path, "PNG" if use_png else "JPEG")
                    return True
                canvas, total_h = _render(scale)
                quality = 90
    except Exception as e:
        log(f"      ❌ รวมรูปผิดพลาด: {e}")
        return False
    finally:
        for im in imgs:
            try:
                im.close()
            except Exception:
                pass


def merge_folder(
    folder: str,
    group_size: int = 5,
    keep_original: bool = False,
    log: Callable[[str], None] = print,
) -> tuple[int, int]:
    """รวมรูปในโฟลเดอร์เดียว ทีละ group_size รูป

    คืน (จำนวนไฟล์รวมที่ได้, จำนวนรูปต้นฉบับ)
    """
    if not _PIL_AVAILABLE:
        log("   ❌ ไม่พบ Pillow — ติดตั้งด้วย: pip install Pillow")
        return (0, 0)
    if group_size < 2:
        log("   ⚠️ จำนวนต่อกลุ่มต้อง >= 2 — ข้ามการรวม")
        return (0, 0)

    images = _list_images(folder)
    if len(images) < 2:
        return (0, len(images))

    if keep_original:
        out_dir = os.path.join(folder, MERGED_SUBDIR)
        os.makedirs(out_dir, exist_ok=True)
        sources = [os.path.join(folder, f) for f in images]
        delete_after = False
    else:
        # rename → tmp_ เพื่อกันชนกับชื่อไฟล์รวม (01.jpg, 02.jpg, ...)
        sources = []
        for f in images:
            if f.startswith("tmp_"):
                sources.append(os.path.join(folder, f))
                continue
            src = os.path.join(folder, f)
            tmp = os.path.join(folder, "tmp_" + f)
            try:
                os.replace(src, tmp)
                sources.append(tmp)
            except Exception:
                sources.append(src)
        out_dir = folder
        delete_after = True

    total_groups = (len(sources) + group_size - 1) // group_size
    merged = 0
    for gi, i in enumerate(range(0, len(sources), group_size), start=1):
        group = sources[i:i + group_size]
        out_path = os.path.join(out_dir, f"{gi:02d}.jpg")
        if _combine(group, out_path, log):
            merged += 1
            log(f"   🧩 รวม {len(group)} รูป → {os.path.basename(out_path)}  [{gi}/{total_groups}]")
            if delete_after:
                for p in group:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
        else:
            log(f"   ⚠️ รวมกลุ่มที่ {gi} ไม่สำเร็จ — เก็บไฟล์ต้นฉบับไว้")
    return (merged, len(images))


def iter_image_folders(root: str):
    """ไล่หาโฟลเดอร์ที่มีรูปอยู่ภายใต้ root (ข้ามโฟลเดอร์ _merged)"""
    if not os.path.isdir(root):
        return
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != MERGED_SUBDIR]
        if any(f.lower().endswith(VALID_EXT) for f in files):
            yield cur


def merge_tree(
    root: str,
    group_size: int = 5,
    keep_original: bool = False,
    log: Callable[[str], None] = print,
    is_running: Callable[[], bool] = lambda: True,
) -> tuple[int, int]:
    """รวมรูปในทุกโฟลเดอร์ย่อยใต้ root (รวม root เองด้วย)

    คืน (จำนวนโฟลเดอร์ที่รวมสำเร็จ, จำนวนไฟล์รวมทั้งหมด)
    """
    folders_done = 0
    files_made = 0
    for folder in iter_image_folders(root):
        if not is_running():
            break
        name = os.path.basename(folder) or folder
        log(f"📂 โฟลเดอร์: {name}")
        made, src = merge_folder(folder, group_size, keep_original, log)
        if made:
            folders_done += 1
            files_made += made
            log(f"   ✅ {src} รูป → {made} ไฟล์")
        else:
            log(f"   – ข้าม (รูปไม่พอ/ไม่สำเร็จ)")
    return (folders_done, files_made)
