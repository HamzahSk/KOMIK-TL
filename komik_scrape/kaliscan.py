import re
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
# Mengambil dari mirror yang ada di build.gradle.kts
DOMAINS = ["kaliscan.com", "kaliscan.me", "kaliscan.io", "mgjinx.com"]

# Konfigurasi Domain Utama
BASE_URL = "https://kaliscan.com"


def get_chapter_list(manga_url, fetch_func, headers):
    """
    Mengambil daftar chapter khusus dari KaliScan (MadTheme).
    Mendukung legacy API backend service seperti yang ada di KaliScanCom.kt
    """
    try:
        # KaliScan menggunakan useLegacyApi = true, jadi kita perlu ambil manga_id
        manga_id_match = re.search(r"/manga/(\d+)-", manga_url)
        
        if manga_id_match:
            manga_id = manga_id_match.group(1)
            # URL API khusus MadTheme Legacy
            api_url = f"{BASE_URL}/service/backend/chaplist/?manga_id={manga_id}"
            res = fetch_func(api_url, headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            # Selector list dari MadTheme
            items = soup.select("#chapter-list > li") or soup.select("li")
        else:
            # Fallback jika URL tidak mengandung manga_id standar
            res = fetch_func(manga_url, headers)
            soup = BeautifulSoup(res.text, 'html.parser')
            items = soup.select("#chapter-list > li")
            
        chapters = []
        for item in items:
            a_tag = item.select_first("a")
            if not a_tag:
                continue
                
            raw_url = a_tag.get('href', '')
            ch_url = urljoin(BASE_URL, raw_url)
            
            # Ambil judul chapter
            title_elem = item.select_first(".chapter-title")
            title = title_elem.text.strip() if title_elem else a_tag.text.strip()
            
            # Ambil tanggal rilis
            date_elem = item.select_first(".chapter-update")
            date = date_elem.text.strip() if date_elem else ""
            
            chapters.append({
                'title': title,
                'url': ch_url,
                'date': date
            })
            
        return chapters

    except Exception as e:
        print(f"[Error - KaliScan] Gagal mengambil daftar chapter: {e}")
        return []


def fetch_chapter_soup(chapter_url, fetch_func, headers):
    """
    Fetch dan parse HTML menjadi objek soup.
    Menerima parameter sesuai standar scraper.py.
    """
    try:
        ks_headers = headers.copy()
        ks_headers['Referer'] = f"{BASE_URL}/"
        
        res = fetch_func(chapter_url, ks_headers)
        return BeautifulSoup(res.text, 'html.parser')
        
    except Exception as e:
        print(f"[Error - KaliScan] Gagal memuat halaman chapter: {e}")
        return None


def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mengambil list gambar dari objek soup.
    Mendeteksi penggunaan API ChapterServer dan variabel javascript (chapImages).
    """
    if not soup:
        return []
    
    try:
        html_content = str(soup)
        
        # 1. Cek apakah chapter perlu difetch melalui Chapter Server (MadTheme logic)
        chapter_id_match = re.search(r"chapterId\s*=\s*(\d+)", html_content)
        if chapter_id_match:
            chapter_id = chapter_id_match.group(1)
            api_url = f"{BASE_URL}/service/backend/chapterServer/?server_id=1&chapter_id={chapter_id}"
            res = fetch_func(api_url, headers)
            html_content = res.text

        pages = []
        
        # 2. Cek metode load gambar menggunakan JavaScript array (Sangat umum di MadTheme)
        main_server_match = re.search(r'var mainServer = "([^"]+)"', html_content)
        chap_images_match = re.search(r"var chapImages = '([^']+)'", html_content)
        
        if main_server_match and chap_images_match:
            main_server = main_server_match.group(1)
            if main_server.startswith("//"):
                main_server = "https:" + main_server
                
            chap_images = chap_images_match.group(1).split(',')
            
            for idx, path in enumerate(chap_images):
                img_url = urljoin(main_server, path.lstrip('/'))
                pages.append({
                    'index': idx,
                    'url': img_url,
                    'imageUrl': img_url
                })
            return pages
            
        # 3. Fallback: Parse dari elemen HTML langsung
        page_soup = BeautifulSoup(html_content, 'html.parser')
        img_elements = page_soup.select("#chapter-images img, .chapter-image[data-src]")
        
        for idx, img in enumerate(img_elements):
            img_url = img.get('data-src') or img.get('src')
            if img_url:
                if img_url.startswith('//'):
                    img_url = 'https:' + img_url
                elif not img_url.startswith('http'):
                    img_url = urljoin(BASE_URL, img_url)
                    
                pages.append({
                    'index': idx, 
                    'url': img_url,
                    'imageUrl': img_url
                })
                
        return pages
        
    except Exception as e:
        print(f"[Error - KaliScan] Gagal memproses halaman gambar: {e}")
        return []


def get_chapter_name(soup, chapter_url=""):
    """
    Mengambil judul komik dan chapter dari Title atau Breadcrumb.
    """
    if not soup:
        return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}
        
    try:
        # Pendekatan 1: Melalui breadcrumb yang umum di MadTheme
        breadcrumb_items = soup.select(".breadcrumb li")
        if len(breadcrumb_items) >= 2:
            return {
                "title": breadcrumb_items[-2].text.strip(),
                "chapter_name": breadcrumb_items[-1].text.strip()
            }
            
        # Pendekatan 2: Fallback ke tag Title
        title_tag = soup.title.string if soup.title else ""
        if title_tag:
            parts = title_tag.split('-')
            if len(parts) > 1:
                return {
                    "title": parts[0].strip(),
                    "chapter_name": parts[1].strip()
                }
            return {
                "title": parts[0].strip(),
                "chapter_name": parts[0].strip()
            }
            
        return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}
        
    except Exception as e:
        print(f"[Error - KaliScan] Gagal memproses nama chapter: {e}")
        return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}

