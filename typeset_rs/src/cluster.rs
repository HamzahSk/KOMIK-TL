//! Spatial text-line clustering using Union-Find (connected components).
//!
//! OCR lines belonging to the same dialog bubble are merged when:
//!   1. their estimated font size (bbox height proxy) differs by at most
//!      `max_size_ratio` (default 1.30 -> max. 30% difference),
//!   2. they are horizontally overlapping and roughly center-aligned,
//!   3. their vertical gap / overlap stays inside the allowed band, and
//!   4. their slant angle is similar.
//!
//! The algorithm is symmetric (unlike the old greedy left-to-right scan), so
//! the same line always clusters the same way no matter the input ordering.

use numpy::PyReadonlyArray2;
use pyo3::exceptions::PyTypeError;
use pyo3::prelude::*;
use pyo3::types::PySequence;

#[derive(Clone, Copy)]
struct BBox {
    x1: f64,
    y1: f64,
    x2: f64,
    y2: f64,
    angle: f64,
}

impl BBox {
    #[inline]
    fn h(&self) -> f64 {
        self.y2 - self.y1
    }

    #[inline]
    fn w(&self) -> f64 {
        self.x2 - self.x1
    }

    #[inline]
    fn cx(&self) -> f64 {
        (self.x1 + self.x2) * 0.5
    }
}

struct ClusterOptions {
    max_size_ratio: f64,
    max_gap_px: f64,
    max_gap_ratio: f64,
    max_overlap_ratio: f64,
    max_angle_diff_deg: f64,
    center_ratio: f64,
}

/// Decision rule for merging two OCR lines into one dialog bubble.
fn should_merge(a: &BBox, b: &BBox, o: &ClusterOptions) -> bool {
    let min_h = a.h().min(b.h()).max(1.0);
    let max_h = a.h().max(b.h());

    // 1. font-size similarity: height is a cheap proxy for font size.
    if max_h / min_h > o.max_size_ratio {
        return false;
    }

    // 2. slant similarity (protects italic lines from being forced together).
    if (a.angle - b.angle).abs() > o.max_angle_diff_deg {
        return false;
    }

    // 3. horizontal proximity + shared center line (text must stack, not sit side-by-side).
    let max_w = a.w().max(b.w()).max(1.0);
    let h_overlap = a.x2.min(b.x2) - a.x1.max(b.x1);
    if h_overlap < -5.0 {
        return false;
    }
    if (a.cx() - b.cx()).abs() >= max_w * o.center_ratio {
        return false;
    }

    // 4. vertical band: a small gap is fine, a bounded overlap is fine too
    //    (overlap happens with slanted text whose bbox height is flaky).
    let v_overlap = a.y2.min(b.y2) - a.y1.max(b.y1);
    let max_gap = o.max_gap_px.max(o.max_gap_ratio * min_h);
    let max_overlap = o.max_overlap_ratio * min_h;
    v_overlap >= -max_gap && v_overlap <= max_overlap
}

/// Disjoint-set union-find with path compression + union by size.
struct Dsu {
    parent: Vec<usize>,
    size: Vec<usize>,
}

impl Dsu {
    fn new(n: usize) -> Self {
        Dsu {
            parent: (0..n).collect(),
            size: vec![1; n],
        }
    }

    fn find(&mut self, x: usize) -> usize {
        let mut root = x;
        while self.parent[root] != root {
            root = self.parent[root];
        }
        let mut cur = x;
        while self.parent[cur] != cur {
            let nxt = self.parent[cur];
            self.parent[cur] = root;
            cur = nxt;
        }
        root
    }

    fn union(&mut self, a: usize, b: usize) {
        let (ra, rb) = (self.find(a), self.find(b));
        if ra == rb {
            return;
        }
        if self.size[ra] < self.size[rb] {
            self.parent[ra] = rb;
            self.size[rb] += self.size[ra];
        } else {
            self.parent[rb] = ra;
            self.size[ra] += self.size[rb];
        }
    }
}

