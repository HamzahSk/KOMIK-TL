import re
import base64
import json
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from Crypto.Cipher import AES
import execjs # Membutuhkan module PyExecJS dan Node.js terinstal

DOMAINS = ["mangago.me", "mangago.zone", "www.mangago.zone", "www.mangago.me"]
BASE_URL = "https://www.mangago.me"
READER_DOMAIN = "www.mangago.zone"

# ==========================================
# DEOBFUSCATOR & UNSCRAMBLER
# ==========================================

def decode_sojson_v4(jsf: str) -> str:
    """Portingan dari SoJsonV4Deobfuscator.kt"""
    if not jsf.startswith("['sojson.v4']"):
        raise ValueError("Obfuscated code is not sojson.v4")
    
    # Ambil substring seperti di Kotlin: jsf.substring(240, jsf.length - 59)
    encoded_part = jsf[240:-59]
    parts = re.split(r'[a-zA-Z]+', encoded_part)
    
    # Map ke integer lalu ke char
    return "".join([chr(int(p)) for p in parts if p.strip().isdigit()])

def unscramble_string(s: str, keys: list) -> str:
    """Fungsi unscramble string dasar dari Kotlin"""
    s_list = list(s)
    for key in reversed(keys):
        for i in range(len(s_list) - 1, key - 1, -1):
            if i % 2 != 0:
                # Swap karakter
                temp = s_list[i - key]
                s_list[i - key] = s_list[i]
                s_list[i] = temp
    return "".join(s_list)

def unscramble_image_list(image_list: str, js_code: str) -> str:
    """Mengambil lokasi key dan melakukan unscramble pada string daftar gambar"""
    try:
        key_locations = []
        for match in re.finditer(r'str\.charAt\(\s*(\d+)\s*\)', js_code):
            val = int(match.group(1))
            if val not in key_locations:
                key_locations.append(val)
                
        unscramble_key = [int(image_list[loc]) for loc in key_locations]
        
        # Hapus karakter pada index key_locations
        img_list_arr = list(image_list)
        for idx, loc in enumerate(key_locations):
            img_list_arr.pop(loc - idx)
            
        img_list_str = "".join(img_list_arr)
        return unscramble_string(img_list_str, unscramble_key)
    except Exception as e:
        print(f"[Mangago Info] Image list sudah di-unscramble atau error: {e}")
        return image_list

# ==========================================
# SCRAPER UTAMA
# ==========================================

def get_chapter_name(soup, chapter_url=""):
    """Mengambil judul komik dan chapter menggunakan selector Cheerio yang diminta"""
    if not soup:
        return {"title": "Unknown Title", "chapter_name": "Unknown Chapter"}
    
    title_el = soup.select_one('#series')
    chapter_el = soup.select_one('.chapter')
    
    return {
        "title": title_el.text.strip() if title_el else "Unknown Title",
        "chapter_name": chapter_el.text.strip() if chapter_el else "Unknown Chapter"
    }

def get_chapter_list(manga_url, fetch_func, default_headers):
    """Mengambil daftar chapter dari halaman komik"""
    try:
        # Gunakan READER_DOMAIN jika path-nya mendukung
        parsed_url = urlparse(manga_url)
        target_url = f"https://{READER_DOMAIN}{parsed_url.path}"
        
        res = fetch_func(target_url, default_headers, timeout=15)
        # Jika fallback 404, kita kembalikan ke base url
        if res.status_code == 404:
             res = fetch_func(f"{BASE_URL}{parsed_url.path}", default_headers, timeout=15)
             
        soup = BeautifulSoup(res.text, 'html.parser')
        chapters = []
        
        # Mangago pakai table#chapter_table > tbody > tr
        for tr in soup.select('table#chapter_table > tbody > tr, table.uk-table > tbody > tr'):
            link = tr.select_one('a.chico')
            if not link:
                continue
                
            href = link.get('href')
            ch_url = urljoin(manga_url, href)
            
            # Normalisasi URL Chapter seperti di Kotlin
            parsed_ch = urlparse(ch_url)
            if parsed_ch.path.startswith("/chapter/"):
                ch_url = f"https://{READER_DOMAIN}{parsed_ch.path}"
                
            chapters.append({
                'url': ch_url,
                'name': link.text.strip()
            })
            
        return chapters
    except Exception as e:
        print(f"[Mangago Error] Gagal fetch chapter list: {e}")
        return []

