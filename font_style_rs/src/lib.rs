//! font_style_rs — pure-Rust computer-vision analyzer for italic / bold / font-type detection.

use numpy::PyReadonlyArray2;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule};

const MAX_SLANT_DEG: f64 = 24.0;
const SLANT_STEP_DEG: f64 = 1.0;
const SQ2: f32 = 1.4142135;
const MIN_INK_PIXELS: usize = 16;

fn otsu_threshold(gray: &[u8]) -> Option<u8> {
    let mut hist = [0u64; 256];
    for &v in gray {
        hist[v as usize] += 1;
    }
    let total = gray.len() as f64;
    if total == 0.0 {
        return None;
    }
    let sum: f64 = hist
        .iter()
        .enumerate()
        .map(|(i, &c)| (i as f64) * (c as f64))
        .sum();
    let mut sum_b = 0.0;
    let mut w_b = 0.0;
    let mut best_var = -1.0;
    let mut best_t = None;
    for t in 0..256usize {
        w_b += hist[t] as f64;
        if w_b == 0.0 {
            continue;
        }
        let w_f = total - w_b;
        if w_f == 0.0 {
            break;
        }
        sum_b += (t as f64) * (hist[t] as f64);
        let m_b = sum_b / w_b;
        let m_f = (sum - sum_b) / w_f;
        let var = w_b * w_f * (m_b - m_f).powi(2);
        if var > best_var {
            best_var = var;
            best_t = Some(t as u8);
        }
    }
    best_t
}

fn binarize(gray: &[u8], h: usize, w: usize) -> Option<(Vec<bool>, Vec<i32>, Vec<i32>)> {
    let t = otsu_threshold(gray)?;
    let mut dark = 0usize;
    for &v in gray {
        if v <= t {
            dark += 1;
        }
    }
    let ink_is_dark = dark <= gray.len() / 2;

    let mut ink = Vec::with_capacity(gray.len());
    let mut xs = Vec::with_capacity(gray.len() / 2);
    let mut ys = Vec::with_capacity(gray.len() / 2);
    let mut idx = 0usize;
    for y in 0..h {
        for x in 0..w {
            let v = gray[idx];
            let is_ink = if ink_is_dark { v <= t } else { v > t };
            ink.push(is_ink);
            if is_ink {
                xs.push(x as i32);
                ys.push(y as i32);
            }
            idx += 1;
        }
    }
    Some((ink, xs, ys))
}

fn distance_transform(ink: &[bool], h: usize, w: usize) -> Vec<f32> {
    let mut d = vec![f32::INFINITY; h * w];
    for (i, v) in d.iter_mut().enumerate() {
        if !ink[i] {
            *v = 0.0;
        }
    }
    for i in 0..h {
        for j in 0..w {
            let idx = i * w + j;
            if d[idx] <= 0.0 {
                continue;
            }
            let mut best = d[idx];
            if i > 0 {
                best = best.min(d[idx - w] + 1.0);
                if j > 0 {
                    best = best.min(d[idx - w - 1] + SQ2);
                }
                if j + 1 < w {
                    best = best.min(d[idx - w + 1] + SQ2);
                }
            }
            if j > 0 {
                best = best.min(d[idx - 1] + 1.0);
            }
            d[idx] = best;
        }
    }
    for i in (0..h).rev() {
        for j in (0..w).rev() {
            let idx = i * w + j;
            if d[idx] <= 0.0 {
                continue;
            }
            let mut best = d[idx];
            if j + 1 < w {
                best = best.min(d[idx + 1] + 1.0);
            }
            if i + 1 < h {
                best = best.min(d[idx + w] + 1.0);
                if j > 0 {
                    best = best.min(d[idx + w - 1] + SQ2);
                }
                if j + 1 < w {
                    best = best.min(d[idx + w + 1] + SQ2);
                }
            }
            d[idx] = best;
        }
    }
    d
}

fn median_stroke_width(d: &[f32], ink: &[bool]) -> Option<f64> {
    let mut vals: Vec<f32> = d
        .iter()
        .zip(ink.iter())
        .filter_map(|(&dv, &is)| if is { Some(dv) } else { None })
        .collect();
    if vals.is_empty() {
        return None;
    }
    vals.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
    let k = ((vals.len() as f64) * 0.60) as usize;
    Some(2.0 * vals[k.min(vals.len() - 1)] as f64)
}

