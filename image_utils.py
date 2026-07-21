import os
import requests
import concurrent.futures
import numpy as np
import cv2
import re # Tambahkan untuk membersihkan teks

from PIL import Image, ImageDraw, ImageFont

class ImageProcessor:
    @staticmethod
    def detect_colors(pil_img, box):
        # 1. Crop gambar sesuai bounding box
        # Kita tambahkan sedikit padding ke dalam (shrink) agar K-means 
        # tidak terlalu banyak menangkap background luar/garis panel
        pad = 2
        crop = pil_img.crop((
            max(0, int(box[0]) + pad), 
            max(0, int(box[1]) + pad), 
            min(pil_img.width, int(box[2]) - pad), 
            min(pil_img.height, int(box[3]) - pad)
        ))
        
        img_np = np.array(crop.convert("RGB"))
        
        if img_np.size == 0 or img_np.shape[0] < 3 or img_np.shape[1] < 3:
            return (0, 0, 0), (255, 255, 255)
            
        pixels = img_np.reshape((-1, 3)).astype(np.float32)
        
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        K = 2
        
        try:
            _, labels, centers = cv2.kmeans(pixels, K, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
            centers = np.uint8(centers)
            counts = np.bincount(labels.flatten())
            
            bg_idx = np.argmax(counts)
            text_idx = 1 - bg_idx 
            
            text_color = tuple(int(c) for c in centers[text_idx])
            stroke_color = tuple(int(c) for c in centers[bg_idx])
            
            # Jika kontras terlalu rendah, paksa jadi Hitam & Putih (berdasarkan luminansi)
            lum_text = 0.299*text_color[0] + 0.587*text_color[1] + 0.114*text_color[2]
            lum_bg = 0.299*stroke_color[0] + 0.587*stroke_color[1] + 0.114*stroke_color[2]
            
            if abs(lum_text - lum_bg) < 60:
                return (0, 0, 0), (255, 255, 255) # Default aman
                
            return text_color, stroke_color
            
        except Exception:
            return (0, 0, 0), (255, 255, 255)


class Typesetter:
    @staticmethod
    def clean_text_for_rendering(text):
        # Membersihkan karakter aneh yang tidak disupport font default (mencegah artefak wajik )
        text = text.replace('…', '...')
        # Hapus spasi zero-width atau karakter unicode yang tidak standar
        text = re.sub(r'[^\x00-\x7F]+', '', text) 
        return text.strip()

    @staticmethod
    def apply_text(pil_img, text_blocks, font_path="arial.ttf"):
        # ==========================================
        # 1. FASE INPAINTING (Masking Teks & Outline)
        # ==========================================
        img_np = np.array(pil_img.convert('RGB'))
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        mask = np.zeros(img_bgr.shape[:2], dtype=np.uint8)
        
        for block in text_blocks:
            box = block['box']
            pad = 3 
            x1, y1 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
            x2, y2 = min(img_bgr.shape[1], int(box[2]) + pad), min(img_bgr.shape[0], int(box[3]) + pad)
            
            if x2 - x1 < 5 or y2 - y1 < 5: continue
            
            roi_gray = gray[y1:y2, x1:x2]
            
            # --- IMPLEMENTASI MASKING OPTIMAL ---
            
            # 1. Canny Edge untuk menangkap outline tegas huruf
            edges = cv2.Canny(roi_gray, 30, 120) 
            
            # 2. Global Threshold + Otsu (Otsu akan mencari batas ideal secara dinamis,
            # sehingga aman dari efek glow yang biasanya mengecoh Adaptive Threshold)
            _, thresh = cv2.threshold(roi_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            
            # 3. Gabungkan agar isi huruf dan garis terluarnya masuk
            combined_mask = cv2.bitwise_or(edges, thresh)
            
            # 4. Tutup rongga dengan kernel Ellipse agar lekukan huruf tetap natural
            kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            closed = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel_close)
            
            # 5. Dilasi halus dengan kernel Ellipse 2x2 (tidak seagresif kotak 3x3)
            kernel_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
            dilated = cv2.dilate(closed, kernel_dilate, iterations=1)
            
            # 6. Filter kontur berdasarkan luas area untuk membuang noise (glow/screentone)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            clean_mask = np.zeros_like(dilated)
            
            for cnt in contours:
                area = cv2.contourArea(cnt)
                # Abaikan kotoran atau sisa efek background yang luasnya < 20 piksel
                if area < 20: 
                    continue
                # Gambar kontur (huruf) yang valid saja
                cv2.drawContours(clean_mask, [cnt], -1, 255, -1)
            
            # 7. Tambahkan hasil filter bersih ke mask utama
            mask[y1:y2, x1:x2] = cv2.bitwise_or(mask[y1:y2, x1:x2], clean_mask)
            
        # 8. Radius inpaint diturunkan ke 2 untuk mencegah blurring berlebih pada background di sekitarnya
        inpainted_bgr = cv2.inpaint(img_bgr, mask, inpaintRadius=2, flags=cv2.INPAINT_TELEA)
        
        inpainted_rgb = cv2.cvtColor(inpainted_bgr, cv2.COLOR_BGR2RGB)
        pil_img = Image.fromarray(inpainted_rgb)

        # ==========================================
        # 2. FASE TYPESETTING (Menempel Teks Baru)
        # ==========================================
        for block in text_blocks:
            box = block['box']
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 6 or bh < 6: continue
            
            raw_text = block.get('translated_text', block['text'])
            display_text = Typesetter.clean_text_for_rendering(raw_text)
            
            words = display_text.upper().split()
            if not words: continue
            
            is_single_word = len(words) <= 1
            
            max_font_limit = 120 
            font_size = int(block.get('orig_line_height', bh) * 0.85) 
            font_size = max(10, min(max_font_limit, font_size)) 
            
            while font_size > 8:
                font = ImageFont.truetype(font_path, font_size) if os.path.exists(font_path) else ImageFont.load_default()
                lines, current_line = [], []
                
                def get_tw(text):
                    bb = font.getbbox(text)
                    return bb[2] - bb[0] if bb else 0
                
                for word in words:
                    word_width = get_tw(word)
                    
                    if word_width > bw * 0.90:
                        if current_line:
                            lines.append(' '.join(current_line))
                            current_line = []
                            
                        temp_word = word
                        while temp_word:
                            for i in range(len(temp_word), 0, -1):
                                suffix = "-" if i < len(temp_word) else ""
                                part = temp_word[:i] + suffix
                                
                                if get_tw(part) <= bw * 0.90 or i == 1:
                                    if i == len(temp_word):
                                        current_line = [part]
                                    else:
                                        lines.append(part)
                                    temp_word = temp_word[i:]
                                    break
                    else:
                        test_line = ' '.join(current_line + [word]) if current_line else word
                        if get_tw(test_line) <= bw * 0.90:
                            current_line.append(word)
                        else:
                            if current_line:
                                lines.append(' '.join(current_line))
                            current_line = [word]
                            
                if current_line: 
                    lines.append(' '.join(current_line))
                
                bbox = font.getbbox("Ay")
                line_height = (bbox[3] - bbox[1]) + int(font_size * 0.2)
                total_height = len(lines) * line_height
                
                if total_height <= bh * 0.95:
                    break
                font_size -= 1

            orig_bw = box[2] - box[0]
            txt_canvas = Image.new('RGBA', (orig_bw, bh), (0, 0, 0, 0))
            txt_draw = ImageDraw.Draw(txt_canvas)
            
            current_y = (bh - total_height) // 2
            
            # Kalkulasi Stroke yang proporsional 
            stroke_w = 2 if is_single_word else max(1, int(font_size * 0.03))
            if font_size < 14: stroke_w = 0 
            
            for line in lines:
                cw = font.getbbox(line)[2] - font.getbbox(line)[0]
                cx = (orig_bw - cw) // 2
                
                fill_color = block['colors'][0] if 'colors' in block else (0,0,0)
                stroke_color = block['colors'][1] if 'colors' in block else (255,255,255)
                
                txt_draw.text(
                    (cx, current_y), 
                    line, 
                    font=font, 
                    fill=fill_color, 
                    stroke_width=stroke_w, 
                    stroke_fill=stroke_color
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
        
    merged_img = Image.new('RGB', (target_width, current_height))
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
    if not raw_paths: return []
    
    img_infos = []
    for path in raw_paths:
        try:
            with Image.open(path) as img:
                img_infos.append((path, img.width, img.height))
        except Exception:
            pass
            
    if not img_infos: return []
    
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
            executor.submit(process_merge_group, grp, idx+1, out_dir, target_w): idx+1
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

def smart_slice_image(image_path, target_height=1200, out_dir="output"):
    """
    Memotong gambar dengan Edge Detection.
    Mampu mengenali background berpola/screentone dengan mencari
    area yang minim garis tegas (minim teks/border panel).
    """
    import cv2
    import numpy as np
    import os

    img = cv2.imread(image_path)
    if img is None:
        print(f"[Error] Tidak bisa membaca gambar {image_path}")
        return [image_path]

    height, width = img.shape[:2]
    
    if height <= target_height:
        return [image_path]

    # 1. Ubah ke Grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 2. Blur yang cukup kuat untuk menghancurkan pola background/screentone tipis
    blurred = cv2.GaussianBlur(gray, (15, 15), 0)
    
    # 3. Deteksi Tepi (Canny) - hanya menangkap garis-garis yang sangat kontras
    edges = cv2.Canny(blurred, 30, 100)
    
    # 4. Hitung kepadatan garis tepi per baris (edges bernilai 255 untuk garis)
    # Kita bagi 255 agar nilainya jadi jumlah piksel (0, 1, 2, dst)
    row_edge_count = np.sum(edges, axis=1) / 255.0
    
    # 5. Baris aman adalah baris yang jumlah piksel garisnya sangat sedikit
    # Toleransi: maksimal 2% dari lebar gambar boleh ada garis (mengabaikan noise/sisa background)
    tolerance = width * 0.02
    safe_rows = row_edge_count <= tolerance
    
    sliced_paths = []
    y_start = 0
    part = 1
    
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    os.makedirs(out_dir, exist_ok=True)

    while y_start < height:
        y_end = y_start + target_height
        
        if y_end >= height:
            y_end = height
        else:
            search_limit_up = max(y_start + int(target_height * 0.3), 0)
            search_limit_down = min(y_start + int(target_height * 1.5), height)
            
            found_safe_cut = False
            
            # Cari celah aman ke ATAS (butuh gap 15 piksel)
            for y_candidate in range(y_end, search_limit_up, -1):
                if y_candidate - 15 > 0 and np.all(safe_rows[y_candidate-15 : y_candidate]):
                    y_end = y_candidate - 7
                    found_safe_cut = True
                    break
            
            # Coba cari ke BAWAH kalau di atas terlalu padat teks/panel
            if not found_safe_cut:
                for y_candidate in range(y_end, search_limit_down):
                    if y_candidate + 15 < height and np.all(safe_rows[y_candidate : y_candidate+15]):
                        y_end = y_candidate + 7
                        found_safe_cut = True
                        break
            
            if not found_safe_cut:
                print(f"[Warning] Area terlalu padat di {base_name}. Potong paksa di Y:{y_end}.")
        
        slice_img = img[y_start:y_end, :]
        slice_path = os.path.join(out_dir, f"{base_name}_part{part}.jpg")
        cv2.imwrite(slice_path, slice_img)
        sliced_paths.append(slice_path)
        
        y_start = y_end
        part += 1
        
    return sliced_paths
