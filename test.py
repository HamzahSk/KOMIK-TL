import cv2
import numpy as np
import sys

img_path = "015.jpg"

# 1. Buka gambar
img = cv2.imread(img_path)

if img is None:
    print(f"Gagal membuka gambar: {img_path}")
    sys.exit()

# 2. Upscale gambar 2x lipat
new_width = img.shape[1] * 2
new_height = img.shape[0] * 2
img_resized = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_CUBIC)

# 3. Ubah ke Grayscale
gray_np = cv2.cvtColor(img_resized, cv2.COLOR_BGR2GRAY)

# --- JURUS 1: CLAHE ---
# Mempertegas kontras lokal biar tulisan yang pudar makin gelap
clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
gray_clahe = clahe.apply(gray_np)

# 4. Binarization (Menggunakan gambar yang sudah kena CLAHE)
blur_np = cv2.GaussianBlur(gray_clahe, (5, 5), 0)
binary_np = cv2.adaptiveThreshold(
    blur_np, 255, 
    cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
    cv2.THRESH_BINARY, 11, 2
)

# --- JURUS 2: EROSION (Penebalan Teks) ---
# Mengikis warna putih agar warna hitam (teks) makin tebal dan tegas.
# Kernel 2x2 ini adalah ukuran "kuas" penebalannya. 
kernel = np.ones((2, 2), np.uint8) 
thick_binary_np = cv2.erode(binary_np, kernel, iterations=1)

# ==========================
# Simpan hasil untuk dicek
# ==========================
cv2.imwrite("1_hasil_gray_clahe.jpg", gray_clahe)
cv2.imwrite("2_hasil_binary.jpg", binary_np)
cv2.imwrite("3_hasil_binary_tebal.jpg", thick_binary_np) # <--- Pakai yang ini untuk OCR

# ==========================
# Masukkan ke OCR
# ==========================
# out = self.reader(thick_binary_np) 
# print(out)

print("Selesai")
