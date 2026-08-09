# komik_scrape/bbato.py
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin

DOMAINS = ["bbato", "bbato.com"]
BASE_URL = "https://bbato.com"

def get_chapter_list(manga_url, fetch_func, default_headers):
    try:
        slug = manga_url.strip("/").split("/")[-1]
        api_url = f"{BASE_URL}/get-chapter-list?slug={slug}"
        
        # --- CUSTOM HEADER ---
        # Copy header bawaan biar User-Agent tetap ikut
        custom_headers = default_headers.copy() 
        custom_headers.update({
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': manga_url
        })
        
        # Gunakan custom_headers saat memanggil fetch_func
        res = fetch_func(api_url, custom_headers, timeout=15)
        res_json = res.json()
        
        if 'data' not in res_json or not isinstance(res_json['data'], list):
            return []
            
        chapters = []
        for ch in res_json['data']:
            ch_url = f"{BASE_URL}/read/{slug}/{ch.get('chapter_slug')}"
            chapters.append({
                'url': ch_url,
                'name': ch.get('chapter_name', 'Unknown_Chapter')
            })
        return chapters

    except Exception as e:
        print(f"[Bbato Error] Gagal mengambil chapter list: {e}")
        return []

def fetch_chapter_soup(chapter_url, fetch_func, default_headers):
    try:
        # --- CUSTOM HEADER UNTUK SOUP ---
        # Root referer sangat penting di sini untuk bypass CDN 403 blocks (seperti di Bbato.kt)
        custom_headers = default_headers.copy()
        custom_headers['Referer'] = f"{BASE_URL}/"
        
        res = fetch_func(chapter_url, custom_headers, timeout=15)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Bbato Error] Gagal mengambil URL chapter: {e}")
        return None

def get_page_list(soup, chapter_url, fetch_func, default_headers):
    pages = []
    if not soup:
        return pages
        
    # Gunakan selector spesifik: ambil img yang punya atribut data-number di dalam .pages
    images = soup.select(".pages .page:not(.notice-page) img[data-number]")
    
    for img in images:
        # Filter ekstra: pastikan kita skip kalau data-number nya "notice"
        if img.get("data-number") == "notice":
            continue
            
        # Urutan prioritas pengambilan URL gambar:
        # 1. data-src (biasanya untuk lazyload)
        # 2. data-fallback (sering dipakai di BBato sebagai cadangan)
        # 3. src (untuk gambar yang diload langsung / eager)
        img_url = img.get("data-src") or img.get("data-fallback") or img.get("src")
        
        # Validasi tambahan:
        # Pastikan img_url ada isinya dan BUKAN placeholder (seperti data:image/svg...)
        if img_url and not img_url.startswith("data:image"):
            # Gabungkan dengan BASE_URL kalau path-nya relatif
            img_url = urljoin(BASE_URL, img_url.strip())
            pages.append(img_url)
            
    return pages

def get_chapter_name(soup, chapter_url=""):
    """
    Fungsi pelengkap untuk mencocokkan format dengan scraper.py.
    Diambil berdasarkan format judul yang umumnya dipakai di Tachiyomi extension.
    """
    title = "Unknown Title"
    chapter_name = "Unknown Chapter"
    
    if soup:
        # Coba ambil judul komik (mangaDetailsParse Kotlin pake h1[itemprop=name])
        h1_title = soup.select_one("h1[itemprop=name]")
        if h1_title:
            title = h1_title.get_text(strip=True)
            
        # Untuk nama chapter saat sedang membaca, kita fallback menggunakan tag title web
        title_tag = soup.find("title")
        if title_tag:
            full_title = title_tag.get_text(strip=True)
            
            # Jika belum dapet title dari h1, coba ekstrak dari tag <title>
            if title == "Unknown Title" and "-" in full_title:
                parts = full_title.split("-", 1)
                title = parts[0].strip()
                chapter_name = parts[1].strip()
            elif "-" in full_title:
                chapter_name = full_title.split("-")[-1].strip()
            else:
                chapter_name = full_title
                
    return {"title": title, "chapter_name": chapter_name}