fn dominant_line_height(ink: &[bool], h: usize, w: usize) -> usize {
    let mut best = 0usize;
    let mut cur = 0usize;
    for y in 0..h {
        let has = ink[y * w..(y + 1) * w].iter().any(|&v| v);
        if has {
            cur += 1;
            best = best.max(cur);
        } else {
            cur = 0;
        }
    }
    best
}

fn estimate_slant(xs: &[i32], ys: &[i32], h: i32, w: i32) -> (f64, f64) {
    let n = xs.len();
    if n < MIN_INK_PIXELS {
        return (0.0, 1.0);
    }
    let steps = (MAX_SLANT_DEG / SLANT_STEP_DEG) as i32;
    let mut best_score = 0.0f64;
    let mut best_angle = 0.0f64;
    let mut zero_score = 0.0f64; // Tambahan: simpan skor saat sudut 0 derajat

    let mut ang = -MAX_SLANT_DEG;
    for _ in -steps..=steps {
        let t = ang.to_radians().tan();
        let shift = (t.abs() * h as f64).ceil() as i32;
        let hw = (w + 2 * shift + 2) as usize;
        let base = shift;
        let mut hist = vec![0u32; hw];
        for k in 0..n {
            let col = (xs[k] as f64 + t * ys[k] as f64) as i32 + base;
            if col >= 0 && (col as usize) < hw {
                hist[col as usize] += 1;
            }
        }
        let score: f64 = hist.iter().map(|&c| (c as f64) * (c as f64)).sum();
        
        if score > best_score {
            best_score = score;
            best_angle = ang;
        }
        // Tangkap skor saat tegak lurus
        if ang == 0.0 {
            zero_score = score;
        }
        
        ang += SLANT_STEP_DEG;
    }
    
    // Hitung rasio keyakinan: seberapa jauh lebih baik sudut miring ini dibanding tegak?
    let confidence_ratio = if zero_score > 0.0 { best_score / zero_score } else { 1.0 };
    
    (best_angle, confidence_ratio)
}

/// --- FUNGSI BARU: Analisis Bentuk Glyphs (Condensed / System Font Detection) ---
/// Mengisolasi tiap huruf (connected components) dan menghitung rata-rata rasio lebar/tinggi huruf.
/// --- FUNGSI BARU: Analisis Bentuk Glyphs (Condensed / System Font Detection) ---
/// Mengisolasi tiap huruf (connected components) dan menggunakan nilai MEDIAN rasio lebar/tinggi huruf.
fn analyze_glyph_shapes(ink: &[bool], h: usize, w: usize, line_h: f64) -> bool {
    if h == 0 || w == 0 || line_h < 5.0 {
        return false;
    }

    let mut visited = vec![false; h * w];
    let mut aspect_ratios = Vec::new();

    for y in 0..h {
        for x in 0..w {
            let idx = y * w + x;
            if ink[idx] && !visited[idx] {
                // BFS Flood-fill sederhana untuk mencari kotak bounding tiap karakter
                let mut min_x = x;
                let mut max_x = x;
                let mut min_y = y;
                let mut max_y = y;
                let mut pixel_count = 0;

                let mut queue = vec![(x, y)];
                visited[idx] = true;

                while let Some((cx, cy)) = queue.pop() {
                    pixel_count += 1;
                    min_x = min_x.min(cx);
                    max_x = max_x.max(cx);
                    min_y = min_y.min(cy);
                    max_y = max_y.max(cy);

                    let neighbors = [
                        (cx.wrapping_sub(1), cy),
                        (cx + 1, cy),
                        (cx, cy.wrapping_sub(1)),
                        (cx, cy + 1),
                    ];

                    for &(nx, ny) in &neighbors {
                        if nx < w && ny < h {
                            let nidx = ny * w + nx;
                            if ink[nidx] && !visited[nidx] {
                                visited[nidx] = true;
                                queue.push((nx, ny));
                            }
                        }
                    }
                }

                let gh = (max_y - min_y + 1) as f64;
                let gw = (max_x - min_x + 1) as f64;

                // PERBAIKAN FILTER: Naikkan threshold tinggi minimal menjadi 40% dari line_h (0.40)
                // Ini mencegah tanda baca kecil atau noise ikut terekap sebagai huruf utuh.
                if pixel_count >= 10 && gh >= (line_h * 0.40) && gh <= (line_h * 1.5) {
                    aspect_ratios.push(gw / gh);
                }
            }
        }
    }

    if aspect_ratios.is_empty() {
        return false;
    }

    // PERBAIKAN UTAMA: Gunakan Median (Nilai Tengah), bukan Rata-rata.
    // Mengurutkan rasio dari yang terkecil hingga terbesar
    aspect_ratios.sort_unstable_by(|a, b| a.partial_cmp(b).unwrap());
    
    // Ambil elemen di tengah array
    let mid_index = aspect_ratios.len() / 2;
    let median_aspect_ratio = aspect_ratios[mid_index];

    // Font Sistem / Condensed biasanya memiliki median di bawah 0.55.
    // Font komik (seperti di gambar) biasanya memiliki median di kisaran 0.65 - 0.85.
    // Threshold 0.60 adalah batas aman yang memisahkan keduanya.
    median_aspect_ratio < 0.60
}

