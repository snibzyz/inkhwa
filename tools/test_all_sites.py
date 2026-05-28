"""ทดสอบทั้ง 5 เว็บ — สุ่มเรื่อง/ตอนฟรี ใช้ credential เดียวกัน

discovery v2: อิงจาก discover_links.py dump
- Bomtoon: SPA แท้ ๆ — ใช้ hardcoded URL Mon_Love EP1 (free trial)
- RidiBooks: ไปยัง /selection/749 (무료 page) → หา /books/<id>
- Lezhin: ไปยัง /ko/free → หา /ko/comic/<series>
- Toptoon: home → หา /comic/ep_list/<series>
- Kakao: ไปยัง /menu/10010/screen/86 (연재무료) → หา /content/<id>
"""
import os
import sys
import time
import random
import shutil
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from downloaders import get_downloader, ChromeManager, DownloaderContext

# อ่านจาก env var เท่านั้น — set ก่อนรัน:
#   PowerShell: $env:INKHWA_USER='you@example.com'; $env:INKHWA_PASS='yourpw'
#   cmd:        set INKHWA_USER=you@example.com & set INKHWA_PASS=yourpw
CREDS_USER = os.environ.get("INKHWA_USER", "")
CREDS_PASS = os.environ.get("INKHWA_PASS", "")
MAX_IMAGES = 5
OUT_BASE = os.path.join(ROOT, "Test_AllSites")
os.makedirs(OUT_BASE, exist_ok=True)


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def dump_sample_links(driver, max_n=10):
    """ใช้ debug เมื่อ discovery fail"""
    try:
        links = driver.execute_script(
            "return Array.from(document.querySelectorAll('a[href]'))"
            ".filter(a => !a.href.startsWith('javascript') && !a.href.startsWith('#'))"
            ".slice(0, " + str(max_n) + ")"
            ".map(a => ({href: a.href, text: (a.textContent||'').trim().slice(0,40)}));"
        )
        for l in links:
            log(f"      sample: '{l['text']}' → {l['href'][:100]}")
    except Exception:
        pass


# =========================================================================
# Per-site discovery (v2)
# =========================================================================
def find_free_bomtoon(driver):
    # Bomtoon SPA = 0 anchors บน homepage
    # ใช้ URL series ที่รู้ว่า ep1 ฟรี (Mon_Love)
    url = "https://www.bomtoon.com/viewer/Mon_Love/1"
    log(f"   📌 Bomtoon hardcoded ep1: {url}")
    return url


def find_free_ridi(driver):
    log("   🔎 Ridi: ไปยัง /selection/749 (무료)")
    driver.get("https://ridibooks.com/selection/749")
    time.sleep(7)
    book_url = driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href]'));
        const books = links
            .map(a => a.href)
            .filter(h => /\/books\/\d+/.test(h));
        if (books.length === 0) return null;
        const uniq = [...new Set(books)];
        return uniq[Math.floor(Math.random() * Math.min(5, uniq.length))];
        """
    )
    if not book_url:
        log("   ⚠️ /books/<id> ไม่เจอ — dump sample:")
        dump_sample_links(driver)
        return None
    log(f"   📍 book: {book_url}")
    driver.get(book_url)
    time.sleep(6)
    # ดู link ที่ลิงก์ไป viewer หรือ first chapter
    return driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href]'));
        // หา link viewer ก่อน
        const viewer = links.map(a => a.href).filter(h => /\/viewer/.test(h) || /\/v\//.test(h));
        if (viewer.length > 0) return viewer[0];
        // fallback: link ที่มีคำว่า '무료' หรือ '체험' หรือ '바로'
        for (const a of links) {
            const t = (a.textContent || '').trim();
            if ((t.includes('무료') || t.includes('체험') || t.includes('바로보기')) && a.href) {
                return a.href;
            }
        }
        return null;
        """
    )


