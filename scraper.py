import requests
import json
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Konfigurasi Domain
VYMANGA_URL = "https://vymanga.com"
BBATO_URL = "https://bbato.com"
CORS_PROXY = "https://cors-proxy1.rockyyrec.workers.dev/?url="

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def detect_provider(url):
    """Menentukan provider: jika bukan bbato, berarti vymanga."""
    if "bbato" in url.lower():
        return "bbato"
    return "vymanga"


def fetch_with_fallback(url, headers, timeout=15):
    """Coba fetch default dulu, kalau kena block/gagal baru pakai CORS."""
    try:
        # Coba request langsung
        res = requests.get(url, headers=headers, timeout=timeout)
        res.raise_for_status() # Melempar error jika status code 4xx atau 5xx (misal 403 Forbidden)
        return res
    except requests.RequestException:
        # Jika gagal (kena block), fallback ke CORS proxy
        print(f"[Info] Request langsung ke {url} gagal/terblokir. Beralih ke CORS proxy...")
        target_url = f"{CORS_PROXY}{url}"
        res_cors = requests.get(target_url, headers=headers, timeout=timeout)
        res_cors.raise_for_status()
        return res_cors


def get_chapter_list(manga_url):
    try:
        provider = detect_provider(manga_url)
        
        # --- LOGIKA UNTUK VYMANGA ---
        if provider == "vymanga":
            # Menggunakan fungsi fallback baru
            res = fetch_with_fallback(manga_url, HEADERS, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            chapters = []
            for a in soup.select('.list-group > a'):
                href = a.get('href')
                span = a.find('span')
                name = span.text.strip() if span else "Unknown_Chapter"
                
                if href:
                    chapters.append({
                        'url': urljoin(VYMANGA_URL, href),
                        'name': name
                    })
            return chapters

        # --- LOGIKA UNTUK BBATO ---
        else:
            # Ambil slug/id paling akhir dari URL manga
            slug = manga_url.strip("/").split("/")[-1]
            
            # Setup headers khusus XMLHttpRequest milik bbato untuk bypass 403
            bbato_headers = HEADERS.copy()
            bbato_headers.update({
                'Accept': 'application/json, text/javascript, */*; q=0.01',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': manga_url
            })
            
            api_url = f"{BBATO_URL}/get-chapter-list?slug={slug}"
            res = fetch_with_fallback(api_url, bbato_headers, timeout=15)
            res_json = res.json()
            
            if 'data' not in res_json or not isinstance(res_json['data'], list):
                return []
                
            chapters = []
            for ch in res_json['data']:
                # Bikin URL absolut untuk chapter read bbato
                ch_url = f"{BBATO_URL}/read/{slug}/{ch.get('chapter_slug')}"
                chapters.append({
                    'url': ch_url,
                    'name': ch.get('chapter_name', 'Unknown_Chapter')
                })
            return chapters

    except Exception as e:
        print(f"[Error] Gagal mengambil detail manga: {e}")
        return []


def fetch_chapter_soup(chapter_url):
    """Fungsi pembantu untuk fetch dan parse HTML menjadi objek soup hanya 1 kali."""
    try:
        provider = detect_provider(chapter_url)
        
        if provider == "vymanga":
            res = fetch_with_fallback(chapter_url, HEADERS, timeout=15)
        else:
            bbato_headers = HEADERS.copy()
            bbato_headers['Referer'] = f"{BBATO_URL}/"
            res = fetch_with_fallback(chapter_url, bbato_headers, timeout=15)
            
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Error] Gagal mengambil URL chapter: {e}")
        return None


def get_page_list(soup, chapter_url=""):
    """Mengambil list gambar dari objek soup (Mendukung VyManga & Bbato)"""
    if not soup:
        return []
    
    pages = []
    try:
        provider = detect_provider(chapter_url)
        
        # --- LOGIKA UNTUK VYMANGA ---
        if provider == "vymanga":
            for idx, img in enumerate(soup.select('img.d-block')):
                img_url = img.get('data-src') or img.get('src')
                if img_url:
                    pages.append({'index': idx, 'imageUrl': urljoin(VYMANGA_URL, img_url)})
                    
        # --- LOGIKA UNTUK BBATO ---
        else:
            # Mengabaikan notice-page sesuai selektor Tachiyomi asli
            for idx, img in enumerate(soup.select('.pages .page:not(.notice-page) img')):
                img_url = img.get('data-src') or img.get('src')
                if img_url:
                    # Pastikan url gambar absolut
                    if not img_url.startswith('http'):
                        img_url = urljoin(BBATO_URL, img_url)
                    pages.append({'index': idx, 'imageUrl': img_url})
                    
        return pages
    except Exception as e:
        print(f"[Error] Gagal memproses halaman chapter: {e}")
        return []

def get_chapter_name(soup, chapter_url=""):
    """
    Mengambil informasi chapter dari DOM.
    Return:
    {
        "title": "...",
        "chapter_name": "..."
    }
    """
    if not soup:
        return {
            "title": "Unknown Title",
            "chapter_name": "Unknown Chapter"
        }

    try:
        provider = detect_provider(chapter_url) if chapter_url else None

        # ==========================
        # BBATO
        # ==========================
        if provider == "bbato":
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                if not script.string:
                    continue

                try:
                    data = json.loads(script.string)

                    if data.get("@type") == "BreadcrumbList":
                        items = data.get("itemListElement", [])

                        if len(items) >= 2:
                            return {
                                "title": items[-2].get("name", "Unknown Title"),
                                "chapter_name": items[-1].get("name", "Unknown Chapter")
                            }
                        elif len(items) == 1:
                            return {
                                "title": "Unknown Title",
                                "chapter_name": items[-1].get("name", "Unknown Chapter")
                            }

                except json.JSONDecodeError:
                    continue

        # ==========================
        # VYMANGA
        # ==========================
        elif provider == "vymanga":
            info_div = soup.find("div", id="chapter-info")
            if info_div:
                text = info_div.get_text(strip=True)

                if ":" in text:
                    title, chapter_name = text.split(":", 1)
                    return {
                        "title": title.strip(),
                        "chapter_name": chapter_name.strip()
                    }

                return {
                    "title": text.strip(),
                    "chapter_name": "Unknown Chapter"
                }

        # ==========================
        # FALLBACK
        # ==========================
        else:
            # Coba format VyManga
            info_div = soup.find("div", id="chapter-info")
            if info_div:
                text = info_div.get_text(strip=True)

                if ":" in text:
                    title, chapter_name = text.split(":", 1)
                    return {
                        "title": title.strip(),
                        "chapter_name": chapter_name.strip()
                    }

                return {
                    "title": text.strip(),
                    "chapter_name": "Unknown Chapter"
                }

            # Coba format Bbato
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                if not script.string:
                    continue

                try:
                    data = json.loads(script.string)

                    if data.get("@type") == "BreadcrumbList":
                        items = data.get("itemListElement", [])

                        if len(items) >= 2:
                            return {
                                "title": items[-2].get("name", "Unknown Title"),
                                "chapter_name": items[-1].get("name", "Unknown Chapter")
                            }
                        elif len(items) == 1:
                            return {
                                "title": "Unknown Title",
                                "chapter_name": items[-1].get("name", "Unknown Chapter")
                            }

                except json.JSONDecodeError:
                    continue

        return {
            "title": "Unknown Title",
            "chapter_name": "Unknown Chapter"
        }

    except Exception as e:
        print(f"[Error] Gagal memproses nama chapter: {e}")
        return {
            "title": "Unknown Title",
            "chapter_name": "Unknown Chapter"
        }