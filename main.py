# main.py
import os
import cv2
import re
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from paddleocr import PaddleOCR  # <--- Menggunakan PaddleOCR

import config
from scraper import get_chapter_list, get_page_list
from translator import AiTranslator 

class OCREngine:
    def __init__(self):
        # Inisialisasi PaddleOCR. 
        # Tips: Ubah lang='en' menjadi 'japan', 'korean', atau 'ch' jika komik raw bukan bahasa Inggris.
        self.ocr = PaddleOCR(use_textline_orientation=True, lang='en')

    def detect_and_merge(self, img_path):
        # Proses OCR gambar
        result = self.ocr.ocr(img_path, cls=True)
        
        # Cek jika tidak ada teks yang terdeteksi
        if not result or result[0] is None:
            return []
        
        raw_lines = []
        for line in result[0]:
            box = line[0]       # Koordinat kotak: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
            text = line[1][0]   # Teks hasil OCR (index 1 adalah tuple (teks, confidence))
            
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            raw_lines.append({
                "text": text,
                "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]
            })
        
        return self._merge_dialog_bubbles(raw_lines)

    def _merge_dialog_bubbles(self, lines):
        # Menggunakan logika penggabungan dari kode lama yang lebih akurat
        if not lines:
            return []
        
        lines.sort(key=lambda item: item['box'][1])
        merged = []
        visited = set()
        
        for i in range(len(lines)):
            if i in visited:
                continue
            
            base = lines[i]
            visited.add(i)
            
            group_boxes = [base['box']]
            combined_text = [base['text']]
            
            for j in range(i + 1, len(lines)):
                if j in visited:
                    continue
                
                next_line = lines[j]
                next_box = next_line['box']
                prev_box = group_boxes[-1] 
                
                y_dist = next_box[1] - prev_box[3]
                
                prev_height = prev_box[3] - prev_box[1]
                next_height = next_box[3] - next_box[1]
                min_height = min(prev_height, next_height)
                max_height = max(prev_height, next_height)
                
                x_overlap = min(prev_box[2], next_box[2]) - max(prev_box[0], next_box[0])
                prev_center = (prev_box[0] + prev_box[2]) / 2
                next_center = (next_box[0] + next_box[2]) / 2
                center_diff = abs(prev_center - next_center)
                max_width = max(prev_box[2] - prev_box[0], next_box[2] - next_box[0])
                
                is_similar_size = (max_height / max(1, min_height)) < 1.6 
                
                max_y_dist = max(8, min_height * 0.8)
                min_y_dist = -min_height * 1.5 
                is_vertically_close = min_y_dist <= y_dist <= max_y_dist
                
                is_horizontally_aligned = x_overlap > 0 and (center_diff < max_width * 0.7)
                
                if is_similar_size and is_vertically_close and is_horizontally_aligned:
                    combined_text.append(next_line['text'])
                    group_boxes.append(next_box)
                    visited.add(j)

            min_x = min([b[0] for b in group_boxes])
            min_y = min([b[1] for b in group_boxes])
            max_x = max([b[2] for b in group_boxes])
            max_y = max([b[3] for b in group_boxes])
            
            h_pad = max(2, int((max_x - min_x) * 0.02))
            v_pad = max(2, int((max_y - min_y) * 0.02))
            
            # Simpan tinggi asli untuk patokan font
            line_heights = [b[3] - b[1] for b in group_boxes]
            avg_line_height = sum(line_heights) / len(line_heights)
            
            merged.append({
                "text": " ".join(combined_text),
                "box": [
                    min_x - h_pad,
                    min_y - v_pad,
                    max_x + h_pad,
                    max_y + v_pad
                ],
                "orig_line_height": avg_line_height 
            })
        
        return merged

class ImageProcessor:
    @staticmethod
    def detect_colors(img, box):
        h, w = img.shape[:2]
        xmin, ymin, xmax, ymax = [max(0, min(box[0], w)), max(0, min(box[1], h)), max(0, min(box[2], w)), max(0, min(box[3], h))]
        crop = img[ymin:ymax, xmin:xmax]
        if crop.size == 0:
            return (0, 0, 0), (255, 255, 255)
        
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        avg_brightness = np.mean(gray)
        if avg_brightness > 127:
            return (0, 0, 0), (255, 255, 255)
        else:
            return (255, 255, 255), (0, 0, 0)

