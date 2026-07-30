# image_utils.py
import os
import requests
import concurrent.futures

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Font registry – maps semantic roles to file names inside FONT_DIR
# ---------------------------------------------------------------------------
FONT_DIR = "font"

FONT_REGULAR = "digistrip.ttf"
FONT_ITALIC = ["digistrip_i.ttf", "Roboto-Italic.ttf"]
FONT_BOLD = ["Komika_display_kaps_bold.ttf", "Roboto-Bold.ttf"]
FONT_SFX = ["Houston Comics Personal Use.ttf", "Komika_display.ttf", "helsinki.ttf"]


class ImageProcessor:
    @staticmethod
    def detect_colors(pil_img, box):
        crop = pil_img.crop((
            max(0, int(box[0])),
            max(0, int(box[1])),
            min(pil_img.width, int(box[2])),
            min(pil_img.height, int(box[3]))
        ))

        img_np = np.array(crop.convert("RGB"))
        if img_np.size == 0 or img_np.shape[0] < 3 or img_np.shape[1] < 3:
            return (0, 0, 0), (255, 255, 255)

        pixels = img_np.reshape((-1, 3)).astype(np.float32)

        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        try:
            _, labels, centers = cv2.kmeans(pixels, 2, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
            centers = np.uint8(centers)
            counts = np.bincount(labels.flatten())

            bg_idx = np.argmax(counts)
            text_idx = 1 - bg_idx

            text_color = tuple(int(c) for c in centers[text_idx])
            stroke_color = tuple(int(c) for c in centers[bg_idx])

            if sum(abs(t - b) for t, b in zip(text_color, stroke_color)) < 50:
                return (0, 0, 0), (255, 255, 255)

            return text_color, stroke_color
        except Exception:
            return (0, 0, 0), (255, 255, 255)


class Typesetter:
    """Renders translated text onto manga panels."""

    # ------------------------------------------------------------------
    # Font helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_font(font_name):
        """Return full path for a font file inside FONT_DIR, or None."""
        path = os.path.join(FONT_DIR, font_name)
        return path if os.path.exists(path) else None

    @staticmethod
    def _estimate_stroke_weight(pil_img, box):
        """
        Mengukur ketebalan huruf asli di gambar menggunakan Distance Transform.
        Mengembalikan rasio ketebalan garis terhadap tinggi kotak (0.0 - 0.3+).
        """
        try:
            crop = pil_img.crop((
                max(0, int(box[0])),
                max(0, int(box[1])),
                min(pil_img.width, int(box[2])),
                min(pil_img.height, int(box[3]))
            ))
            
            img_np = np.array(crop.convert("L"))
            if img_np.size == 0 or img_np.shape[0] < 5 or img_np.shape[1] < 5:
                return 0.08

            _, binary = cv2.threshold(img_np, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            if np.sum(binary == 255) > np.sum(binary == 0):
                binary = cv2.bitwise_not(binary)

            dist = cv2.distanceTransform(binary, cv2.DIST_L2, 3)
            
            stroke_pixels = dist[dist > 1.0]
            if len(stroke_pixels) == 0:
                return 0.08
                
            avg_stroke_thickness = np.percentile(stroke_pixels, 80) * 2.0
            box_height = img_np.shape[0]
            
            weight_ratio = avg_stroke_thickness / max(1, box_height)
            return weight_ratio
        except Exception:
            return 0.08

    @staticmethod
    def _select_font(block, pil_img=None):
        """
        Memilih font berdasarkan pengukuran KETEBALAN HURUF asli pada gambar
        dan memisahkan font Italic dengan SFX.
        """
        text = block.get("text", "")
        box = block["box"]
        bh = box[3] - box[1]
        font_size_est = int(block.get("orig_line_height", bh) * 0.9)
        words = text.split()
        is_single = len(words) <= 1

        # 1. SFX detection (kata tunggal ukuran sangat besar)
        if is_single and font_size_est > 45:
            for name in FONT_SFX:
                path = Typesetter._resolve_font(name)
                if path:
                    return path

        # 2. Cek Ketebalan Huruf dari gambar asli
        is_bold_weight = False
        if pil_img is not None:
            stroke_weight = Typesetter._estimate_stroke_weight(pil_img, box)
            if stroke_weight >= 0.14:
                is_bold_weight = True

        # 3. Bold detection: Hanya jika huruf tebal / teriakan
        has_exclamation = "!" in text
        if is_bold_weight or (has_exclamation and font_size_est > 38):
            for name in FONT_BOLD:
                path = Typesetter._resolve_font(name)
                if path:
                    return path

        # 4. Angle-based Italic vs SFX detection
        angle = abs(block.get("angle", 0.0))
        if angle > 10:
            if is_single and font_size_est > 35:
                for name in FONT_SFX:
                    path = Typesetter._resolve_font(name)
                    if path:
                        return path
            for name in FONT_ITALIC:
                path = Typesetter._resolve_font(name)
                if path:
                    return path

        # 5. Default -> FONT REGULAR (digistrip.ttf)
        reg = Typesetter._resolve_font(FONT_REGULAR)
        return reg if reg else None

    @staticmethod
    def _text_width(text, font):
        bb = font.getbbox(text)
        return bb[2] - bb[0] if bb else 0

    @staticmethod
    def _text_height(font):
        bb = font.getbbox("A")
        return bb[3] - bb[1] if bb else font.size

    @staticmethod
    def _wrap_text(words, font, max_width):
        """Greedy line-wrap – returns list of lines (strings)."""
        lines = []
        cur = []
        for w in words:
            test = " ".join(cur + [w])
            if Typesetter._text_width(test, font) <= max_width:
                cur.append(w)
            else:
                if cur:
                    lines.append(" ".join(cur))
                cur = [w]
        if cur:
            lines.append(" ".join(cur))
        return lines

    @staticmethod
    def _fit_font_size(text, font_path, box, max_font=160, min_font=8):
        """Binary-search the largest font size that still fits inside `box`."""
        bw, bh = box[2] - box[0], box[3] - box[1]
        if bw < 8 or bh < 8:
            return None, [], 0

        words = text.split()
        best = None

        lo, hi = min_font, min(max_font, int(bh))
        while lo <= hi:
            mid = (lo + hi) // 2
            if not os.path.exists(font_path):
                font = ImageFont.load_default()
            else:
                font = ImageFont.truetype(font_path, mid)

            lines = Typesetter._wrap_text(words, font, int(bw * 0.95))
            if not lines:
                hi = mid - 1
                continue

            lh = Typesetter._text_height(font) + int(mid * 0.35)
            total_h = len(lines) * lh
            max_lw = max(Typesetter._text_width(l, font) for l in lines)

            width_ok = max_lw <= bw * 0.95
            height_ok = total_h <= bh * 0.95

            if width_ok and height_ok:
                best = (lines, total_h, mid, font, max_lw)
                lo = mid + 1
            else:
                hi = mid - 1

        if best is not None:
            return best

        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, min_font)
        else:
            font = ImageFont.load_default()
        lines = Typesetter._wrap_text(words, font, int(bw * 0.95))
        lh = Typesetter._text_height(font) + int(min_font * 0.35)
        total_h = len(lines) * lh if lines else 0
        max_lw = max((Typesetter._text_width(l, font) for l in lines), default=0)
        return lines, total_h, min_font, font, max_lw

    # ------------------------------------------------------------------
    # Inpainting
    # ------------------------------------------------------------------
    @staticmethod
    def _build_inpaint_mask(img_bgr, text_blocks):
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        mask = np.zeros(img_bgr.shape[:2], dtype=np.uint8)

        for block in text_blocks:
            box = block["box"]
            pad = 5
            x1 = max(0, int(box[0]) - pad)
            y1 = max(0, int(box[1]) - pad)
            x2 = min(img_bgr.shape[1], int(box[2]) + pad)
            y2 = min(img_bgr.shape[0], int(box[3]) + pad)

            if x2 - x1 < 6 or y2 - y1 < 6:
                continue

            roi = gray[y1:y2, x1:x2]

            med = np.median(roi)
            lower = int(max(0, 0.5 * med))
            upper = int(min(255, 1.3 * med))
            edges = cv2.Canny(roi, lower, upper)

            _, th_dark = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            _, th_light = cv2.threshold(roi, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            thresh = th_dark if np.sum(th_dark) > np.sum(th_light) else th_light

            combined = cv2.bitwise_or(edges, thresh)

            k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            closed = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, k_close, iterations=1)

            cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for c in cnts:
                if cv2.contourArea(c) > 20:
                    cv2.drawContours(closed, [c], -1, 255, -1)

            stroke_est = max(2, int(min(roi.shape) * 0.03))
            k_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (stroke_est, stroke_est))
            closed = cv2.dilate(closed, k_dilate, iterations=1)

            mask[y1:y2, x1:x2] = cv2.bitwise_or(mask[y1:y2, x1:x2], closed)

        return mask

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    @staticmethod
    def apply_text(pil_img, text_blocks):
        """Pipeline: filter → inpaint → typeset."""
        valid = []
        for blk in text_blocks:
            box = blk["box"]
            bh = box[3] - box[1]
            font_est = int(blk.get("orig_line_height", bh) * 0.9)
            angle = abs(blk.get("angle", 0.0))
            words = blk.get("text", "").split()
            is_single = len(words) <= 1

            is_sfx = is_single and font_est > 50
            if is_sfx and angle > 5:
                continue
            if font_est > 120:
                continue

            valid.append(blk)

        text_blocks = valid

        img_np = np.array(pil_img.convert("RGB"))
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        inpaint_mask = Typesetter._build_inpaint_mask(img_bgr, text_blocks)

        if np.any(inpaint_mask):
            inpainted_bgr = cv2.inpaint(img_bgr, inpaint_mask, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
        else:
            inpainted_bgr = img_bgr

        inpainted_rgb = cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(inpainted_rgb)

        for blk in text_blocks:
            box = blk["box"]
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 8 or bh < 8:
                continue

            display_text = blk.get("translated_text", blk.get("text", ""))
            if not display_text.strip():
                continue

            font_path = Typesetter._select_font(blk, pil_img)
            if font_path is None:
                font_path = Typesetter._resolve_font(FONT_REGULAR)

            result = Typesetter._fit_font_size(display_text, font_path, box)
            if result is None:
                continue
            lines, total_height, font_size, font, max_line_w = result

            pad = max(15, int(font_size * 0.3))
            canvas_w = bw + pad * 2
            canvas_h = bh + pad * 2
            txt_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            txt_draw = ImageDraw.Draw(txt_canvas)

            is_sfx = len(display_text.split()) <= 1 and font_size > 40
            stroke_w = max(2, int(font_size * 0.08)) if is_sfx else max(1, int(font_size * 0.05))

            lh = Typesetter._text_height(font) + int(font_size * 0.35)
            current_y = (canvas_h - total_height) // 2

            for line in lines:
                lw = Typesetter._text_width(line, font)
                cx = (canvas_w - lw) // 2

                txt_draw.text(
                    (cx, current_y),
                    line,
                    font=font,
                    fill=blk["colors"][0],
                    stroke_width=stroke_w,
                    stroke_fill=blk["colors"][1],
                )
                current_y += lh

            # --- Rotate if angled ---
            angle = blk.get("angle", 0.0)
            if abs(angle) > 3:
                txt_canvas = txt_canvas.rotate(-angle, expand=True, resample=Image.BICUBIC)

            # --- Mirror / Flip jika teks aslinya terdeteksi cermin (hologram) ---
            if blk.get("is_mirrored", False):
                txt_canvas = txt_canvas.transpose(Image.FLIP_LEFT_RIGHT)
            elif blk.get("is_rotated", False):
                txt_canvas = txt_canvas.rotate(180, expand=True, resample=Image.BICUBIC)

            # --- Paste onto page image ---
            paste_x = box[0] + (bw - txt_canvas.width) // 2
            paste_y = box[1] + (bh - txt_canvas.height) // 2
            pil_img.paste(txt_canvas, (paste_x, paste_y), txt_canvas)

        return pil_img


# ======================================================================
# Helper utilities (download, merge, slice) – unchanged
# ======================================================================

def download_image(url, save_path, chapter_url=""):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    if "bbato" in chapter_url:
        headers["Referer"] = "https://bbato.com/"
    elif "vymanga" in chapter_url:
        headers["Referer"] = "https://vymanga.com/"

    try:
        res = requests.get(url, headers=headers, stream=True, timeout=15)
        if res.status_code == 200:
            with open(save_path, "wb") as f:
                for chunk in res.iter_content(1024):
                    if chunk:
                        f.write(chunk)
            if os.path.getsize(save_path) > 0:
                return True
            else:
                os.remove(save_path)
                return False
    except Exception:
        pass
    return False


def download_page(page, out_dir, chapter_url=""):
    idx = page["index"]
    raw_path = os.path.join(out_dir, f"raw_{idx}.jpg")
    if download_image(page["imageUrl"], raw_path, chapter_url):
        return raw_path
    return None


def process_merge_group(group_data, merge_idx, out_dir, target_width):
    current_height = 0
    images_to_paste = []
    for path, w, h in group_data:
        try:
            img = Image.open(path).convert("RGB")
            if img.width != target_width:
                new_h = int(img.height * (target_width / img.width))
                img = img.resize((target_width, new_h), Image.Resampling.LANCZOS)
            images_to_paste.append(img)
            current_height += img.height
        except Exception:
            continue

    if not images_to_paste:
        return None

    merged_img = Image.new("RGB", (target_width, current_height))
    y_offset = 0
    for im in images_to_paste:
        merged_img.paste(im, (0, y_offset))
        y_offset += im.height

    new_path = os.path.join(out_dir, f"merged_raw_{str(merge_idx).zfill(3)}.jpg")
    merged_img.save(new_path, format="JPEG", quality=95)

    for path, _, _ in group_data:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    return new_path


def merge_short_images(raw_paths, target_height=2200, max_workers=6):
    if not raw_paths:
        return []

    img_infos = []
    for path in raw_paths:
        try:
            with Image.open(path) as img:
                img_infos.append((path, img.width, img.height))
        except Exception:
            pass

    if not img_infos:
        return []

    groups = []
    current_group = []
    current_h = 0
    target_w = img_infos[0][1]

    for info in img_infos:
        path, w, h = info
        est_h = int(h * (target_w / w)) if w != target_w else h
        current_group.append(info)
        current_h += est_h
        if current_h >= target_height:
            groups.append(current_group)
            current_group = []
            current_h = 0

    if current_group:
        groups.append(current_group)

    out_dir = os.path.dirname(raw_paths[0])
    merged_paths = []

    print(f"Mengeksekusi penggabungan {len(groups)} grup gambar secara paralel...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(process_merge_group, grp, idx + 1, out_dir, target_w): idx + 1
            for idx, grp in enumerate(groups)
        }
        results = {}
        for future in concurrent.futures.as_completed(future_to_idx):
            idx = future_to_idx[future]
            res_path = future.result()
            if res_path:
                results[idx] = res_path

    for i in sorted(results.keys()):
        merged_paths.append(results[i])

    return merged_paths


def smart_slice_image(
    image_path, 
    target_height=1200, 
    out_dir="output",
    min_height=600, 
    max_height=1800,
    ocr_engine=None
):
    img = cv2.imread(image_path)
    if img is None:
        print(f"[Error] Tidak bisa membaca gambar: {image_path}")
        return [image_path]

    height, width = img.shape[:2]
    if height <= max_height:
        return [image_path]

    forbidden_rows = np.zeros(height, dtype=bool)
    if ocr_engine is not None:
        try:
            blocks = ocr_engine.detect_and_merge(image_path)
            for b in blocks:
                box = b['box']
                y1 = max(0, int(box[1]) - 25)
                y2 = min(height, int(box[3]) + 25)
                forbidden_rows[y1:y2] = True
        except Exception as e:
            print(f"[Warning] Gagal cek OCR untuk smart slice: {e}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    row_std = np.std(gray.astype(np.float32), axis=1)
    edge_density = np.sum(edges > 0, axis=1) / float(width)
    
    safe_rows = (row_std < 3.5) & (edge_density < 0.015) & (~forbidden_rows)

    sliced_paths = []
    y_start = 0
    part = 1
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    os.makedirs(out_dir, exist_ok=True)

    def find_empty_gap(start_y, end_y, gap_size=20):
        start_y = max(0, int(start_y))
        end_y = min(height, int(end_y))
        if end_y - start_y < gap_size:
            return None
            
        for y in range(end_y - gap_size, start_y, -1):
            if np.all(safe_rows[y : y + gap_size]):
                return y + (gap_size // 2)
        return None

    while y_start < height:
        if height - y_start <= max_height:
            slice_img = img[y_start:height, :]
            slice_path = os.path.join(out_dir, f"{base_name}_part{part}.jpg")
            cv2.imwrite(slice_path, slice_img)
            sliced_paths.append(slice_path)
            break

        y_target = min(y_start + target_height, height)
        found_cut = None
        gap = 25

        search_up = max(y_start + min_height, y_target - 150)
        search_down = min(y_start + max_height, y_target + 150)
        found_cut = find_empty_gap(search_up, search_down, gap)

        if not found_cut:
            found_cut = find_empty_gap(y_start + min_height, search_up, gap)

        if not found_cut:
            found_cut = find_empty_gap(search_down, min(y_start + max_height, height), gap)

        if not found_cut:
            print(f"[Warning] Area penuh di {base_name} (Y: {y_start}-{y_start+max_height}). Mencari titik potong paksa teraman...")
            force_min = min(y_start + target_height, height - 1)
            force_max = min(y_start + max_height, height)
            
            best_y = force_min
            min_score = float('inf')
            
            for y in range(force_min, force_max):
                penalty = 1000000 if forbidden_rows[y] else 0
                score = (edge_density[y] * 100) + row_std[y] + penalty
                if score < min_score:
                    min_score = score
                    best_y = y
            
            found_cut = best_y

        slice_img = img[y_start:found_cut, :]
        slice_path = os.path.join(out_dir, f"{base_name}_part{part}.jpg")
        cv2.imwrite(slice_path, slice_img)
        sliced_paths.append(slice_path)

        y_start = found_cut
        part += 1

    return sliced_paths