/// Accepts a NumPy `(N, 4)` / `(N, 5)` array of `[x1, y1, x2, y2, angle?]` or a
/// plain Python list of such rows.
fn load_boxes(obj: &Bound<'_, PyAny>) -> PyResult<Vec<BBox>> {
    if let Ok(a) = obj.extract::<PyReadonlyArray2<f64>>() {
        let arr = a.as_array();
        let (n, d) = (arr.shape()[0], arr.shape()[1]);
        if d < 4 || d > 5 {
            return Err(PyTypeError::new_err(format!(
                "boxes must have shape (N, 4) or (N, 5) as [x1, y1, x2, y2, angle?], got (N, {d})"
            )));
        }
        let mut boxes = Vec::with_capacity(n);
        for i in 0..n {
            let row = arr.row(i);
            boxes.push(BBox {
                x1: row[0],
                y1: row[1],
                x2: row[2],
                y2: row[3],
                angle: if d >= 5 { row[4] } else { 0.0 },
            });
        }
        return Ok(boxes);
    }

    let seq = obj.downcast::<PySequence>().map_err(|_| {
        PyTypeError::new_err(
            "boxes must be a NumPy (N, 4)/(N, 5) array or a list of [x1, y1, x2, y2, angle?] rows",
        )
    })?;
    let mut boxes = Vec::with_capacity(seq.len()?);
    for item in seq.iter()? {
        let row: Vec<f64> = item?.extract()?;
        if row.len() < 4 || row.len() > 5 {
            return Err(PyTypeError::new_err(
                "each box must have 4 or 5 values: [x1, y1, x2, y2, angle?]",
            ));
        }
        boxes.push(BBox {
            x1: row[0],
            y1: row[1],
            x2: row[2],
            y2: row[3],
            angle: if row.len() >= 5 { row[4] } else { 0.0 },
        });
    }
    Ok(boxes)
}

/// Cluster OCR bounding boxes into dialog-bubble groups.
///
/// Args:
///     boxes: NumPy array of shape `(N, 4)` or `(N, 5)` where each row is
///         `[x1, y1, x2, y2, angle?]` (angle in degrees, optional).
///     max_size_ratio: max font-size ratio between two lines to still merge
///         (1.30 = max. 30% difference).
///     max_gap_px: absolute minimum vertical gap (pixels) always tolerated.
///     max_gap_ratio: extra vertical gap tolerance as a ratio of the smaller
///         line height.
///     max_overlap_ratio: allowed vertical overlap as a ratio of the smaller
///         line height (slanted/italic boxes overlap more).
///     max_angle_diff_deg: max slant-angle difference (degrees).
///     center_ratio: how far (ratio of the widest box) the centers may drift
///         apart and still be considered aligned.
///
/// Returns:
///     A list of groups; each group is a list of row indices sorted top-to-bottom.
#[pyfunction]
#[pyo3(signature = (
    boxes,
    max_size_ratio = 1.3,
    max_gap_px = 10.0,
    max_gap_ratio = 0.8,
    max_overlap_ratio = 2.0,
    max_angle_diff_deg = 12.0,
    center_ratio = 0.6,
))]
pub fn cluster_boxes(
    boxes: &Bound<'_, PyAny>,
    max_size_ratio: f64,
    max_gap_px: f64,
    max_gap_ratio: f64,
    max_overlap_ratio: f64,
    max_angle_diff_deg: f64,
    center_ratio: f64,
) -> PyResult<Vec<Vec<usize>>> {
    let records = load_boxes(boxes)?;
    let n = records.len();
    if n == 0 {
        return Ok(Vec::new());
    }

    let opts = ClusterOptions {
        max_size_ratio: max_size_ratio.max(1.0),
        max_gap_px: max_gap_px.max(0.0),
        max_gap_ratio: max_gap_ratio.max(0.0),
        max_overlap_ratio: max_overlap_ratio.max(0.0),
        max_angle_diff_deg: max_angle_diff_deg.max(0.0),
        center_ratio: center_ratio.max(0.0),
    };

    // Union every pair that qualifies -> connected components.
    let mut dsu = Dsu::new(n);
    for i in 0..n {
        for j in (i + 1)..n {
            if should_merge(&records[i], &records[j], &opts) {
                dsu.union(i, j);
            }
        }
    }

    // Group rows by their root.
    let mut groups: std::collections::HashMap<usize, Vec<usize>> =
        std::collections::HashMap::new();
    for i in 0..n {
        groups.entry(dsu.find(i)).or_default().push(i);
    }

    // Stable reading order: sort every group by its centre-Y...
    let mut result: Vec<Vec<usize>> = groups.into_values().collect();
    for g in result.iter_mut() {
        g.sort_by(|&a, &b| {
            let cya = (records[a].y1 + records[a].y2) * 0.5;
            let cyb = (records[b].y1 + records[b].y2) * 0.5;
            cya.partial_cmp(&cyb)
                .unwrap_or(std::cmp::Ordering::Equal)
        });
    }
    // ...and the groups themselves by their topmost box (tie-break: centre-Y).
    result.sort_by(|ga, gb| {
        let top = |g: &Vec<usize>| {
            g.iter()
                .map(|&i| records[i].y1)
                .fold(f64::INFINITY, f64::min)
        };
        let cy = |g: &Vec<usize>| {
            g.iter()
                .map(|&i| (records[i].y1 + records[i].y2) * 0.5)
                .sum::<f64>()
                / g.len() as f64
        };
        top(ga)
            .partial_cmp(&top(gb))
            .unwrap_or(std::cmp::Ordering::Equal)
            .then(
                cy(ga)
                    .partial_cmp(&cy(gb))
                    .unwrap_or(std::cmp::Ordering::Equal),
            )
    });

    Ok(result)
}
