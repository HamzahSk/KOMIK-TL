# scraper.py
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://vymanga.net"
CORS_PROXY = "https://cors-proxy1.rockyyrec.workers.dev/?url="
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

def get_chapter_list(manga_url):
    try:
        target_url = f"{CORS_PROXY}{manga_url}"
        res = requests.get(target_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        chapters = []
        for a in soup.select('.list-group > a'):
            href = a.get('href')
            span = a.find('span')
            name = span.text.strip() if span else "Unknown_Chapter"
            
            if href:
                chapters.append({
                    'url': urljoin(BASE_URL, href),
                    'name': name
                })
        return chapters
    except Exception as e:
        print(f"[Error] Gagal mengambil detail manga: {e}")
        return []

def get_page_list(chapter_url):
    try:
        # Menambahkan CORS proxy di depan URL target
        target_url = f"{CORS_PROXY}{chapter_url}"
        res = requests.get(target_url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        pages = []
        for idx, img in enumerate(soup.select('img.d-block')):
            img_url = img.get('data-src') or img.get('src')
            if img_url:
                pages.append({'index': idx, 'imageUrl': urljoin(BASE_URL, img_url)})
        return pages
    except Exception as e:
        print(f"[Error] Gagal mengambil halaman chapter: {e}")
        return []
