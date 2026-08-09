import os
import importlib
import requests
from bs4 import BeautifulSoup

# Konfigurasi Dasar
CORS_PROXY = "https://cors-proxy1.rockyyrec.workers.dev/?url="
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Dictionary untuk menyimpan daftar scraper yang aktif
# Format: {"vymanga": <module object>, "bbato": <module object>}
ACTIVE_SCRAPERS = {}

def load_scrapers():
    """Fungsi untuk scan otomatis folder komik_scrape dan me-load module."""
    folder_name = "komik_scrape"
    
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
        print(f"[Info] Folder '{folder_name}' dibuat. Taruh file scraper-mu di sini.")
        return

    # Looping semua file di dalam folder
    for filename in os.listdir(folder_name):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3] # Hilangkan ekstensi .py
            
            try:
                # Import module secara dinamis
                module = importlib.import_module(f"{folder_name}.{module_name}")
                
                # Wajibkan tiap module punya list DOMAINS 
                if hasattr(module, 'DOMAINS'):
                    for domain in module.DOMAINS:
                        ACTIVE_SCRAPERS[domain] = module
                else:
                    print(f"[Warning] {module_name}.py dilewati karena tidak punya variabel DOMAINS.")
                    
            except Exception as e:
                print(f"[Error] Gagal me-load scraper {module_name}: {e}")

def get_scraper_module(url):
    """Cari module mana yang cocok dengan URL yang diberikan."""
    for domain, module in ACTIVE_SCRAPERS.items():
        if domain in url.lower():
            return module
    return None

def fetch_with_fallback(url, headers, timeout=15):
    """Fungsi fetch umum yang bisa dipanggil oleh semua scraper."""
    try:
        res = requests.get(url, headers=headers, timeout=timeout)
        res.raise_for_status()
        return res
    except requests.RequestException:
        print(f"[Info] Request ke {url} gagal. Beralih ke CORS proxy...")
        target_url = f"{CORS_PROXY}{url}"
        res_cors = requests.get(target_url, headers=headers, timeout=timeout)
        res_cors.raise_for_status()
        return res_cors

# ==========================================
# FUNGSI UTAMA (Menjadi jembatan ke module)
# ==========================================

def get_chapter_list(manga_url):
    scraper = get_scraper_module(manga_url)
    if scraper and hasattr(scraper, 'get_chapter_list'):
        # Lempar tugas ke module yang sesuai, sambil ngasih fungsi fetch_with_fallback
        return scraper.get_chapter_list(manga_url, fetch_with_fallback, HEADERS)
    print(f"[Error] Tidak ada scraper yang mendukung URL: {manga_url}")
    return []

def fetch_chapter_soup(chapter_url):
    scraper = get_scraper_module(chapter_url)
    if scraper and hasattr(scraper, 'fetch_chapter_soup'):
        return scraper.fetch_chapter_soup(chapter_url, fetch_with_fallback, HEADERS)
    
    # Fallback default kalau module nggak bikin fungsi ini
    try:
        res = fetch_with_fallback(chapter_url, HEADERS)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Error] Default fetch gagal: {e}")
        return None

def get_page_list(soup, chapter_url=""):
    scraper = get_scraper_module(chapter_url)
    if scraper and hasattr(scraper, 'get_page_list'):
        return scraper.get_page_list(soup)
    return []

def get_chapter_name(soup, chapter_url=""):
    scraper = get_scraper_module(chapter_url)
    if scraper and hasattr(scraper, 'get_chapter_name'):
        return scraper.get_chapter_name(soup)
    return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}

# Jangan lupa jalankan load_scrapers saat file ini di-import/dijalankan
load_scrapers()
