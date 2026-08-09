import requests

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
DOMAINS = ["manhuarmtl.com"]

# Sesuaikan port dengan server Express.js kamu
API_BASE_URL = "http://78.154.103.13:15453/" 

def get_chapter_list(manga_url, fetch_func, headers):
    """
    Ekstrak daftar chapter dari API.
    Sesuai template: menerima (manga_url, fetch_func, headers)
    """
    try:
        api_url = f"{API_BASE_URL}/api/chapters"
        
        # Karena kita memanggil API lokal buatan sendiri, kita pakai requests biasa 
        # (tidak perlu fetch_func/fallback ke proxy untuk API lokal)
        response = requests.get(api_url, params={"url": manga_url})
        response.raise_for_status() 
        
        data = response.json()
        if data.get("success"):
            return data.get("data", [])
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
            # Return dictionary data (berisi images, mangaTitle, dll)
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
    Sesuai template: 'soup' di sini sekarang BUKAN BeautifulSoup, 
    melainkan dictionary JSON yang dikirim dari fetch_chapter_soup di atas.
    """
    if isinstance(soup, dict):
        return soup.get("images", [])
    
    return []

def get_chapter_name(soup, chapter_url):
    """
    Mengambil judul komik dan chapter.
    Sesuai template: 'soup' di sini adalah dictionary JSON.
    """
    if isinstance(soup, dict):
        return {
            "title": soup.get("mangaTitle", "Unknown Title"),
            "chapter_name": soup.get("chapterNumber", "Unknown Chapter")
        }
        
    return {
        "title": "Unknown Title", 
        "chapter_name": "Unknown Chapter"
    }
