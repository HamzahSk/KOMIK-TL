import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from curl_cffi import requests as cffi_requests
from .stealth_helpers import fetch_chapter_html

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
DOMAINS = ["bbato.com"]
BBATO_URL = "https://bbato.com"

# ==========================================
# FUNGSI SCRAPING UTAMA
# ==========================================

def get_chapter_list(manga_url, fetch_func, headers):
    """
    Mengambil daftar chapter khusus dari Bbato.
    Otomatis fallback ke curl_cffi dan Playwright Sync jika ditolak Cloudflare.
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
        # 1. Coba fetch normal dengan requests standar scraper.py
        res = fetch_func(api_url, bbato_headers)
        res_json = res.json()
    except Exception as e:
        print(f"[Info Bbato] Requests API gagal ({e}). Mencoba curl_cffi...")
        try:
            # 2. Fallback ke curl_cffi (Sangat ringan, membypass perlindungan TLS)
            res = cffi_requests.get(api_url, headers=bbato_headers, impersonate="chrome120", timeout=30)
            res_json = res.json()
        except Exception as e_cffi:
            print(f"[Info Bbato] curl_cffi gagal ({e_cffi}). Beralih ke Playwright Sync...")
            try:
                # 3. Fallback terakhir ke Playwright (meminjam fungsi fetch_chapter_html)
                raw_html = fetch_chapter_html(api_url, bbato_headers)
                # Browser biasanya membungkus JSON mentah dalam tag <pre> atau <body>
                soup_json = BeautifulSoup(raw_html, "html.parser")
                res_json = json.loads(soup_json.text)
            except Exception as e_play:
                print(f"[Error Bbato] Playwright gagal mengambil API chapter: {e_play}")
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
    Otomatis fallback ke curl_cffi dan Playwright Sync melalui stealth_helpers.
    """
    try:
        bbato_headers = headers.copy()
        bbato_headers['Referer'] = f"{BBATO_URL}/"
        
        # Coba cara ringan terlebih dahulu
        res = fetch_func(chapter_url, bbato_headers)
        return BeautifulSoup(res.text, 'html.parser')
        
    except Exception as e:
        print(f"[Info Bbato] Requests HTML ditolak ({e}). Memanggil module stealth...")
        
        # Panggil fungsi Sync secara langsung (tidak perlu await/asyncio.run)
        html_content = fetch_chapter_html(chapter_url, bbato_headers)
        if html_content:
            return BeautifulSoup(html_content, 'html.parser')
        return None


def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mengambil list gambar dari objek soup.
    Karena halaman berhasil diload (entah via requests atau playwright), elemen gambar pasti ada di soup.
    """
    if not soup:
        return []
    
    pages = []
    try:
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
