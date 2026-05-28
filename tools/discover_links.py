"""สแกน homepage ของแต่ละเว็บ → dump candidate URLs + "free" indicators"""
import os
import sys
import time
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from downloaders import get_downloader, ChromeManager, DownloaderContext


def log(msg):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


PROBE_URLS = {
    "Bomtoon": [
        "https://www.bomtoon.com/",
        "https://www.bomtoon.com/board/series_completion",
        "https://www.bomtoon.com/board/free",
    ],
    "RidiBooks": [
        "https://ridibooks.com/",
        "https://ridibooks.com/comics",
        "https://ridibooks.com/category/comic",
        "https://comic.ridibooks.com/",
    ],
    "Lezhin": [
        "https://www.lezhin.com/ko",
        "https://www.lezhin.com/ko/comic",
        "https://www.lezhin.com/ko/ranking",
    ],
    "Toptoon": [
        "https://toptoon.com/",
        "https://toptoon.com/freeWebtoon",
        "https://toptoon.com/event/free",
    ],
    "Kakao": [
        "https://page.kakao.com/",
        "https://page.kakao.com/menu/10010",
        "https://page.kakao.com/menu/10011",
    ],
}

DUMP_JS = r"""
() => {
    const seen = new Set();
    const candidates = [];
    document.querySelectorAll('a[href]').forEach(a => {
        const href = a.href;
        if (!href || href.startsWith('javascript:') || href.startsWith('#')) return;
        if (seen.has(href)) return;
        seen.add(href);
        const text = (a.textContent || '').trim().slice(0, 60);
        candidates.push({href, text});
    });
    return {
        title: document.title,
        url: location.href,
        bodyLen: (document.body && document.body.innerText || '').length,
        linkCount: candidates.length,
        links: candidates.slice(0, 50),
    };
}
"""


def probe(site_name: str, urls: list[str]) -> dict:
    downloader = get_downloader(site_name)
    chrome = ChromeManager(
        profile_dir=os.path.join(ROOT, "profiles", downloader.profile_dir),
        log=log,
    )
    out = {"site": site_name, "pages": []}
    try:
        driver = chrome.launch(start_url=urls[0])
        time.sleep(5)
        for url in urls:
            log(f"   📍 {url}")
            try:
                driver.get(url)
                time.sleep(7)  # SPA — รอ render
                info = driver.execute_script("return (" + DUMP_JS + ")();")
                log(f"     title='{info['title']}' links={info['linkCount']}")
                # log free-related links
                free_links = [
                    l for l in info["links"]
                    if any(kw in l["text"] for kw in ["무료", "Free", "FREE", "ฟรี", "0원"])
                ]
                if free_links:
                    log(f"     🆓 free-keyword links: {len(free_links)}")
                    for l in free_links[:5]:
                        log(f"        '{l['text']}' → {l['href']}")
                # log all unique pattern
                patterns = {}
                for l in info["links"]:
                    h = l["href"]
                    for key in ["/viewer/", "/content/", "/comic/", "/books/", "/episode/", "/series/", "/toon/", "/webtoon/"]:
                        if key in h:
                            patterns.setdefault(key, 0)
                            patterns[key] += 1
                            break
                if patterns:
                    log(f"     patterns: {patterns}")
                out["pages"].append({
                    "url": url,
                    "title": info["title"],
                    "linkCount": info["linkCount"],
                    "free_links": free_links,
                    "patterns": patterns,
                    "all_links": info["links"][:30],
                })
            except Exception as e:
                log(f"     ❌ {e}")
    finally:
        chrome.quit()
        time.sleep(2)
    return out


def main():
    all_results = []
    for site, urls in PROBE_URLS.items():
        log("=" * 60)
        log(f"🔬 PROBE {site}")
        log("=" * 60)
        r = probe(site, urls)
        all_results.append(r)
        time.sleep(2)

    out_path = os.path.join(ROOT, "Test_AllSites", "discovery_dump.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    log(f"\n💾 saved: {out_path}")


if __name__ == "__main__":
    main()
