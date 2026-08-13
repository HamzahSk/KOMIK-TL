import re
import asyncio
from bs4 import BeautifulSoup

# Domain yang didukung scraper
DOMAINS = ['mangafire.to']

# ==========================================
# PLAYWRIGHT STEALTH INJECTORS (v2.x API)
# ==========================================
async def _get_html_with_playwright(url):
    """Menggunakan Playwright untuk mengambil HTML dan mem-bypass Cloudflare."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth
    
    # Membungkus playwright dengan class Stealth() standar v2.0+
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        # Buka halaman dan tunggu sampai HTML ter-load
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        html_content = await page.content()
        await browser.close()
        
        return html_content

async def _get_pages_with_playwright(chapter_url):
    """Menyadap response API gambar dari background browser."""
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    pages_list = []
    
    async with Stealth().use_async(async_playwright()) as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        ajax_response_data = None
        
        async def handle_response(response):
            nonlocal ajax_response_data
            if "ajax/read/chapter" in response.url or "ajax/read/volume" in response.url:
                try:
                    ajax_response_data = await response.json()
                except:
                    pass
                    
        page.on("response", handle_response)
        
        try:
            await page.goto(chapter_url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            print(f"[Info] Playwright timeout (gambar): {e}")
            
        await browser.close()
        
    if ajax_response_data and "result" in ajax_response_data:
        images_data = ajax_response_data["result"].get("images", [])
        for img in images_data:
            url = img[0]
            offset = int(img[2]) if len(img) > 2 else 0
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
    manga_id = _get_manga_id(manga_url)
    lang_code = "en" 
    
    ajax_url = f"https://mangafire.to/ajax/manga/{manga_id}/chapter/{lang_code}"
    
    try:
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
    """Ambil HTML. Jika requests ditolak 403, gunakan Playwright Stealth."""
    try:
        # Coba cara cepat dulu
        res = fetch_func(chapter_url, headers)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Info MangaFire] Requests ditolak Cloudflare ({e}). Membuka browser Playwright untuk memuat HTML...")
        try:
            html_content = asyncio.run(_get_html_with_playwright(chapter_url))
            return BeautifulSoup(html_content, 'html.parser')
        except Exception as play_e:
            print(f"[Error MangaFire] Playwright gagal memuat HTML: {play_e}")
            return None

def get_page_list(soup, chapter_url, fetch_func, headers):
    print("[MangaFire] Mencoba mengekstrak gambar menggunakan Playwright...")
    pages = []
    
    try:
        pages = asyncio.run(_get_pages_with_playwright(chapter_url))
        if pages:
            print("[MangaFire] Berhasil mendapatkan halaman via Playwright.")
            return pages
    except Exception as e:
        print(f"[Error Playwright] {e}. Beralih ke fallback requests...")

    print("[MangaFire] Menjalankan Fallback Requests untuk gambar...")
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
        print(f"[Error MangaFire Fallback] Gagal: {e}")
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
