# ocr_engine.py
import re
import cv2
import math 
import numpy as np
from rapidocr import RapidOCR

class OCREngine:
    def __init__(self, config_path="config.yaml"):
        self.reader = RapidOCR(config_path=config_path)

    def detect_and_merge(self, img_path):
        img = cv2.imread(img_path)
        if img is None:
            return []
        
        new_width = img.shape[1] * 2
        new_height = img.shape[0] * 2
        img_resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        
        gray_np = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced_img = clahe.apply(gray_np)
        clean_img = cv2.medianBlur(enhanced_img, 3)

        out = self.reader(clean_img, use_det=True, use_cls=True, use_rec=True)
        if not out: return []
        
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
            if bbox is None or len(bbox) < 4: continue
            
            xs = [p[0] / 2.0 for p in bbox]
            ys = [p[1] / 2.0 for p in bbox]
            
            dx = bbox[1][0] - bbox[0][0]
            dy = bbox[1][1] - bbox[0][1]
            angle = math.degrees(math.atan2(dy, dx))
            
            fixed_text = text.replace('|', 'I').replace('[', 'I').replace(']', 'I').replace('{', 'I').replace('}', 'I')
            fixed_text = fixed_text.upper()
            
            clean_text = re.sub(r'[^A-Z0-9\s.,!?\'"~-]', '', fixed_text).strip() 
            clean_text = re.sub(r'\s+', ' ', clean_text)
            
            # PERBAIKAN FILTER SAMPAH:
            # Pastikan teks minimal punya 1 huruf (A-Z). Kalau isinya cuma angka/simbol, buang.
            # Kalau isinya cuma "O" diulang-ulang (titik keringat/gelembung kosong), buang.
            has_letters = bool(re.search(r'[A-Z]', clean_text))
            is_sweat_drops = re.fullmatch(r'[O0-9\W_]+', clean_text) and len(clean_text) >= 2
            
            if not has_letters or is_sweat_drops:
                continue 
            
            if clean_text: 
                raw_lines.append({
                    "text": clean_text,
                    "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))],
                    "angle": angle 
                })
                
        return self._merge_dialog_bubbles(raw_lines)

    def _merge_dialog_bubbles(self, lines):
        if not lines: return []
        
        lines.sort(key=lambda item: (item['box'][1] + item['box'][3]) / 2)
        
        merged, visited = [], set()
        
        for i in range(len(lines)):
            if i in visited: continue
            base = lines[i]
            visited.add(i)
            group_boxes, combined_text, group_angles = [base['box']], [base['text']], [base['angle']]
            
            for j in range(i + 1, len(lines)):
                if j in visited: continue
                next_box = lines[j]['box']
                prev_box = group_boxes[-1] 
                
                prev_h = prev_box[3] - prev_box[1]
                next_h = next_box[3] - next_box[1]
                min_h = min(prev_h, next_h)
                max_h = max(prev_h, next_h)
                
                is_horizontally_overlapping = (min(prev_box[2], next_box[2]) - max(prev_box[0], next_box[0])) > -5
                prev_cx = (prev_box[0] + prev_box[2]) / 2
                next_cx = (next_box[0] + next_box[2]) / 2
                max_w = max(prev_box[2] - prev_box[0], next_box[2] - next_box[0])
                
                is_center_aligned = abs(prev_cx - next_cx) < (max_w * 0.3) 
                is_horizontally_aligned = is_horizontally_overlapping and is_center_aligned
                
                is_vertically_close = (-min_h * 1.5) <= (next_box[1] - prev_box[3]) <= (min_h * 1.5)
                is_height_similar = (max_h / max(1, min_h)) < 1.6 
                is_angle_similar = abs(lines[j]['angle'] - group_angles[-1]) < 12
            
                if is_horizontally_aligned and is_vertically_close and is_height_similar and is_angle_similar:
                    combined_text.append(lines[j]['text'])
                    group_boxes.append(next_box)
                    group_angles.append(lines[j]['angle'])
                    visited.add(j)

            min_x, min_y = min([b[0] for b in group_boxes]), min([b[1] for b in group_boxes])
            max_x, max_y = max([b[2] for b in group_boxes]), max([b[3] for b in group_boxes])
            
            gabungan_teks = " ".join(combined_text)
            
            # PERBAIKAN BATAS HURUF:
            # Cukup minimal 1 huruf yang valid (bukan spasi/simbol) biar dialog pendek kayak "OK", "I", "AH" gak hilang!
            jumlah_huruf = len(re.sub(r'[^A-Z]', '', gabungan_teks.upper()))
            
            if jumlah_huruf >= 1:
                merged.append({
                    "text": gabungan_teks,
                    "box": [min_x, min_y, max_x, max_y], 
                    "orig_line_height": sum([b[3] - b[1] for b in group_boxes]) / len(group_boxes),
                    "angle": sum(group_angles) / len(group_angles)
                })
                
        return merged
