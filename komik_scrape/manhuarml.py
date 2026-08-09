import requests

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
DOMAINS = ["manhuarmtl.com"]

# Sesuaikan port dengan server Express.js kamu
API_BASE_URL = "http://78.154.103.13:15453" 

def get_chapter_list(manga_url, fetch_func, headers):
    """
    Ekstrak daftar chapter dari API.
    Sesuai template: menerima (manga_url, fetch_func, headers)
    """
    try:
        api_url = f"{API_BASE_URL}/api/chapters"
        
        response = requests.get(api_url, params={"url": manga_url})
        response.raise_for_status() 
        
        data = response.json()
        if data.get("success"):
            chapters = data.get("data", [])
            formatted_chapters = []
            
            # [PERBAIKAN] Ubah key 'link' dari API menjadi 'url' agar tidak error di main.py (Baris 45)
            for ch in chapters:
                formatted_chapters.append({
                    "title": ch.get("title", "Unknown Title"),
                    "url": ch.get("link", ""), 
                    "date": ch.get("date", "")
                })
            return formatted_chapters
        else:
            print(f"[Error - API] {data.get('error')}")
            return []
            
    except Exception as e:
        print(f"[Error - ManhuaRMTL] Gagal memanggil API chapter list: {e}")
        return []

def fetch_chapter_soup(chapter_url, fetch_func, headers):
    """
    TRIK KHUSUS: Menggantikan fungsi fetch_chapter_soup default.
    Alih-alih mereturn BeautifulSoup, ini akan mereturn JSON Dictionary dari API.
    """
    try:
        api_url = f"{API_BASE_URL}/api/chapter-detail"
        
        response = requests.get(api_url, params={"url": chapter_url})
        response.raise_for_status()
        
        data = response.json()
        if data.get("success"):
            return data.get("data", {})
        else:
            print(f"[Error - API] {data.get('error')}")
            return {}
            
    except Exception as e:
        print(f"[Error - ManhuaRMTL] Gagal memanggil API chapter detail: {e}")
        return {}

def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mengambil list gambar.
    Sesuai template: 'soup' di sini sekarang adalah dictionary JSON.
    """
    if isinstance(soup, dict):
        images = soup.get("images", [])
        formatted_pages = []
        
        # [PERBAIKAN] Ubah list string URL gambar menjadi list of dictionary
        # agar tidak error di main.py (Baris 85)
        for i, img_url in enumerate(images):
            formatted_pages.append({
                "index": i,
                "url": img_url
            })
        return formatted_pages
    
    return []

def get_chapter_name(soup, chapter_url):
    """
    Mengambil judul komik dan chapter.
    Sesuai template: 'soup' di sini adalah dictionary JSON.
    """
    if isinstance(soup, dict):
        return {
            # Fallback berjenjang kalau mangaTitle kosong
            "title": soup.get("mangaTitle") or soup.get("rawHeading") or "Unknown Title",
            "chapter_name": soup.get("chapterNumber") or "Unknown Chapter"
        }
        
    return {
        "title": "Unknown Title", 
        "chapter_name": "Unknown Chapter"
    }
