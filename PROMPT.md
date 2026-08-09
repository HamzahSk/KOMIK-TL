
# 🎯 Role & Context
You are an expert Python Developer. I am building a manga scraping and translation pipeline. 
My project has three main files:
1. `main.py`: The orchestrator that processes data.
2. `scraper.py`: A routing system that calls specific module scrapers.
3. `manhuarml.py`: A scraper module that fetches data from my testing API (Express.js) which returns JSON.

In `manhuarml.py`, I am using a trick: `fetch_chapter_soup` returns a **JSON dictionary** (from my API) instead of a BeautifulSoup object. The functions `get_page_list` and `get_chapter_name` then read from this JSON dictionary.

# 🐛 The Problem
When I run `main.py`, I get this error log:
```text
[Warning] Tidak ada halaman gambar yang ditemukan.

```
Sometimes it also fails to get the chapter URL properly. The issue is a **data structure mismatch** between what manhuarml.py returns and what main.py expects.
# 🔍 Root Cause Analysis (Where it clashes)
**1. Chapter List format clash:**
 * My API returns: [{"title": "...", "link": "...", "date": "..."}]
 * manhuarml.py currently returns this directly.
 * But main.py (around line 45) expects the URL key to be exactly 'url':
   all_targets.append(ch['url']) -> *This breaks because the key is 'link', not 'url'.*
**2. Image Page List format clash:**
 * My API returns a simple list of strings: ["img1.webp", "img2.webp"]
 * manhuarml.py (get_page_list) currently returns this list of strings.
 * But main.py (around line 85) expects a list of dictionaries with index and url:
   executor.submit(download_page, page, out_dir, ch_url): page['index'] -> *This breaks because a string doesn't have an 'index' or 'url' key.*
# 🛠️ Your Task
Please rewrite the **entire manhuarml.py code** to fix these formatting bridges.
DO NOT touch main.py or scraper.py.
You need to map the JSON responses inside manhuarml.py so they perfectly match main.py's expectations:
 1. In get_chapter_list: iterate the API response and map the "link" key to "url".
 2. In get_page_list: convert the list of image URL strings into a list of dictionaries formatted exactly like {"index": i, "url": img_url}.
 3. Ensure get_chapter_name correctly handles missing keys gracefully.
Provide the complete, updated manhuarml.py script.
