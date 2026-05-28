import os
from PIL import Image
import io

# โฟลเดอร์หลัก = ตำแหน่งที่ไฟล์ .py อยู่
ROOT_FOLDER = os.path.dirname(os.path.abspath(__file__))

# จำนวนภาพต่อการรวม 1 ภาพ
GROUP_SIZE = 7

# ประเภทไฟล์ภาพที่รองรับ
VALID_EXT = (".png", ".jpg", ".jpeg")

def get_images(folder):
    files = [f for f in os.listdir(folder) if f.lower().endswith(VALID_EXT)]
    # เรียงตามตัวเลขในชื่อไฟล์ เช่น 1.png, 01.jpg, 2.jpeg
    try:
        files.sort(key=lambda x: int(os.path.splitext(x)[0].lstrip("tmp_")))
    except ValueError:
        files.sort()
    return files

def combine_images(images, save_path):
    imgs = []
    try:
        # โหลดภาพทั้งหมด
        for img_path in images:
            try:
                img = Image.open(img_path)
                # แปลงเป็น RGB ถ้าเป็น RGBA หรือ mode อื่น
                if img.mode != "RGB":
                    img = img.convert("RGB")
                imgs.append(img)
            except Exception as e:
                print(f"  ⚠️ ไม่สามารถโหลดภาพ {img_path}: {e}")
                continue
        
        if not imgs:
            print(f"  ❌ ไม่มีภาพที่โหลดได้")
            return False

        # ปรับความกว้างให้เท่ากันตามภาพแรก
        base_width = imgs[0].width
        resized_imgs = []
        for im in imgs:
            if im.width != base_width:
                new_height = int(im.height * base_width / im.width)
                im = im.resize((base_width, new_height), Image.LANCZOS)
            resized_imgs.append(im)

        total_height = sum(i.height for i in resized_imgs)
        
        # ตรวจสอบขนาดภาพก่อนสร้าง
        MAX_DIMENSION = 65500  # ขนาดสูงสุดที่ JPEG รองรับ
        if total_height > MAX_DIMENSION:
            print(f"  ⚠️ ภาพรวมสูงเกิน {MAX_DIMENSION} pixels ({total_height}px)")
            print(f"  💡 กำลังปรับขนาดภาพ...")
            # คำนวณ scale factor
            scale_factor = MAX_DIMENSION / total_height
            new_width = int(base_width * scale_factor)
            new_total_height = int(total_height * scale_factor)
            
            # Resize ทุกภาพ
            resized_imgs = []
            for im in imgs:
                if im.width != base_width:
                    new_height = int(im.height * base_width / im.width)
                    im = im.resize((base_width, new_height), Image.LANCZOS)
                # Resize ตาม scale factor
                final_height = int(im.height * scale_factor)
                im = im.resize((new_width, final_height), Image.LANCZOS)
                resized_imgs.append(im)
            
            base_width = new_width
            total_height = new_total_height
            print(f"  ✅ ปรับขนาดเป็น {base_width}x{total_height}")

        new_img = Image.new("RGB", (base_width, total_height), (255, 255, 255))

        y_offset = 0
        for im in resized_imgs:
            new_img.paste(im, (0, y_offset))
            y_offset += im.height

        # ตรวจสอบและปรับขนาดไฟล์ให้น้อยกว่า 30MB
        MAX_FILE_SIZE = 30 * 1024 * 1024  # 30MB ใน bytes
        
        # ลองบันทึกเป็น JPEG ก่อน
        quality = 95
        use_png = False
        
        if total_height > 30000:
            # สำหรับภาพขนาดใหญ่ ใช้ PNG
            use_png = True
            save_path_final = save_path.replace('.jpg', '.png')
        else:
            save_path_final = save_path
        
        # วนลูปปรับ quality/resize จนกว่าจะได้ขนาดไฟล์น้อยกว่า 30MB
        while True:
            # ทดสอบขนาดไฟล์ใน memory
            buffer = io.BytesIO()
            if use_png:
                new_img.save(buffer, 'PNG', optimize=True)
            else:
                new_img.save(buffer, 'JPEG', quality=quality, optimize=True)
            file_size = buffer.tell()
            buffer.close()
            
            if file_size < MAX_FILE_SIZE:
                # ขนาดไฟล์พอดีแล้ว บันทึกจริง
                if use_png:
                    new_img.save(save_path_final, 'PNG', optimize=True)
                    print(f"  💾 บันทึกเป็น PNG: {save_path_final} ({file_size / 1024 / 1024:.2f} MB)")
                else:
                    new_img.save(save_path_final, 'JPEG', quality=quality, optimize=True)
                    print(f"  💾 บันทึกเป็น JPEG (quality={quality}): {save_path_final} ({file_size / 1024 / 1024:.2f} MB)")
                break
            
            # ถ้าไฟล์ใหญ่เกินไป ลด quality หรือ resize
            if use_png:
                # สำหรับ PNG ลดขนาดภาพ
                print(f"  ⚠️ ไฟล์ใหญ่เกิน ({file_size / 1024 / 1024:.2f} MB) กำลังปรับขนาด...")
                scale_factor = 0.9  # ลดลง 10%
                new_width = int(base_width * scale_factor)
                new_total_height = int(total_height * scale_factor)
                
                # Resize ภาพใหม่
                resized_imgs = []
                for im in imgs:
                    if im.width != base_width:
                        new_height = int(im.height * base_width / im.width)
                        im = im.resize((base_width, new_height), Image.LANCZOS)
                    final_height = int(im.height * scale_factor)
                    im = im.resize((new_width, final_height), Image.LANCZOS)
                    resized_imgs.append(im)
                
                # สร้างภาพใหม่
                new_img.close()
                new_img = Image.new("RGB", (new_width, new_total_height), (255, 255, 255))
                y_offset = 0
                for im in resized_imgs:
                    new_img.paste(im, (0, y_offset))
                    y_offset += im.height
                
                base_width = new_width
                total_height = new_total_height
                print(f"  ✅ ปรับขนาดเป็น {base_width}x{total_height}")
            else:
                # สำหรับ JPEG ลด quality
                if quality > 50:
                    quality -= 5
                    print(f"  ⚠️ ไฟล์ใหญ่เกิน ({file_size / 1024 / 1024:.2f} MB) ลด quality เป็น {quality}")
                else:
                    # ถ้า quality ต่ำเกินไปแล้ว เปลี่ยนเป็น resize
                    print(f"  ⚠️ Quality ต่ำเกินไป กำลังปรับขนาดภาพ...")
                    scale_factor = 0.9
                    new_width = int(base_width * scale_factor)
                    new_total_height = int(total_height * scale_factor)
                    
                    resized_imgs = []
                    for im in imgs:
                        if im.width != base_width:
                            new_height = int(im.height * base_width / im.width)
                            im = im.resize((base_width, new_height), Image.LANCZOS)
                        final_height = int(im.height * scale_factor)
                        im = im.resize((new_width, final_height), Image.LANCZOS)
                        resized_imgs.append(im)
                    
                    new_img.close()
                    new_img = Image.new("RGB", (new_width, new_total_height), (255, 255, 255))
                    y_offset = 0
                    for im in resized_imgs:
                        new_img.paste(im, (0, y_offset))
                        y_offset += im.height
                    
                    base_width = new_width
                    total_height = new_total_height
                    quality = 85  # Reset quality
                    print(f"  ✅ ปรับขนาดเป็น {base_width}x{total_height}")
        
        # ปิดไฟล์ภาพทั้งหมด
        for img in imgs:
            img.close()
        new_img.close()
        
        return True
        
    except Exception as e:
        print(f"  ❌ Error รวมภาพ: {e}")
        # ปิดไฟล์ภาพทั้งหมดในกรณี error
        for img in imgs:
            try:
                img.close()
            except:
                pass
        return False

