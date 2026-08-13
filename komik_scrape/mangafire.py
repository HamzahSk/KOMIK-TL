import re
import asyncio
from bs4 import BeautifulSoup

# Domain yang didukung scraper
DOMAINS = ['mangafire.to']

# ==========================================
# PLAYWRIGHT STEALTH INJECTOR
# ==========================================
async def _get_pages_with_playwright(chapter_url):
    """
    Fungsi async untuk menjalankan Playwright dengan mode Stealth.
    Fungsi ini akan membuka halaman chapter dan menyadap response JSON 
    dari endpoint ajax/read/... tanpa perlu meretas token vrf secara manual.
    """
    from playwright.async_api import async_playwright
    from playwright_stealth import stealth_async

    pages_list = []
    
    async with async_playwright() as p:
        # Launch browser Chromium headless
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Terapkan stealth untuk bypass deteksi bot/Cloudflare
        await stealth_async(page)
        
        ajax_response_data = None
        
        async def handle_response(response):
            nonlocal ajax_response_data
            # Tangkap response dari endpoint Ajax MangaFire yang memuat daftar gambar
            if "ajax/read/chapter" in response.url or "ajax/read/volume" in response.url:
                try:
                    ajax_response_data = await response.json()
                except:
                    pass
                    
        # Pasang listener untuk setiap response jaringan
        page.on("response", handle_response)
        
        try:
            # Buka halaman chapter dan tunggu hingga jaringan tenang (networkidle)
            await page.goto(chapter_url, wait_until="networkidle", timeout=25000)
            # Beri sedikit waktu tambahan jaga-jaga JS masih mengeksekusi request
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[Info] Playwright timeout/terkendala saat memuat halaman: {e}")
            
        await browser.close()
        
    # Jika berhasil menangkap response, parse daftar gambarnya
    if ajax_response_data and "result" in ajax_response_data:
        images_data = ajax_response_data["result"].get("images", [])
        for img in images_data:
            url = img[0]
            offset = int(img[2]) if len(img) > 2 else 0
            
            # Tambahkan tag scrambled jika offset > 0 (sesuai Kotlin)
            image_url = f"{url}#scrambled_{offset}" if offset > 0 else url
            pages_list.append(image_url)
            
    return pages_list

# ==========================================
# FUNGSI SCRAPING UTAMA
# ==========================================

def _get_manga_id(url):
    """Ekstrak manga_id dari URL."""
    clean_url = url.split('#')[0].strip('/')
    return clean_url.split('.')[-1]

def get_chapter_list(manga_url, fetch_func, headers):
    """Mengambil list chapter khusus bahasa Inggris (en)."""
    manga_id = _get_manga_id(manga_url)
    lang_code = "en" 
    
    ajax_url = f"https://mangafire.to/ajax/manga/{manga_id}/chapter/{lang_code}"
    
    try:
        # Endpoint ini biasanya tidak dikunci seketat chapter read, aman pakai requests
        res = fetch_func(ajax_url, headers)
        data = res.json()
        
        html_content = data.get("result", "")
        soup = BeautifulSoup(html_content, "html.parser")
        
        chapters = []
        for li in soup.select("li"):
            a_tag = li.select_first("a")
            if not a_tag:
                continue
                
            link = "https://mangafire.to" + a_tag.get("href")
            number = li.get("data-number", "0")
            
            spans = li.select("span")
            raw_name = spans[0].text.strip() if len(spans) > 0 else ""
            
            prefix = f"Chap {number}: "
            if raw_name.startswith(prefix):
                real_name = raw_name[len(prefix):]
                if str(number) in real_name:
                    name = real_name
                else:
                    name = f"Chapter {number}: {real_name}"
            else:
                name = raw_name if raw_name else f"Chapter {number}"

            chapters.append({
                "chapter_url": link,
                "chapter_name": name,
                "chapter_number": number
            })
            
        return chapters
    except Exception as e:
        print(f"[Error MangaFire] Gagal mengambil daftar chapter: {e}")
        return []

def fetch_chapter_soup(chapter_url, fetch_func, headers):
    try:
        res = fetch_func(chapter_url, headers)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Error MangaFire] Gagal memuat HTML chapter: {e}")
        return None

def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mencoba mengambil gambar dengan Playwright Stealth terlebih dahulu.
    Jika gagal/error, akan fallback ke metode Requests + CORS proxy.
    """
    print("[MangaFire] Mencoba mengekstrak halaman menggunakan Playwright Stealth...")
    pages = []
    
    # 1. Coba Menggunakan Playwright Stealth
    try:
        # Karena dipanggil dari environment synchronous (requests), kita jalankan event loop
        pages = asyncio.run(_get_pages_with_playwright(chapter_url))
        if pages:
            print("[MangaFire] Berhasil mendapatkan halaman via Playwright.")
            return pages
    except ImportError:
        print("[Warning] 'playwright' atau 'playwright-stealth' belum diinstal. Beralih ke fallback requests...")
    except Exception as e:
        print(f"[Error Playwright] {e}. Beralih ke fallback requests...")

    # 2. Fallback menggunakan requests biasa + CORS proxy (sesuai permintaanmu)
    print("[MangaFire] Menjalankan Fallback Requests...")
    try:
        chapter_wrapper = soup.select_first("[data-id]")
        if not chapter_wrapper:
            print("[Error MangaFire] Fallback gagal: 'data-id' tidak ditemukan.")
            return []
            
        chapter_id = chapter_wrapper.get("data-id")
        ajax_read_url = f"https://mangafire.to/ajax/read/chapter/{chapter_id}"
        
        res = fetch_func(ajax_read_url, headers)
        data = res.json()
        
        images_data = data.get("result", {}).get("images", [])
        
        for img in images_data:
            url = img[0]
            offset = int(img[2]) if len(img) > 2 else 0
            image_url = f"{url}#scrambled_{offset}" if offset > 0 else url
            pages.append(image_url)
            
        return pages
    except Exception as e:
        print(f"[Error MangaFire Fallback] Gagal mengambil API karena tidak ada token VRF: {e}")
        return []

def get_chapter_name(soup, chapter_url=""):
    title = "Unknown Manga"
    chapter_name = "Unknown Chapter"
    
    if soup:
        breadcrumb = soup.select(".breadcrumb li")
        if len(breadcrumb) >= 3:
            title = breadcrumb[1].text.strip()
            chapter_name = breadcrumb[2].text.strip()
            
    return {"title": title, "chapter_name": chapter_name}
