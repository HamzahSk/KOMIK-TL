# main.py
import os
import re
import requests
import zipfile
import numpy as np
import concurrent.futures
from PIL import Image, ImageDraw, ImageFont

from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

import config
from scraper import get_chapter_list, fetch_chapter_soup, get_page_list, get_chapter_name
from translator import AiTranslator 

class OCREngine:
    def __init__(self):
        self.reader = RapidOCR(
            params={
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.lang_type": LangDet.EN,               
                "Det.model_type": ModelType.SMALL,         
                "Det.ocr_version": OCRVersion.PPOCRV6,     
                "Rec.engine_type": EngineType.ONNXRUNTIME, 
                "Rec.lang_type": LangRec.EN,               
                "Rec.model_type": ModelType.SMALL,         
                "Rec.ocr_version": OCRVersion.PPOCRV6,     
            }
        )

    def detect_and_merge(self, img_path):
        try:
            img = Image.open(img_path).convert("RGB")
        except Exception:
            return []
        
        # Upscale gambar 2x lipat agar teks kecil lebih tajam
        new_size = (img.width * 2, img.height * 2)
        img_resized = img.resize(new_size, Image.Resampling.BICUBIC)
        
        # Ubah ke Grayscale (Hitam Putih)
        gray_np = np.array(img_resized.convert("L"))

        out = self.reader(gray_np)
        if not out: return []
        
        raw_lines = []
        boxes, texts = [], []

        # Ekstraksi Data RapidOCR
        if isinstance(out, (tuple, list)):
            iterable_result = out[0] if isinstance(out, tuple) else out
            for item in iterable_result:
                if len(item) >= 2:
                    boxes.append(item[0])
                    texts.append(item[1])
        else:
            if hasattr(out, 'boxes') and hasattr(out, 'txts'):
                boxes, texts = out.boxes, out.txts
            elif hasattr(out, 'dt_boxes') and hasattr(out, 'rec_res'):
                boxes = out.dt_boxes
                texts = [res[0] if isinstance(res, (tuple, list)) else res for res in out.rec_res]
            else:
                raw_list = getattr(out, 'result', getattr(out, 'res', getattr(out, 'ocr_res', [])))
                for item in raw_list:
                    if isinstance(item, (list, tuple)) and len(item) >= 2:
                        boxes.append(item[0])
                        texts.append(item[1])

        # Post-Processing
        for bbox, text in zip(boxes, texts):
            if bbox is None or len(bbox) < 4: continue
            
            # Kembalikan koordinat ke ukuran asli (karena tadi di-upscale 2x)
            xs = [p[0] / 2.0 for p in bbox]
            ys = [p[1] / 2.0 for p in bbox]
            
            fixed_text = text.replace('|', 'I').replace('[', 'I').replace(']', 'I').replace('{', 'I').replace('}', 'I')
            fixed_text = fixed_text.upper()
            
            clean_text = re.sub(r'[^A-Z0-9\s.,!?\'"~-]', '', fixed_text).strip() 
            clean_text = re.sub(r'\s+', ' ', clean_text)
            
            if clean_text: 
                raw_lines.append({
                    "text": clean_text,
                    "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
                })
                
        return self._merge_dialog_bubbles(raw_lines)

    def _merge_dialog_bubbles(self, lines):
        if not lines: return []
        lines.sort(key=lambda item: item['box'][1])
        merged, visited = [], set()
        
        for i in range(len(lines)):
            if i in visited: continue
            base = lines[i]
            visited.add(i)
            group_boxes, combined_text = [base['box']], [base['text']]
            
            for j in range(i + 1, len(lines)):
                if j in visited: continue
                next_box = lines[j]['box']
                prev_box = group_boxes[-1] 
                min_h = min(prev_box[3] - prev_box[1], next_box[3] - next_box[1])
                
                # Toleransi diperketat agar teks yang beda konteks tidak mudah menyatu
                is_vertically_close = (-min_h * 1.0) <= (next_box[1] - prev_box[3]) <= max(5, min_h * 0.5)
                is_horizontally_aligned = (min(prev_box[2], next_box[2]) - max(prev_box[0], next_box[0])) > 0 and (abs((prev_box[0] + prev_box[2])/2 - (next_box[0] + next_box[2])/2) < max(prev_box[2] - prev_box[0], next_box[2] - next_box[0]) * 0.5)
                
                if (max(prev_box[3] - prev_box[1], next_box[3] - next_box[1]) / max(1, min_h) < 1.6) and is_vertically_close and is_horizontally_aligned:
                    combined_text.append(lines[j]['text'])
                    group_boxes.append(next_box)
                    visited.add(j)

            min_x, min_y = min([b[0] for b in group_boxes]), min([b[1] for b in group_boxes])
            max_x, max_y = max([b[2] for b in group_boxes]), max([b[3] for b in group_boxes])
            
            gabungan_teks = " ".join(combined_text)
            
            # FILTER TEKS: Hitung jumlah huruf (hanya A-Z) dalam kelompok ini
            jumlah_huruf = len(re.sub(r'[^A-Z]', '', gabungan_teks.upper()))
            
            if jumlah_huruf > 2:
                merged.append({
                    "text": gabungan_teks,
                    "box": [min_x, min_y, max_x, max_y], 
                    "orig_line_height": sum([b[3] - b[1] for b in group_boxes]) / len(group_boxes)
                })
                
        return merged


