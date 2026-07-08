from PIL import Image
import numpy as np

img_path = "015.jpg"

try:
    img = Image.open(img_path).convert("RGB")
except Exception as e:
    print(f"Gagal membuka gambar: {e}")
    exit()

# Upscale gambar 2x lipat agar teks kecil lebih tajam
new_size = (img.width * 2, img.height * 2)
img_resized = img.resize(new_size, Image.Resampling.BICUBIC)

# Ubah ke Grayscale (Hitam Putih)
gray_np = np.array(img_resized.convert("L"))

# ==========================
# Simpan hasil untuk dicek
# ==========================

# Simpan gambar upscale
img_resized.save("hasil_upscale.jpg")

# Ubah lagi array NumPy jadi Image, sama persis kayak yang masuk OCR
Image.fromarray(gray_np).save("hasil_gray.jpg")

# Nanti tinggal ganti ini
# out = self.reader(gray_np)
# print(out)

print("Selesai")