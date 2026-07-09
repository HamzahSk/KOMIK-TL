# ocr_engine.py
import re
import cv2
import numpy as np
from paddleocr import PaddleOCR

class OCREngine:
    def __init__(self):
        # Inisialisasi PaddleOCR versi 3.7.0 (PP-OCRv6)
        self.reader = PaddleOCR(
            lang='en',
            device='cpu',
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=True,
            enable_mkldnn=True,
            cpu_threads=2
        )
        # Batas maksimum ukuran gambar untuk OCR
        self.max_height = 3000
        self.max_width = 2000

    def detect_and_merge(self, img_path):
        # 1. Buka gambar menggunakan OpenCV
        img = cv2.imread(img_path)
        if img is None:
            return []
        
        h, w = img.shape[:2]
        
        # 2. Resize jika terlalu besar (tapi tidak terlalu kecil)
        # Tujuan: menjaga proporsi tapi tidak melebihi batas
        scale = 1.0
        if h > self.max_height:
            scale = self.max_height / h
        if w > self.max_width:
            scale = min(scale, self.max_width / w)
        
        # Jika perlu resize, lakukan dengan INTER_LANCZOS4
        if scale < 1.0:
            new_w = int(w * scale)
            new_h = int(h * scale)
            img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
            print(f"  [OCR] Resize dari {w}x{h} ke {new_w}x{new_h} (scale: {scale:.2f})")
        else:
            # Upscale 1.5x untuk gambar kecil (bukan 2x)
            if h < 1500 and w < 1000:
                scale = 1.5
                new_w = int(w * scale)
                new_h = int(h * scale)
                img_resized = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
                print(f"  [OCR] Upscale dari {w}x{h} ke {new_w}x{new_h} (scale: {scale:.2f})")
            else:
                img_resized = img
        
        # 3. Preprocessing: Grayscale + CLAHE + Denoising
        gray_np = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced_img = clahe.apply(gray_np)
        clean_img = cv2.medianBlur(enhanced_img, 3)
        
        # 4. Konversi kembali ke BGR (3 channel) untuk PaddleOCR
        clean_img_bgr = cv2.cvtColor(clean_img, cv2.COLOR_GRAY2BGR)

        # 5. OCR
        out = self.reader.predict(clean_img_bgr)
        
        if not out: 
            return []
        
        raw_lines = []

        try:
            res_data = out[0]['res']
        except (TypeError, KeyError, IndexError):
            res_data = getattr(out[0], 'res', {})
            if not res_data and hasattr(out[0], '__dict__'):
                res_data = out[0].__dict__.get('res', {})

        rec_texts = res_data.get('rec_texts', [])
        rec_polys = res_data.get('rec_polys', [])
        
        if len(rec_texts) == 0:
            return []

        for i in range(len(rec_texts)):
            text = rec_texts[i]
            bbox = rec_polys[i]
            
            if not bbox or not text: 
                continue
            
            # Kembalikan koordinat ke ukuran asli
            # Jika gambar di-resize, skalakan kembali koordinatnya
            if scale < 1.0:
                # Resize down, koordinat perlu di-scale up
                scale_back = 1.0 / scale
                xs = [p[0] * scale_back for p in bbox]
                ys = [p[1] * scale_back for p in bbox]
            elif scale > 1.0:
                # Upscale, koordinat perlu di-scale down
                scale_back = 1.0 / scale
                xs = [p[0] * scale_back for p in bbox]
                ys = [p[1] * scale_back for p in bbox]
            else:
                xs = [p[0] for p in bbox]
                ys = [p[1] for p in bbox]
            
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
        if not lines: 
            return []
        
        lines.sort(key=lambda item: item['box'][1])
        merged, visited = [], set()
        
        for i in range(len(lines)):
            if i in visited: 
                continue
            
            base = lines[i]
            visited.add(i)
            group_boxes, combined_text = [base['box']], [base['text']]
            
            for j in range(i + 1, len(lines)):
                if j in visited: 
                    continue
                
                next_box = lines[j]['box']
                prev_box = group_boxes[-1] 
                min_h = min(prev_box[3] - prev_box[1], next_box[3] - next_box[1])
                
                is_vertically_close = (-min_h * 1.0) <= (next_box[1] - prev_box[3]) <= max(5, min_h * 0.5)
                is_horizontally_aligned = (min(prev_box[2], next_box[2]) - max(prev_box[0], next_box[0])) > 0 and (abs((prev_box[0] + prev_box[2])/2 - (next_box[0] + next_box[2])/2) < max(prev_box[2] - prev_box[0], next_box[2] - next_box[0]) * 0.5)
                
                if (max(prev_box[3] - prev_box[1], next_box[3] - next_box[1]) / max(1, min_h) < 1.6) and is_vertically_close and is_horizontally_aligned:
                    combined_text.append(lines[j]['text'])
                    group_boxes.append(next_box)
                    visited.add(j)

            min_x = min([b[0] for b in group_boxes])
            min_y = min([b[1] for b in group_boxes])
            max_x = max([b[2] for b in group_boxes])
            max_y = max([b[3] for b in group_boxes])
            
            gabungan_teks = " ".join(combined_text)
            
            jumlah_huruf = len(re.sub(r'[^A-Z]', '', gabungan_teks.upper()))
            
            if jumlah_huruf > 2:
                merged.append({
                    "text": gabungan_teks,
                    "box": [min_x, min_y, max_x, max_y], 
                    "orig_line_height": sum([b[3] - b[1] for b in group_boxes]) / len(group_boxes)
                })
                
        return merged