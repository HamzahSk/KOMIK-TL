# image_utils.py
import os
import requests
import concurrent.futures
import numpy as np
import cv2 # Tambahkan ini di deretan import atas

from PIL import Image, ImageDraw, ImageFont

class ImageProcessor:
    @staticmethod
    def detect_colors(pil_img, box):
        crop = pil_img.crop((max(0, box[0]), max(0, box[1]), min(pil_img.width, box[2]), min(pil_img.height, box[3])))
        gray_crop = crop.convert("L")
        
        if not gray_crop.getbbox(): 
            return (0, 0, 0), (255, 255, 255)
            
        if np.mean(np.array(gray_crop)) > 127: 
            return (0, 0, 0), (255, 255, 255)
        return (255, 255, 255), (0, 0, 0)

class Typesetter:
    @staticmethod
    def apply_text(pil_img, text_blocks, font_path="arial.ttf"):
        # Layer putih untuk latar belakang teks agar tidak bertabrakan dengan gambar asli
        overlay = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        for block in text_blocks:
            box = block['box']
            display_text = block.get('translated_text', block['text'])
            
            # Jangan hapus background jika kata tunggal (biasanya SFX) atau jika kemiringannya ekstrem
            angle = block.get('angle', 0.0)
            if len(display_text.split()) > 1 and abs(angle) < 15:
                draw_overlay.rounded_rectangle(box, radius=6, fill=(255, 255, 255, 240))
            
        pil_img = Image.alpha_composite(pil_img.convert('RGBA'), overlay).convert('RGB')
        
        for block in text_blocks:
            box = block['box']
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 6 or bh < 6: continue
            
            display_text = block.get('translated_text', block['text'])
            words = display_text.upper().split()
            is_single_word = len(words) <= 1
            
            max_font_limit = 100
            if is_single_word:
                aspect_ratio = bw / max(1, bh)
                if aspect_ratio > 1.5:
                    bw = int(bw * 0.6) 
                    max_font_limit = min(40, int(bh * 0.7))
            
            font_size = int(block.get('orig_line_height', bh) * 0.8)
            font_size = max(10, min(max_font_limit, font_size)) 
            
            while font_size > 8:
                font = ImageFont.truetype(font_path, font_size) if os.path.exists(font_path) else ImageFont.load_default()
                lines, current_line = [], []
                
                for word in words:
                    test_line = ' '.join(current_line + [word]) if current_line else word
                    test_bbox = font.getbbox(test_line)
                    if (test_bbox[2] - test_bbox[0]) <= bw * 0.95:
                        current_line.append(word)
                    else:
                        if current_line:
                            lines.append(' '.join(current_line))
                        current_line = [word]
                if current_line: lines.append(' '.join(current_line))
                
                line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + int(font_size * 0.45)
                total_height = len(lines) * line_height
                
                if total_height <= bh * 0.95:
                    break
                font_size -= 1

            orig_bw = box[2] - box[0]
            
            # --- MULAI PROSES ROTASI ---
            # 1. Buat kanvas kecil transparan untuk teks
            txt_canvas = Image.new('RGBA', (orig_bw, bh), (0, 0, 0, 0))
            txt_draw = ImageDraw.Draw(txt_canvas)
            
            current_y = (bh - total_height) // 2
            
            for line in lines:
                cw = font.getbbox(line)[2] - font.getbbox(line)[0]
                cx = (orig_bw - cw) // 2
                
                stroke_w = max(2, int(font_size * 0.25)) if is_single_word else max(1, int(font_size * 0.05))
                
                # 2. Gambar teks di kanvas kecil
                txt_draw.text(
                    (cx, current_y), 
                    line, 
                    font=font, 
                    fill=block['colors'][0], 
                    stroke_width=stroke_w, 
                    stroke_fill=block['colors'][1]
                )
                current_y += line_height
            
            # 3. Cek sudut kemiringan
            angle = block.get('angle', 0.0)
            if abs(angle) > 3: # Putar jika kemiringan lebih dari 3 derajat
                # Pillow memutar berlawanan jarum jam, jadi kita gunakan -angle
                txt_canvas = txt_canvas.rotate(-angle, expand=True, resample=Image.BICUBIC)
            
            # 4. Kalkulasi ulang titik tengah agar pas saat ditempel ke gambar utama
            paste_x = box[0] + (orig_bw - txt_canvas.width) // 2
            paste_y = box[1] + (bh - txt_canvas.height) // 2
            
            # 5. Tempel teks yang sudah (atau tidak) diputar ke gambar utama
            pil_img.paste(txt_canvas, (paste_x, paste_y), txt_canvas)
            # ---------------------------
                
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
