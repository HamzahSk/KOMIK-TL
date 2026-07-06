# main.py
import os
import cv2
import re
import requests
import zipfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr_onnxruntime import RapidOCR

import config
from scraper import get_chapter_list, get_page_list
from translator import AiTranslator 

class OCREngine:
    def __init__(self):
        self.ocr = RapidOCR()

    def detect_and_merge(self, img_path):
        result, _ = self.ocr(img_path)
        if not result: return []
        raw_lines = [{"text": l[1], "box": [int(min([p[0] for p in l[0]])), int(min([p[1] for p in l[0]])), int(max([p[0] for p in l[0]])), int(max([p[1] for p in l[0]]))]} for l in result]
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
                
                is_vertically_close = (-min_h * 1.5) <= (next_box[1] - prev_box[3]) <= max(8, min_h * 0.8)
                is_horizontally_aligned = (min(prev_box[2], next_box[2]) - max(prev_box[0], next_box[0])) > 0 and (abs((prev_box[0] + prev_box[2])/2 - (next_box[0] + next_box[2])/2) < max(prev_box[2] - prev_box[0], next_box[2] - next_box[0]) * 0.7)
                
                if (max(prev_box[3] - prev_box[1], next_box[3] - next_box[1]) / max(1, min_h) < 1.6) and is_vertically_close and is_horizontally_aligned:
                    combined_text.append(lines[j]['text'])
                    group_boxes.append(next_box)
                    visited.add(j)

            min_x, min_y = min([b[0] for b in group_boxes]), min([b[1] for b in group_boxes])
            max_x, max_y = max([b[2] for b in group_boxes]), max([b[3] for b in group_boxes])
            merged.append({
                "text": " ".join(combined_text),
                "box": [min_x - max(2, int((max_x - min_x) * 0.02)), min_y - max(2, int((max_y - min_y) * 0.02)), max_x + max(2, int((max_x - min_x) * 0.02)), max_y + max(2, int((max_y - min_y) * 0.02))],
                "orig_line_height": sum([b[3] - b[1] for b in group_boxes]) / len(group_boxes)
            })
        return merged

class ImageProcessor:
    @staticmethod
    def detect_colors(img, box):
        h, w = img.shape[:2]
        crop = img[max(0, min(box[1], h)):max(0, min(box[3], h)), max(0, min(box[0], w)):max(0, min(box[2], w))]
        if crop.size == 0 or np.mean(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)) > 127: return (0, 0, 0), (255, 255, 255)
        return (255, 255, 255), (0, 0, 0)

