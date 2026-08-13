import os
import importlib
import requests
from bs4 import BeautifulSoup

# Konfigurasi Dasar
CORS_PROXY = "https://cors-proxy9.rockyyrec.workers.dev/?url="
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

ACTIVE_SCRAPERS = {}

def load_scrapers():
    """Fungsi untuk scan otomatis folder komik_scrape dan me-load module."""
    folder_name = "komik_scrape"
    
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        print(f"[Info] Folder '{folder_name}' dibuat. Taruh file scraper-mu di sini.")
        return

    for filename in os.listdir(folder_name):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3] 
            
            try:
                module = importlib.import_module(f"{folder_name}.{module_name}")
                if hasattr(module, 'DOMAINS'):
                    for domain in module.DOMAINS:
                        ACTIVE_SCRAPERS[domain] = module
                else:
                    print(f"[Warning] {module_name}.py dilewati (tidak punya DOMAINS).")
            except Exception as e:
                print(f"[Error] Gagal me-load scraper {module_name}: {e}")

def get_scraper_module(url):
    """Cari module mana yang cocok dengan URL yang diberikan."""
    for domain, module in ACTIVE_SCRAPERS.items():
        if domain in url.lower():
            return module
    return None

# ==========================================
# FETCH SYSTEM DENGAN FALLBACK
# ==========================================

def fetch_with_fallback(url, headers, timeout=15):
    """Fungsi fetch umum menggunakan requests dengan fallback ke CORS proxy."""
    try:
        # Request utama
        res = requests.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res
    except requests.RequestException as e:
        print(f"[Info] Request ke {url} gagal ({e}). Beralih ke CORS proxy...")
        
        # Fallback ke CORS Proxy
        target_url = f"{CORS_PROXY}{url}"
        try:
            res_cors = requests.get(target_url, headers=headers, timeout=timeout)
            res_cors.raise_for_status()
            return res_cors
        except requests.RequestException as e_cors:
            print(f"[Error] Proxy juga gagal: {e_cors}")
            raise e_cors

# ==========================================
# FUNGSI UTAMA (Menjadi jembatan ke module)
# ==========================================

def get_chapter_list(manga_url):
    scraper = get_scraper_module(manga_url)
    if scraper and hasattr(scraper, 'get_chapter_list'):
        return scraper.get_chapter_list(manga_url, fetch_with_fallback, HEADERS)
    print(f"[Error] Tidak ada scraper yang mendukung URL: {manga_url}")
    return []

def fetch_chapter_soup(chapter_url):
    scraper = get_scraper_module(chapter_url)
    if scraper and hasattr(scraper, 'fetch_chapter_soup'):
        return scraper.fetch_chapter_soup(chapter_url, fetch_with_fallback, HEADERS)
    
    try:
        res = fetch_with_fallback(chapter_url, HEADERS)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Error] Default fetch gagal: {e}")
        return None

def get_page_list(soup, chapter_url=""):
    scraper = get_scraper_module(chapter_url)
    if scraper and hasattr(scraper, 'get_page_list'):
        return scraper.get_page_list(soup, chapter_url, fetch_with_fallback, HEADERS)
    return []

def get_chapter_name(soup, chapter_url=""):
    scraper = get_scraper_module(chapter_url)
    if scraper and hasattr(scraper, 'get_chapter_name'):
        return scraper.get_chapter_name(soup, chapter_url)
    return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}

# Inisialisasi
load_scrapers()
