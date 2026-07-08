import cv2
import sys

img_path = "015.jpg"

# 1. Buka gambar
# cv2.imread otomatis mengubah gambar menjadi array NumPy (format BGR)
img = cv2.imread(img_path)

if img is None:
    print(f"Gagal membuka gambar: {img_path}")
    sys.exit()

# 2. Upscale gambar 2x lipat agar teks kecil lebih tajam
# cv2.INTER_CUBIC sangat disarankan untuk memperbesar gambar (upscaling)
new_width = img.shape[1] * 2
new_height = img.shape[0] * 2
img_resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)

# 3. Ubah ke Grayscale (Hitam Putih / Abu-abu)
gray_np = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)

# 4. Binarization (Biar teks jadi hitam pekat & background putih bersih) - SANGAT DIREKOMENDASIKAN UNTUK OCR
# Blur sedikit untuk hilangkan bintik/noise
blur_np = cv2.GaussianBlur(gray_np, (5, 5), 0)
# Adaptive thresholding
binary_np = cv2.adaptiveThreshold(
    blur_np, 255, 
    cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
    cv2.THRESH_BINARY, 11, 2
)

# ==========================
# Simpan hasil untuk dicek
# ==========================

# Simpan gambar upscale (masih berwarna)
cv2.imwrite("hasil_upscale_cv.jpg", img_resized)

# Simpan hasil grayscale
cv2.imwrite("hasil_gray_cv.jpg", gray_np)

# Simpan hasil binarization (hitam putih tegas)
cv2.imwrite("hasil_binary_cv.jpg", binary_np)

# ==========================
# Masukkan ke OCR
# ==========================
# Tinggal masukkan array numpy-nya. Kamu bisa coba masukkan `binary_np` atau `gray_np` 
# (Biasanya binary_np hasilnya jauh lebih minim typo)

# out = self.reader(binary_np) 
# print(out)

print("Selesai")
