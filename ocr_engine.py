# ocr_engine.py
import re
import cv2
import math
import numpy as np
from rapidocr import RapidOCR


class OCREngine:
    def __init__(self, config_path="config.yaml"):
        self.reader = RapidOCR(config_path=config_path)

    def _adaptive_preprocess(self, img):
        """Adaptive preprocessing for manga/manhwa text detection.

        Analyzes image statistics (contrast, noise, sharpness) and applies
        the optimal combination of:
          - Upscaling (for small text)
          - Bilateral filtering (screentone removal)
          - CLAHE (contrast enhancement)
          - Unsharp masking (text edge sharpening)
        """
        h, w = img.shape[:2]

        scale = 1.0
        if max(h, w) < 2000:
            target = 2000.0
            scale = min(3.0, max(1.5, target / max(h, w)))
        if scale > 1.0:
            img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        mean_val = np.mean(gray)
        std_val = np.std(gray)

        result = gray.copy()

        laplacian_var = np.var(cv2.Laplacian(gray, cv2.CV_64F))
        if laplacian_var > 600:
            result = cv2.bilateralFilter(result, 7, 50, 50)

        if std_val < 50:
            clip, grid = 3.5, (6, 6)
        elif std_val < 80:
            clip, grid = 2.5, (8, 8)
        else:
            clip, grid = 1.5, (10, 10)

        clahe = cv2.createCLAHE(clipLimit=clip, tileGridSize=grid)
        result = clahe.apply(result)

        sharpen = np.array([
            [-0.3, -0.3, -0.3],
            [-0.3,  3.4, -0.3],
            [-0.3, -0.3, -0.3]
        ])
        result = cv2.filter2D(result, -1, sharpen)

        result = cv2.medianBlur(result, 3)

        return result

    def _clean_ocr_text(self, text):
        """Cleans OCR output while preserving meaningful characters.

        Fixes common OCR confusions for comic fonts (| → I, brackets → I)
        and retains punctuation important for natural-language translation.
        """
        text = text.replace('|', 'I')
        text = text.replace('[', 'I').replace(']', 'I')
        text = text.replace('{', 'I').replace('}', 'I')

        text = re.sub(r'[^\w\s.,!?\'"~\-:;()@#$%^&*+=/<>]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        return text

    def detect_and_merge(self, img_path):
        img = cv2.imread(img_path)
        if img is None:
            return []

        processed_img = self._adaptive_preprocess(img)

        out = self.reader(processed_img, use_det=True, use_cls=True, use_rec=True)
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

        # Reconstruct the preprocessed image shape for coordinate scaling
        proc_h, proc_w = processed_img.shape[:2]
        orig_h, orig_w = img.shape[:2]
        scale_x = orig_w / proc_w if proc_w > 0 else 1.0
        scale_y = orig_h / proc_h if proc_h > 0 else 1.0

        for bbox, text in zip(boxes, texts):
            if bbox is None or len(bbox) < 4:
                continue

            xs = [p[0] * scale_x for p in bbox]
            ys = [p[1] * scale_y for p in bbox]

            dx = bbox[1][0] - bbox[0][0]
            dy = bbox[1][1] - bbox[0][1]
            angle = math.degrees(math.atan2(dy, dx))

            clean_text = self._clean_ocr_text(text)
            if not clean_text:
                continue

            raw_lines.append({
                "text": clean_text,
                "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))],
                "angle": angle
            })

        return self._merge_dialog_bubbles(raw_lines)

    def _can_merge(self, candidate, cluster_info):
        """Determines whether `candidate` belongs to the same dialog bubble as
        the growing cluster tracked in `cluster_info`.
        """
        box = candidate['box']
        cw = box[2] - box[0]
        ch = box[3] - box[1]

        # Menghitung rata-rata tinggi baris di dalam cluster saat ini
        avg_h = sum(b[3] - b[1] for b in cluster_info['boxes']) / len(cluster_info['boxes'])

        # 1. CEK PERBEDAAN UKURAN FONT (Judul vs Teks Normal)
        # Diperketat: Jika beda tinggi rata-rata baris > 1.35x, pisahkan jadi kelompok baru!
        if max(avg_h, ch) / max(1, min(avg_h, ch)) > 1.35:
            return False

        # 2. CEK PERBEDAAN SUDUT (KEMIRINGAN)
        avg_angle = sum(cluster_info['angles']) / len(cluster_info['angles'])
        angle_diff = abs(candidate['angle'] - avg_angle)
        
        if angle_diff > 10:
            return False
            
        if (abs(candidate['angle']) > 5 or abs(avg_angle) > 5) and angle_diff > 4:
            return False

        # 3. CEK TUMPANG TINDIH HORIZONTAL
        horizontal_ok = False
        for cbox in cluster_info['boxes']:
            cbw = cbox[2] - cbox[0]
            overlap = min(box[2], cbox[2]) - max(box[0], cbox[0])
            if overlap > 0:
                if overlap / min(cw, cbw) > 0.15:
                    horizontal_ok = True
                    break
            else:
                ca = (box[0] + box[2]) / 2.0
                cc = (cbox[0] + cbox[2]) / 2.0
                if abs(ca - cc) < max(cw, cbw) * 0.28:
                    horizontal_ok = True
                    break

        if not horizontal_ok:
            return False

        # 4. CEK JARAK VERTIKAL (SPACE TAMBAHAN)
        vertical_ok = False
        for cbox in cluster_info['boxes']:
            cch = cbox[3] - cbox[1]
            mh = min(ch, cch)

            if box[1] >= cbox[3]:
                gap = box[1] - cbox[3]
            elif box[3] <= cbox[1]:
                gap = cbox[1] - box[3]
            else:
                gap = 0

            # PERBAIKAN: Batas gap diperketat menjadi 0.9x.
            # Jika ada "space tambahan" antar baris yang besarnya hampir menyamai tinggi 1 huruf,
            # berarti itu beda kelompok/paragraf.
            if gap <= max(mh * 0.9, 14) and gap >= -mh * 0.5:
                vertical_ok = True
                break

        if not vertical_ok:
            return False

        return True

    def _merge_dialog_bubbles(self, lines):
        """Groups OCR text lines into dialog-bubble clusters using single-
        linkage merging with adaptive geometric criteria.

        Lines are visited top-to-bottom. Each unvisited line seeds a new
        cluster; the cluster greedily absorbs any later line that satisfies
        `_can_merge` against the cluster's aggregate state.
        """
        if not lines:
            return []

        n = len(lines)
        y_centers = [(lines[i]['box'][1] + lines[i]['box'][3]) / 2.0 for i in range(n)]
        order = sorted(range(n), key=lambda i: y_centers[i])

        visited = set()
        merged_clusters = []

        for idx in order:
            if idx in visited:
                continue

            cluster_indices = [idx]
            visited.add(idx)

            cluster_info = {
                'boxes': [lines[idx]['box']],
                'angles': [lines[idx]['angle']],
                'min_h': lines[idx]['box'][3] - lines[idx]['box'][1],
                'max_h': lines[idx]['box'][3] - lines[idx]['box'][1],
            }

            changed = True
            while changed:
                changed = False
                for j in order:
                    if j in visited:
                        continue
                    if self._can_merge(lines[j], cluster_info):
                        cluster_indices.append(j)
                        visited.add(j)
                        bj = lines[j]['box']
                        hj = bj[3] - bj[1]
                        cluster_info['boxes'].append(bj)
                        cluster_info['angles'].append(lines[j]['angle'])
                        cluster_info['min_h'] = min(cluster_info['min_h'], hj)
                        cluster_info['max_h'] = max(cluster_info['max_h'], hj)
                        changed = True

            merged_clusters.append(sorted(cluster_indices))

        result = []
        for cluster in merged_clusters:
            cluster_lines = [lines[i] for i in cluster]

            min_x = min(l['box'][0] for l in cluster_lines)
            min_y = min(l['box'][1] for l in cluster_lines)
            max_x = max(l['box'][2] for l in cluster_lines)
            max_y = max(l['box'][3] for l in cluster_lines)

            combined_text = " ".join(l['text'] for l in cluster_lines)
            letter_count = len(re.sub(r'[^A-Za-z0-9]', '', combined_text))

            if letter_count > 2:
                avg_height = sum(l['box'][3] - l['box'][1] for l in cluster_lines) / len(cluster_lines)
                avg_angle = sum(l['angle'] for l in cluster_lines) / len(cluster_lines)

                result.append({
                    "text": combined_text,
                    "box": [min_x, min_y, max_x, max_y],
                    "orig_line_height": avg_height,
                    "angle": avg_angle,
                    "lines_info": cluster_lines
                })

        return result
