# SYSTEM CONTEXT
Saya sedang mengembangkan alat auto-typesetter untuk komik/manhwa menggunakan Python dan RapidOCR. Saat ini, skrip Python saya sudah berhasil mendeteksi dan melakukan *cropping* koordinat *bounding box* teks dengan baik. 

# OBJECTIVE
Buatkan modul Rust menggunakan **PyO3** dan **rust-numpy** yang berfungsi sebagai *Computer Vision analyzer* murni untuk mendeteksi gaya font (*italic* dan *bold*). Modul ini harus sangat cepat dan minim *overhead*.

**ATURAN STRICT:** JANGAN ubah, mendikte, atau merestrukturisasi arsitektur kode Python saya yang sudah ada. Fokus HANYA pada pembuatan ekstensi Rust dan berikan contoh *snippet* cara memanggilnya dari Python.

# RUST MODULE REQUIREMENTS
1. **Input:** Fungsi Rust harus bisa menerima potongan gambar (*crop*) dalam format Grayscale 2D (NumPy array yang di-passing dari Python).
2. **Algoritma Deteksi Italic (Kemiringan):**
   - Gunakan pendekatan *Vertical Projection Profile* atau *Slant Detection* manual.
   - Analisis matriks piksel untuk mencari tahu apakah tumpukan piksel hitam paling padat terjadi pada sudut lurus (0 derajat) atau miring (misal 10-20 derajat). Jika kemiringan dominan melewati *threshold* tertentu, tetapkan `is_italic = true`.
3. **Algoritma Deteksi Bold (Ketebalan):**
   - Gunakan perhitungan rasio piksel gelap terhadap ukuran area (atau *Stroke Width Transform* sederhana) tanpa melatih model AI.
   - Jika rasio ketebalan tinta/piksel huruf melebihi *threshold* standar (bisa di-*hardcode* atau dijadikan parameter), tetapkan `is_bold = true`.
4. **Output:** Fungsi harus mengembalikan Python Dictionary berformat: `{"is_italic": bool, "is_bold": bool}`.

# DELIVERABLES
1. Isi file `Cargo.toml` untuk *setup* PyO3 dan *dependencies* gambar/matriks yang dibutuhkan.
2. Kode Rust murni (`lib.rs`) yang mengimplementasikan pemrosesan piksel secara efisien (gunakan operasi vektor/matriks bawaan Rust yang cepat).
3. Contoh *snippet* kode Python (3-5 baris saja) yang menunjukkan cara meng-*import* modul hasil *compile* (*maturin build*) dan memanggil fungsi tersebut dengan *passing* array OpenCV.
