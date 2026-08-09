import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
DOMAINS = ["bbato.com"]

# Konfigurasi Domain
BBATO_URL = "https://bbato.com"


def get_chapter_list(manga_url, fetch_func, headers):
    """
    Mengambil daftar chapter khusus dari Bbato.
    Menggunakan fetch_func bawaan dari scraper.py
    """
    try:
        # Ambil slug/id paling akhir dari URL manga
        slug = manga_url.strip("/").split("/")[-1]
        
        # Setup headers khusus XMLHttpRequest milik bbato untuk bypass perlindungan
        bbato_headers = headers.copy()
        bbato_headers.update({
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': manga_url
        })
        
        api_url = f"{BBATO_URL}/get-chapter-list?slug={slug}"
        res = fetch_func(api_url, bbato_headers)
        res_json = res.json()
        
        if 'data' not in res_json or not isinstance(res_json['data'], list):
            return []
            
        chapters = []
        for ch in res_json['data']:
            # Menyusun URL asli untuk membaca chapter
            ch_url = f"{BBATO_URL}/read/{slug}/{ch.get('chapter_slug')}"
            
            # Format standar yang diharapkan main.py
            chapters.append({
                'title': ch.get('chapter_name', 'Unknown_Chapter'),
                'url': ch_url,
                'date': ""
            })
            
        return chapters

    except Exception as e:
        print(f"[Error - Bbato] Gagal mengambil daftar chapter: {e}")
        return []


def fetch_chapter_soup(chapter_url, fetch_func, headers):
    """
    Fetch dan parse HTML menjadi objek soup.
    Menerima parameter sesuai standar scraper.py.
    """
    try:
        bbato_headers = headers.copy()
        bbato_headers['Referer'] = f"{BBATO_URL}/"
        
        res = fetch_func(chapter_url, bbato_headers)
        return BeautifulSoup(res.text, 'html.parser')
        
    except Exception as e:
        print(f"[Error - Bbato] Gagal memuat halaman chapter: {e}")
        return None


def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mengambil list gambar dari objek soup.
    Format return dibuat kompatibel 100% dengan main.py
    """
    if not soup:
        return []
    
    pages = []
    try:
        # Mengambil elemen gambar dan menghindari notice-page (seperti di Tachiyomi)
        for idx, img in enumerate(soup.select('.pages .page:not(.notice-page) img')):
            img_url = img.get('data-src') or img.get('src')
            
            if img_url:
                # Pastikan link gambar berbentuk absolut
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
        return {
            "title": "Unknown Title",
            "chapter_name": "Unknown Chapter"
        }

    try:
        # Mencari metadata BreadcrumbList yang tersembunyi di tag script
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
