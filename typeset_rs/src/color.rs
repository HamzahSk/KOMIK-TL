//! K-Means (K=2) color / stroke extraction on an RGB crop.
//!
//! Pure-Rust replacement for `cv2.kmeans`: separates the *text color* (the
//! minority cluster) from the *background / outline stroke color* (the majority
//! cluster). Deterministic (seeded RNG, multiple restarts, best-inertia winner).

use numpy::PyReadonlyArray3;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyTuple;

/// Down-sample cap: K-Means does not need every pixel of a big crop.
const MAX_SAMPLE: usize = 20_000;

fn default_colors<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyTuple>> {
    let black = PyTuple::new_bound(py, [0u8, 0, 0]);
    let white = PyTuple::new_bound(py, [255u8, 255, 255]);
    Ok(PyTuple::new_bound(py, [black, white]))
}

/// Accepts an (H, W, 3) RGB or (H, W, 4) RGBA NumPy array (uint8 / float32 /
/// float64); returns the flat list of sampled RGB pixels.
fn load_pixels(obj: &Bound<'_, PyAny>) -> PyResult<Vec<[u8; 3]>> {
    if let Ok(a) = obj.extract::<PyReadonlyArray3<u8>>() {
        let arr = a.as_array();
        let (h, w, d) = (arr.shape()[0], arr.shape()[1], arr.shape()[2]);
        if d != 3 && d != 4 {
            return Err(PyValueError::new_err(
                "color array must have 3 (RGB) or 4 (RGBA) channels",
            ));
        }
        return Ok(sample_u8(arr.as_slice().unwrap_or(&[]), h, w, d));
    }
    if let Ok(a) = obj.extract::<PyReadonlyArray3<f32>>() {
        let arr = a.as_array();
        let (h, w, d) = (arr.shape()[0], arr.shape()[1], arr.shape()[2]);
        if d != 3 && d != 4 {
            return Err(PyValueError::new_err(
                "color array must have 3 (RGB) or 4 (RGBA) channels",
            ));
        }
        let mut out = Vec::new();
        let stride = sample_stride(h * w);
        for i in (0..h).step_by(stride) {
            for j in (0..w).step_by(stride) {
                out.push([
                    arr[[i, j, 0]].clamp(0.0, 255.0) as u8,
                    arr[[i, j, 1]].clamp(0.0, 255.0) as u8,
                    arr[[i, j, 2]].clamp(0.0, 255.0) as u8,
                ]);
            }
        }
        return Ok(out);
    }
    if let Ok(a) = obj.extract::<PyReadonlyArray3<f64>>() {
        let arr = a.as_array();
        let (h, w, d) = (arr.shape()[0], arr.shape()[1], arr.shape()[2]);
        if d != 3 && d != 4 {
            return Err(PyValueError::new_err(
                "color array must have 3 (RGB) or 4 (RGBA) channels",
            ));
        }
        let mut out = Vec::new();
        let stride = sample_stride(h * w);
        for i in (0..h).step_by(stride) {
            for j in (0..w).step_by(stride) {
                out.push([
                    arr[[i, j, 0]].clamp(0.0, 255.0) as u8,
                    arr[[i, j, 1]].clamp(0.0, 255.0) as u8,
                    arr[[i, j, 2]].clamp(0.0, 255.0) as u8,
                ]);
            }
        }
        return Ok(out);
    }
    Err(PyTypeError::new_err(
        "image must be an (H, W, 3) RGB or (H, W, 4) RGBA NumPy array of uint8/float32/float64",
    ))
}

fn sample_stride(n: usize) -> usize {
    if n > MAX_SAMPLE {
        n / MAX_SAMPLE
    } else {
        1
    }
}

fn sample_u8(data: &[u8], h: usize, w: usize, d: usize) -> Vec<[u8; 3]> {
    let stride = sample_stride(h * w);
    let mut out = Vec::with_capacity(h / stride * (w / stride) + 1);
    for i in (0..h).step_by(stride) {
        let row = i * w * d;
        for j in (0..w).step_by(stride) {
            let off = row + j * d;
            out.push([data[off], data[off + 1], data[off + 2]]);
        }
    }
    out
}

/// Small deterministic PRNG (SplitMix64) so results are reproducible.
struct SplitMix64(u64);