class Typesetter:
    @staticmethod
    def apply_text(cv2_img, text_blocks, font_path="arial.ttf"):
        img_rgb = cv2.cvtColor(cv2_img, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(img_rgb)
        
        overlay = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        # Buat background balon dialog
        for block in text_blocks:
            box = block['box']
            box_width = box[2] - box[0]
            box_height = box[3] - box[1]
            radius = int(min(box_width, box_height) * 0.25)
            
            draw_overlay.rounded_rectangle(
                [box[0], box[1], box[2], box[3]], 
                radius=radius,
                fill=(255, 255, 255, 235)
            )

        pil_img = Image.alpha_composite(pil_img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(pil_img)
        
        # Tulis teks terjemahan
        for block in text_blocks:
            text = block.get('translated_text', block['text'])
            box = block['box']
            text_color, outline_color = block['colors']
            
            box_width = box[2] - box[0]
            box_height = box[3] - box[1]
            
            if box_width < 6 or box_height < 6:
                continue
            
            if not os.path.exists(font_path):
                font = ImageFont.load_default()
                import textwrap
                lines = textwrap.wrap(text, width=max(1, int(box_width / 8)), break_long_words=False)
                current_y = box[1] + (box_height - (len(lines)*14)) // 2
                for line in lines:
                    draw.text((box[0] + 2, current_y), line, fill=text_color)
                    current_y += 14
                continue

            orig_line_height = block.get('orig_line_height', box_height)
            font_size = max(10, int(orig_line_height * 0.85)) 
            
            while font_size > 6:
                font = ImageFont.truetype(font_path, font_size)
                words = text.split() 
                lines = []
                current_line = []
                
                for word in words:
                    test_line = ' '.join(current_line + [word]) if current_line else word
                    bbox = draw.textbbox((0, 0), test_line, font=font)
                    w = bbox[2] - bbox[0]
                    
                    if w <= box_width * 0.95:
                        current_line.append(word)
                    else:
                        if not current_line: 
                            current_line.append(word)
                        else:
                            lines.append(' '.join(current_line))
                            current_line = [word]
                
                if current_line:
                    lines.append(' '.join(current_line))
                
                line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + 3
                total_height = len(lines) * line_height
                
                max_w = max([draw.textbbox((0,0), l, font=font)[2] - draw.textbbox((0,0), l, font=font)[0] for l in lines] + [0])
                
                if total_height <= box_height * 0.95 and max_w <= box_width * 0.95:
                    break
                
                font_size -= 1

            font = ImageFont.truetype(font_path, font_size)
            line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + 3
            total_height = len(lines) * line_height
            current_y = box[1] + (box_height - total_height) // 2
            
            for line in lines:
                bbox = draw.textbbox((0, 0), line, font=font)
                line_width = bbox[2] - bbox[0]
                current_x = box[0] + (box_width - line_width) // 2
                
                stroke_w = max(1, int(font_size * 0.05))
                
                for adj_x in range(-stroke_w, stroke_w + 1):
                    for adj_y in range(-stroke_w, stroke_w + 1):
                        if adj_x != 0 or adj_y != 0:
                            draw.text((current_x + adj_x, current_y + adj_y), line, font=font, fill=outline_color)
                
                draw.text((current_x, current_y), line, font=font, fill=text_color)
                current_y += line_height
        
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

def translate_comic(input_path, output_path, ocr, translator):
    img = cv2.imread(input_path)
    if img is None: return False
    blocks = ocr.detect_and_merge(input_path)
    if not blocks: return False
    
    translations = translator.translate_batch([b['text'] for b in blocks])
    for i, b in enumerate(blocks):
        b['translated_text'] = translations[i] if i < len(translations) else b['text']
        b['colors'] = ImageProcessor.detect_colors(img, b['box'])
        
    final_img = Typesetter.apply_text(img, blocks)
    cv2.imwrite(output_path, final_img)
    return True

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
            all_targets.append(ch)
            
    for c_url in chapters:
        if not any(t['url'] == c_url for t in all_targets):
            clean_url = c_url.split('?')[0]
            parts = [p for p in clean_url.split('/') if p]
            fallback_name = f"{parts[-2]}_{parts[-1]}" if len(parts) >= 2 else parts[-1]
            all_targets.append({'url': c_url, 'name': fallback_name})

    ocr = OCREngine()
    translator = AiTranslator()

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
                if translate_comic(raw_path, final_path, ocr, translator):
                    if os.path.exists(raw_path):
                        os.remove(raw_path) 
                    print(f"Halaman {idx} -> Selesai!")
                else:
                    print(f"Halaman {idx} -> Dilewati (Tidak ada teks/Error)")

if __name__ == "__main__":
    main()