def fetch_chapter_soup(chapter_url, fetch_func, default_headers):
    """Mengambil DOM dari chapter_url (biasanya pakai readerDomain)"""
    try:
        parsed_url = urlparse(chapter_url)
        if parsed_url.path.startswith("/chapter/"):
            chapter_url = f"https://{READER_DOMAIN}{parsed_url.path}"
            
        res = fetch_func(chapter_url, default_headers, timeout=15)
        return BeautifulSoup(res.text, 'html.parser')
    except Exception as e:
        print(f"[Mangago Error] Gagal mengambil URL chapter: {e}")
        return None

def get_page_list(soup, chapter_url="", fetch_func=None, default_headers=None):
    """Mengambil, mendekripsi, dan melakukan deobfuscate pada daftar gambar chapter"""
    if not soup:
        return []

    try:
        # 1. Cari base64 string imgsrcs
        script_imgsrcs = soup.find(lambda tag: tag.name == "script" and "imgsrcs" in tag.text)
        if not script_imgsrcs:
            raise Exception("Tidak menemukan script 'imgsrcs'")
            
        imgsrcs_match = re.search(r'var imgsrcs\s*=\s*[\'"]([a-zA-Z0-9+=/]+)[\'"]', script_imgsrcs.text)
        if not imgsrcs_match:
            raise Exception("Gagal mengekstrak value imgsrcs")
            
        encrypted_images = base64.b64decode(imgsrcs_match.group(1))

        # 2. Ambil script chapter.js dan deobfuscate
        script_chapter_js = soup.select_one('script[src*="chapter.js"]')
        if not script_chapter_js or not fetch_func:
             raise Exception("Tidak menemukan tag script chapter.js atau fetch_func tidak dipassing")
             
        js_url = urljoin(chapter_url, script_chapter_js.get('src'))
        js_res = fetch_func(js_url, default_headers, timeout=15)
        
        chapter_js_decoded = decode_sojson_v4(js_res.text)

        # 3. Temukan Key & IV untuk AES (Hex Parsing)
        def get_hex_var(var_name):
            match = re.search(fr'var {var_name}\s*=\s*CryptoJS\.enc\.Hex\.parse\("([0-9a-zA-Z]+)"\)', chapter_js_decoded)
            return bytes.fromhex(match.group(1)) if match else b""

        key = get_hex_var("key")
        iv = get_hex_var("iv")

        # 4. Dekripsi AES
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted_bytes = cipher.decrypt(encrypted_images)
        
        # Hapus padding (ZeroBytePadding)
        decrypted_string = decrypted_bytes.rstrip(b'\x00').decode('utf-8')

        # 5. Unscramble string daftar gambar
        image_list_str = unscramble_image_list(decrypted_string, chapter_js_decoded)
        raw_urls = image_list_str.split(',')

        # 6. Jalankan JavaScript ringan untuk descrambling key (opsional, untuk cspiclink)
        # Meniru getDescramblingKey via PyExecJS
        try:
            cols_match = re.search(r'var\s*widthnum\s*=\s*heightnum\s*=\s*(\d+);', chapter_js_decoded)
            cols = cols_match.group(1) if cols_match else ""

            # Ambil potongan JS untuk generate desckey
            js_logic = chapter_js_decoded.split("var renImg = function(img,width,height,id){")[1].split("key = key.split(")[0]
            
            # Buat JS Context
            js_context = execjs.compile(f"""
                function getDescramblingKey(url) {{
                    {js_logic.replace('img.src', 'url')}
                    return key;
                }}
            """)
        except Exception:
            js_context = None

        pages = []
        for idx, img in enumerate(raw_urls):
            if "cspiclink" in img and js_context:
                # Resolve descrambling key untuk mangago
                try:
                    desc_key = js_context.call("getDescramblingKey", img)
                    img = f"{img}#desckey={desc_key}&cols={cols}"
                except:
                    pass
            
            if img.strip():
                pages.append({
                    'index': idx,
                    'imageUrl': img.strip()
                })

        return pages

    except Exception as e:
        print(f"[Mangago Error] Gagal memproses gambar: {e}")
        return []
