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


# ======================================================================
# GANTI KESELURUHAN CLASS Typesetter DI image_utils.py DENGAN INI
# ======================================================================

class Typesetter:
    # ------------------------------------------------------------------
    # Font helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_font(font_name):
        path = os.path.join(FONT_DIR, font_name)
        return path if os.path.exists(path) else None

    @staticmethod
    def _is_italic_slant(pil_img, box):
        """
        Mendeteksi apakah huruf di dalam bounding box miring ke kanan (Italic/Slant)
        dengan menganalisis pergeseran pusat massa piksel dari baris atas ke baris bawah.
        """
        try:
            crop = pil_img.crop((
                max(0, int(box[0])),
                max(0, int(box[1])),
                min(pil_img.width, int(box[2])),
                min(pil_img.height, int(box[3]))
            ))
            img_np = np.array(crop.convert("L"))
            if img_np.size == 0 or img_np.shape[0] < 10 or img_np.shape[1] < 10:
                return False

            _, binary = cv2.threshold(img_np, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            if np.sum(binary == 255) > np.sum(binary == 0):
                binary = cv2.bitwise_not(binary)

            h, w = binary.shape
            # Ambil bagian 25% atas dan 25% bawah dari teks
            top_part = binary[0 : int(h * 0.25), :]
            bottom_part = binary[int(h * 0.75) : h, :]

            # Hitung pusat massa (center of mass) horizontal (sumbu X)
            top_coords = np.where(top_part > 0)[1]
            bottom_coords = np.where(bottom_part > 0)[1]

            if len(top_coords) == 0 or len(bottom_coords) == 0:
                return False

            top_mean = np.mean(top_coords)
            bottom_mean = np.mean(bottom_coords)

            # Pada font Italic, bagian atas huruf bergeser lebih ke kanan dibanding bagian bawah
            # Rasio pergeseran > 4% dari lebar box menandakan teks tersebut Italic
            slant_ratio = (top_mean - bottom_mean) / max(1, w)
            return slant_ratio > 0.04
        except Exception:
            return False

    @staticmethod
    def _estimate_stroke_weight(pil_img, box):
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
            return avg_stroke_thickness / max(1, box_height)
        except Exception:
            return 0.08

    @staticmethod
    def _select_font(block, pil_img=None):
        text = block.get("text", "")
        box = block["box"]
        bh = box[3] - box[1]
        font_size_est = int(block.get("orig_line_height", bh) * 0.9)
        words = text.split()
        is_single = len(words) <= 1

        # 1. Cek SFX / Kata tunggal berukuran besar
        if is_single and font_size_est > 45:
            for name in FONT_SFX:
                path = Typesetter._resolve_font(name)
                if path:
                    return path

        # 2. CEK ITALIC TERLEBIH DAHULU (Kemiringan kotak > 6 derajat ATAU bentuk huruf miring)
        angle = abs(block.get("angle", 0.0))
        is_italic = angle > 6.0
        if not is_italic and pil_img is not None:
            is_italic = Typesetter._is_italic_slant(pil_img, box)

        if is_italic:
            if is_single and font_size_est > 35:
                for name in FONT_SFX:
                    path = Typesetter._resolve_font(name)
                    if path:
                        return path
            for name in FONT_ITALIC:
                path = Typesetter._resolve_font(name)
                if path:
                    return path

        # 3. CEK BOLD (Threshold dinaikkan ke >= 0.17 agar tidak mudah terpicu teks biasa)
        is_bold_weight = False
        if pil_img is not None:
            stroke_weight = Typesetter._estimate_stroke_weight(pil_img, box)
            if stroke_weight >= 0.17:
                is_bold_weight = True

        has_exclamation = "!" in text
        if is_bold_weight or (has_exclamation and font_size_est > 38):
            for name in FONT_BOLD:
                path = Typesetter._resolve_font(name)
                if path:
                    return path

        # 4. Fallback ke Regular
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

    # ------------------------------------------------------------------
    # PERBAIKAN 1: Word-Wrapping dengan Pemenggalan Kata (Hyphenation '-')
    # ------------------------------------------------------------------
    @staticmethod
    def _wrap_text_with_hyphens(words, font, max_width):
        """
        Membungkus teks berdasarkan batas lebar nyata (max_width).
        Jika ada kata yang melampaui lebar kotak, kata tersebut PAKSA dipenggal
        menggunakan tanda hubung '-' agar font tidak perlu dikecilkan.
        """
        if not words:
            return []

        lines = []
        cur_line = []

        for w in words:
            # Uji coba kalau kata dimasukkan ke baris saat ini
            test_line = " ".join(cur_line + [w]) if cur_line else w
            
            if Typesetter._text_width(test_line, font) <= max_width:
                cur_line.append(w)
            else:
                # Jika baris sudah terisi kata lain, simpan dulu baris tersebut
                if cur_line:
                    lines.append(" ".join(cur_line))
                    cur_line = []

                # Cek apakah 1 kata 'w' ini sendiri lebih lebar dari kotak dialog (max_width)
                if Typesetter._text_width(w, font) > max_width:
                    # POTONG KATA PER KARAKTER DENGAN TANDA '-'
                    part_word = ""
                    for char in w:
                        test_part = part_word + char + "-"
                        if Typesetter._text_width(test_part, font) <= max_width:
                            part_word += char
                        else:
                            if part_word:
                                lines.append(part_word + "-")
                                part_word = char
                            else:
                                part_word = char
                    if part_word:
                        cur_line = [part_word]
                else:
                    cur_line = [w]

        if cur_line:
            lines.append(" ".join(cur_line))
            
        return lines

    @staticmethod
    def _fit_font_size(text, font_path, box, max_font=140, min_font=12):
        """
        Mendeteksi dan menyesuaikan ukuran font secara akurat berdasarkan
        kapasitas panjang (lebar) dan tinggi bounding box teks.
        """
        bw = max(10, box[2] - box[0])
        bh = max(10, box[3] - box[1])

        words = text.split()
        if not words:
            return None, 0, min_font, ImageFont.load_default(), 0

        # Gunakan 90% dari lebar & tinggi box sebagai ruang kerja aman (padding internal)
        target_w = int(bw * 0.90)
        target_h = int(bh * 0.90)

        best_result = None
        
        # Mulai pencarian dari font kecil sampai batas ideal tinggi kotak
        lo = min_font
        hi = min(max_font, int(bh * 0.85))

        while lo <= hi:
            mid = (lo + hi) // 2
            try:
                font = ImageFont.truetype(font_path, mid) if font_path and os.path.exists(font_path) else ImageFont.load_default()
            except Exception:
                font = ImageFont.load_default()

            # 1. Bungkus & potong kata menggunakan tanda '-' berdasarkan target_w
            lines = Typesetter._wrap_text_with_hyphens(words, font, target_w)
            if not lines:
                hi = mid - 1
                continue

            # 2. Hitung total tinggi yang dibutuhkan (termasuk jarak antar baris / line spacing)
            line_spacing = int(mid * 0.25)
            single_line_h = Typesetter._text_height(font)
            total_h = (len(lines) * single_line_h) + ((len(lines) - 1) * line_spacing)
            
            # 3. Hitung lebar baris terpanjang
            max_lw = max(Typesetter._text_width(l, font) for l in lines)

            # 4. Evaluasi: Apakah teks muat di dalam target_w DAN target_h?
            if max_lw <= target_w and total_h <= target_h:
                # Muat! Simpan sebagai kandidat terbaik, lalu coba perbesar font-nya lagi
                best_result = (lines, total_h, mid, font, max_lw)
                lo = mid + 1
            else:
                # Tidak muat (kebanyakan baris/terlalu tinggi), kecilkan font-nya
                hi = mid - 1

        if best_result is not None:
            return best_result

        # Fallback darurat jika kotak terlalu kecil: gunakan ukuran font minimum (min_font)
        try:
            font = ImageFont.truetype(font_path, min_font) if font_path and os.path.exists(font_path) else ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
            
        lines = Typesetter._wrap_text_with_hyphens(words, font, target_w)
        single_line_h = Typesetter._text_height(font)
        line_spacing = int(min_font * 0.25)
        total_h = (len(lines) * single_line_h) + (max(0, len(lines) - 1) * line_spacing)
        max_lw = max((Typesetter._text_width(l, font) for l in lines), default=0)
        
        return lines, total_h, min_font, font, max_lw

    # ------------------------------------------------------------------
    # PERBAIKAN 2: Inpaint Mask Lebih Bersih Menghapus Bekas Garis/Shadow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_inpaint_mask(img_bgr, text_blocks):
        """
        Menghapus huruf beserta stroke/drop-shadow-nya sampai bersih sempurna
        menggunakan Canny Edge dan penambalan kontur tanpa merusak tepi luar balon kata.
        """
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        mask = np.zeros(img_bgr.shape[:2], dtype=np.uint8)

        for block in text_blocks:
            box = block["box"]
            pad = 5
            x1, y1 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
            x2, y2 = min(img_bgr.shape[1], int(box[2]) + pad), min(img_bgr.shape[0], int(box[3]) + pad)

            if (x2 - x1) < 5 or (y2 - y1) < 5:
                continue

            roi_gray = gray[y1:y2, x1:x2]

            # 1. Cari garis tegas (huruf) menggunakan Canny Edge Detection
            edges = cv2.Canny(roi_gray, 50, 150)

            # 2. Tebalkan garis tersebut agar outline (stroke) putih/shadow ikut tertutup
            kernel = np.ones((5, 5), np.uint8)
            dilated = cv2.dilate(edges, kernel, iterations=2)

            # 3. Isi lubang di dalam huruf (seperti bagian dalam huruf O, A, P, D, dll)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(dilated, contours, -1, 255, -1)

            # Tempelkan bentuk persis hurufnya ke mask utama
            mask[y1:y2, x1:x2] = cv2.bitwise_or(mask[y1:y2, x1:x2], dilated)

        return mask

    @staticmethod
    def apply_text(pil_img, text_blocks):
        """Pipeline: filter -> inpaint -> typeset."""
        valid = []
        for blk in text_blocks:
            box = blk["box"]
            bh = box[3] - box[1]
            font_est = int(blk.get("orig_line_height", bh) * 0.9)
            angle = abs(blk.get("angle", 0.0))
            words = blk.get("text", "").split()
            is_single = len(words) <= 1

            if (is_single and font_est > 60 and angle > 5) or font_est > 130:
                continue
            valid.append(blk)

        text_blocks = valid

        # --- INPAINTING (DIPERBAIKI) ---
        img_np = np.array(pil_img.convert("RGB"))
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        inpaint_mask = Typesetter._build_inpaint_mask(img_bgr, text_blocks)

        if np.any(inpaint_mask):
            # Menggunakan INPAINT_NS dengan radius 4 px agar sapuan penambalan mulus
            inpainted_bgr = cv2.inpaint(img_bgr, inpaint_mask, inpaintRadius=4, flags=cv2.INPAINT_NS)
        else:
            inpainted_bgr = img_bgr

        inpainted_rgb = cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(inpainted_rgb)

        # --- TYPESETTING ---
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

            pad = max(10, int(font_size * 0.2))
            canvas_w = bw + pad * 2
            canvas_h = bh + pad * 2
            txt_canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            txt_draw = ImageDraw.Draw(txt_canvas)

            is_sfx = len(display_text.split()) <= 1 and font_size > 40
            stroke_w = max(2, int(font_size * 0.08)) if is_sfx else max(1, int(font_size * 0.05))

            lh = Typesetter._text_height(font)
            line_spacing = int(font_size * 0.25)
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
                current_y += lh + line_spacing

            angle = blk.get("angle", 0.0)
            if abs(angle) > 3:
                txt_canvas = txt_canvas.rotate(-angle, expand=True, resample=Image.BICUBIC)

            paste_x = box[0] + (bw - txt_canvas.width) // 2
            paste_y = box[1] + (bh - txt_canvas.height) // 2
            pil_img.paste(txt_canvas, (paste_x, paste_y), txt_canvas)

        return pil_img
# ======================================================================
# Helper utilities (download, merge, slice) – kept largely unchanged
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
    """
    Memotong gambar manhwa panjang secara cerdas tanpa memotong balon percakapan.
    
    Alur pencarian area potong:
    1. Cari area kosong (gutter) di sekitar target_height.
    2. Jika tidak ada, cari ke atas (perkecil sampai min_height).
    3. Jika tidak ada, cari ke bawah (perbesar maksimal sampai max_height).
    4. Jika tetap tidak ada, potong paksa di titik paling aman (0% risiko memotong teks dari OCR/skor terendah).
    """
    img = cv2.imread(image_path)
    if img is None:
        print(f"[Error] Tidak bisa membaca gambar: {image_path}")
        return [image_path]

    height, width = img.shape[:2]
    if height <= max_height:
        return [image_path]

    # --- 0. CEK ZONA LARANGAN POTONG DARI OCR (OPTIONAL TAPI SANGAT AKURAT) ---
    forbidden_rows = np.zeros(height, dtype=bool)
    if ocr_engine is not None:
        try:
            blocks = ocr_engine.detect_and_merge(image_path)
            for b in blocks:
                box = b['box']
                # Beri margin pengaman 25px di atas dan di bawah kotak teks/balon
                y1 = max(0, int(box[1]) - 25)
                y2 = min(height, int(box[3]) + 25)
                forbidden_rows[y1:y2] = True
        except Exception as e:
            print(f"[Warning] Gagal cek OCR untuk smart slice: {e}")

    # --- 1. PEMETAAN AKTIVITAS VISUAL ---
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    row_std = np.std(gray.astype(np.float32), axis=1)
    edge_density = np.sum(edges > 0, axis=1) / float(width)
    
    # Baris aman: variasi warna rendah, minim garis, DAN TIDAK MENABRAK TEKS OCR
    safe_rows = (row_std < 3.5) & (edge_density < 0.015) & (~forbidden_rows)

    sliced_paths = []
    y_start = 0
    part = 1
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    os.makedirs(out_dir, exist_ok=True)

    def find_empty_gap(start_y, end_y, gap_size=20):
        """Mencari blok baris kosong berturut-turut setinggi gap_size."""
        start_y = max(0, int(start_y))
        end_y = min(height, int(end_y))
        if end_y - start_y < gap_size:
            return None
            
        for y in range(end_y - gap_size, start_y, -1):
            if np.all(safe_rows[y : y + gap_size]):
                return y + (gap_size // 2)  # Potong di tengah-tengah gap
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
        gap = 25  # Butuh minimal 25px area kosong berturut-turut agar aman

        # --- LANGKAH 1: Cari di sekitar target_height (+/- 150px) ---
        search_up = max(y_start + min_height, y_target - 150)
        search_down = min(y_start + max_height, y_target + 150)
        found_cut = find_empty_gap(search_up, search_down, gap)

        # --- LANGKAH 2: Jika tidak ketemu, PERKECIL (cari ke atas sampai min_height) ---
        if not found_cut:
            found_cut = find_empty_gap(y_start + min_height, search_up, gap)

        # --- LANGKAH 3: Jika tidak ketemu, PERBESAR (cari ke bawah sampai max_height: 1800) ---
        if not found_cut:
            found_cut = find_empty_gap(search_down, min(y_start + max_height, height), gap)

        # --- LANGKAH 4: POTONG PAKSA DI AREA PALING AMAN (Bukan Balon Teks/Teks) ---
        if not found_cut:
            print(f"[Warning] Area penuh di {base_name} (Y: {y_start}-{y_start+max_height}). Mencari titik potong paksa teraman...")
            force_min = min(y_start + target_height, height - 1)
            force_max = min(y_start + max_height, height)
            
            best_y = force_min
            min_score = float('inf')
            
            for y in range(force_min, force_max):
                # Beri penalti skor sangat besar (1,000,000) jika baris tersebut menabrak teks OCR
                penalty = 1000000 if forbidden_rows[y] else 0
                score = (edge_density[y] * 100) + row_std[y] + penalty
                if score < min_score:
                    min_score = score
                    best_y = y
            
            found_cut = best_y

        # Simpan potongan
        slice_img = img[y_start:found_cut, :]
        slice_path = os.path.join(out_dir, f"{base_name}_part{part}.jpg")
        cv2.imwrite(slice_path, slice_img)
        sliced_paths.append(slice_path)

        # Lanjut ke potongan berikutnya
        y_start = found_cut
        part += 1

    return sliced_paths
