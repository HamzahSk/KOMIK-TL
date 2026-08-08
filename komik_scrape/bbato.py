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
        
        # --- CUSTOM HEADER DI SINI ---
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
        # --- CUSTOM HEADER LAGI UNTUK SOUP ---
        custom_headers = default_headers.copy()
        custom_headers['Referer'] = f"{BASE_URL}/"
        
        res = fetch_func(chapter_url, custom_headers, timeout=15)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Bbato Error] Gagal mengambil URL chapter: {e}")
        return None

# ... (fungsi get_page_list dan get_chapter_name menyesuaikan format template sebelumnya)