class Typesetter:
    @staticmethod
    def apply_text(cv2_img, text_blocks, font_path="arial.ttf"):
        pil_img = Image.fromarray(cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB))
        overlay = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        for block in text_blocks:
            box = block['box']
            draw_overlay.rounded_rectangle(box, radius=int(min(box[2]-box[0], box[3]-box[1]) * 0.25), fill=(255, 255, 255, 235))
            
        pil_img = Image.alpha_composite(pil_img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(pil_img)
        
        for block in text_blocks:
            box = block['box']
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 6 or bh < 6: continue
            
            font_size = max(10, int(block.get('orig_line_height', bh) * 0.85))
            while font_size > 6:
                font = ImageFont.truetype(font_path, font_size) if os.path.exists(font_path) else ImageFont.load_default()
                lines, current_line = [], []
                for word in block.get('translated_text', block['text']).split():
                    test_line = ' '.join(current_line + [word]) if current_line else word
                    if draw.textbbox((0, 0), test_line, font=font)[2] <= bw * 0.95:
                        current_line.append(word)
                    else:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                if current_line: lines.append(' '.join(current_line))
                
                if (len(lines) * (font.getbbox("A")[3] - font.getbbox("A")[1] + 3)) <= bh * 0.95: break
                font_size -= 1

            current_y = box[1] + (bh - (len(lines) * (font.getbbox("A")[3] - font.getbbox("A")[1] + 3))) // 2
            for line in lines:
                cw = draw.textbbox((0, 0), line, font=font)[2]
                cx = box[0] + (bw - cw) // 2
                stroke_w = max(1, int(font_size * 0.05))
                for adj_x in range(-stroke_w, stroke_w + 1):
                    for adj_y in range(-stroke_w, stroke_w + 1):
                        draw.text((cx + adj_x, current_y + adj_y), line, font=font, fill=block['colors'][1])
                draw.text((cx, current_y), line, font=font, fill=block['colors'][0])
                current_y += (font.getbbox("A")[3] - font.getbbox("A")[1] + 3)
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

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
    img = cv2.imread(input_path)
    if img is None: return False
    blocks = ocr.detect_and_merge(input_path)
    if not blocks: return False
    
    translations = translator.translate_batch([b['text'] for b in blocks])
    for i, b in enumerate(blocks):
        b['translated_text'] = translations[i] if i < len(translations) else b['text']
        b['colors'] = ImageProcessor.detect_colors(img, b['box'])
        
    final_img = Typesetter.apply_text(img, blocks, font_path)
    cv2.imwrite(output_path, final_img)
    return True

def main():
    mangas = [u for u in config.URLMANGA if u.strip()]
    chapters = [u for u in config.URLCHAPTER if u.strip()]
    
    # === PENGATURAN FONT ===
    # Kamu bisa menambahkan FONT_PATH = "nama_font.ttf" di config.py
    # Jika tidak ada, script akan mencari "arial.ttf" atau fallback ke default
    font_path = getattr(config, 'FONT_PATH', 'arial.ttf')
    
    if not mangas and not chapters:
        print("[System] URL kosong di config.py. Tidak ada yang diproses.")
        return

    os.makedirs("output", exist_ok=True)
    all_targets = []

    # 1. Ambil dari URL Manga
    for m_url in mangas:
        print(f"\n[Scraper] Mendapatkan daftar chapter dari: {m_url}")
        for ch in get_chapter_list(m_url):
            all_targets.append(ch)
            
    # 2. Ambil dari URL Chapter spesifik
    for c_url in chapters:
        if not any(t['url'] == c_url for t in all_targets):
            clean_url = c_url.split('?')[0]
            parts = [p for p in clean_url.split('/') if p]
            fallback_name = f"{parts[-2]}_{parts[-1]}" if len(parts) >= 2 else parts[-1]
            all_targets.append({'url': c_url, 'name': fallback_name})

    ocr = OCREngine()
    translator = AiTranslator()

    # 3. Proses pengunduhan
    for target in all_targets:
        ch_url = target['url']
        raw_name = target['name']
        
        folder_name = re.sub(r'[^a-zA-Z0-9_\-\s]', '_', raw_name).strip()[:100]
        out_dir = os.path.join("output", folder_name)
        os.makedirs(out_dir, exist_ok=True)
        
        print(f"\n{'='*40}\nMemproses Chapter: {folder_name}\n{'='*40}")
        pages = get_page_list(ch_url)
        
        for page in pages:
            idx = page['index']
            raw_path = os.path.join(out_dir, f"raw_{idx}.jpg")
            final_path = os.path.join(out_dir, f"terjemahan_{idx}.jpg")
            
            print(f"Halaman {idx} -> Mengunduh...")
            if download_image(page['imageUrl'], raw_path):
                print(f"Halaman {idx} -> Scanning & Translate...")
                # Mengoper font_path ke fungsi translate_comic
                if translate_comic(raw_path, final_path, ocr, translator, font_path):
                    if os.path.exists(raw_path):
                        os.remove(raw_path) 
                    print(f"Halaman {idx} -> Selesai!")
                else:
                    print(f"Halaman {idx} -> Dilewati (Tidak ada teks/Error)")
                    
        # 4. Membuat file CBZ setelah satu chapter selesai diproses
        cbz_path = os.path.join("output", f"{folder_name}.cbz")
        print(f"\nMengarsipkan ke: {cbz_path}...")
        
        with zipfile.ZipFile(cbz_path, 'w', zipfile.ZIP_DEFLATED) as cbz_file:
            for file_name in os.listdir(out_dir):
                file_path = os.path.join(out_dir, file_name)
                # Hanya masukkan file gambar terjemahan ke dalam archive
                if os.path.isfile(file_path):
                    cbz_file.write(file_path, arcname=file_name)
                    os.remove(file_path) # Hapus gambar aslinya setelah masuk ke CBZ
                    
        # Hapus folder chapter yang sekarang sudah kosong
        try:
            os.rmdir(out_dir)
        except OSError:
            print(f"[Warning] Tidak dapat menghapus folder sementara: {out_dir}")
            
        print(f"Sukses mengarsipkan {folder_name}.cbz!")

if __name__ == "__main__":
    main()
