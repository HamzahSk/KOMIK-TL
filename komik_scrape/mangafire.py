import re
from bs4 import BeautifulSoup

# Domain yang didukung oleh scraper ini
DOMAINS = ['mangafire.to']

def _get_manga_id(url):
    """
    Ekstrak manga_id dari URL.
    Contoh URL: https://mangafire.to/manga/boku-no-hero-academia.m2mo
    ID yang diambil: m2mo
    """
    clean_url = url.split('#')[0].strip('/')
    return clean_url.split('.')[-1]

def get_chapter_list(manga_url, fetch_func, headers):
    """
    Mengambil daftar chapter.
    Sesuai dengan kode Kotlin: menggunakan endpoint /ajax/manga/{id}/chapter/{lang}
    """
    manga_id = _get_manga_id(manga_url)
    lang_code = "en" # Mengambil yang bahasa Inggris saja sesuai permintaan
    
    ajax_url = f"https://mangafire.to/ajax/manga/{manga_id}/chapter/{lang_code}"
    
    try:
        res = fetch_func(ajax_url, headers)
        data = res.json()
        html_content = data.get("result", "")
        
        soup = BeautifulSoup(html_content, "html.parser")
        chapters = []
        
        # Sesuai Kotlin: mencari <li> untuk chapter list
        for li in soup.select("li"):
            a_tag = li.select_first("a")
            if not a_tag:
                continue
            
            link = "https://mangafire.to" + a_tag.get("href")
            number = li.get("data-number", "")
            
            # Mencari nama chapter
            span = li.select("span")
            name = span[0].text.strip() if len(span) > 0 else f"Chapter {number}"
            
            chapters.append({
                "chapter_url": link,
                "chapter_name": name,
                "chapter_number": number
            })
            
        return chapters
    except Exception as e:
        print(f"[Error MangaFire] Gagal mengambil chapter list: {e}")
        return []

def fetch_chapter_soup(chapter_url, fetch_func, headers):
    """
    Mengambil raw HTML dari halaman chapter.
    """
    try:
        res = fetch_func(chapter_url, headers)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Error MangaFire] Gagal fetch soup: {e}")
        return None

def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mengambil daftar gambar (pages).
    Sesuai dengan kode Kotlin: endpoints /ajax/read/chapter/{id}
    """
    try:
        # 1. Cari ID chapter dari elemen HTML (biasanya ada di wrapper/container utama)
        # MangaFire menaruh data-id di div utama untuk dirender oleh JS
        chapter_wrapper = soup.select_first("[data-id]")
        if not chapter_wrapper:
            print("[Error MangaFire] Tidak dapat menemukan chapter ID di halaman.")
            return []
            
        chapter_id = chapter_wrapper.get("data-id")
        
        # 2. Hit API Ajax untuk mendapatkan gambar
        # Catatan: Di Kotlin, mereka butuh token ?vrf=... yang ditangkap dari WebView
        ajax_read_url = f"https://mangafire.to/ajax/read/chapter/{chapter_id}"
        
        res = fetch_func(ajax_read_url, headers)
        data = res.json()
        
        # 3. Parse JSON untuk mendapatkan list gambar
        images_data = data.get("result", {}).get("images", [])
        
        pages = []
        for img in images_data:
            # Sesuai Kotlin `PageListDto`: img[0] = url, img[2] = offset (scramble)
            url = img[0]
            offset = int(img[2]) if len(img) > 2 else 0
            
            # Jika gambar diacak (scrambled), tandai di URL agar nantinya 
            # downloader script milikmu tahu bahwa gambar ini harus di-descramble (diputar balik).
            image_url = f"{url}#scrambled_{offset}" if offset > 0 else url
            pages.append(image_url)
            
        return pages
        
    except Exception as e:
        print(f"[Error MangaFire] Gagal mendapatkan page list: {e}")
        return []

def get_chapter_name(soup, chapter_url=""):
    """Mengekstrak judul manga dan nama chapter dari soup halaman baca."""
    title = "Unknown Title"
    chapter_name = "Unknown Chapter"
    
    if soup:
        # Coba ambil judul dari breadcrumb atau title tag
        breadcrumb = soup.select(".breadcrumb li")
        if len(breadcrumb) >= 3:
            title = breadcrumb[1].text.strip()
            chapter_name = breadcrumb[2].text.strip()
        else:
            h1 = soup.select_first("h1")
            if h1:
                chapter_name = h1.text.strip()
                
    return {"title": title, "chapter_name": chapter_name}
    