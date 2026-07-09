# main.py
import os
import re
import json
import concurrent.futures
from PIL import Image

import config
from scraper import get_chapter_list, fetch_chapter_soup, get_page_list, get_chapter_name

# Modul untuk OCR dan Image processing aja, hapus translator
from ocr_engine import OCREngine
from image_utils import download_page, merge_short_images, smart_slice_image

def main():
    mangas = [u for u in config.URLMANGA if u.strip()]
    chapters = [u for u in config.URLCHAPTER if u.strip()]
    
    if not mangas and not chapters:
        print("[System] URL kosong di config.py. Tidak ada yang diproses.")
        return

    os.makedirs("output", exist_ok=True)
    all_targets = []

    for m_url in mangas:
        print(f"\n[Scraper] Mendapatkan daftar chapter dari: {m_url}")
        for ch in get_chapter_list(m_url):
            all_targets.append(ch['url'])
            
    for c_url in chapters:
        if c_url not in all_targets:
            all_targets.append(c_url)

    ocr = OCREngine()

    for ch_url in all_targets:
        print(f"\n[Scraper] Mengambil data halaman untuk: {ch_url}")
        
        soup = fetch_chapter_soup(ch_url)
        if not soup:
            print("[Error] Gagal memuat halaman web. Melewati chapter ini...")
            continue
            
        raw_name = get_chapter_name(soup)
        folder_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '_', raw_name).strip()[:100]
        out_dir = os.path.join("output", folder_name)
        os.makedirs(out_dir, exist_ok=True)
        
        print(f"\n{'='*40}\nMemproses Chapter: {folder_name}\n{'='*40}")
        
        pages = get_page_list(soup)
        if not pages:
            print("[Warning] Tidak ada halaman gambar yang ditemukan.")
            continue
            
        # ==========================================
        # FASE 1: Download Semua Gambar Paralel
        # ==========================================
        print(f"Mengunduh {len(pages)} halaman asli (max_workers=4)...")
        downloaded_paths = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_page = {
                executor.submit(download_page, page, out_dir, ch_url): page['index'] 
                for page in pages
            }
            for future in concurrent.futures.as_completed(future_to_page):
                idx = future_to_page[future]
                path_result = future.result()
                if path_result:
                    downloaded_paths[idx] = path_result

        raw_paths = [downloaded_paths[idx] for idx in sorted(downloaded_paths.keys())]

        # ==========================================
        # FASE 2: Gabungkan Gambar yang Terlalu Pendek
        # ==========================================
        print("Mengecek dimensi & menggabungkan gambar-gambar yang pendek...")
        merged_paths = merge_short_images(raw_paths, target_height=2200, max_workers=6)

        # ==========================================
        # FASE 3: Ekstraksi Teks (OCR) dari Semua Halaman
        # ==========================================
        print(f"Mengekstraksi teks (OCR) dari {len(merged_paths)} gambar gabungan...")
        ocr_results = []

        for idx, path in enumerate(merged_paths):
            # 1. Potong gambar menggunakan Smart Slicing
            # (Gunakan out_dir yang sudah dideklarasikan di atasnya)
            sliced_paths = smart_slice_image(path, target_height=2000, out_dir=out_dir)
            
            page_texts = []
            
            # 2. Lakukan OCR pada setiap potongan gambar
            for slice_path in sliced_paths:
                blocks = ocr.detect_and_merge(slice_path)
                
                # Membersihkan noise teks yang cuma 1 kata
                if blocks and len(blocks) == 1:
                    if len(blocks[0]['text'].split()) <= 1:
                        blocks = [] 
                
                # Masukkan teks dari potongan ini ke wadah halaman utama
                if blocks:
                    page_texts.extend([b['text'] for b in blocks])
                
                # Hapus file potongan setelah di-OCR agar tidak nyampah
                if os.path.exists(slice_path) and slice_path != path:
                    os.remove(slice_path)
            
            # 3. Simpan hasil akhir halaman ke list utama
            ocr_results.append({
                "halaman": idx + 1,
                "gambar_sumber": os.path.basename(path),
                "teks": page_texts
            })
            
            # Hapus file gambar gabungan utama setelah semua potongannya selesai
            if os.path.exists(path):
                os.remove(path)

        # ==========================================
        # FASE 4: Simpan Hasil ke JSON
        # ==========================================
        json_filename = f"{folder_name}_OCR.json"
        json_path = os.path.join("output", json_filename)
        
        print(f"\nMenyimpan hasil ekstraksi teks ke: {json_path}...")
        with open(json_path, 'w', encoding='utf-8') as json_file:
            json.dump(ocr_results, json_file, ensure_ascii=False, indent=4)
            
        try:
            os.rmdir(out_dir) # Hapus folder temporer kalau udah kosong
        except OSError:
            pass
            
        print(f"Sukses! Hasil OCR tersimpan di output/{json_filename}")

if __name__ == "__main__":
    main()
