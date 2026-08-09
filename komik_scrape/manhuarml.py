import requests

# Wajib ada agar scraper.py bisa mendeteksi kecocokan URL
DOMAINS = ["manhuarmtl.com", "manhuarml.com"]

# Sesuaikan port dengan server Express.js kamu
API_BASE_URL = "http://78.154.103.13:15453"

def get_chapter_list(manga_url, fetch_func, headers):
    """
    Mengambil daftar chapter dari API dan menormalkan formatnya.
    Sesuai template scraper: menerima (manga_url, fetch_func, headers).

    API mengembalikan:  [{"title": "...", "link": "...", "date": "..."}]
    main.py (Baris 45) mengharapkan key 'url':
        all_targets.append(ch['url'])
    Maka key 'link' di-map menjadi 'url'.
    """
    try:
        api_url = f"{API_BASE_URL}/api/chapters"

        response = requests.get(api_url, params={"url": manga_url}, timeout=15)
        response.raise_for_status()

        data = response.json()
        if not data.get("success"):
            print(f"[Error - API] {data.get('error', 'Unknown error')}")
            return []

        chapters = data.get("data", [])
        if not isinstance(chapters, list):
            print("[Error - API] Format 'data' tidak berupa list.")
            return []

        formatted_chapters = []
        for ch in chapters:
            if not isinstance(ch, dict):
                continue
            formatted_chapters.append({
                "title": ch.get("title", "Unknown Title"),
                "url": ch.get("link", ""),
                "date": ch.get("date", "")
            })

        return formatted_chapters

    except requests.RequestException as e:
        print(f"[Error - ManhuaRMTL] Gagal menghubungi API chapter list: {e}")
        return []
    except Exception as e:
        print(f"[Error - ManhuaRMTL] Gagal memanggil API chapter list: {e}")
        return []

def fetch_chapter_soup(chapter_url, fetch_func, headers):
    """
    TRIK KHUSUS: Menggantikan fetch_chapter_soup default.
    Alih-alih mereturn BeautifulSoup, fungsi ini mereturn JSON Dictionary dari API.
    """
    try:
        api_url = f"{API_BASE_URL}/api/chapter-detail"

        response = requests.get(api_url, params={"url": chapter_url}, timeout=15)
        response.raise_for_status()

        data = response.json()
        if data.get("success"):
            return data.get("data", {})
        else:
            print(f"[Error - API] {data.get('error', 'Unknown error')}")
            return {}

    except requests.RequestException as e:
        print(f"[Error - ManhuaRMTL] Gagal menghubungi API chapter detail: {e}")
        return {}
    except Exception as e:
        print(f"[Error - ManhuaRMTL] Gagal memanggil API chapter detail: {e}")
        return {}

def get_page_list(soup, chapter_url, fetch_func, headers):
    """
    Mengambil list gambar dan menormalkan formatnya.
    'soup' di sini adalah dictionary JSON, bukan BeautifulSoup.

    API mengembalikan:  ["img1.webp", "img2.webp", ...]
    main.py (Baris 85) mengharapkan list of dict dengan 'index':
        executor.submit(download_page, page, out_dir, ch_url): page['index']

    Catatan penting:
      - 'url'    : sesuai format yang diminta (key 'url').
      - 'imageUrl': tambahan agar kompatibel dengan download_page()
                    (image_utils.py Baris 323 membaca page['imageUrl']).
    """
    if not isinstance(soup, dict):
        return []

    images = soup.get("images", [])
    if not isinstance(images, list):
        return []

    formatted_pages = []
    for i, img_url in enumerate(images):
        formatted_pages.append({
            "index": i,
            "url": img_url,
            "imageUrl": img_url
        })

    return formatted_pages

def get_chapter_name(soup, chapter_url):
    """
    Mengambil judul komik dan chapter dari dictionary JSON API.
    Menangani key yang hilang secara bertahap (layered fallback).
    """
    if not isinstance(soup, dict):
        return {
            "title": "Unknown Title",
            "chapter_name": "Unknown Chapter"
        }

    # Fallback berjenjang untuk judul manga
    title = (
        soup.get("mangaTitle")
        or soup.get("title")
        or soup.get("rawHeading")
        or "Unknown Title"
    )

    # Fallback berjenjang untuk nama/kode chapter
    chapter_name = (
        soup.get("chapterNumber")
        or soup.get("chapter_name")
        or soup.get("chapter")
        or "Unknown Chapter"
    )

    return {
        "title": title,
        "chapter_name": chapter_name
    }