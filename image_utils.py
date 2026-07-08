# image_utils.py
import os
import requests
import concurrent.futures
import numpy as np
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
            is_single_word = len(display_text.split()) <= 1
            
            font_size = int(block.get('orig_line_height', bh) * 0.8)
            font_size = max(10, min(100, font_size)) 
            
            while font_size > 8:
                font = ImageFont.truetype(font_path, font_size) if os.path.exists(font_path) else ImageFont.load_default()
                lines, current_line = [], []
                
                for word in display_text.upper().split():
                    test_line = ' '.join(current_line + [word]) if current_line else word
                    test_bbox = draw.textbbox((0, 0), test_line, font=font)
                    if (test_bbox[2] - test_bbox[0]) <= bw * 0.95:
                        current_line.append(word)
                    else:
                        if current_line:
                            lines.append(' '.join(current_line))
                        current_line = [word]
                if current_line: lines.append(' '.join(current_line))
                
                line_height = font.getbbox("A")[3] - font.getbbox("A")[1] + int(font_size * 0.25)
                total_height = len(lines) * line_height
                
                if total_height <= bh * 0.95:
                    break
                font_size -= 1

            current_y = box[1] + (bh - total_height) // 2
            
            for line in lines:
                cw = draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0]
                cx = box[0] + (bw - cw) // 2
                
                # --- PERUBAHAN OPTIMASI PILLOW ---
                if is_single_word:
                    stroke_w = max(2, int(font_size * 0.12))
                else:
                    stroke_w = max(1, int(font_size * 0.05))
                
                # Menggunakan parameter bawaan Pillow yang lebih cepat daripada looping manual X dan Y
                draw.text(
                    (cx, current_y), 
                    line, 
                    font=font, 
                    fill=block['colors'][0], 
                    stroke_width=stroke_w, 
                    stroke_fill=block['colors'][1]
                )
                # ---------------------------------
                
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
