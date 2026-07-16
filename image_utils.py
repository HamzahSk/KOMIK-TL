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
        overlay = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
        draw_overlay = ImageDraw.Draw(overlay)
        
        for block in text_blocks:
            box = block['box']
            display_text = block.get('translated_text', block['text'])
            
            if len(display_text.split()) > 1:
                draw_overlay.rounded_rectangle(box, radius=6, fill=(255, 255, 255, 240))
            
        pil_img = Image.alpha_composite(pil_img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(pil_img)
        
        for block in text_blocks:
            box = block['box']
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw < 6 or bh < 6: continue
            
            display_text = block.get('translated_text', block['text'])
            words = display_text.upper().split()
            is_single_word = len(words) <= 1
            
            # --- OPTIMASI KHUSUS UNTUK SFX / TEKS MIRING ---
            max_font_limit = 100
            if is_single_word:
                aspect_ratio = bw / max(1, bh)
                # Jika kotak terlalu lebar (khas SFX miring/memanjang), persempit area cetak (mepetkan)
                if aspect_ratio > 1.5:
                    # Kurangi lebar target pencocokan teks agar font dipaksa mengecil
                    bw = int(bw * 0.6) 
                    # Batasi font agar tidak menjadi raksasa menutupi layar
                    max_font_limit = min(40, int(bh * 0.7))
            # -----------------------------------------------
            
            font_size = int(block.get('orig_line_height', bh) * 0.8)
            font_size = max(10, min(max_font_limit, font_size)) 
            
            while font_size > 8:
                font = ImageFont.truetype(font_path, font_size) if os.path.exists(font_path) else ImageFont.load_default()
                lines, current_line = [], []
                
                for word in words:
                    test_line = ' '.join(current_line + [word]) if current_line else word
                    test_bbox = draw.textbbox((0, 0), test_line, font=font)
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

            current_y = box[1] + (bh - total_height) // 2
            
            # Hitung ulang bw asli untuk penempatan posisi horizontal di tengah box semula
            orig_bw = box[2] - box[0]
            
            for line in lines:
                cw = draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0]
                # Posisikan tetap di tengah-tengah bounding box asli
                cx = box[0] + (orig_bw - cw) // 2
                
                if is_single_word:
                    stroke_w = max(2, int(font_size * 0.25))
                else:
                    stroke_w = max(1, int(font_size * 0.05))
                
                draw.text(
                    (cx, current_y), 
                    line, 
                    font=font, 
                    fill=block['colors'][0], 
                    stroke_width=stroke_w, 
                    stroke_fill=block['colors'][1]
                )
                
                current_y += line_height
                
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

def smart_slice_image(image_path, target_height=2000, out_dir="output"):
    """
    Memotong gambar memanjang secara cerdas tanpa memotong teks/gambar penting.
    Mencari celah (ruang kosong) di antara panel komik.
    """
    # Baca gambar pakai OpenCV
    img = cv2.imread(image_path)
    if img is None:
        print(f"[Error] Tidak bisa membaca gambar {image_path}")
        return [image_path]

    height, width = img.shape[:2]
    
    # Kalau gambar masih pendek dari target, tidak usah dipotong
    if height <= target_height:
        return [image_path]

    # Ubah ke grayscale untuk mempermudah deteksi baris kosong
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Hitung standar deviasi (variansi warna) per baris piksel
    # Kalau nilainya kecil banget (< 5.0), berarti baris itu warnanya solid (putih/hitam polos) -> AMAN dipotong
    row_std = np.std(gray, axis=1)
    safe_rows = row_std < 5.0 
    
    sliced_paths = []
    y_start = 0
    part = 1
    
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    os.makedirs(out_dir, exist_ok=True)

    while y_start < height:
        y_end = y_start + target_height
        
        if y_end >= height:
            y_end = height # Potongan terakhir sampai ujung bawah
        else:
            # Cari baris aman terdekat dari titik potong (y_end) naik ke atas
            # Kita mundur maksimal setengah dari target_height biar potongannya nggak kekecilan
            search_limit = max(y_start + (target_height // 2), 0)
            
            found_safe_cut = False
            for y_candidate in range(y_end, search_limit, -1):
                if safe_rows[y_candidate]:
                    # Ketemu baris kosong! Kita potong di sini
                    y_end = y_candidate
                    found_safe_cut = True
                    break
            
            # Kalau komiknya terlalu padat dan nggak ada ruang kosong sama sekali
            if not found_safe_cut:
                print(f"[Warning] Gagal mencari ruang kosong untuk {base_name}. Potong paksa.")
        
        # Eksekusi potong gambar dari y_start sampai y_end
        slice_img = img[y_start:y_end, :]
        
        # Simpan hasil potongan
        slice_path = os.path.join(out_dir, f"{base_name}_part{part}.jpg")
        cv2.imwrite(slice_path, slice_img)
        sliced_paths.append(slice_path)
        
        # Geser titik awal untuk potongan berikutnya
        y_start = y_end
        part += 1
        
    return sliced_paths
    