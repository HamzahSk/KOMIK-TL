//! Layout heuristics: ideal font-size estimation and safe-margin detection.
//!
//! These functions are pure numeric estimators. They are intentionally fast:
//! they let the Python typesetter seed the font size close to the optimum and
//! clamp canvas padding so the new text never overflows the dialog bubble.

use pyo3::prelude::*;

/// Does a given font size fit `text_len` characters into the box?
fn fits(
    fs: f64,
    text_len: usize,
    eff_w: f64,
    height_budget: f64,
    char_w_ratio: f64,
    line_h_ratio: f64,
) -> bool {
    let chars_per_line = (eff_w / (char_w_ratio * fs)).max(1.0);
    let n_lines = (text_len as f64 / chars_per_line).ceil().max(1.0);
    let total_h = n_lines * line_h_ratio * fs;
    total_h <= height_budget
}

/// Estimate the ideal font size that keeps `text_len` characters inside a box.
///
/// Args:
///     text_len: number of characters (without spaces) of the translated text.
///     num_words: number of words; single-word texts (SFX) get a wider width budget.
///     box_w / box_h: width / height of the dialog bubble or OCR box (pixels).
///     base_font_size: preferred starting size; defaults to `0.9 * box_h`.
///     max_font_size / min_font_size: clamping range for the result.
///     char_width_ratio: average glyph advance as a ratio of the font size.
///     line_height_ratio: line spacing as a ratio of the font size.
///     width_limit / height_limit: how much of the box may be used (0..1).
///     single_word_width_factor: extra width budget multiplier for one-word texts.
///
/// Returns:
///     The largest font size (float) that fits, clamped to `[min_font_size, base_font_size]`.
#[pyfunction]
#[pyo3(signature = (
    text_len,
    num_words,
    box_w,
    box_h,
    base_font_size = None,
    max_font_size = 150.0,
    min_font_size = 8.0,
    char_width_ratio = 0.52,
    line_height_ratio = 1.2,
    width_limit = 0.95,
    height_limit = 0.95,
    single_word_width_factor = 1.5,
))]
pub fn estimate_font_size(
    text_len: usize,
    num_words: usize,
    box_w: f64,
    box_h: f64,
    base_font_size: Option<f64>,
    max_font_size: f64,
    min_font_size: f64,
    char_width_ratio: f64,
    line_height_ratio: f64,
    width_limit: f64,
    height_limit: f64,
    single_word_width_factor: f64,
) -> PyResult<f64> {
    if box_w <= 0.0 || box_h <= 0.0 {
        return Ok(min_font_size);
    }

    let base = base_font_size
        .unwrap_or(box_h * 0.9)
        .clamp(min_font_size, max_font_size);
    if text_len == 0 {
        return Ok(base);
    }

    let eff_w = (box_w * width_limit
        * if num_words <= 1 {
            single_word_width_factor
        } else {
            1.0
        })
    .max(4.0);
    let height_budget = (box_h * height_limit).max(4.0);

    // The block height grows monotonically with the font size, so binary search
    // for the largest size that still fits.
    let mut lo = min_font_size;
    let mut hi = base;
    let mut best = lo;
    for _ in 0..64 {
        let mid = (lo + hi) * 0.5;
        if fits(mid, text_len, eff_w, height_budget, char_width_ratio, line_height_ratio) {
            best = mid;
            lo = mid;
        } else {
            hi = mid;
        }
    }
    if fits(base, text_len, eff_w, height_budget, char_width_ratio, line_height_ratio) {
        best = base;
    }

    Ok(best.clamp(min_font_size, base))
}

/// Compute safe (non-overflowing) padding around a text block.
///
/// Args:
///     font_size: the font size that will be used (pixels).
///     min_padding: smallest allowed padding (pixels).
///     padding_ratio: padding as a ratio of the font size.
///     stroke_ratio: outline/stroke width as a ratio of the font size; the
///         stroke is added to the padding so the outline cannot escape the
///         bubble either.
///
/// Returns:
///     Tuple `(left, right, top, bottom)` of safe margins in pixels.
#[pyfunction]
#[pyo3(signature = (font_size, min_padding = 15.0, padding_ratio = 0.3, stroke_ratio = 0.0))]
pub fn safe_padding(
    font_size: f64,
    min_padding: f64,
    padding_ratio: f64,
    stroke_ratio: f64,
) -> PyResult<(f64, f64, f64, f64)> {
    let fs = font_size.max(0.0);
    let stroke = fs * stroke_ratio.max(0.0);
    let pad = (fs * padding_ratio + stroke).max(min_padding);
    Ok((pad, pad, pad, pad))
}
