import json
import asyncio
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
DOMAINS = ["bbato.com"]
BBATO_URL = "https://bbato.com"


# ==========================================
# PLAYWRIGHT STEALTH INJECTORS (v2.x API)
# ==========================================
async def _get_json_with_playwright(url, referer_url):
    """Membuka API Json langsung via browser Playwright jika requests terblokir."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            extra_http_headers={'Referer': referer_url, 'X-Requested-With': 'XMLHttpRequest'}
        )
        page = await context.new_page()
        
        # Buka URL API secara langsung. Browser biasanya akan me-render JSON sebagai text/pre
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        content = await page.inner_text("body")
        await browser.close()
        
        return json.loads(content)


async def _get_html_with_playwright(url):
    """Menggunakan Playwright untuk mengambil HTML penuh dan mem-bypass Cloudflare."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Buka halaman dan tunggu sampai HTML ter-load
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        
        # Tunggu sebentar memastikan elemen lazy-load DOM muncul (jika ada)
        await page.wait_for_timeout(2000)
        html_content = await page.content()
        await browser.close()
        
        return html_content


# ==========================================
# FUNGSI SCRAPING UTAMA
# ==========================================

def get_chapter_list(manga_url, fetch_func, headers):
    """
    Mengambil daftar chapter khusus dari Bbato.
    Otomatis fallback ke Playwright jika API ditolak Cloudflare.
    """
    slug = manga_url.strip("/").split("/")[-1]
    api_url = f"{BBATO_URL}/get-chapter-list?slug={slug}"
    
    bbato_headers = headers.copy()
    bbato_headers.update({
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': manga_url
    })
    
    try:
        # 1. Coba fetch normal dengan requests
        res = fetch_func(api_url, bbato_headers)
        res_json = res.json()
    except Exception as e:
        print(f"[Info Bbato] Requests API gagal ({e}). Membuka Playwright untuk bypass...")
        try:
            # 2. Fallback ke Playwright jika terblokir 403
            res_json = asyncio.run(_get_json_with_playwright(api_url, manga_url))
        except Exception as play_e:
            print(f"[Error Bbato] Playwright gagal mengambil API chapter: {play_e}")
            return []

    if not res_json or 'data' not in res_json or not isinstance(res_json['data'], list):
        return []
        
    chapters = []
    for ch in res_json['data']:
        ch_url = f"{BBATO_URL}/read/{slug}/{ch.get('chapter_slug')}"
        chapters.append({
            'title': ch.get('chapter_name', 'Unknown_Chapter'),
            'url': ch_url,
            'date': ""
        })
        
    return chapters


def fetch_chapter_soup(chapter_url, fetch_func, headers):
    """
    Fetch dan parse HTML menjadi objek soup.
    Otomatis fallback ke Playwright jika HTML diblokir.
    """
    try:
        bbato_headers = headers.copy()
        bbato_headers['Referer'] = f"{BBATO_URL}/"
        
        res = fetch_func(chapter_url, bbato_headers)
        return BeautifulSoup(res.text, 'html.parser')
        
    except Exception as e:
        print(f"[Info Bbato] Requests HTML ditolak ({e}). Membuka browser Playwright...")
        try:
            html_content = asyncio.run(_get_html_with_playwright(chapter_url))
            return BeautifulSoup(html_content, 'html.parser')
        except Exception as play_e:
            print(f"[Error Bbato] Playwright gagal memuat HTML: {play_e}")
            return None


def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mengambil list gambar dari objek soup.
    Format return dibuat kompatibel 100% dengan main.py.
    """
    if not soup:
        return []
    
    pages = []
    try:
        # Karena soup sudah diekstrak dengan sukses (baik via requests atau Playwright),
        # elemen DOM gambar harusnya sudah tersedia di sini.
        for idx, img in enumerate(soup.select('.pages .page:not(.notice-page) img')):
            img_url = img.get('data-src') or img.get('src')
            
            if img_url:
                if not img_url.startswith('http'):
                    img_url = urljoin(BBATO_URL, img_url)
                    
                pages.append({
                    'index': idx, 
                    'url': img_url,
                    'imageUrl': img_url
                })
                
        return pages
        
    except Exception as e:
        print(f"[Error - Bbato] Gagal memproses halaman gambar: {e}")
        return []


def get_chapter_name(soup, chapter_url=""):
    """
    Mengambil judul komik dan chapter dari struktur JSON-LD (Breadcrumb) di DOM.
    """
    if not soup:
        return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}

    try:
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            if not script.string:
                continue
            try:
                data = json.loads(script.string)
                if data.get("@type") == "BreadcrumbList":
                    items = data.get("itemListElement", [])
                    
                    if len(items) >= 2:
                        return {
                            "title": items[-2].get("name", "Unknown Title"),
                            "chapter_name": items[-1].get("name", "Unknown Chapter")
                        }
                    elif len(items) == 1:
                        return {
                            "title": "Unknown Title",
                            "chapter_name": items[-1].get("name", "Unknown Chapter")
                        }
            except json.JSONDecodeError:
                continue

        return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}

    except Exception as e:
        print(f"[Error - Bbato] Gagal memproses nama chapter: {e}")
        return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}
