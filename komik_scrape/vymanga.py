# komik_scrape/vymanga.py
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Wajib ada agar scraper.py bisa mendeteksi URL mana yang dikerjakan file ini
DOMAINS = ["vymanga", "vymanga.com"]
BASE_URL = "https://vymanga.com"

def get_chapter_list(manga_url, fetch_func, headers):
    try:
        res = fetch_func(manga_url, headers, timeout=15)
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
        print(f"[VyManga Error] {e}")
        return []

def get_page_list(soup):
    pages = []
    try:
        for idx, img in enumerate(soup.select('img.d-block')):
            img_url = img.get('data-src') or img.get('src')
            if img_url:
                pages.append({'index': idx, 'imageUrl': urljoin(BASE_URL, img_url)})
        return pages
    except Exception as e:
        return []

def get_chapter_name(soup):
    try:
        info_div = soup.find("div", id="chapter-info")
        if info_div:
            text = info_div.get_text(strip=True)
            if ":" in text:
                title, chapter_name = text.split(":", 1)
                return {"title": title.strip(), "chapter_name": chapter_name.strip()}
            return {"title": text.strip(), "chapter_name": "Unknown Chapter"}
    except Exception:
        pass
    
    return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}

# (Opsional) Bikin kalau butuh custom header kayak si Bbato
def fetch_chapter_soup(chapter_url, fetch_func, headers):
    try:
        res = fetch_func(chapter_url, headers, timeout=15)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        return None