class ImageProcessor:
    @staticmethod
    def detect_colors(pil_img, box):
        crop = pil_img.crop((max(0, box[0]), max(0, box[1]), min(pil_img.width, box[2]), min(pil_img.height, box[3])))
        gray_crop = crop.convert("L")
        
        if not gray_crop.getbbox(): 
            return (0, 0, 0), (255, 255, 255)
            
        if np.mean(np.array(gray_crop)) > 127: 
            return (0, 0, 0), (255, 255, 255)
        return (255, 255, 255), (0, 0, 0)

class Typesetter:
    @staticmethod
    def apply_text(pil_img, text_blocks, font_path="arial.ttf"):
        overlay = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        # 1. Modifikasi: Gambar background HANYA jika teks lebih dari 1 kata
        for block in text_blocks:
            box = block['box']
            display_text = block.get('translated_text', block['text'])
            
            # Cek jumlah kata
            if len(display_text.split()) > 1:
                draw_overlay.rounded_rectangle(box, radius=6, fill=(255, 255, 255, 240))
            
        pil_img = Image.alpha_composite(pil_img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(pil_img)
        
        for block in text_blocks:
            box = block['box']
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 6 or bh < 6: continue
            
            display_text = block.get('translated_text', block['text'])
            is_single_word = len(display_text.split()) <= 1 # Deteksi 1 kata
            
            font_size = int(block.get('orig_line_height', bh) * 0.8)
            font_size = max(10, min(100, font_size)) 
            
            while font_size > 8:
                font = ImageFont.truetype(font_path, font_size) if os.path.exists(font_path) else ImageFont.load_default()
                lines, current_line = [], []
                
                for word in display_text.upper().split():
                    test_line = ' '.join(current_line + [word]) if current_line else word
                    test_bbox = draw.textbbox((0, 0), test_line, font=font)
                    if (test_bbox[2] - test_bbox[0]) <= bw * 0.95:
                        current_line.append(word)
                    else:
                        if current_line:
                            lines.append(' '.join(current_line))
                        current_line = [word]
                if current_line: lines.append(' '.join(current_line))
                
                line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + 3
                total_height = len(lines) * line_height
                
                if total_height <= bh * 0.95:
                    break
                font_size -= 1

            current_y = box[1] + (bh - total_height) // 2
            
            for line in lines:
                cw = draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0]
                cx = box[0] + (bw - cw) // 2
                
                # 2. Modifikasi: Atur ketebalan stroke (shadow)
                if is_single_word:
                    stroke_w = max(2, int(font_size * 0.12)) # Lebih tebal untuk 1 kata
                else:
                    stroke_w = max(1, int(font_size * 0.05)) # Normal
                
                for adj_x in range(-stroke_w, stroke_w + 1):
                    for adj_y in range(-stroke_w, stroke_w + 1):
                        draw.text((cx + adj_x, current_y + adj_y), line, font=font, fill=block['colors'][1])
                draw.text((cx, current_y), line, font=font, fill=block['colors'][0])
                current_y += line_height
                
        return pil_img

def download_image(url, save_path):
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, stream=True, timeout=15)
        if res.status_code == 200:
            with open(save_path, 'wb') as f:
                for chunk in res.iter_content(1024): f.write(chunk)
            return True
    except Exception: pass
    return False

# --- 1. Fungsi Mengunduh Saja ---
def download_page(page, out_dir):
    idx = page['index']
    raw_path = os.path.join(out_dir, f"raw_{idx}.jpg")
    if download_image(page['imageUrl'], raw_path):
        return raw_path
    return None

# --- 2a. Fungsi Proses Gabung Per Grup ---
def process_merge_group(group_data, merge_idx, out_dir, target_width):
    current_height = 0
    images_to_paste = []
    
    # Buka dan sesuaikan ukuran gambar di grup ini
    for path, w, h in group_data:
        try:
            img = Image.open(path).convert("RGB")
            if img.width != target_width:
                new_h = int(img.height * (target_width / img.width))
                img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            images_to_paste.append(img)
            current_height += img.height
        except Exception:
            continue
            
    if not images_to_paste:
        return None
        
    # Gabungkan gambar
    merged_img = Image.new('RGB', (target_width, current_height))
    y_offset = 0
    for im in images_to_paste:
        merged_img.paste(im, (0, y_offset))
        y_offset += im.height
        
    new_path = os.path.join(out_dir, f"merged_raw_{str(merge_idx).zfill(3)}.jpg")
    merged_img.save(new_path, format="JPEG", quality=95)
    
    # Hapus gambar raw asli yang sudah digabung
    for path, _, _ in group_data:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass
                
    return new_path