def find_free_lezhin(driver):
    log("   🔎 Lezhin: ไปยัง /ko/free")
    driver.get("https://www.lezhin.com/ko/free")
    time.sleep(7)
    comic_url = driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href*="/ko/comic/"]'));
        const filtered = links
            .map(a => a.href)
            .filter(h => /\/ko\/comic\/[^/?#]+$/.test(h) || /\/ko\/comic\/[^/?#]+\/[^/?#]+$/.test(h));
        if (filtered.length === 0) return null;
        const uniq = [...new Set(filtered)];
        return uniq[Math.floor(Math.random() * Math.min(6, uniq.length))];
        """
    )
    if not comic_url:
        # fallback ใช้ homepage
        log("   ⚠️ /ko/free ไม่เจอ comic — ลอง homepage")
        driver.get("https://www.lezhin.com/ko")
        time.sleep(5)
        comic_url = driver.execute_script(
            r"""
            const links = Array.from(document.querySelectorAll('a[href*="/ko/comic/"]'));
            const uniq = [...new Set(links.map(a => a.href).filter(h => /\/ko\/comic\/[^/?#]+$/.test(h)))];
            return uniq.length > 0 ? uniq[0] : null;
            """
        )
    if not comic_url:
        return None
    log(f"   📍 comic: {comic_url}")
    driver.get(comic_url)
    time.sleep(6)
    # หา episode ตอนแรก
    return driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href]'));
        // หา link episode 1 — มักอยู่ท้ายลิสต์
        const eps = links
            .map(a => a.href)
            .filter(h => /\/ko\/comic\/[^/?#]+\/\d+/.test(h));
        if (eps.length === 0) return null;
        const uniq = [...new Set(eps)];
        return uniq[uniq.length - 1];
        """
    )


def find_free_toptoon(driver):
    log("   🔎 Toptoon: หา series จาก homepage")
    driver.get("https://toptoon.com/")
    time.sleep(7)
    series_url = driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href*="/comic/ep_list/"]'));
        const uniq = [...new Set(links.map(a => a.href))];
        if (uniq.length === 0) return null;
        return uniq[Math.floor(Math.random() * Math.min(6, uniq.length))];
        """
    )
    if not series_url:
        log("   ⚠️ ไม่เจอ /comic/ep_list/")
        dump_sample_links(driver)
        return None
    log(f"   📍 series: {series_url}")
    driver.get(series_url)
    time.sleep(6)
    return driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href]'));
        const eps = links
            .map(a => a.href)
            .filter(h => /\/comic\/episode\//.test(h) || /\/comic\/[^/]+\/\d+/.test(h));
        if (eps.length === 0) return null;
        const uniq = [...new Set(eps)];
        return uniq[uniq.length - 1];
        """
    )


def find_free_kakao(driver):
    log("   🔎 Kakao: ไปยัง 연재무료 (/menu/10010/screen/86)")
    driver.get("https://page.kakao.com/menu/10010/screen/86")
    time.sleep(8)
    content_url = driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href*="/content/"]'));
        const uniq = [...new Set(links.map(a => a.href).filter(h => /\/content\/\d+$/.test(h)))];
        if (uniq.length === 0) return null;
        return uniq[Math.floor(Math.random() * Math.min(6, uniq.length))];
        """
    )
    if not content_url:
        log("   ⚠️ ไม่เจอ /content/<id>")
        dump_sample_links(driver)
        return None
    log(f"   📍 content: {content_url}")
    driver.get(content_url)
    time.sleep(7)
    # หา link viewer — ตอน 1 มักอยู่ท้ายลิสต์
    return driver.execute_script(
        r"""
        const links = Array.from(document.querySelectorAll('a[href*="/viewer/"]'));
        const uniq = [...new Set(links.map(a => a.href))];
        if (uniq.length === 0) return null;
        return uniq[uniq.length - 1];
        """
    )


DISCOVERY = {
    "Bomtoon": find_free_bomtoon,
    "RidiBooks": find_free_ridi,
    "Lezhin": find_free_lezhin,
    "Toptoon": find_free_toptoon,
    "Kakao": find_free_kakao,
}


# =========================================================================
# Limited-download context
# =========================================================================
class LimitedCtx:
    def __init__(self, max_images):
        self._max = max_images
        self._count = 0
        self.log = log
        self.progress = self._progress
        self._stop = False

    def _progress(self, c, t):
        self._count = c
        if c >= self._max:
            self._stop = True

    def is_running(self):
        return not self._stop


# =========================================================================
def test_site(site_name: str) -> dict:
    result = {"site": site_name, "login": False, "chapter_url": None,
              "images": 0, "error": None}
    log("=" * 60)
    log(f"🌐 TEST {site_name}")
    log("=" * 60)

    chrome = None
    try:
        downloader = get_downloader(site_name)
        chrome = ChromeManager(
            profile_dir=os.path.join(ROOT, "profiles", downloader.profile_dir),
            log=log,
        )
        driver = chrome.launch(start_url=downloader.url)
        time.sleep(3)

        ctx = DownloaderContext(log=log, is_running=lambda: True)
        result["login"] = downloader.login(driver, CREDS_USER, CREDS_PASS, ctx)
        log(f"   login: {result['login']}")

        chapter_url = DISCOVERY[site_name](driver)
        if not chapter_url:
            result["error"] = "discovery failed"
            return result
        result["chapter_url"] = chapter_url
        log(f"   🎯 chapter: {chapter_url}")
        driver.get(chapter_url)
        time.sleep(8)

        save_dir = os.path.join(OUT_BASE, site_name)
        if os.path.exists(save_dir):
            shutil.rmtree(save_dir, ignore_errors=True)
        os.makedirs(save_dir, exist_ok=True)

        lctx = LimitedCtx(max_images=MAX_IMAGES)
        count = downloader.download_chapter(driver, save_dir, lctx)
        result["images"] = count
        log(f"   📊 saved: {count}")

    except Exception as e:
        result["error"] = f"{type(e).__name__}: {e}"
        log(f"   ❌ {result['error']}")
        traceback.print_exc()
    finally:
        if chrome:
            chrome.quit()
            time.sleep(2)
    return result


def main():
    log("🚀 Test all sites — credential = " + CREDS_USER)
    sites = ["Bomtoon", "RidiBooks", "Lezhin", "Toptoon", "Kakao"]
    results = [test_site(s) for s in sites]

    log("=" * 60)
    log("📋 SUMMARY")
    log("=" * 60)
    for r in results:
        emoji = "✅" if r["images"] > 0 else "❌"
        log(f"{emoji} {r['site']:10} login={r['login']!s:5} images={r['images']:>3} "
            f"err={r['error']!s:.50}")
        if r["chapter_url"]:
            log(f"      → {r['chapter_url']}")


if __name__ == "__main__":
    main()