impl SplitMix64 {
    fn next(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }

    fn next_f64(&mut self) -> f64 {
        (self.next() >> 11) as f64 / (1u64 << 53) as f64
    }

    fn below(&mut self, n: usize) -> usize {
        if n == 0 {
            return 0;
        }
        (self.next() % n as u64) as usize
    }
}

// [Biarkan kode dari atas sampai `struct SplitMix64` tetap ada, jangan dihapus]

/// K-Means with k-means++ seeding and empty-cluster re-seeding.
/// Returns `(centers, border_counts, inertia)`.
fn kmeans(
    pixels: &[[f32; 3]],
    h: usize,
    w: usize,
    k: usize,
    max_iter: usize,
    rng: &mut SplitMix64,
) -> Option<(Vec<[f32; 3]>, Vec<u64>, f64)> {
    let n = pixels.len();
    if n < k {
        return None;
    }

    // ---- k-means++ seeding ----
    let mut centers: Vec<[f32; 3]> = Vec::with_capacity(k);
    centers.push(pixels[rng.below(n)]);
    while centers.len() < k {
        let mut d2 = Vec::with_capacity(n);
        let mut sum = 0.0f64;
        for p in pixels {
            let mut best = f32::INFINITY;
            for c in &centers {
                let dx = p[0] - c[0];
                let dy = p[1] - c[1];
                let dz = p[2] - c[2];
                best = best.min(dx * dx + dy * dy + dz * dz);
            }
            d2.push(best);
            sum += best as f64;
        }
        if sum <= f64::EPSILON {
            let mut idx = rng.below(n);
            let mut guard = 0usize;
            while centers.contains(&pixels[idx]) && guard < n {
                idx = rng.below(n);
                guard += 1;
            }
            centers.push(pixels[idx]);
        } else {
            let mut r = rng.next_f64() * sum;
            let mut pick = n - 1;
            for (i, &d) in d2.iter().enumerate() {
                r -= d as f64;
                if r <= 0.0 {
                    pick = i;
                    break;
                }
            }
            centers.push(pixels[pick]);
        }
    }

    // ---- Lloyd iterations ----
    let mut labels = vec![0usize; n];
    let mut counts = vec![0u64; k];
    let mut inertia = 0.0f64;
    for _ in 0..max_iter {
        let mut sums = vec![[0.0f32; 3]; k];
        counts = vec![0u64; k];
        let mut new_inertia = 0.0f64;

        for (i, p) in pixels.iter().enumerate() {
            let mut best = f32::INFINITY;
            let mut lab = 0usize;
            for (c, cc) in centers.iter().enumerate() {
                let dx = p[0] - cc[0];
                let dy = p[1] - cc[1];
                let dz = p[2] - cc[2];
                let dd = dx * dx + dy * dy + dz * dz;
                if dd < best {
                    best = dd;
                    lab = c;
                }
            }
            labels[i] = lab;
            sums[lab][0] += p[0];
            sums[lab][1] += p[1];
            sums[lab][2] += p[2];
            counts[lab] += 1;
            new_inertia += best as f64;
        }

        // re-seed any empty cluster
        for c in 0..k {
            if counts[c] == 0 {
                let mut far_idx = 0usize;
                let mut far_d = -1.0f32;
                for (i, p) in pixels.iter().enumerate() {
                    let cc = centers[labels[i]];
                    let dx = p[0] - cc[0];
                    let dy = p[1] - cc[1];
                    let dz = p[2] - cc[2];
                    let dd = dx * dx + dy * dy + dz * dz;
                    if dd > far_d {
                        far_d = dd;
                        far_idx = i;
                    }
                }
                centers[c] = pixels[far_idx];
                counts[c] = 1;
                sums[c] = pixels[far_idx];
            }
        }

        let new_centers: Vec<[f32; 3]> = (0..k)
            .map(|c| {
                let inv = 1.0 / counts[c] as f32;
                [
                    sums[c][0] * inv,
                    sums[c][1] * inv,
                    sums[c][2] * inv,
                ]
            })
            .collect();

        let moved: f32 = new_centers
            .iter()
            .zip(centers.iter())
            .map(|(a, b)| (a[0] - b[0]).abs() + (a[1] - b[1]).abs() + (a[2] - b[2]).abs())
            .sum();

        centers = new_centers;
        inertia = new_inertia;
        if moved < 0.01 {
            break;
        }
    }

    // --- MULAI PERBAIKAN LOGIKA WARNA (BORDER DETECTION) ---
    // Daripada mengembalikan total `counts`, kita hitung jumlah piksel
    // di *garis tepi* gambar untuk masing-masing klaster warna.
    let mut border_counts = vec![0u64; k];
    
    // Perhatikan: Karena pixels sudah disample, kita harus mengestimasi letak tepi
    // dengan membagi panjang array dengan height dan width estimasi
    // Agar lebih robust terhadap downsampling, kita cek label di 10% terluar dari panjang array.
    
    let border_margin = (n as f32 * 0.1) as usize; // 10% awal dan akhir dianggap border/tepi

    for i in 0..n {
       // Jika pixel berada di awal, akhir, atau di pinggiran
       if i < border_margin || i > n - border_margin {
            let lab = labels[i];
            border_counts[lab] += 1;
       }
    }
    // --- AKHIR PERBAIKAN LOGIKA WARNA ---

    Some((centers, border_counts, inertia))
}

