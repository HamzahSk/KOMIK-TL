# ocr_engine.py
import re
import cv2
import numpy as np
from paddleocr import PaddleOCR

class OCREngine:
    def __init__(self):
        # Inisialisasi PaddleOCR versi 3.7.0 (PP-OCRv6)
        self.reader = PaddleOCR(
            lang='en',                       # Fokus ke deteksi bahasa Inggris
            device='cpu',                    # Menggantikan use_gpu=False, wajib CPU untuk free runner
            use_doc_orientation_classify=False, # Matikan untuk hemat resource
            use_doc_unwarping=False,         # Matikan koreksi lengkungan agar lebih enteng
            use_textline_orientation=True,   # Menggantikan use_angle_cls=True untuk deteksi orientasi teks
            enable_mkldnn=True,              # Memaksimalkan akselerasi CPU
            cpu_threads=2                    # Set thread CPU (GitHub Actions free biasanya pakai 2 core)
        )

    def detect_and_merge(self, img_path):
        # 1. Buka gambar menggunakan OpenCV
        img = cv2.imread(img_path)
        if img is None:
            return []
        
        # 2. Upscale 2x lipat (Ubah ke INTER_LANCZOS4 karena lebih tajam)

        
        # 3. Ubah ke Grayscale untuk preprocessing
        gray_np = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # 4. Terapkan CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced_img = clahe.apply(gray_np)

        # 5. Denoising Ringan
        clean_img = cv2.medianBlur(enhanced_img, 3)
        
        # 6. Konversi kembali ke BGR (3 channel) untuk PaddleOCR
        clean_img_bgr = cv2.cvtColor(clean_img, cv2.COLOR_GRAY2BGR)

        # Gunakan API predict() versi terbaru
        out = self.reader.predict(clean_img_bgr)
        
        # Jika kosong, skip
        if not out: 
            return []
        
        raw_lines = []

        # Ekstraksi Data dari objek Result PaddleOCR v3.7
        try:
            # Mengakses dictionary hasil prediksi
            res_data = out[0]['res']
        except (TypeError, KeyError, IndexError):
            # Fallback jika out[0] di-return sebagai object murni
            res_data = getattr(out[0], 'res', {})
            if not res_data and hasattr(out[0], '__dict__'):
                res_data = out[0].__dict__.get('res', {})

        # Ambil array teks dan koordinat
        rec_texts = res_data.get('rec_texts', [])
        rec_polys = res_data.get('rec_polys', [])
        
        if len(rec_texts) == 0:
            return []

        # Looping hasil ekstraksi
        for i in range(len(rec_texts)):
            text = rec_texts[i]
            bbox = rec_polys[i]
            
            if not bbox or not text: 
                continue
            
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
                
        # Logika penggabungan balon dialog tetap sama, tidak perlu diganti
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