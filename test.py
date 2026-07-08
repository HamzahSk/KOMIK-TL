from PIL import Image, ImageEnhance
import numpy as np

img_path = "015.jpg"

try:
    img = Image.open(img_path).convert("RGB")
except Exception as e:
    print(f"Gagal membuka gambar: {e}")
    exit()

# 1. Upscale gambar 2x lipat agar teks kecil lebih tajam
new_size = (img.width * 2, img.height * 2)
img_resized = img.resize(new_size, Image.Resampling.BICUBIC)

# 2. Pertajam gambar (Sharpen)
# Biar pinggiran teks nggak "mbleber"
enhancer_sharpness = ImageEnhance.Sharpness(img_resized)
img_sharp = enhancer_sharpness.enhance(2.0) 

# 3. Ubah ke Grayscale (Abu-abu)
img_gray = img_sharp.convert("L")

# 4. Tingkatkan Kontras 
# Biar tulisan makin gelap, background makin terang
enhancer_contrast = ImageEnhance.Contrast(img_gray)
img_contrast = enhancer_contrast.enhance(2.0) 

# 5. Binarization / Thresholding (Opsional tapi SANGAT disarankan untuk OCR)
# Mengubah pixel jadi murni Hitam (0) atau murni Putih (255). 
# Angka 130 ini batasnya, bisa kamu naik-turunin (0-255) buat cari hasil terbaik.
threshold_value = 130
img_binary = img_contrast.point(lambda p: 255 if p > threshold_value else 0)

# Ubah ke array NumPy untuk dimasukkan ke OCR
final_np = np.array(img_binary)

# ==========================
# Simpan hasil untuk dicek
# ==========================
img_sharp.save("1_hasil_upscale_sharp.jpg")
img_contrast.save("2_hasil_gray_contrast.jpg")
img_binary.save("3_hasil_binary.jpg")

# Nanti tinggal ganti ini
# out = self.reader(final_np)
# print(out)

print("Selesai")
