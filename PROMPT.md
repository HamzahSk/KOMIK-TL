# Role
Kamu adalah Expert Python Web Scraper, spesialis dalam mem-bypass sistem Anti-Bot (Cloudflare, reCAPTCHA, Datadome) menggunakan Playwright di ekosistem Python.

# Context & Problem
Saat ini adalah bulan Agustus 2026. Saya sedang membangun aplikasi *scraper* komik (MangaFire & Bbato) menggunakan Python. Saya menggunakan `requests` sebagai *fetcher* utama, namun sering terblokir (Error 403/404 via Cloudflare). 
Sebagai *fallback*, saya mencoba menggunakan `playwright` dan `playwright-stealth`. Namun, integrasi `playwright-stealth` sering mengalami error (seperti `cannot import name 'stealth_async'` atau API yang sudah usang), dan penggunaan `asyncio.run()` di dalam script `requests` yang *synchronous* sering membuat *event loop crash*.

# Task
Lakukan riset web (*browsing*) secara mendalam terkait dokumentasi terbaru (Agustus 2026) dan diskusi komunitas (GitHub Issues, StackOverflow, Reddit) mengenai topik berikut:
1. **Status `playwright-stealth` di Python:** Apakah library ini masih di-maintain? Jika iya, bagaimana cara import dan *usage* API terbarunya (v2.x atau yang lebih baru)? 
2. **Alternatif Stealth Modern:** Jika `playwright-stealth` sudah mati/usang, apa alternatif terbaik di Python saat ini untuk *headless browser stealth*? (misal: pure Playwright dengan argumen khusus, `curl_cffi`, `nodriver`, atau `DrissionPage`).
3. **Best Practice Sync Playwright:** Bagaimana cara terbaik menjalankan Playwright secara *synchronous* (`sync_playwright`) di dalam fungsi biasa (non-async) untuk menyadap *network response* (API JSON gambar) tanpa bentrok dengan *thread* utama?

# Output Requirement
1. Berikan rangkuman hasil risetmu secara singkat dan *to-the-point*.
2. Buatkan fungsi Python `fetch_chapter_html(url)` dan `get_images_from_network(url)` menggunakan **cara stealth terbaik dan paling stabil di tahun 2026**. 
3. Pastikan kodenya bersifat *synchronous* agar mudah diintegrasikan dengan `requests`.
4. Berikan komentar pada bagian *intercept response* JSON-nya.
