# image_utils.py
import os
import requests
import concurrent.futures
import numpy as np
import cv2 # Tambahkan ini di deretan import atas
import typeset_rs # Modul Rust untuk clustering / layout / deteksi warna

from PIL import Image, ImageDraw, ImageFont

class ImageProcessor:
    @staticmethod
    def detect_colors(pil_img, box):
        # 1. Crop gambar sesuai bounding box (kotak teks)
        crop = pil_img.crop((
            max(0, int(box[0])), 
            max(0, int(box[1])), 
            min(pil_img.width, int(box[2])), 
            min(pil_img.height, int(box[3]))
        ))
        
        # 2. Ubah ke numpy array RGB
        img_np = np.array(crop.convert("RGB"))
        
        # Keamanan: Jika crop gagal atau terlalu kecil, pakai warna default hitam-putih
        if img_np.size == 0 or img_np.shape[0] < 3 or img_np.shape[1] < 3:
            return (0, 0, 0), (255, 255, 255)

        # --- MULAI INTEGRASI RUST ---
        # Deteksi warna teks & background/stroke via K-Means (K=2) murni di Rust
        # (menggantikan cv2.kmeans milik OpenCV). Teks = klaster minoritas,
        # stroke/background = klaster mayoritas. Jika kontras terlalu kecil,
        # Rust mengembalikan hitam-putih sebagai fallback aman.
        try:
            text_color, stroke_color = typeset_rs.detect_colors(img_np)
            return tuple(text_color), tuple(stroke_color)
        except Exception as e:
            # Fallback jika perhitungan gagal
            return (0, 0, 0), (255, 255, 255)
        # --- AKHIR INTEGRASI RUST ---


