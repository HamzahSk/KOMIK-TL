# ocr_engine.py
import re
import cv2
import math
import numpy as np
from rapidocr import RapidOCR
import font_style_rs
import typeset_rs

class OCREngine:
    def __init__(self, config_path="config.yaml"):
        # Inisialisasi RapidOCR langsung menggunakan file config.yaml
        self.reader = RapidOCR(config_path=config_path)

    def detect_and_merge(self, img_path):

        img = cv2.imread(img_path)
        if img is None:
            return []

        new_width = img.shape[1] * 2
        new_height = img.shape[0] * 2
        img_resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)

        gray_np = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced_img = clahe.apply(gray_np)
        clean_img = cv2.medianBlur(enhanced_img, 3)

        out = self.reader(clean_img, use_det=True, use_cls=True, use_rec=True)
        if not out:
            return []

        raw_lines = []
        boxes, texts = [], []

        if hasattr(out, 'boxes') and hasattr(out, 'txts') and out.boxes is not None:
            boxes, texts = out.boxes, out.txts
        elif isinstance(out, (tuple, list)):
            iterable_result = out[0] if isinstance(out, tuple) else out
            for item in iterable_result:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    boxes.append(item[0])
                    texts.append(item[1])

        for bbox, text in zip(boxes, texts):
            if bbox is None or len(bbox) < 4:
                continue

            xs = [p[0] / 2.0 for p in bbox]
            ys = [p[1] / 2.0 for p in bbox]

            # Hitung sudut kemiringan (Titik Kanan Atas - Titik Kiri Atas)
            dx = bbox[1][0] - bbox[0][0]
            dy = bbox[1][1] - bbox[0][1]
            angle = math.degrees(math.atan2(dy, dx))

            fixed_text = text.replace('|', 'I').replace('[', 'I').replace(']', 'I').replace('{', 'I').replace('}', 'I')
            fixed_text = fixed_text.upper()

            clean_text = re.sub(r'[^A-Z0-9\s.,!?\'"~-]', '', fixed_text).strip()
            clean_text = re.sub(r'\s+', ' ', clean_text)

            if re.fullmatch(r'[O0-9\s.,!?\'"~-]+', clean_text) and len(clean_text) < 6:
                continue

            if clean_text:
                # --- MULAI INTEGRASI RUST ---
                x_min, y_min = int(min(xs)), int(min(ys))
                x_max, y_max = int(max(xs)), int(max(ys))

                # Pastikan koordinat tidak keluar batas gambar asli
                y_min, y_max = max(0, y_min), min(img.shape[0], y_max)
                x_min, x_max = max(0, x_min), min(img.shape[1], x_max)

                # Crop gambar dan ubah ke Grayscale
                crop_bgr = img[y_min:y_max, x_min:x_max]
                is_italic, is_bold = False, False
                if crop_bgr.size > 0:
                    gray_crop = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
                    # Panggil modul Rust!
                    style = font_style_rs.analyze(gray_crop)
                    is_italic = style["is_italic"]
                    is_bold = style["is_bold"]
                # --- AKHIR INTEGRASI RUST ---

                raw_lines.append({
                    "text": clean_text,
                    "box": [x_min, y_min, x_max, y_max],
                    "angle": angle,            # <-- Menyimpan nilai kemiringan
                    "is_italic": is_italic,    # <-- Simpan status italic
                    "is_bold": is_bold         # <-- Simpan status bold
                })

        return self._merge_dialog_bubbles(raw_lines)

    def _merge_dialog_bubbles(self, lines):
        if not lines:
            return []

        # Susun matriks kotak teks [x1, y1, x2, y2, angle] untuk clustering Rust
        boxes = np.asarray(
            [[l['box'][0], l['box'][1], l['box'][2], l['box'][3], l['angle']] for l in lines],
            dtype=np.float64,
        )

        # --- MULAI INTEGRASI RUST ---
        # Clustering balon percakapan berbasis Union-Find / Spatial Clustering.
        # Garis digabung jika jarak spasialnya berdekatan DAN perbedaan ukuran
        # font (tinggi box) masih dalam toleransi (default maks. 30%).
        clusters = typeset_rs.cluster_boxes(boxes)
        # --- AKHIR INTEGRASI RUST ---

        merged = []
        for cluster in clusters:
            group_lines = [lines[i] for i in cluster]
            group_boxes = [l['box'] for l in group_lines]
            group_angles = [l['angle'] for l in group_lines]

            min_x = min(b[0] for b in group_boxes)
            min_y = min(b[1] for b in group_boxes)
            max_x = max(b[2] for b in group_boxes)
            max_y = max(b[3] for b in group_boxes)

            gabungan_teks = " ".join(l['text'] for l in group_lines)
            jumlah_huruf = len(re.sub(r'[^A-Z]', '', gabungan_teks.upper()))

            if jumlah_huruf > 2:
                merged.append({
                    "text": gabungan_teks,
                    "box": [min_x, min_y, max_x, max_y],
                    "orig_line_height": sum(b[3] - b[1] for b in group_boxes) / len(group_boxes),
                    "angle": sum(group_angles) / len(group_angles),
                    # Jika ada setidaknya 1 baris di dalam balon yang terdeteksi italic/bold, anggap seluruh balon italic/bold
                    "is_italic": any(l['is_italic'] for l in group_lines),
                    "is_bold": any(l['is_bold'] for l in group_lines),
                })

        return merged
