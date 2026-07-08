# ocr_engine.py
import re
import cv2
import numpy as np
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

class OCREngine:
    def __init__(self):
        self.reader = RapidOCR(
            params={
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.lang_type": LangDet.EN,               
                "Det.model_type": ModelType.SMALL,         
                "Det.ocr_version": OCRVersion.PPOCRV6,     
                
                # --- TAMBAHAN BARU ---
                # Menambahkan parameter Cls untuk mendeteksi kemiringan/orientasi teks
                "Cls.engine_type": EngineType.ONNXRUNTIME,
                "Cls.model_type": ModelType.MOBILE,  # Menggunakan versi mobile sesuai standar default terbaru
                # ---------------------
                
                "Rec.engine_type": EngineType.ONNXRUNTIME, 
                "Rec.lang_type": LangRec.EN,               
                "Rec.model_type": ModelType.SMALL,         
                "Rec.ocr_version": OCRVersion.PPOCRV6,     
            }
        )

    def detect_and_merge(self, img_path):
        # 1. Buka gambar menggunakan OpenCV
        img = cv2.imread(img_path)
        if img is None:
            return []
        
        # 2. Upscale gambar 2x lipat agar teks kecil lebih tajam
        new_width = img.shape[1] * 2
        new_height = img.shape[0] * 2
        img_resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
        
        # 3. Ubah ke Grayscale
        gray_np = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)

        # 4. Terapkan CLAHE (Mempertegas kontras lokal sebelum binarization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        gray_clahe = clahe.apply(gray_np)

        # 5. Binarization / Adaptive Thresholding
        blur_np = cv2.GaussianBlur(gray_clahe, (5, 5), 0)
        binary_np = cv2.adaptiveThreshold(
            blur_np, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )

        # --- PERUBAHAN BARU ---
        # Masukkan hasil binarization ke RapidOCR dengan use_cls=True untuk mengoreksi teks miring
        out = self.reader(binary_np, use_det=True, use_cls=True, use_rec=True)
        if not out: return []
        
        raw_lines = []
        boxes, texts = [], []

        # Ekstraksi Data RapidOCR yang sudah disederhanakan
        if hasattr(out, 'boxes') and hasattr(out, 'txts') and out.boxes is not None:
            boxes, texts = out.boxes, out.txts
        # Fallback jika output berbentuk tuple/list (versi lama)
        elif isinstance(out, (tuple, list)):
            iterable_result = out[0] if isinstance(out, tuple) else out
            for item in iterable_result:
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
