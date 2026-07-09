# ocr_engine.py
import re
import cv2
import numpy as np
from paddleocr import PaddleOCR

class OCREngine:
    def __init__(self):
        # Inisialisasi PaddleOCR
        # Karena berjalan di GitHub Actions (Free Tier), kita paksa gunakan CPU
        self.reader = PaddleOCR(
            use_angle_cls=True,  # Mengaktifkan deteksi kemiringan/orientasi teks (seperti parameter Cls sebelumnya)
            lang='en',           # Fokus ke deteksi bahasa Inggris
            use_gpu=False,       # Wajib False untuk GitHub Actions free runner
            show_log=False       # Mematikan log bawaan agar log di GitHub Actions tidak terlalu berisik
        )

    def detect_and_merge(self, img_path):
        # 1. Buka gambar menggunakan OpenCV
        img = cv2.imread(img_path)
        if img is None:
            return []
        
        # 2. Upscale 2x lipat (Ubah ke INTER_LANCZOS4 karena lebih tajam untuk teks dibanding CUBIC)
        new_width = img.shape[1] * 2
        new_height = img.shape[0] * 2
        img_resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        
        # 3. Ubah ke Grayscale
        gray_np = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)

        # 4. Terapkan CLAHE (Mempertegas kontras lokal, menjaga huruf pudar agar lebih tebal)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced_img = clahe.apply(gray_np)

        # 5. Denoising Ringan (Gunakan Median Blur daripada Gaussian Blur)
        clean_img = cv2.medianBlur(enhanced_img, 3)

        # Masukkan hasil preprocessing ke PaddleOCR
        # cls=True memastikan classifier sudut dijalankan
        out = self.reader.ocr(clean_img, cls=True)
        
        # PaddleOCR mengembalikan list kosong atau None jika tidak ada teks
        if not out or not out[0]: 
            return []
        
        raw_lines = []

        # Ekstraksi Data PaddleOCR
        # Output format PaddleOCR: [ [ [[x1,y1], [x2,y2], [x3,y3], [x4,y4]], ('Teks', confidence_score) ], ... ]
        for line in out[0]:
            bbox, (text, score) = line
            
            if not bbox or not text: 
                continue
            
            # Kembalikan koordinat ke ukuran asli (karena tadi di-upscale 2x)
            # PaddleOCR memberikan 4 titik sudut, kita ambil x dan y nya
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
