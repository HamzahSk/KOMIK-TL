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

# --- PERUBAHAN DIMULAI DI SINI ---

def fetch_chapter_soup(chapter_url):
    """Fungsi pembantu untuk fetch dan parse HTML menjadi objek soup hanya 1 kali."""
    try:
        target_url = f"{CORS_PROXY}{chapter_url}"
        res = requests.get(target_url, headers=HEADERS, timeout=15)
        res.raise_for_status() # Pastikan status code 200 OK
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Error] Gagal mengambil URL chapter: {e}")
        return None

def get_page_list(soup):
    """Mengambil list gambar dari objek soup"""
    if not soup:
        return []
    
    pages = []
    try:
        for idx, img in enumerate(soup.select('img.d-block')):
            img_url = img.get('data-src') or img.get('src')
            if img_url:
                pages.append({'index': idx, 'imageUrl': urljoin(BASE_URL, img_url)})
        return pages
    except Exception as e:
        print(f"[Error] Gagal memproses halaman chapter: {e}")
        return []

def get_chapter_name(soup):
    """Mengambil nama chapter dari div id='chapter-info'"""
    if not soup:
        return "Unknown Chapter"
        
    try:
        # Mencari <div id="chapter-info">
        info_div = soup.find('div', id='chapter-info')
        if info_div:
            return info_div.text.strip()
        return "Unknown Chapter"
    except Exception as e:
        print(f"[Error] Gagal memproses nama chapter: {e}")
        return "Unknown Chapter"