# --- 2b. Fungsi Utama Penggabungan Gambar Pendek (Paralel) ---
def merge_short_images(raw_paths, target_height=2200, max_workers=6):
    if not raw_paths: return []
    
    # 1. Ngintip dimensi gambar secara berurutan (Sangat Cepat)
    img_infos = []
    for path in raw_paths:
        try:
            with Image.open(path) as img:
                img_infos.append((path, img.width, img.height))
        except Exception:
            pass
            
    if not img_infos: return []
    
    # 2. Tentukan grup-grup gambar
    groups = []
    current_group = []
    current_h = 0
    target_w = img_infos[0][1] # Patokan lebar dari gambar pertama
    
    for info in img_infos:
        path, w, h = info
        est_h = int(h * (target_w / w)) if w != target_w else h
        
        current_group.append(info)
        current_h += est_h
        
        if current_h >= target_height:
            groups.append(current_group)
            current_group = []
            current_h = 0
            
    if current_group: # Masukkan sisa gambar ke grup terakhir
        groups.append(current_group)
        
    # 3. Proses penggabungan tiap grup secara PARALEL
    out_dir = os.path.dirname(raw_paths[0])
    merged_paths = []
    
    print(f"Mengeksekusi penggabungan {len(groups)} grup gambar secara paralel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(process_merge_group, grp, idx+1, out_dir, target_w): idx+1
            for idx, grp in enumerate(groups)
        }
        
        results = {}
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            res_path = future.result()
            if res_path:
                results[idx] = res_path
                
    # Urutkan berdasarkan index agar halamannya tidak acak saat di-OCR
    for i in sorted(results.keys()):
        merged_paths.append(results[i])
        
    return merged_paths


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
                executor.submit(download_page, page, out_dir): page['index'] 
                for page in pages
            }
            for future in concurrent.futures.as_completed(future_to_page):
                idx = future_to_page[future]
                path_result = future.result()
                if path_result:
                    downloaded_paths[idx] = path_result

        # Urutkan berdasarkan index asli agar saat digabung tidak acak
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
        page_blocks_list = [] # Menyimpan tuple (path, blocks_valid)
        kumpulan_teks = []    # Gabungan seluruh teks untuk batch translation

        for path in merged_paths:
            blocks = ocr.detect_and_merge(path)
            
            # --- LOGIKA SKIP 1 KELOMPOK & 1 KATA ---
            if blocks and len(blocks) == 1:
                if len(blocks[0]['text'].split()) <= 1:
                    blocks = [] # Kosongkan agar tidak diterjemahkan/typeset
            # ---------------------------------------

            page_blocks_list.append((path, blocks))
            
            # Kumpulkan teks yang valid ke satu wadah besar
            for b in blocks:
                kumpulan_teks.append(b['text'])

        # ==========================================
        # FASE 4: Batch Translation (Limit 1000 Karakter & Max 25 Teks/Batch)
        # ==========================================
        hasil_terjemahan = []
        if kumpulan_teks:
            print(f"Menerjemahkan {len(kumpulan_teks)} blok teks...")
            
            current_batch = []
            current_len = 0
            
            for teks in kumpulan_teks:
                panjang_teks = len(teks)
                
                # Jika ditambah teks ini melebihi 1000 karakter ATAU jumlah teks di batch sudah 25
                if (current_len + panjang_teks > 1000) or (len(current_batch) >= 25):
                    if current_batch: # Pastikan batch tidak kosong sebelum dikirim
                        hasil_terjemahan.extend(translator.translate_batch(current_batch))
                    current_batch = []
                    current_len = 0
                
                # Masukkan teks ke batch saat ini
                current_batch.append(teks)
                current_len += panjang_teks
                
            # Jangan lupa terjemahkan sisa teks yang ada di batch terakhir
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
            
            # Jika tidak ada teks di gambar ini, langsung save ulang jadi webp
            if not blocks:
                try:
                    img = Image.open(path).convert("RGB")
                    img.save(final_path, format="WEBP", quality=80)
                except Exception as e:
                    print(f"Gagal menyimpan halaman {idx+1}: {e}")
                finally:
                    if os.path.exists(path): os.remove(path)
                continue
                
            # Proses Typesetting jika ada teks
            try:
                img = Image.open(path).convert("RGB")
                
                # Pasangkan teks terjemahan ke block yang sesuai
                for b in blocks:
                    if text_index < len(hasil_terjemahan):
                        b['translated_text'] = hasil_terjemahan[text_index]
                    else:
                        b['translated_text'] = b['text'] # Fallback kalau beda panjang array
                        
                    b['colors'] = ImageProcessor.detect_colors(img, b['box'])
                    text_index += 1
                    
                # Eksekusi apply_text
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
            for file_name in sorted(os.listdir(out_dir)):  # Pakai sorted agar halamannya rapi
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
