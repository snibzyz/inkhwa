"""Regression test สำหรับปุ่ม "다음화" (next chapter) ของ Bomtoon.

ทดสอบ BomtoonDownloader._NEXT_JS ตัวจริงกับ HTML ที่จำลอง nav bar ของ Bomtoon
(설정 / 이전화 / 다음화 ที่เป็น React <div> ไม่ใช่ <button>) บน Chrome จริง (headless)

จุดที่พิสูจน์:
  1. หา + กดปุ่ม 다음화 ได้ (return "clicked")
  2. onClick อยู่ที่ "ตัว wrapper" แต่เรากดที่ leaf → event ต้อง bubble ขึ้นไปถึง  ✅
  3. ห้ามกดผิดเป็น 이전화 (previous) หรือ 설정 (settings)
  4. ถ้าปุ่มถูกปิด (aria-disabled / pointer-events:none) → return "disabled" ไม่กดอะไร

รัน:  python tools/test_next_button.py
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options

from downloaders.bomtoon import BomtoonDownloader

# ดึง JS ตัวจริงจากโค้ดที่ใช้งานจริง (ไม่ใช่สำเนา) เพื่อให้เทสสะท้อนของจริง
NEXT_JS = BomtoonDownloader._NEXT_JS


# --- nav bar จำลองตาม HTML จริงของ Bomtoon ---------------------------------
# โครงสร้าง/ชื่อ class ลอกจาก HTML ที่ผู้ใช้ส่งมา: 다음화 เป็น <div> ลูกของ wrapper
# ที่มี onClick อยู่ และมี cursor:pointer (เหมือน React component จริง)
def fixture(next_attr: str = "") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>
  .ctrl {{ cursor: pointer; display:inline-flex; }}
  .icon {{ width:24px; height:24px; }}
  .label {{ font-size:14px; }}
</style></head><body>
<div style="height:3000px"></div>  <!-- ดันให้ต้อง scrollIntoView จริง -->
<div class="sc-iFwKgL bufnxB">
  <div class="sc-iqGgem iTRagi">
    <div class="sc-eVQfli kvLyqP ctrl" onclick="window.__hit='settings'">
      <div class="sc-eFWqGp kTJXXc icon"><svg viewBox="0 0 24 24"></svg></div>
      <div class="sc-kTvvXX jxOUyb label">설정</div>
    </div>
  </div>
  <div class="sc-iqGgem iTRagi">
    <div class="sc-eVQfli kvLyqP ctrl" onclick="window.__hit='prev'">
      <div class="sc-eFWqGp kTJXXc icon"><svg viewBox="0 0 24 24"></svg></div>
      <div class="sc-kTvvXX fscKCH label">이전화</div>
    </div>
    <div class="sc-eVQfli kvLyqP ctrl" {next_attr} onclick="window.__hit='next'">
      <div class="sc-eFWqGp kTJXXc icon"><svg viewBox="0 0 24 24"></svg></div>
      <div class="sc-kTvvXX fscKCH label">다음화</div>
    </div>
  </div>
</div>
</body></html>"""


def fixture_no_next() -> str:
    """ตอนสุดท้าย: ไม่มีปุ่ม 다음화 (มีแต่ 이전화 / 설정)"""
    return """<!doctype html><html><head><meta charset="utf-8">
<style>.ctrl{cursor:pointer;display:inline-flex;}</style></head><body>
<div class="sc-iqGgem iTRagi">
  <div class="sc-eVQfli kvLyqP ctrl" onclick="window.__hit='settings'">
    <div class="sc-kTvvXX jxOUyb">설정</div></div>
  <div class="sc-eVQfli kvLyqP ctrl" onclick="window.__hit='prev'">
    <div class="sc-kTvvXX fscKCH">이전화</div></div>
</div>
</body></html>"""


def make_driver():
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1280,900")
    # Selenium Manager จะโหลด chromedriver ที่ตรงกับ Chrome ให้อัตโนมัติ
    return webdriver.Chrome(options=opts)


def load(driver, html: str):
    import tempfile
    fd, path = tempfile.mkstemp(suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(html)
    driver.get("file:///" + path.replace("\\", "/"))
    driver.execute_script("window.__hit = null;")
    return path


def run_case(driver, name, html, expect_ret, expect_hit):
    path = load(driver, html)
    try:
        ret = driver.execute_script("return (" + NEXT_JS + ")();")
        hit = driver.execute_script("return window.__hit;")
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    ok = (ret == expect_ret) and (hit == expect_hit)
    mark = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {mark}  {name}")
    print(f"         return = {ret!r:12s} (want {expect_ret!r})")
    print(f"         clicked= {hit!r:12s} (want {expect_hit!r})")
    return ok


def main():
    print("=" * 60)
    print("🧪 Bomtoon next-button (다음화) regression test")
    print("=" * 60)
    driver = make_driver()
    results = []
    try:
        # 1) ปกติ: ต้องกด 다음화 ได้ และ event bubble จาก leaf → wrapper onClick
        results.append(run_case(
            driver, "normal: คลิก 다음화 (div + bubble)",
            fixture(), expect_ret="clicked", expect_hit="next"))

        # 2) ปุ่มถูกปิดด้วย aria-disabled → ต้องไม่กด
        results.append(run_case(
            driver, "disabled: aria-disabled=true → ไม่กด",
            fixture('aria-disabled="true"'),
            expect_ret="disabled", expect_hit=None))

        # 3) ปุ่มถูกปิดด้วย pointer-events:none → ต้องไม่กด
        results.append(run_case(
            driver, "disabled: pointer-events:none → ไม่กด",
            fixture('style="pointer-events:none"'),
            expect_ret="disabled", expect_hit=None))

        # 4) ตอนสุดท้าย: ไม่มี 다음화 → คืน null (run_loop จะหยุดสะอาด ๆ)
        results.append(run_case(
            driver, "end: ไม่มี 다음화 → return null",
            fixture_no_next(), expect_ret=None, expect_hit=None))

        # 5) ยืนยันชัด ๆ: เมื่อมีทั้งคู่ ห้ามไปโดน 이전화 (กรณีเทส 1 ผ่านแล้ว
        #    แต่ใส่ assert แยกให้ชัดว่า hit ต้องเป็น 'next' ไม่ใช่ 'prev')
        path = load(driver, fixture())
        driver.execute_script("return (" + NEXT_JS + ")();")
        hit = driver.execute_script("return window.__hit;")
        try:
            os.remove(path)
        except OSError:
            pass
        ok5 = (hit == "next")
        print(f"  {'✅ PASS' if ok5 else '❌ FAIL'}  guard: ไม่กดโดน 이전화/설정 (hit={hit!r})")
        results.append(ok5)
    finally:
        driver.quit()

    print("-" * 60)
    passed = sum(results)
    total = len(results)
    print(f"ผลรวม: {passed}/{total} ผ่าน")
    if passed != total:
        sys.exit(1)
    print("🎉 ผ่านครบ — ปุ่ม Next ทำงานจริง")


if __name__ == "__main__":
    main()