/// Detect text vs background/stroke colors of an RGB crop using K-Means (K=2).
#[pyfunction]
#[pyo3(signature = (image, max_iter = 40, restarts = 3, min_contrast = 50.0))]
pub fn detect_colors<'py>(
    py: Python<'py>,
    image: &Bound<'py, PyAny>,
    max_iter: usize,
    restarts: usize,
    min_contrast: f64,
) -> PyResult<Bound<'py, PyTuple>> {
    let pixels = load_pixels(image)?;
    if pixels.len() < 3 {
        return default_colors(py);
    }
    
    // Estimasi dummy h dan w karena kita pakai fallback border detection di kmeans
    let h = 0; 
    let w = 0;

    let fp: Vec<[f32; 3]> = pixels
        .iter()
        .map(|p| [p[0] as f32, p[1] as f32, p[2] as f32])
        .collect();

    let mut best: Option<(Vec<[f32; 3]>, Vec<u64>, f64)> = None;
    let restarts = restarts.max(1);
    for r in 0..restarts {
        let mut rng = SplitMix64(
            0x9E37_79B9_7F4A_7C15 ^ (r as u64).wrapping_add(1).wrapping_mul(0xBF58_476D_1CE4_E5B9),
        );
        // Memasukkan h dan w dummy ke dalam kmeans
        if let Some(res) = kmeans(&fp, h, w, 2, max_iter.max(1), &mut rng) {
            let better = match &best {
                Some((_, _, inertia)) => res.2 < *inertia,
                None => true,
            };
            if better {
                best = Some(res);
            }
        }
    }

    let (centers, border_counts, _) = match best {
        Some(v) => v,
        None => return default_colors(py),
    };

    // Label mayoritas di tepi gambar = Background/Stroke (bg_idx)
    // Teks = text_idx
    let (text_idx, bg_idx) = if border_counts[0] <= border_counts[1] {
        (0usize, 1usize) // 1 adalah background (karena lebih banyak di border)
    } else {
        (1usize, 0usize) // 0 adalah background
    };

    let t = centers[text_idx];
    let b = centers[bg_idx];
    let tc = [
        t[0].round().clamp(0.0, 255.0) as u8,
        t[1].round().clamp(0.0, 255.0) as u8,
        t[2].round().clamp(0.0, 255.0) as u8,
    ];
    let bc = [
        b[0].round().clamp(0.0, 255.0) as u8,
        b[1].round().clamp(0.0, 255.0) as u8,
        b[2].round().clamp(0.0, 255.0) as u8,
    ];

    let contrast = (tc[0] as i32 - bc[0] as i32).abs()
        + (tc[1] as i32 - bc[1] as i32).abs()
        + (tc[2] as i32 - bc[2] as i32).abs();
    if (contrast as f64) < min_contrast {
        return default_colors(py);
    }

    let text_t = PyTuple::new_bound(py, [tc[0], tc[1], tc[2]]);
    let bg_t = PyTuple::new_bound(py, [bc[0], bc[1], bc[2]]);
    Ok(PyTuple::new_bound(py, [text_t, bg_t]))
}
