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
            
            merged.append({
                "text": " ".join(combined_text),
                "box": [min_x, min_y, max_x, max_y], # Padding tambahan dihapus agar background tidak kebesaran
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
        
        for block in text_blocks:
            box = block['box']
            # Background dibuat lebih ngepas dengan box asli
            draw_overlay.rounded_rectangle(box, radius=6, fill=(255, 255, 255, 240))
            
        pil_img = Image.alpha_composite(pil_img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(pil_img)
        
        for block in text_blocks:
            box = block['box']
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 6 or bh < 6: continue
            
            # Membatasi ukuran font agar tidak terlalu raksasa atau terlalu mikroskopis
            font_size = int(block.get('orig_line_height', bh) * 0.8)
            font_size = max(10, min(32, font_size)) 
            
            while font_size > 8:
                font = ImageFont.truetype(font_path, font_size) if os.path.exists(font_path) else ImageFont.load_default()
                lines, current_line = [], []
                
                # Word wrap yang lebih akurat
                for word in block.get('translated_text', block['text']).upper().split():
                    test_line = ' '.join(current_line + [word]) if current_line else word
                    test_bbox = draw.textbbox((0, 0), test_line, font=font)
                    if (test_bbox[2] - test_bbox[0]) <= bw * 0.95:
                        current_line.append(word)
                    else:
                        if current_line:
                            lines.append(' '.join(current_line))
                        current_line = [word]
                if current_line: lines.append(' '.join(current_line))
                
                # Hitung tinggi keseluruhan teks
                line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + 3
                total_height = len(lines) * line_height
                
                # Cek apakah teks muat di dalam box
                if total_height <= bh * 0.95:
                    break
                font_size -= 1

            # Hitung posisi Y agar teks berada di tengah (Vertical Center)
            current_y = box[1] + (bh - total_height) // 2
            
            for line in lines:
                cw = draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0]
                cx = box[0] + (bw - cw) // 2
                stroke_w = max(1, int(font_size * 0.05))
                
                # Bikin stroke/outline pada teks
                for adj_x in range(-stroke_w, stroke_w + 1):
                    for adj_y in range(-stroke_w, stroke_w + 1):
                        draw.text((cx + adj_x, current_y + adj_y), line, font=font, fill=block['colors'][1])
                # Gambar teks utama
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

def translate_comic(input_path, output_path, ocr, translator, font_path):
    try:
        img = Image.open(input_path).convert("RGB")
    except Exception:
        return False
        
    blocks = ocr.detect_and_merge(input_path)
    if not blocks: return False
    
    translations = translator.translate_batch([b['text'] for b in blocks])
    for i, b in enumerate(blocks):
        b['translated_text'] = translations[i] if i < len(translations) else b['text']
        b['colors'] = ImageProcessor.detect_colors(img, b['box'])
        
    final_img = Typesetter.apply_text(img, blocks, font_path)
    
    final_img.save(output_path, format="WEBP", quality=80)
    return True

def process_single_page(page, out_dir, ocr, translator, font_path):
    idx = page['index']
    raw_path = os.path.join(out_dir, f"raw_{idx}.jpg")
    final_path = os.path.join(out_dir, f"terjemahan_{idx}.webp")
    
    msg = f"Halaman {idx} -> "
    if download_image(page['imageUrl'], raw_path):
        if translate_comic(raw_path, final_path, ocr, translator, font_path):
            if os.path.exists(raw_path):
                os.remove(raw_path) 
            return msg + "Selesai!"
        else:
            return msg + "Dilewati (Tidak ada teks/Error)"
    return msg + "Gagal mengunduh gambar."

def main():
    mangas = [u for u in config.URLMANGA if u.strip()]
    chapters = [u for u in config.URLCHAPTER if u.strip()]
    
    font_path = getattr(config, 'FONT_PATH', 'arial.ttf')
    
    if not mangas and not chapters:
        print("[System] URL kosong di config.py. Tidak ada yang diproses.")
        return

    os.makedirs("output", exist_ok=True)
    all_targets = []

    # 1. Kumpulkan semua URL yang mau diproses
    for m_url in mangas:
        print(f"\n[Scraper] Mendapatkan daftar chapter dari: {m_url}")
        for ch in get_chapter_list(m_url):
            all_targets.append(ch['url'])
            
    for c_url in chapters:
        if c_url not in all_targets:
            all_targets.append(c_url)

    ocr = OCREngine()
    translator = AiTranslator()

    # 2. Proses masing-masing chapter
    for ch_url in all_targets:
        print(f"\n[Scraper] Mengambil data halaman untuk: {ch_url}")
        
        # --- PERUBAHAN UTAMA DI SINI ---
        # Fetch web satu kali saja untuk mengambil object soup
        soup = fetch_chapter_soup(ch_url)
        if not soup:
            print("[Error] Gagal memuat halaman web. Melewati chapter ini...")
            continue
            
        # Ambil nama chapter khusus dari fungsi get_chapter_name()
        raw_name = get_chapter_name(soup)
        
        folder_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '_', raw_name).strip()[:100]
        out_dir = os.path.join("output", folder_name)
        os.makedirs(out_dir, exist_ok=True)
        
        print(f"\n{'='*40}\nMemproses Chapter: {folder_name}\n{'='*40}")
        
        # Ambil list halaman menggunakan object soup yang sama
        pages = get_page_list(soup)
        # -------------------------------
        
        if not pages:
            print("[Warning] Tidak ada halaman gambar yang ditemukan.")
            continue
            
        print(f"Memulai pemrosesan {len(pages)} halaman (Multithreading max_workers=2)...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(process_single_page, page, out_dir, ocr, translator, font_path): page['index'] 
                for page in pages
            }
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    result_msg = future.result()
                    print(result_msg)
                except Exception as exc:
                    print(f"Halaman {futures[future]} -> Terjadi error tak terduga: {exc}")
                    
        cbz_path = os.path.join("output", f"{folder_name}.cbz")
        print(f"\nMengarsipkan ke: {cbz_path}...")
        
        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz_file:
            for file_name in os.listdir(out_dir):
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
