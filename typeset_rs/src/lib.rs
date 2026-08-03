//! typeset_rs — pure-Rust pixel-level processing for comic/manhwa typesetting.
//!
//! Exposes three independent modules to Python:
//!   * `cluster.rs`   -> `cluster_boxes(...)`  spatial Union-Find clustering
//!   * `layout.rs`    -> `estimate_font_size(...)` / `safe_padding(...)`
//!   * `color.rs`     -> `detect_colors(...)`  K-Means (K=2) text/stroke colors

mod cluster;
mod color;
mod layout;

use pyo3::prelude::*;

/// Python entry point: `import typeset_rs`.
#[pymodule]
fn typeset_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(cluster::cluster_boxes, m)?)?;
    m.add_function(wrap_pyfunction!(layout::estimate_font_size, m)?)?;
    m.add_function(wrap_pyfunction!(layout::safe_padding, m)?)?;
    m.add_function(wrap_pyfunction!(color::detect_colors, m)?)?;
    m.add(
        "__doc__",
        "Rust helpers for comic auto-typesetting: spatial text clustering, font/layout & safe-margin estimation, and K-Means color/stroke extraction.",
    )?;
    Ok(())
}
