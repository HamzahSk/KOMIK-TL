# main.py
import os
import re
import zipfile
import time
import concurrent.futures
from PIL import Image

import config
from scraper import get_chapter_list, fetch_chapter_soup, get_page_list, get_chapter_name
from translator import AiTranslator 

# Import modul yang sudah dipisah
from ocr_engine import OCREngine
from image_utils import ImageProcessor, Typesetter, download_page, merge_short_images, smart_slice_image

def main():
    mangas = [u for u in config.URLMANGA if u.strip()]
    chapters = [u for u in config.URLCHAPTER if u.strip()]
    
    font_path = getattr(config, 'FONT_PATH', 'arial.ttf')
    
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
    translator = AiTranslator()

    for ch_url in all_targets:
        print(f"\n[Scraper] Mengambil data halaman untuk: {ch_url}")
        
        translator.reset_chapter_session() 
        
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
        # FASE 2.5: Smart Slicing (Baru)
        # ==========================================
        print("Merapikan potongan panel gambar (Smart Slicing)...")
        final_paths = []
        for m_path in merged_paths:
            # Potong secara cerdas pakai fungsi baru
            slices = smart_slice_image(m_path, target_height=2000, out_dir=out_dir)
            final_paths.extend(slices)
            
            # Jika gambar beneran dipotong (hasilnya lebih dari 1 file), 
            # hapus gambar gabungan aslinya biar storage nggak penuh
            if len(slices) > 1 and os.path.exists(m_path):
                os.remove(m_path)

        # ==========================================
        # FASE 3: Ekstraksi Teks (OCR) dari Semua Halaman
        # ==========================================
        # PERHATIKAN: Ubah 'merged_paths' menjadi 'final_paths' di bawah ini
        print(f"Mengekstraksi teks (OCR) dari {len(final_paths)} gambar...")
        page_blocks_list = [] 
        kumpulan_teks = []    

        for path in final_paths: # <--- INI YANG DIUBAH
            blocks = ocr.detect_and_merge(path)
            
            if blocks and len(blocks) == 1:
                if len(blocks[0]['text'].split()) <= 1:
                    blocks = [] 

            page_blocks_list.append((path, blocks))
            
            for b in blocks:
                kumpulan_teks.append(b['text'])

        # ==========================================
        # FASE 4: Batch Translation 
        # ==========================================
        hasil_terjemahan = []
        if kumpulan_teks:
            print(f"Menerjemahkan {len(kumpulan_teks)} blok teks...")
            
            current_batch = []
            current_len = 0
            
            for teks in kumpulan_teks:
                panjang_teks = len(teks)
                
                if (current_len + panjang_teks > 1000) or (len(current_batch) >= 25):
                    if current_batch: 
                        hasil_terjemahan.extend(translator.translate_batch(current_batch))
                        time.sleep(4)
                    current_batch = []
                    current_len = 0
                
                current_batch.append(teks)
                current_len += panjang_teks
                
            if current_batch:
                hasil_terjemahan.extend(translator.translate_batch(current_batch))
                
            print(f"Selesai menerjemahkan total {len(hasil_terjemahan)} blok teks.")
        else:
            print("Tidak ada teks yang perlu diterjemahkan di chapter ini.")

        # ==========================================
        # FASE 5: Typesetting & Distribusi Kembali
        # ==========================================
        print("Merender teks ke gambar dan menyimpan hasil akhir...")
        text_index = 0
        
        for idx, (path, blocks) in enumerate(page_blocks_list):
            final_path = os.path.join(out_dir, f"terjemahan_{str(idx+1).zfill(3)}.webp")
            
            if not blocks:
                try:
                    img = Image.open(path).convert("RGB")
                    img.save(final_path, format="WEBP", quality=80)
                except Exception as e:
                    print(f"Gagal menyimpan halaman {idx+1}: {e}")
                finally:
                    if os.path.exists(path): os.remove(path)
                continue
                
            try:
                img = Image.open(path).convert("RGB")
                
                for b in blocks:
                    if text_index < len(hasil_terjemahan):
                        b['translated_text'] = hasil_terjemahan[text_index]
                    else:
                        b['translated_text'] = b['text'] 
                        
                    b['colors'] = ImageProcessor.detect_colors(img, b['box'])
                    text_index += 1
                    
                final_img = Typesetter.apply_text(img, blocks, font_path)
                final_img.save(final_path, format="WEBP", quality=80)
                
            except Exception as e:
                print(f"Gagal memproses typesetting halaman {idx+1}: {e}")
            finally:
                if os.path.exists(path): os.remove(path)
                    
        # ==========================================
        # FASE 6: Pengarsipan CBZ
        # ==========================================
        cbz_path = os.path.join("output", f"{folder_name}.cbz")
        print(f"\nMengarsipkan ke: {cbz_path}...")
        
        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz_file:
            for file_name in sorted(os.listdir(out_dir)): 
                file_path = os.path.join(out_dir, file_name)
                if os.path.isfile(file_path):
                    cbz_file.write(file_path, arcname=file_name)
                    os.remove(file_path)
                    
        try:
            os.rmdir(out_dir)
        except OSError:
            print(f"[Warning] Tidak dapat menghapus folder sementara: {out_dir}")
            
        print(f"Sukses mengarsipkan {folder_name}.cbz!")

if __name__ == "__main__":
    main()
