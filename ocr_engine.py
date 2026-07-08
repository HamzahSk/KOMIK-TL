# ocr_engine.py
import re
import numpy as np
from PIL import Image
from rapidocr import EngineType, LangDet, LangRec, ModelType, OCRVersion, RapidOCR

class OCREngine:
    def __init__(self):
        self.reader = RapidOCR(
            params={
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.lang_type": LangDet.EN,               
                "Det.model_type": ModelType.MEDIUM,         
                "Det.ocr_version": OCRVersion.PPOCRV6,     
                "Rec.engine_type": EngineType.ONNXRUNTIME, 
                "Rec.lang_type": LangRec.EN,               
                "Rec.model_type": ModelType.MEDIUM,         
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
        