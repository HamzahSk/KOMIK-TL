from PIL import Image
import numpy as np

img_path = "015.jpg"

img = Image.open(img_path).convert("RGB")

# Upscale 2x
new_size = (img.width * 2, img.height * 2)
img_resized = img.resize(new_size, Image.Resampling.BICUBIC)

# Grayscale
gray = img_resized.convert("L")

# Simpan hasil
img_resized.save("hasil_upscale.jpg")
gray.save("hasil_gray.jpg")

print("Selesai")