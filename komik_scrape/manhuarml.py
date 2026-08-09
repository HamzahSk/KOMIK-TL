import re
from bs4 import BeautifulSoup

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
DOMAINS = ["manhuarmtl.com"]

def get_chapter_list(manga_url, fetch_func, headers):
    """
    Ekstrak daftar chapter dari halaman utama manga.
    Sesuai dengan fungsi fetchMangaChapters di JS.
    """
    try:
        # Menggunakan fungsi fetch_with_fallback bawaan dari scraper.py
        res = fetch_func(manga_url, headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        chapters = []
        
        # Cari semua elemen li dengan class wp-manga-chapter
        for element in soup.select('li.wp-manga-chapter'):
            a_tag = element.select_one('a')
            if not a_tag:
                continue
                
            title = a_tag.text.strip()
            link = a_tag.get('href', '').strip()
            
            # Cari elemen i di dalam class chapter-release-date
            date_tag = element.select_one('.chapter-release-date i')
            date = date_tag.text.strip() if date_tag else ""
            
            if title and link:
                chapters.append({
                    "title": title,
                    "link": link,
                    "date": date
                })
                
        return chapters
    except Exception as e:
        print(f"[Error - ManhuaRMTL] Gagal mengambil daftar chapter: {e}")
        return []


def get_page_list(soup):
    """
    Ekstrak semua link gambar dari dalam chapter.
    Sesuai dengan fungsi fetchChapterImages di JS.
    """
    images = []
    
    # Cari img dengan class wp-manga-chapter-img di dalam class page-break
    for element in soup.select('.page-break img.wp-manga-chapter-img'):
        src = element.get('src')
        
        # Kadang website manga pakai atribut 'data-src' untuk lazy load
        if not src:
            src = element.get('data-src')
            
        if src:
            images.append(src.strip())
            
    return images


def get_chapter_name(soup):
    """
    Ekstrak dan pisahkan judul manga serta nomor chapter.
    Sesuai dengan fungsi fetchChapterTitleAndNumber di JS.
    """
    heading_tag = soup.select_one('h1#chapter-heading')
    raw_heading = heading_tag.text.strip() if heading_tag else "Unknown Title"
    
    manga_title = raw_heading
    chapter_number = ""
    
    # Regex untuk memisahkan teks sebelum dan sesudah kata Chapter/Chap/Bab
    # re.IGNORECASE memastikan tidak sensitif huruf besar/kecil
    regex = r'(.*?)\s*(?:Chapter|Chap|Bab)\s*(.*)'
    match = re.search(regex, raw_heading, re.IGNORECASE)
    
    if match:
        manga_title = match.group(1).strip()
        chapter_number = match.group(2).strip()
        
    return {
        "title": manga_title,
        "chapter_name": chapter_number
    }