class Typesetter:
    @staticmethod
    def apply_text(pil_img, text_blocks, fonts_dict=None):
        if fonts_dict is None:
            # Fallback aman jika tidak ada font
            fonts_dict = {'normal': 'arial.ttf', 'bold': 'arial.ttf', 'italic': 'arial.ttf', 'sfx': 'arial.ttf'}

        
        # ==========================================
        # 0. FASE FILTERING (Menyaring Teks)
        # ==========================================
        valid_blocks = []
        for block in text_blocks:
            box = block['box']
            bh = box[3] - box[1]
            
            # Ambil teks asli untuk mengecek apakah ini 1 kata
            original_text = block.get('text', '')
            words = original_text.split()
            
            # Hitung estimasi ukuran font dan kemiringan
            font_size_est = int(block.get('orig_line_height', bh) * 0.9)
            angle = block.get('angle', 0.0)
            
            is_single_word = len(words) <= 1
            is_sfx = is_single_word and font_size_est > 50
            
            # Syarat 1: SFX (1 kata) yang miring dibiarkan aslinya
            # Angka 5 adalah batas toleransi kemiringan (derajat). Bisa kamu sesuaikan.
            if is_sfx and abs(angle) > 5:
                continue 
                
            # Syarat 2: Teks dengan ukuran raksasa dibiarkan aslinya
            # Angka 120 adalah batas ukuran font. Jika lebih dari 120px, skip.
            if font_size_est > 120:
                continue
                
            # Jika lolos syarat, masukkan ke daftar blok yang akan diproses
            valid_blocks.append(block)
            
        # Timpa text_blocks lama dengan yang sudah difilter
        text_blocks = valid_blocks

        # ==========================================
        # 1. FASE INPAINTING (Masking Teks via Canny Edge)
        # ==========================================
        img_np = np.array(pil_img.convert('RGB'))
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        mask = np.zeros(img_bgr.shape[:2], dtype=np.uint8)
        
        for block in text_blocks:
            box = block['box']
            pad = 5
            x1, y1 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
            x2, y2 = min(img_bgr.shape[1], int(box[2]) + pad), min(img_bgr.shape[0], int(box[3]) + pad)
            
            if x2 - x1 < 5 or y2 - y1 < 5: continue
            
            roi_gray = gray[y1:y2, x1:x2]
            
            # 1. Cari garis tegas (huruf). Gradasi halus otomatis diabaikan!
            edges = cv2.Canny(roi_gray, 50, 150)
            
            # 2. Tebalkan garis tersebut agar outline (stroke) putih khas komik ikut tertutup
            kernel = np.ones((5,5), np.uint8)
            dilated = cv2.dilate(edges, kernel, iterations=2)
            
            # 3. Isi lubang di dalam huruf (seperti bagian dalam huruf O, A, P, dll)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cv2.drawContours(dilated, contours, -1, 255, -1)
            
            # Tempelkan bentuk persis hurufnya ke mask utama
            mask[y1:y2, x1:x2] = cv2.bitwise_or(mask[y1:y2, x1:x2], dilated)
            
        # Eksekusi Inpainting (hanya akan menambal jalur huruf, background aman)
        inpainted_bgr = cv2.inpaint(img_bgr, mask, inpaintRadius=4, flags=cv2.INPAINT_NS)
        
        inpainted_rgb = cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(inpainted_rgb)

        # ==========================================
        # 2. FASE TYPESETTING (Menempel Teks Baru)
        # ==========================================
        for block in text_blocks:
            box = block['box']
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 6 or bh < 6: continue
            
            display_text = block.get('translated_text', block['text'])
            words = display_text.upper().split()
            is_single_word = len(words) <= 1
            
            max_font_limit = 150

            # --- MULAI INTEGRASI RUST ---
            # Estimasi ukuran font ideal dari Rust: memperhitungkan panjang
            # teks, jumlah kata, lebar/tinggi balon, serta rasio lebar karakter
            # dan tinggi baris, sehingga teks tidak meluap keluar batas aman.
            font_size = int(typeset_rs.estimate_font_size(
                len(display_text),
                len(words),
                bw,
                bh,
                base_font_size=block.get('orig_line_height', bh) * 0.9,
                max_font_size=max_font_limit,
                min_font_size=10,
            ))
            # --- AKHIR INTEGRASI RUST ---
            font_size = max(10, min(max_font_limit, font_size)) 

            is_sfx = is_single_word and font_size > 50
            
            # --- MULAI: Logika Pemilihan Font ---
            is_italic = block.get('is_italic', False)
            is_bold = block.get('is_bold', False)
            is_system = block.get('is_system', False) # Flag opsional untuk UI/System text

            if is_sfx:
                active_font_path = fonts_dict['sfx']
            elif is_system:
                active_font_path = fonts_dict['sistem_bold'] if is_bold else fonts_dict['sistem']
            elif is_bold and is_italic:
                active_font_path = fonts_dict['bold_italic']
            elif is_bold:
                active_font_path = fonts_dict['bold']
            elif is_italic:
                active_font_path = fonts_dict['italic']
            else:
                active_font_path = fonts_dict['normal']
                
            # Keamanan: Jika font yang dipilih ternyata file-nya tidak ada di folder, balik ke normal
            if not os.path.exists(active_font_path):
                active_font_path = fonts_dict['normal']
            # --- AKHIR ---

            total_height = 0

            line_height = 0
            lines = []
            
            while font_size > 8:
                font = ImageFont.truetype(active_font_path, font_size) if os.path.exists(active_font_path) else ImageFont.load_default()
                lines, current_line = [], []
                
                def get_tw(text):
                    bb = font.getbbox(text)
                    return bb[2] - bb[0] if bb else 0
                
                if is_single_word:
                    stroke_w = max(2, int(font_size * 0.08))
                    
                    word_width = get_tw(words[0]) + (stroke_w * 2) 
                    line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + int(font_size * 0.45)
                    total_needed_h = line_height + (stroke_w * 2)
                    
                    if word_width <= (bw * 1.5) and total_needed_h <= (bh * 1.2):

                        lines = [words[0]]
                        total_height = line_height
                        break  
                    else:
                        font_size -= 2 
                        continue
                
                for word in words:
                    word_width = get_tw(word)
                    
                    if word_width > bw * 0.95:
                        if current_line:
                            lines.append(' '.join(current_line))
                            current_line = []
                            
                        temp_word = word
                        while temp_word:
                            for i in range(len(temp_word), 0, -1):
                                suffix = "-" if i < len(temp_word) else ""
                                part = temp_word[:i] + suffix
                                
                                if get_tw(part) <= bw * 0.95 or i == 1:
                                    if i == len(temp_word):
                                        current_line = [part]
                                    else:
                                        lines.append(part)
                                    temp_word = temp_word[i:]
                                    break
                    else:
                        test_line = ' '.join(current_line + [word]) if current_line else word
                        if get_tw(test_line) <= bw * 0.95:
                            current_line.append(word)
                        else:
                            if current_line:
                                lines.append(' '.join(current_line))
                            current_line = [word]
                            
                if current_line: 
                    lines.append(' '.join(current_line))
                
                line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + int(font_size * 0.45)
                total_height = len(lines) * line_height
                
                if total_height <= bh * 0.95:
                    break
                font_size -= 1

            orig_bw = box[2] - box[0]

            # --- MULAI INTEGRASI RUST ---
            # Margin aman (safe padding) dari Rust agar teks + stroke outline
            # tetap berada di dalam batas aman balon percakapan.
            pad_l, pad_r, pad_t, pad_b = typeset_rs.safe_padding(
                font_size, min_padding=15.0, padding_ratio=0.3
            )
            pad_canvas = int(max(pad_l, pad_r, pad_t, pad_b))
            # --- AKHIR INTEGRASI RUST ---

            canvas_w = orig_bw + (pad_canvas * 2)
            canvas_h = bh + (pad_canvas * 2)
            
            txt_canvas = Image.new('RGBA', (canvas_w, canvas_h), (0, 0, 0, 0))
            txt_draw = ImageDraw.Draw(txt_canvas)
            
            current_y = (canvas_h - total_height) // 2
            
            for line in lines:
                cw = font.getbbox(line)[2] - font.getbbox(line)[0]
                cx = (canvas_w - cw) // 2
                
                stroke_w = max(2, int(font_size * 0.08)) if is_single_word else max(1, int(font_size * 0.05))
                
                txt_draw.text(
                    (cx, current_y), 
                    line, 
                    font=font, 
                    fill=block['colors'][0], 
                    stroke_width=stroke_w, 
                    stroke_fill=block['colors'][1]
                )
                current_y += line_height
            
            angle = block.get('angle', 0.0)
            if abs(angle) > 3: 
                txt_canvas = txt_canvas.rotate(-angle, expand=True, resample=Image.BICUBIC)
            
            paste_x = box[0] + (orig_bw - txt_canvas.width) // 2
            paste_y = box[1] + (bh - txt_canvas.height) // 2
            
            pil_img.paste(txt_canvas, (paste_x, paste_y), txt_canvas)
                
        return pil_img

def download_image(url, save_path, chapter_url=""):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
    
    if "bbato" in chapter_url:
        headers['Referer'] = "https://bbato.com/"
    elif "vymanga" in chapter_url:
        headers['Referer'] = "https://vymanga.com/"

    try:
        res = requests.get(url, headers=headers, stream=True, timeout=15)
        if res.status_code == 200:
            with open(save_path, 'wb') as f:
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
    idx = page['index']
    raw_path = os.path.join(out_dir, f"raw_{idx}.jpg")
    
    if download_image(page['imageUrl'], raw_path, chapter_url):
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

        # --- KODE BARU: Pastikan hasil potong tidak 0 piksel ---
        if found_cut <= y_start:
            print(f"[Warning] Perhitungan potong paksa gagal, memaksa potong di ukuran target.")
            found_cut = min(y_start + target_height, height)
        # --------------------------------------------------------

        # Simpan potongan
        slice_img = img[y_start:found_cut, :]
        slice_path = os.path.join(out_dir, f"{base_name}_part{part}.jpg")
        cv2.imwrite(slice_path, slice_img)
        sliced_paths.append(slice_path)

        # Lanjut ke potongan berikutnya
        y_start = found_cut
        part += 1

    return sliced_paths