fn load_u8_gray(image: &Bound<'_, PyAny>) -> PyResult<(usize, usize, Vec<u8>)> {
    if let Ok(a) = image.extract::<PyReadonlyArray2<u8>>() {
        let v = a.as_array();
        let (h, w) = (v.shape()[0], v.shape()[1]);
        return Ok((h, w, v.iter().copied().collect()));
    }
    if let Ok(a) = image.extract::<PyReadonlyArray2<f32>>() {
        let v = a.as_array();
        let (h, w) = (v.shape()[0], v.shape()[1]);
        let bytes: Vec<u8> = v.iter().map(|&f| f.clamp(0.0, 255.0) as u8).collect();
        return Ok((h, w, bytes));
    }
    if let Ok(a) = image.extract::<PyReadonlyArray2<f64>>() {
        let v = a.as_array();
        let (h, w) = (v.shape()[0], v.shape()[1]);
        let bytes: Vec<u8> = v.iter().map(|&f| f.clamp(0.0, 255.0) as u8).collect();
        return Ok((h, w, bytes));
    }
    Err(PyTypeError::new_err(
        "image must be a 2D grayscale NumPy array (uint8/float32/float64)",
    ))
}

#[pyfunction]
#[pyo3(signature = (image, italic_threshold_deg=10.0, bold_stroke_ratio=0.18, bold_ink_density=0.40))]
fn analyze<'py>(
    py: Python<'py>,
    image: &Bound<'py, PyAny>,
    italic_threshold_deg: f64,
    bold_stroke_ratio: f64,
    _bold_ink_density: f64, // Diabaikan karena sering bikin false-positive di komik
) -> PyResult<Bound<'py, PyDict>> {
    let (h, w, gray) = load_u8_gray(image)?;
    if h == 0 || w == 0 {
        return Err(PyValueError::new_err("image must be non-empty"));
    }

    let out = PyDict::new_bound(py);

    let (ink, xs, ys) = match binarize(&gray, h, w) {
        Some(v) => v,
        None => {
            out.set_item("is_italic", false)?;
            out.set_item("is_bold", false)?;
            out.set_item("is_system", false)?;
            return Ok(out);
        }
    };

    if xs.len() < MIN_INK_PIXELS {
        out.set_item("is_italic", false)?;
        out.set_item("is_bold", false)?;
        out.set_item("is_system", false)?;
        return Ok(out);
    }

    // 1. Deteksi Italic dengan Confidence Score
    let (slant_deg, slant_confidence) = estimate_slant(&xs, &ys, h as i32, w as i32);
    // Italic sah JIKA kemiringannya tembus threshold DAN histogramnya 15% lebih rapat dari teks tegak
    let is_italic = slant_deg.abs() >= italic_threshold_deg && slant_confidence > 1.15;

    // 2. Deteksi Bold (Fokus murni di Stroke Ratio vs Line Height)
    let d = distance_transform(&ink, h, w);
    let line_h = dominant_line_height(&ink, h, w) as f64;
    let stroke = median_stroke_width(&d, &ink).unwrap_or(0.0);
    let stroke_ratio = if line_h > 1.0 { stroke / line_h } else { 0.0 };

    // Font bold sejati memiliki ketebalan goresan signifikan dibanding tinggi font
    let is_bold = stroke_ratio >= bold_stroke_ratio;

    // 3. Deteksi Font Sistem / Condensed Font Shape
    let is_system = analyze_glyph_shapes(&ink, h, w, line_h);

    out.set_item("is_italic", is_italic)?;
    out.set_item("is_bold", is_bold)?;
    out.set_item("is_system", is_system)?;
    Ok(out)
}

#[pymodule]
fn font_style_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(analyze, m)?)?;
    m.add("__doc__", "Rust CV analyzer: detects italic, bold, and system/condensed font shape.")?;
    Ok(())
}
