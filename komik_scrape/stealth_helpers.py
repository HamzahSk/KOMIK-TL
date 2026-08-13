# -*- coding: utf-8 -*-
"""Helper stealth (2026) untuk MangaFire/Bbato.

Kenapa synchronous:
  - `asyncio.run()` di dalam fungsi sync memunculkan event loop BARU tiap panggilan,
    dan crash kalau dipanggil dari thread/loop yang sudah berjalan. `sync_playwright`
    memakai greenlet internal sendiri, jadi aman dipanggil dari fungsi biasa / script `requests`.
Engine stealth:
  1. curl_cffi  -> meniru TLS/JA4 + HTTP/2 Chrome di level network (paling cepat, tanpa browser).
  2. patchright -> fork Playwright, patch di level CDP (fix `Runtime.enable` leak), standar 2026.
  3. playwright-stealth v2 -> fallback bila patchright belum terinstall.
"""

import re
import logging
from contextlib import contextmanager
from typing import Any, List

try:
    from curl_cffi import requests as cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False

try:
    from patchright.sync_api import sync_playwright
    ENGINE = "patchright"
except ImportError:
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
        ENGINE = "playwright"
    except ImportError:
        sync_playwright = None
        ENGINE = "none"

_IMG_URL_RE = re.compile(r"https?://[^\s\"'<>]+?\.(?:jpe?g|png|webp|gif|avif)", re.I)


@contextmanager
def _browser_cm():
    """Context manager browser stealth. yield `p` (Playwright) yang sudah ter-stealth."""
    if ENGINE == "patchright":
        with sync_playwright() as p:
            yield p
    elif ENGINE == "playwright":
        with Stealth().use_sync(sync_playwright()) as p:
            yield p
    else:
        raise RuntimeError("Install 'patchright' atau 'playwright + playwright-stealth' dulu.")


def _collect_urls(data: Any, out: List[str]) -> None:
    """Rekursi semua string di dalam JSON, kumpulkan yang berupa URL gambar."""
    if isinstance(data, dict):
        for v in data.values():
            _collect_urls(v, out)
    elif isinstance(data, list):
        for v in data:
            _collect_urls(v, out)
    elif isinstance(data, str):
        for m in _IMG_URL_RE.findall(data):
            if m not in out:
                out.append(m)


def fetch_chapter_html(url: str, timeout: int = 45, use_browser: bool = True) -> str:
    """Ambil HTML chapter secara synchronous, dengan bypass anti-bot terbaik 2026."""
    # 1) Fast path: curl_cffi — impersonate TLS Chrome. Sering lolos Cloudflare
    #    tanpa perlu render JS sama sekali (lebih cepat & lebih stabil).
    if HAS_CURL_CFFI:
        try:
            resp = cffi_requests.get(
                url,
                impersonate="chrome",
                timeout=timeout,
                headers={
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": url.rsplit("/", 2)[0] + "/",
                },
            )
            if resp.status_code == 200 and "challenge" not in resp.url.lower():
                return resp.text
        except Exception as e:
            logging.info("curl_cffi gagal (%s), fallback ke browser.", e)

    if not use_browser or ENGINE == "none":
        return ""

    # 2) Fallback: browser stealthy merender JS (HTML biasa ditolak 403/404).
    with _browser_cm() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return page.content()
        finally:
            browser.close()


def get_images_from_network(url: str, timeout: int = 60) -> List[str]:
    """Ambil URL gambar dengan mencegat response JSON API dari browser.

    Murni synchronous (sync_playwright), sehingga aman diintegrasikan dengan
    script `requests` tanpa membuat event loop crash.
    """
    image_urls: List[str] = []
    found = {"flag": False}

    def on_response(response):
        # ============================================================
        # INTERCEPT RESPONSE JSON
        # page.on("response") memanggil handler ini untuk SETIAP response
        # HTTP (HTML, JS, JSON, gambar, dsb). Filter yang kita lakukan:
        #   1. content-type harus JSON  -> menyingkirkan HTML/JS/image.
        #   2. URL endpoint harus "berbau" chapter/reader -> mencegah data
        #      JSON lain (iklan/analytics) ikut ter-scan.
        # response.json() mengembalikan body yang SUDAH di-buffer oleh
        # Playwright, jadi lebih cepat & akurat daripada parse HTML DOM.
        # Dipasang SEBELUM page.goto() agar tidak ada response terlewat.
        # ============================================================
        try:
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            if not re.search(r"(ajax/read|chapter|reader|images|get-page|source)", response.url, re.I):
                return
            data = response.json()
        except Exception:
            return

        # Kasus khusus MangaFire: result.images = [[url, n, offset], ...]
        # offset > 0 artinya gambar di-scramble -> tandai #scrambled_<offset>
        result = data.get("result") if isinstance(data, dict) else None
        if isinstance(result, dict) and isinstance(result.get("images"), list):
            for img in result["images"]:
                if not (isinstance(img, (list, tuple)) and img and isinstance(img[0], str)):
                    continue
                offset = int(img[2]) if len(img) > 2 else 0
                u = img[0]
                image_urls.append(f"{u}#scrambled_{offset}" if offset > 0 else u)
            found["flag"] = True
            return

        # Generic: rekursi semua string di JSON, ambil yang berupa URL gambar
        _collect_urls(data, image_urls)
        found["flag"] = bool(image_urls)

    if ENGINE == "none":
        return []

    with _browser_cm() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.on("response", on_response)  # pasang listener SEBELUM navigasi

            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

            # Scroll bertahap supaya lazy-load API gambar ikut ke-trigger
            if not found["flag"]:
                for _ in range(8):
                    page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)

            # Fallback terakhir: ambil URL dari DOM <img> bila interceptor kosong
            if not image_urls:
                try:
                    image_urls = page.eval_on_selector_all(
                        "img",
                        "els => els.map(e => e.currentSrc || e.src || '')"
                        ".filter(u => u.startsWith('http'))",
                    )
                except Exception:
                    pass
        finally:
            browser.close()

    return image_urls