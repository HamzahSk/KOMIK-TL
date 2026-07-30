
# Peningkatan dan Refactoring Seluruh Pipeline Manga Translator

Saat ini saya memiliki sebuah project Python untuk mengunduh, membersihkan teks, menerjemahkan, dan melakukan typesetting otomatis (Manga/Manhwa Translator). Struktur project saat ini adalah sebagai berikut:

```text
.
├── README.md
├── config.py
├── config.yaml
├── font
│   ├── Houston Comics Personal Use.ttf
│   ├── Komika_display.ttf
│   ├── Komika_display_kaps.ttf
│   ├── Komika_display_kaps_bold.ttf
│   ├── Roboto-Bold.ttf
│   ├── digistrip.ttf
│   └── helsinki.ttf
├── image_utils.py
├── main.py
├── ocr_engine.py
├── requirements.txt
├── scraper.py
└── translator.py

```
## 1. Penjelasan Alur Sistem Saat Ini
Berikut adalah alur kerja (workflow) utama dalam sistem ini:
 1. **Scraping & Download (scraper.py & main.py):** Mengambil daftar gambar per chapter dari provider yang didukung (VyManga/Bbato), mengunduhnya secara paralel, lalu menggabungkan gambar yang terlalu pendek menggunakan merge_short_images.
 2. **Smart Slicing (image_utils.py):** Gambar yang terlalu panjang akan dipotong menggunakan analisis densitas tepi (smart_slice_image) agar potongan tidak menabrak teks atau panel penting.
 3. **OCR & Merge Bubbles (ocr_engine.py):** Menggunakan RapidOCR untuk mendeteksi teks dan bounding box, kemudian menggabungkan teks-teks yang berdekatan menjadi satu kelompok gelembung dialog (_merge_dialog_bubbles).
 4. **Filtering SFX & Translation (main.py & translator.py):** Memisahkan kata-kata pendek/SFX agar tidak masuk ke antrean AI, lalu mengirim sisa teks dialog ke model NMT offline (Helsinki-NLP/opus-mt-en-id) secara batch.
 5. **Inpainting / Removal Teks (image_utils.py):** Membersihkan teks asli di dalam gambar menggunakan cv2.Canny, dibantu morphological dilation, dan dihapus dengan algoritma cv2.inpaint.
 6. **Typesetting & Rendering (image_utils.py):** Menempelkan teks terjemahan ke atas canvas gambar dengan mengestimasi ukuran font, mendeteksi warna dominan, dan menyesuaikan kemiringan (*angle*), kemudian menyimpan hasil akhirnya sebagai file .cbz.
## 2. Instruksi Upgrade Logika & Perbaikan Kode
Saya ingin kamu mengupgrade, mengoptimalkan, dan merefactor seluruh pipeline di atas. Tolong ubah atau perbaiki file-file terkait (ocr_engine.py, image_utils.py, dan main.py jika perlu) untuk memenuhi spesifikasi di bawah ini:
### A. Peningkatan Akurasi & Kedalaman OCR (ocr_engine.py)
 * **Perbaikan Deteksi Teks:** Buat pemrosesan gambar awal (*image preprocessing*) di detect_and_merge lebih adaptif dan akurat terhadap teks manga yang kecil, rapat, atau memiliki noise/screentone.
 * **Toleransi Karakter Miring:** Pastikan OCR tidak salah membaca atau mengabaikan tanda baca serta huruf kapital yang dimodifikasi oleh gaya font komik.
### B. Perbaikan Deteksi Kelompok Percakapan (_merge_dialog_bubbles di ocr_engine.py)
 * Logika pengelompokan saat ini sering keliru dalam menggabungkan baris kalimat.
 * **Perbaiki Alur Penggabungan (Clustering):** Buat algoritma pengelompokan dialog (*bubble merging*) yang lebih cerdas dengan memperhitungkan:
   * Jarak vertikal antarbaris yang proporsional terhadap ukuran font.
   * Overlap horizontal atau perataan tengah (*center alignment*).
   * Kemiringan teks (*angle similarity*) agar dialog miring dalam satu balon tidak terpecah menjadi banyak blok atau sebaliknya (menggabungkan panel yang berbeda).
### C. Perbaikan Penghapusan Teks / Inpainting (apply_text - Fase Inpainting di image_utils.py)
 * **Masalah Saat Ini:** Masking teks sering kali "meluber" ke luar balon dialog atau sebaliknya tidak menghapus outline (stroke) huruf secara bersih, meninggalkan bekas buram pada background.
 * **Solusi yang Diharapkan:**
   * Perbaiki logika pembuatan *mask* menggunakan gabungan *Edge Detection*, thresholding warna/kontras, atau operasi morfologi (dilation/closing) yang lebih presisi.
   * Pastikan area putih pada balon dialog tetap rapi, tidak meluber ke garis panel hitam di sekitarnya, dan hasil inpainting terlihat mulus tanpa artefak.
### D. Dukungan Font Mendalam & Penyesuaian Ukuran (Typesetter di image_utils.py)
 * **Masalah Saat Ini:** Ukuran font hasil typesetting sering kali **terlalu kecil** di dalam balon dialog yang luas dan hanya mengandalkan satu/dua font.
 * **Aturan Font Baru (Gunakan aset dari folder font/):**
   1. **Percakapan Normal / Regular:** Wajib menggunakan font font/digistrip.ttf.
   2. **Teks Tebal / Seruan (Bold/Shout):** Gunakan font/Komika_display_kaps_bold.ttf atau font/Roboto-Bold.ttf (otomatis terdeteksi berdasarkan ukuran bounding box atau jika teks didominasi huruf kapital/tanda seru).
   3. **Teks Miring / Dalam Hati / SFX (Italic/SFX):** Gunakan font/Houston Comics Personal Use.ttf, font/Komika_display.ttf, atau font/helsinki.ttf.
 * **Perbaikan Logika Ukuran Font (Auto-Sizing):**
   * Rancang ulang algoritma fitting teks agar font **mengisi balon percakapan secara optimal (tidak terlalu kecil dan tidak kebesaran)**.
   * Gunakan perhitungan *aspect ratio* dari bounding box untuk menentukan pemenggalan baris (*word wrapping*) yang seimbang, sehingga bentuk blok teks menyerupai oval/belah ketupat yang indah di tengah gelembung.
## 3. Output yang Diharapkan
 1. Berikan penjelasan singkat mengenai konsep logika baru yang kamu terapkan untuk setiap perbaikan (OCR, Merge Bubble, Inpainting, dan Typesetting).
 2. Tuliskan kode lengkap atau bagian kode yang direfactor secara terstruktur untuk ocr_engine.py dan image_utils.py (serta file lain jika ada dependensi yang perlu disesuaikan) agar langsung siap digunakan tanpa error.
