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
            
        # Mengambil data dict { "title": "...", "chapter_name": "..." }
        ch_info = get_chapter_name(soup)
        
        # Sanitasi nama agar aman untuk folder dan file sistem
        manga_title = re.sub(r'[^a-zA-Z0-9_\-\s]', '_', ch_info.get('title', 'Unknown_Manga')).strip()[:100]
        chapter_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '_', ch_info.get('chapter_name', 'Unknown_Chapter')).strip()[:100]
        
        # Path Folder: output/[Nama Manga]/[Nama Chapter Sementara]
        manga_dir = os.path.join("output", manga_title)
        out_dir = os.path.join(manga_dir, chapter_name)
        os.makedirs(out_dir, exist_ok=True)
        
        print(f"\n{'='*40}\nManga: {manga_title}")
        print(f"Memproses Chapter: {chapter_name}\n{'='*40}")
        
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
            slices = smart_slice_image(m_path, target_height=1200, out_dir=out_dir)
            final_paths.extend(slices)
            
            if len(slices) > 1 and os.path.exists(m_path):
                os.remove(m_path)

        # ==========================================
        # FASE 3: Ekstraksi Teks & Filter SFX
        # ==========================================
        print(f"Mengekstraksi teks (OCR) dari {len(final_paths)} gambar...")
        page_blocks_list = [] 
        kumpulan_teks_untuk_ai = []    
        
        # KAMUS SFX SEDERHANA (Tambahkan kata-kata lain di sini)
        SFX_DICT = {
            "DROP": "JATUH",
            "BAM": "DUAG",
            "WHOOSH": "WUSSS",
            "SLAP": "PLAK",
            "SIGH": "HAHH",
            "UHH": "EHH"
        }

        for path in final_paths: 
            blocks = ocr.detect_and_merge(path)
            
            if blocks and len(blocks) == 1:
                if len(blocks[0]['text'].split()) <= 1:
                    blocks = [] 
            
            for b in blocks:
                teks_asli = b['text'].upper()
                kata_kata = teks_asli.split()
                
                # Cek jika ini cuma 1 kata (SFX / Suara)
                if len(kata_kata) == 1:
                    kata_bersih = re.sub(r'[^A-Z]', '', teks_asli)
                    if kata_bersih in SFX_DICT:
                        b['translated_text'] = SFX_DICT[kata_bersih]
                        continue # Langsung lewati, jangan masukkan ke antrean AI
                
                # Jika bukan 1 kata, ATAU 1 kata tapi tidak ada di kamus, kirim ke AI
                b['ai_index'] = len(kumpulan_teks_untuk_ai)
                kumpulan_teks_untuk_ai.append(teks_asli)
                
            page_blocks_list.append((path, blocks))

        # ==========================================
        # FASE 4: Batch Translation (Hanya untuk teks panjang/tak terdaftar)
        # ==========================================
        hasil_terjemahan = []
        if kumpulan_teks_untuk_ai:
            print(f"Menerjemahkan {len(kumpulan_teks_untuk_ai)} blok dialog via AI...")
            
            current_batch = []
            current_len = 0
            
            for teks in kumpulan_teks_untuk_ai:
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
                
        # Gabungkan hasil AI kembali ke blok masing-masing
        for path, blocks in page_blocks_list:
            for b in blocks:
                if 'translated_text' not in b: # Jika belum diisi oleh Kamus SFX
                    idx_ai = b.get('ai_index', -1)
                    if 0 <= idx_ai < len(hasil_terjemahan):
                        b['translated_text'] = hasil_terjemahan[idx_ai]
                    else:
                        b['translated_text'] = b['text']

        # ==========================================
        # FASE 5: Typesetting & Distribusi Kembali
        # ==========================================
        print("Merender teks ke gambar dan menyimpan hasil akhir...")
        for idx, (path, blocks) in enumerate(page_blocks_list):
            final_path = os.path.join(out_dir, f"terjemahan_{str(idx+1).zfill(3)}.webp")
            
            if not blocks:
                try:
                    Image.open(path).convert("RGB").save(final_path, format="WEBP", quality=80)
                except Exception: pass
                finally:
                    if os.path.exists(path): os.remove(path)
                continue
                
            try:
                img = Image.open(path).convert("RGB")
                for b in blocks:
                    b['colors'] = ImageProcessor.detect_colors(img, b['box'])
                    
                final_img = Typesetter.apply_text(img, blocks, font_path)
                final_img.save(final_path, format="WEBP", quality=80)
            except Exception as e:
                print(f"Gagal memproses typesetting halaman {idx+1}: {e}")
            finally:
                if os.path.exists(path): os.remove(path)

                    
        # ==========================================
        # FASE 6: Pengarsipan CBZ
        # ==========================================
        # File CBZ disimpan langsung di dalam folder manga: output/[Nama Manga]/[Nama Chapter].cbz
        cbz_path = os.path.join(manga_dir, f"{chapter_name}.cbz")
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
            
        print(f"Sukses mengarsipkan {chapter_name}.cbz ke folder {manga_title}!")

if __name__ == "__main__":
    main()
