import requests
import json
import re
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
        res = requests.get(url, headers=headers, timeout=timeout)
        res.raise_for_status() 
        return res
    except requests.RequestException:
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
            slug = manga_url.strip("/").split("/")[-1]
            
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
            # Gunakan filter Python untuk stabilitas ketimbang mengandalkan selector bs4 :not()
            images = soup.select(".pages img")
            valid_idx = 0
            
            for img in images:
                # Lewati gambar yang tidak punya atribut data-number atau jika isinya "notice" (iklan)
                if not img.has_attr("data-number") or img.get("data-number") == "notice":
                    continue
                    
                # Urutan prioritas: data-src -> data-fallback -> src
                img_url = img.get("data-src") or img.get("data-fallback") or img.get("src")
                
                # Pastikan URL valid dan bukan base64 placeholder
                if img_url and not img_url.startswith("data:image"):
                    if not img_url.startswith('http'):
                        img_url = urljoin(BBATO_URL, img_url)
                    pages.append({'index': valid_idx, 'imageUrl': img_url})
                    valid_idx += 1
                    
        return pages
    except Exception as e:
        print(f"[Error] Gagal memproses halaman chapter: {e}")
        return []


def get_chapter_name(soup, chapter_url=""):
    """
    Mengambil informasi chapter dari DOM dengan Fallback Cerdas
    """
    # 1. Fallback dari URL sebagai jaring pengaman utama
    title = "Unknown Title"
    chapter_name = "Unknown Chapter"
    
    if chapter_url:
        parts = chapter_url.strip("/").split("/")
        if len(parts) >= 2:
            title = parts[-2].replace("-", " ").title()
            chapter_name = parts[-1].replace("-", " ").title()

    if not soup:
        return {"title": title, "chapter_name": chapter_name}
        
    # 2. Cek apakah dicegat Cloudflare
    title_tag = soup.find("title")
    if title_tag:
        full_title = title_tag.get_text(strip=True)
        if "Just a moment" in full_title or "Cloudflare" in full_title or "Attention Required" in full_title:
            print("\n[🚨 Warning] Akses dicegat oleh Cloudflare! Menggunakan fallback URL.")
            return {"title": title, "chapter_name": f"{chapter_name} (Blocked)"}

    try:
        provider = detect_provider(chapter_url) if chapter_url else None

        # ==========================
        # BBATO
        # ==========================
        if provider == "bbato":
            # Coba menggunakan ld+json
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
                                "title": items[-2].get("name", title),
                                "chapter_name": items[-1].get("name", chapter_name)
                            }
                        elif len(items) == 1:
                            return {
                                "title": title,
                                "chapter_name": items[-1].get("name", chapter_name)
                            }
                except json.JSONDecodeError:
                    continue
            
            # Jika JSON gagal, gunakan Regex dari Title Tag
            if title_tag:
                match = re.search(r'Read\s+(.+?)\s+chapter\s+([\d\.]+)', full_title, re.IGNORECASE)
                if match:
                    return {
                        "title": match.group(1).strip(),
                        "chapter_name": f"Chapter {match.group(2).strip()}"
                    }

        # ==========================
        # VYMANGA
        # ==========================
        elif provider == "vymanga":
            info_div = soup.find("div", id="chapter-info")
            if info_div:
                text = info_div.get_text(strip=True)
                if ":" in text:
                    v_title, v_chapter_name = text.split(":", 1)
                    return {
                        "title": v_title.strip(),
                        "chapter_name": v_chapter_name.strip()
                    }
                return {
                    "title": text.strip(),
                    "chapter_name": chapter_name
                }

        # ==========================
        # KEMBALIKAN FALLBACK JIKA SEMUA GAGAL
        # ==========================
        return {
            "title": title,
            "chapter_name": chapter_name
        }

    except Exception as e:
        print(f"[Error] Gagal memproses nama chapter: {e}")
        return {
            "title": title,
            "chapter_name": chapter_name
        }