def process_folder(folder):
    files = [f for f in os.listdir(folder) if f.lower().endswith(VALID_EXT)]
    if not files:
        return

    # --- ขั้นตอนที่ 1: เปลี่ยนชื่อไฟล์ทั้งหมดเป็น temporary ---
    tmp_files = []
    for f in files:
        old_path = os.path.join(folder, f)
        tmp_name = f"tmp_{f}"
        new_path = os.path.join(folder, tmp_name)
        os.rename(old_path, new_path)
        tmp_files.append(tmp_name)

    # --- ขั้นตอนที่ 2: ทำงานกับไฟล์ temporary ---
    tmp_files = get_images(folder)

    merged_count = 1
    for i in range(0, len(tmp_files), GROUP_SIZE):
        group = tmp_files[i:i+GROUP_SIZE]
        if not group:
            continue

        paths = [os.path.join(folder, f) for f in group]
        save_name = f"{merged_count:02}.jpg"
        save_path = os.path.join(folder, save_name)

        print(f"[{os.path.basename(folder)}] รวม: {group} -> {save_name}")
        success = combine_images(paths, save_path)

        # ลบไฟล์ temp เฉพาะเมื่อรวมสำเร็จ
        if success:
            for p in paths:
                try:
                    os.remove(p)
                except Exception as e:
                    print(f"  ⚠️ ไม่สามารถลบไฟล์ {p}: {e}")
        else:
            print(f"  ⚠️ ข้ามการลบไฟล์ temp เนื่องจากเกิด error")

        merged_count += 1

def main():
    for root, dirs, files in os.walk(ROOT_FOLDER):
        process_folder(root)

if __name__ == "__main__":
    main()
