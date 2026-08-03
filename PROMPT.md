# SYSTEM CONTEXT
Saya sedang mengembangkan alat auto-typesetter untuk komik/manhwa menggunakan Python (`ocr_engine.py`, `image_utils.py`) dan RapidOCR. Sebelumnya, modul Rust (`font_style_rs`) berbasis PyO3 sudah berhasil digunakan untuk deteksi *italic* dan *bold*.

Sekarang, saya ingin memindahkan logika pemrosesan gambar dan *layouting* tingkat piksel lainnya dari Python ke Rust (seperti *clustering* teks, kalkulasi ukuran font & margin, serta deteksi warna/stroke K-Means) demi akurasi dan kecepatan yang lebih tinggi. Selain itu, saya ingin kode Python yang ada langsung di-update dan diintegrasikan secara penuh.

# OBJECTIVE
1. Buat modul Rust modular berbasis **PyO3** dan **rust-numpy** untuk menangani *clustering*, *layout/margin*, dan *color/stroke extraction*.
2. Update dan sediakan kode Python utuh (`ocr_engine.py` dan `image_utils.py`) yang sudah langsung terintegrasi dengan fungsi-fungsi Rust baru tersebut tanpa ada kode yang terpotong.

# REQUIREMENTS & SPECIFICATIONS

## A. MODUL RUST (Harus Dipisah per File Modul)
JANGAN menumpuk semua kode di `lib.rs`. Pisahkan ke dalam struktur folder `src/`:
1. `src/cluster.rs`:
   - Fungsi *Text Clustering* menggunakan algoritma *Union-Find* / *Spatial Clustering*.
   - Menggabungkan *bounding box* jika jarak spasialnya berdekatan DAN rasio perbedaan ukuran font-nya masih dalam batas toleransi (misal maksimal beda 30%).
2. `src/layout.rs`:
   - Fungsi kalkulasi estimasi ukuran font ideal dan deteksi margin/batas aman (*safe padding*) agar teks baru tidak meluap (*overflow*) keluar dari garis/balon dialog.
3. `src/color.rs`:
   - Fungsi *K-Means Clustering* (K=2) atau analisis histogram warna pada *crop* gambar (NumPy array) murni di Rust untuk memisahkan **Warna Teks** dan **Warna Background/Outline (Stroke)** secara akurat.
4. `src/lib.rs`:
   - Pintu masuk PyO3 (`#[pymodule]`) yang menyatukan dan mengekspos semua fungsi dari modul-modul di atas ke Python.
5. `Cargo.toml`:
   - Configuration file dengan *dependencies* yang dibutuhkan (`pyo3`, `ndarray`, `rust-numpy`, dll).

## B. INTEGRASI KODE PYTHON (Sediakan Kode Utuh)
Perbarui file Python berikut agar langsung memanfaatkan modul Rust baru tersebut:
1. `ocr_engine.py`:
   - Panggil fungsi *clustering* dari Rust di dalam metode `_merge_dialog_bubbles` (atau gantikan logikanya) agar pengelompokan balon percakapan jauh lebih presisi berdasarkan jarak dan ukuran font.
2. `image_utils.py`:
   - Perbarui metode `detect_colors` untuk memanggil fungsi deteksi warna Rust (menggantikan OpenCV K-Means Python).
   - Gunakan hasil kalkulasi margin/layout dari Rust di metode `apply_text` (`Typesetter`) agar penempatan dan ukuran teks tidak keluar dari batas aman balon dialog.

# DELIVERABLES
Sediakan output kode lengkap untuk file-file berikut:
1. `Cargo.toml`
2. Kode Rust Modular: `src/lib.rs`, `src/cluster.rs`, `src/layout.rs`, dan `src/color.rs`
3. Kode Python Utuh (Siap Pakai): `ocr_engine.py` dan `image_utils.py`
