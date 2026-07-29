use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use image::{
    DynamicImage, GenericImage, GenericImageView, ImageBuffer, Luma, Rgba, RgbaImage,
};
use imageproc::distance_transform::Norm;
use imageproc::edges::canny;
use imageproc::morphology::dilate;
use log::{debug, info, warn};
use rayon::prelude::*;
use reqwest::blocking::Client;
use reqwest::header;
use rusttype;

use crate::ocr::TextBlock;

pub struct ImageProcessor;

impl ImageProcessor {
    pub fn detect_colors(img: &DynamicImage, box_coords: &[i32; 4]) -> ([u8; 3], [u8; 3]) {
        let x1 = box_coords[0].max(0) as u32;
        let y1 = box_coords[1].max(0) as u32;
        let x2 = (box_coords[2] as u32).min(img.width());
        let y2 = (box_coords[3] as u32).min(img.height());

        if x2 <= x1 || y2 <= y1 || (x2 - x1) < 3 || (y2 - y1) < 3 {
            return ([0, 0, 0], [255, 255, 255]);
        }

        let crop = img.crop_imm(x1, y1, x2 - x1, y2 - y1);
        let rgb = crop.to_rgb8();
        let pixels: Vec<[f32; 3]> = rgb.pixels()
            .map(|p| [p.0[0] as f32, p.0[1] as f32, p.0[2] as f32])
            .collect();

        if pixels.len() < 10 {
            return ([0, 0, 0], [255, 255, 255]);
        }

        let (centers, counts) = simple_kmeans_2(&pixels, 20);
        if centers.len() < 2 {
            return ([0, 0, 0], [255, 255, 255]);
        }

        let bg_idx = if counts[0] >= counts[1] { 0 } else { 1 };
        let text_idx = 1 - bg_idx;

        let text_color = centers[text_idx];
        let bg_color = centers[bg_idx];

        let diff: u16 = (0..3).map(|i| {
            (text_color[i] as i16 - bg_color[i] as i16).unsigned_abs() as u16
        }).sum();
        if diff < 50 {
            return ([0, 0, 0], [255, 255, 255]);
        }

        (text_color, bg_color)
    }
}

fn simple_kmeans_2(pixels: &[[f32; 3]], max_iter: usize) -> (Vec<[u8; 3]>, Vec<u32>) {
    if pixels.is_empty() {
        return (vec![[0, 0, 0], [255, 255, 255]], vec![0, 0]);
    }

    let n = pixels.len();
    let idx1 = 0;
    let idx2 = n / 2;

    let mut c0 = pixels[idx1];
    let mut c1 = pixels[idx2];

    if (c0[0] - c1[0]).abs() < 0.1 && (c0[1] - c1[1]).abs() < 0.1 && (c0[2] - c1[2]).abs() < 0.1 {
        c1 = pixels[(n * 3 / 4).min(n - 1)];
    }

    let mut labels = vec![0u8; n];

    for _iter in 0..max_iter {
        let mut changed = 0;
        for (i, p) in pixels.iter().enumerate() {
            let d0 = (p[0] - c0[0]).powi(2) + (p[1] - c0[1]).powi(2) + (p[2] - c0[2]).powi(2);
            let d1 = (p[0] - c1[0]).powi(2) + (p[1] - c1[1]).powi(2) + (p[2] - c1[2]).powi(2);
            let new_label = if d0 <= d1 { 0 } else { 1 };
            if new_label != labels[i] {
                labels[i] = new_label;
                changed += 1;
            }
        }

        let mut sum0 = [0.0f32; 3];
        let mut sum1 = [0.0f32; 3];
        let mut count0 = 0u32;
        let mut count1 = 0u32;

        for (i, p) in pixels.iter().enumerate() {
            if labels[i] == 0 {
                sum0[0] += p[0]; sum0[1] += p[1]; sum0[2] += p[2];
                count0 += 1;
            } else {
                sum1[0] += p[0]; sum1[1] += p[1]; sum1[2] += p[2];
                count1 += 1;
            }
        }

        if count0 > 0 {
            c0 = [sum0[0] / count0 as f32, sum0[1] / count0 as f32, sum0[2] / count0 as f32];
        }
        if count1 > 0 {
            c1 = [sum1[0] / count1 as f32, sum1[1] / count1 as f32, sum1[2] / count1 as f32];
        }

        if changed == 0 { break; }
    }

    let to_u8 = |c: [f32; 3]| -> [u8; 3] {
        [c[0].round().min(255.0).max(0.0) as u8,
         c[1].round().min(255.0).max(0.0) as u8,
         c[2].round().min(255.0).max(0.0) as u8]
    };

    let count0 = labels.iter().filter(|&&l| l == 0).count() as u32;
    let count1 = labels.iter().filter(|&&l| l == 1).count() as u32;
    (vec![to_u8(c0), to_u8(c1)], vec![count0, count1])
}

pub struct Typesetter;

impl Typesetter {
    pub fn apply_text(
        img: &DynamicImage,
        blocks: &[TextBlock],
        font_path: &Path,
        sfx_font_path: &Path,
    ) -> Result<DynamicImage> {
        let mut img = img.clone();

        let valid_blocks: Vec<&TextBlock> = blocks.iter()
            .filter(|b| {
                let bh = b.box_coords[3] - b.box_coords[1];
                let font_size_est = (b.orig_line_height.max(bh as f32) * 0.9) as i32;
                let words: Vec<&str> = b.text.split_whitespace().collect();
                let is_single_word = words.len() <= 1;
                let is_sfx = is_single_word && font_size_est > 50;

                if is_sfx && b.angle.abs() > 5.0 { return false; }
                if font_size_est > 120 { return false; }
                true
            })
            .collect();

        if valid_blocks.is_empty() {
            return Ok(img);
        }

        img = inpaint_text(&img, &valid_blocks);

        for block in &valid_blocks {
            img = render_text_block(img, block, font_path, sfx_font_path)?;
        }

        Ok(img)
    }
}

fn inpaint_text(img: &DynamicImage, blocks: &[&TextBlock]) -> DynamicImage {
    let (w, h) = img.dimensions();
    let rgb = img.to_rgb8();
    let gray = img.to_luma8();

    let edges = canny(&gray, 50.0, 150.0);
    let dilated = dilate(&edges, Norm::LInf, 5);

    let mut mask = ImageBuffer::from_pixel(w, h, Luma([0u8]));

    for y in 0..h {
        for x in 0..w {
            if dilated.get_pixel(x, y).0[0] > 0 {
                mask.put_pixel(x, y, Luma([255]));
            }
        }
    }

    for block in blocks {
        let b = &block.box_coords;
        let pad = 5i32;
        let x1 = (b[0] - pad).max(0) as u32;
        let y1 = (b[1] - pad).max(0) as u32;
        let x2 = (b[2] + pad).min(w as i32 - 1) as u32;
        let y2 = (b[3] + pad).min(h as i32 - 1) as u32;

        if x2 <= x1 || y2 <= y1 { continue; }

        for y in y1..=y2 {
            for x in x1..=x2 {
                mask.put_pixel(x, y, Luma([255]));
            }
        }
    }

    let mut inpainted = rgb.clone();
    let radius = 6;

    let mask_pixels: Vec<(u32, u32)> = (0..h).flat_map(|y| {
        (0..w).map(move |x| (x, y))
    }).filter(|&(x, y)| mask.get_pixel(x, y).0[0] > 0)
    .collect();

    for &(mx, my) in &mask_pixels {
        let mut r_sum = 0u32; let mut g_sum = 0u32; let mut b_sum = 0u32;
        let mut count = 0u32;

        let x_start = mx.saturating_sub(radius);
        let x_end = (mx + radius).min(w - 1);
        let y_start = my.saturating_sub(radius);
        let y_end = (my + radius).min(h - 1);

        for sy in y_start..=y_end {
            for sx in x_start..=x_end {
                if mask.get_pixel(sx, sy).0[0] == 0 {
                    let p = rgb.get_pixel(sx, sy);
                    r_sum += p.0[0] as u32;
                    g_sum += p.0[1] as u32;
                    b_sum += p.0[2] as u32;
                    count += 1;
                }
            }
        }

        if count > 0 {
            inpainted.put_pixel(mx, my, image::Rgb([
                (r_sum / count) as u8,
                (g_sum / count) as u8,
                (b_sum / count) as u8,
            ]));
        }
    }

    DynamicImage::ImageRgb8(inpainted)
}

fn render_text_block(
    img: DynamicImage,
    block: &TextBlock,
    font_path: &Path,
    sfx_font_path: &Path,
) -> Result<DynamicImage> {
    let box_coords = &block.box_coords;
    let bw = (box_coords[2] - box_coords[0]) as u32;
    let bh = (box_coords[3] - box_coords[1]) as u32;

    if bw < 6 || bh < 6 { return Ok(img); }

    let display_text = block.translated_text.as_deref().unwrap_or(&block.text);
    let display_text_upper = display_text.to_uppercase();
    let words: Vec<&str> = display_text_upper.split_whitespace().collect();
    let is_single_word = words.len() <= 1;

    let font_size = ((block.orig_line_height * 0.9) as i32).max(10).min(150);
    let is_sfx = is_single_word && font_size > 50;

    let active_font_path = if is_sfx && sfx_font_path.exists() {
        sfx_font_path
    } else {
        font_path
    };

    let font = load_font(active_font_path)?;

    let (lines, total_height, final_font_size) = layout_text(
        &words, bw as i32, bh as i32, font_size, &font, is_single_word,
    )?;

    let (text_color, bg_color) = ImageProcessor::detect_colors(&img, box_coords);

    let pad_canvas = (final_font_size as f32 * 0.3).max(15.0) as u32;
    let canvas_w = bw + pad_canvas * 2;
    let canvas_h = bh + pad_canvas * 2;

    let mut txt_canvas = RgbaImage::new(canvas_w, canvas_h);
    for pixel in txt_canvas.pixels_mut() {
        *pixel = Rgba([0, 0, 0, 0]);
    }

    let draw_scale = rusttype::Scale::uniform(final_font_size as f32);
    let v_metrics = font.v_metrics(draw_scale);
    let line_height = (v_metrics.ascent - v_metrics.descent + v_metrics.line_gap) as i32;
    let current_y = ((canvas_h as i32 - total_height) / 2).max(0) as i32;

    let stroke_w = if is_single_word {
        (final_font_size as f32 * 0.08).max(2.0) as i32
    } else {
        (final_font_size as f32 * 0.05).max(1.0) as i32
    };

    for (line_idx, line) in lines.iter().enumerate() {
        let cw = get_text_width(&font, draw_scale, line);
        let cx = ((canvas_w as i32 - cw) / 2).max(0) as i32;
        let cy = current_y + (line_idx as i32) * line_height;

        draw_text_with_stroke(
            &mut txt_canvas, &font, draw_scale,
            cx, cy, line, text_color, bg_color, stroke_w,
        );
    }

    let angle = block.angle;
    let txt_rgba = DynamicImage::ImageRgba8(txt_canvas);

    let rotated = if angle.abs() > 3.0 {
        let (w, h) = txt_rgba.dimensions();
        let cx = w as f64 / 2.0;
        let cy = h as f64 / 2.0;
        let cos_a = (-angle as f64).to_radians().cos();
        let sin_a = (-angle as f64).to_radians().sin();
        let new_w = (w as f64 * cos_a.abs() + h as f64 * sin_a.abs()).ceil() as u32;
        let new_h = (w as f64 * sin_a.abs() + h as f64 * cos_a.abs()).ceil() as u32;
        let mut rotated = RgbaImage::new(new_w, new_h);

        for dy in 0..new_h {
            for dx in 0..new_w {
                let src_x = (dx as f64 - new_w as f64 / 2.0) * cos_a
                    - (dy as f64 - new_h as f64 / 2.0) * sin_a
                    + cx;
                let src_y = (dx as f64 - new_w as f64 / 2.0) * sin_a
                    + (dy as f64 - new_h as f64 / 2.0) * cos_a
                    + cy;

                if src_x >= 0.0 && src_x < w as f64 - 1.0 && src_y >= 0.0 && src_y < h as f64 - 1.0 {
                    let px = txt_rgba.get_pixel(src_x as u32, src_y as u32);
                    rotated.put_pixel(dx, dy, px);
                }
            }
        }
        DynamicImage::ImageRgba8(rotated)
    } else {
        txt_rgba
    };

    let paste_x = (box_coords[0] as i32 + (bw as i32 - rotated.width() as i32) / 2).max(0) as u32;
    let paste_y = (box_coords[1] as i32 + (bh as i32 - rotated.height() as i32) / 2).max(0) as u32;

    let src_rgba = img.to_rgba8();
    let (w, h) = src_rgba.dimensions();
    let mut result = RgbaImage::new(w, h);
    result.copy_from(&src_rgba, 0, 0).ok();

    for ry in 0..rotated.height() {
        for rx in 0..rotated.width() {
            let px = rotated.get_pixel(rx, ry);
            if px.0[3] > 50 {
                let dx = paste_x + rx;
                let dy = paste_y + ry;
                if dx < result.width() && dy < result.height() {
                    result.put_pixel(dx, dy, px);
                }
            }
        }
    }

    Ok(DynamicImage::ImageRgba8(result))
}

fn load_font(path: &Path) -> Result<rusttype::Font<'_>> {
    let data = std::fs::read(path)
        .context(format!("Failed to read font file: {:?}", path))?;
    let font = rusttype::Font::try_from_vec(data)
        .ok_or_else(|| anyhow::anyhow!("Failed to parse font: {:?}", path))?;
    Ok(font)
}

fn get_text_width(font: &rusttype::Font, scale: rusttype::Scale, text: &str) -> i32 {
    let mut width = 0f32;
    for c in text.chars() {
        let glyph = font.glyph(c).scaled(scale);
        let hm = glyph.h_metrics();
        width += hm.advance_width;
    }
    width.ceil() as i32
}

fn draw_text_with_stroke(
    canvas: &mut RgbaImage,
    font: &rusttype::Font,
    scale: rusttype::Scale,
    x: i32,
    y: i32,
    text: &str,
    text_color: [u8; 3],
    stroke_color: [u8; 3],
    stroke_width: i32,
) {
    let v_metrics = font.v_metrics(scale);
    let y_offset = y + v_metrics.ascent.ceil() as i32;

    for sx in -stroke_width..=stroke_width {
        for sy in -stroke_width..=stroke_width {
            if sx == 0 && sy == 0 { continue; }
            let dist = ((sx * sx + sy * sy) as f32).sqrt().round() as i32;
            if dist > stroke_width { continue; }

            let mut px = x + sx;
            let py = y_offset + sy;

            for c in text.chars() {
                let glyph = font.glyph(c).scaled(scale);
                let hm = glyph.h_metrics();
                let g = glyph.positioned(rusttype::Point { x: px as f32, y: py as f32 });
                if let Some(bb) = g.pixel_bounding_box() {
                    for by in bb.min.y..bb.max.y {
                        for bx in bb.min.x..bb.max.x {
                            if bx >= 0 && by >= 0
                                && (bx as u32) < canvas.width()
                                && (by as u32) < canvas.height()
                            {
                                canvas.put_pixel(bx as u32, by as u32,
                                    Rgba([stroke_color[0], stroke_color[1], stroke_color[2], 255]));
                            }
                        }
                    }
                }
                px += hm.advance_width.ceil() as i32;
            }
        }
    }

    let mut px = x;
    let py = y_offset;
    for c in text.chars() {
        let glyph = font.glyph(c).scaled(scale);
        let hm = glyph.h_metrics();
        let g = glyph.positioned(rusttype::Point { x: px as f32, y: py as f32 });
        if let Some(bb) = g.pixel_bounding_box() {
            for by in bb.min.y..bb.max.y {
                for bx in bb.min.x..bb.max.x {
                    if bx >= 0 && by >= 0
                        && (bx as u32) < canvas.width()
                        && (by as u32) < canvas.height()
                    {
                        canvas.put_pixel(bx as u32, by as u32,
                            Rgba([text_color[0], text_color[1], text_color[2], 255]));
                    }
                }
            }
        }
        px += hm.advance_width.ceil() as i32;
    }
}

fn layout_text(
    words: &[&str],
    max_width: i32,
    max_height: i32,
    initial_font_size: i32,
    font: &rusttype::Font,
    is_single_word: bool,
) -> Result<(Vec<String>, i32, i32)> {
    let mut font_size = initial_font_size;

    loop {
        if font_size <= 8 { break; }
        let scale = rusttype::Scale::uniform(font_size as f32);
        let v_metrics = font.v_metrics(scale);
        let line_height = (v_metrics.ascent - v_metrics.descent + v_metrics.line_gap) as i32;

        if is_single_word {
            let word_w = get_text_width(font, scale, words[0]);
            let stroke_w = (font_size as f32 * 0.08).max(2.0) as i32;
            let total_w = word_w + stroke_w * 2;
            let total_h = line_height + stroke_w * 2;
            if (total_w as f32) <= (max_width as f32 * 1.5)
                && (total_h as f32) <= (max_height as f32 * 1.2)
            {
                return Ok((vec![words[0].to_string()], line_height, font_size));
            }
            font_size -= 2;
            continue;
        }

        let mut lines: Vec<String> = Vec::new();
        let mut current_line: Vec<String> = Vec::new();

        for &word in words {
            let word_w = get_text_width(font, scale, word);
            if (word_w as f32) > (max_width as f32 * 0.95) {
                if !current_line.is_empty() {
                    lines.push(current_line.join(" "));
                    current_line.clear();
                }
                let mut temp = word.to_string();
                while !temp.is_empty() {
                    let mut found = false;
                    for i in (1..=temp.len()).rev() {
                        let suffix = if i < temp.len() { "-" } else { "" };
                        let part = format!("{}{}", &temp[..i], suffix);
                        let pw = get_text_width(font, scale, &part);
                        if (pw as f32) <= (max_width as f32 * 0.95) || i == 1 {
                            if i == temp.len() {
                                current_line.push(part);
                            } else {
                                lines.push(part);
                            }
                            temp = temp[i..].to_string();
                            found = true;
                            break;
                        }
                    }
                    if !found { break; }
                }
            } else {
                let test_line = if current_line.is_empty() {
                    word.to_string()
                } else {
                    format!("{} {}", current_line.join(" "), word)
                };
                let tw = get_text_width(font, scale, &test_line);
                if (tw as f32) <= (max_width as f32 * 0.95) {
                    current_line.push(word.to_string());
                } else {
                    if !current_line.is_empty() {
                        lines.push(current_line.join(" "));
                    }
                    current_line = vec![word.to_string()];
                }
            }
        }
        if !current_line.is_empty() {
            lines.push(current_line.join(" "));
        }

        let total_h = lines.len() as i32 * line_height;
        if (total_h as f32) <= (max_height as f32 * 0.95) {
            return Ok((lines, total_h, font_size));
        }
        font_size -= 1;
    }

    if words.is_empty() {
        return Ok((vec![String::new()], 0, 8));
    }
    let fallback = words.join(" ");
    let scale = rusttype::Scale::uniform(8.0);
    let v_metrics = font.v_metrics(scale);
    let lh = (v_metrics.ascent - v_metrics.descent + v_metrics.line_gap) as i32;
    Ok((vec![fallback], lh, 8))
}

pub fn download_image(url: &str, save_path: &Path, chapter_url: &str) -> Result<bool> {
    let client = Client::builder()
        .timeout(std::time::Duration::from_secs(30))
        .build()?;

    let mut headers = header::HeaderMap::new();
    headers.insert(
        header::USER_AGENT,
        header::HeaderValue::from_static(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        ),
    );
    if chapter_url.contains("bbato") {
        headers.insert(header::REFERER,
            header::HeaderValue::from_static("https://bbato.com/"));
    } else if chapter_url.contains("vymanga") {
        headers.insert(header::REFERER,
            header::HeaderValue::from_static("https://vymanga.com/"));
    }

    let resp = client.get(url).headers(headers).send()?;
    if !resp.status().is_success() {
        warn!("Download failed for {}: status {}", url, resp.status());
        return Ok(false);
    }

    let bytes = resp.bytes()?;
    if bytes.is_empty() { return Ok(false); }

    std::fs::write(save_path, &bytes)?;
    Ok(true)
}

pub fn download_page(
    page: &crate::scraper::PageInfo,
    out_dir: &Path,
    chapter_url: &str,
) -> Option<PathBuf> {
    let raw_path = out_dir.join(format!("raw_{}.jpg", page.index));
    match download_image(&page.image_url, &raw_path, chapter_url) {
        Ok(true) => {
            debug!("Downloaded page {} to {:?}", page.index, raw_path);
            Some(raw_path)
        }
        _ => {
            warn!("Failed to download page {}", page.index);
            None
        }
    }
}

pub fn merge_short_images(
    raw_paths: &[PathBuf],
    target_height: u32,
    _max_workers: usize,
) -> Result<Vec<PathBuf>> {
    if raw_paths.is_empty() { return Ok(Vec::new()); }

    let img_infos: Vec<(PathBuf, u32, u32)> = raw_paths.iter()
        .filter_map(|p| {
            image::ImageReader::open(p).ok()
                .and_then(|r| r.decode().ok())
                .map(|img| (p.clone(), img.width(), img.height()))
        })
        .collect();

    if img_infos.is_empty() { return Ok(Vec::new()); }

    let target_w = img_infos[0].1;
    let mut groups: Vec<Vec<(PathBuf, u32, u32)>> = Vec::new();
    let mut current_group = Vec::new();
    let mut current_h = 0u32;

    for info in &img_infos {
        let est_h = if info.1 != target_w {
            (info.2 as f64 * target_w as f64 / info.1 as f64) as u32
        } else {
            info.2
        };

        current_group.push(info.clone());
        current_h += est_h;

        if current_h >= target_height {
            groups.push(std::mem::take(&mut current_group));
            current_h = 0;
        }
    }
    if !current_group.is_empty() {
        groups.push(current_group);
    }

    info!("Merging {} image groups (target: {}px)", groups.len(), target_height);

    let out_dir = raw_paths[0].parent().unwrap_or(Path::new("output")).to_path_buf();

    let merged_paths: Vec<PathBuf> = groups.par_iter()
        .enumerate()
        .filter_map(|(idx, group)| {
            let mut current_height = 0u32;
            let mut images_to_paste: Vec<DynamicImage> = Vec::new();

            for (path, _w, _h) in group {
                match image::open(path) {
                    Ok(im) => {
                        let im = if im.width() != target_w {
                            let new_h = (im.height() as f64 * target_w as f64 / im.width() as f64) as u32;
                            im.resize_exact(target_w, new_h, image::imageops::FilterType::Lanczos3)
                        } else {
                            im
                        };
                        current_height += im.height();
                        images_to_paste.push(im);
                    }
                    Err(e) => warn!("Failed to open image {:?}: {}", path, e),
                }
            }

            if images_to_paste.is_empty() { return None; }

            let mut merged = DynamicImage::new_rgb8(target_w, current_height);
            let mut y_offset = 0u32;
            for im in &images_to_paste {
                merged.copy_from(im, 0, y_offset).ok()?;
                y_offset += im.height();
            }

            let new_path = out_dir.join(format!("merged_raw_{:03}.jpg", idx + 1));
            merged.save(&new_path).ok()?;

            for (path, _, _) in group {
                let _ = std::fs::remove_file(path);
            }
            Some(new_path)
        })
        .collect();

    Ok(merged_paths)
}

pub fn smart_slice_image(image_path: &Path, target_height: u32, out_dir: &Path) -> Result<Vec<PathBuf>> {
    let img = image::open(image_path)?;
    let (width, height) = img.dimensions();

    if height <= target_height {
        return Ok(vec![image_path.to_path_buf()]);
    }

    let gray = img.to_luma8();
    let edges = canny(&gray, 50.0, 150.0);
    let dilated = dilate(&edges, Norm::LInf, 30);

    let mut row_density: Vec<f32> = Vec::with_capacity(height as usize);
    for y in 0..height {
        let mut sum = 0u32;
        for x in 0..width {
            if dilated.get_pixel(x, y).0[0] > 0 { sum += 1; }
        }
        row_density.push(sum as f32 / 255.0);
    }

    let base_name = image_path.file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("slice");
    let mut sliced_paths = Vec::new();
    let mut y_start = 0u32;
    let mut part = 1u32;

    while y_start < height {
        let mut y_end = y_start + target_height;

        if y_end >= height {
            y_end = height;
            let slice = img.crop_imm(0, y_start, width, y_end - y_start);
            let slice_path = out_dir.join(format!("{}_part{}.jpg", base_name, part));
            slice.save(&slice_path)?;
            sliced_paths.push(slice_path);
            break;
        }

        let gap_size = 15usize;
        let mut found_safe_cut = false;
        let mut tolerance = 0.0f32;
        let max_tolerance = width as f32 * 0.10;

        while tolerance <= max_tolerance && !found_safe_cut {
            let search_up = (y_start + (target_height as f32 * 0.5) as u32)
                .max(y_start + gap_size as u32);

            for y in (search_up..=y_end).rev() {
                if y < gap_size as u32 { continue; }
                let y_idx = y as usize;
                if y_idx >= row_density.len() { continue; }
                let start_idx = y_idx.saturating_sub(gap_size);
                if start_idx >= y_idx { continue; }
                let slice = &row_density[start_idx..y_idx];
                if slice.iter().all(|&v| v <= tolerance) {
                    y_end = y - (gap_size as u32 / 2);
                    found_safe_cut = true;
                    break;
                }
            }

            if !found_safe_cut {
                let search_down = (y_start + (target_height as f32 * 1.5) as u32)
                    .min(height - gap_size as u32);
                for y in y_end..=search_down {
                    let y_idx = y as usize;
                    if y_idx + gap_size > row_density.len() { break; }
                    let slice = &row_density[y_idx..y_idx + gap_size];
                    if slice.iter().all(|&v| v <= tolerance) {
                        y_end = y + (gap_size as u32 / 2);
                        found_safe_cut = true;
                        break;
                    }
                }
            }

            if !found_safe_cut {
                if tolerance == 0.0 {
                    tolerance = width as f32 * 0.02;
                } else {
                    tolerance += width as f32 * 0.03;
                }
            }
        }

        if !found_safe_cut {
            warn!("Area too dense, force-cutting at Y:{}", y_end);
        }

        let slice = img.crop_imm(0, y_start, width, y_end - y_start);
        let slice_path = out_dir.join(format!("{}_part{}.jpg", base_name, part));
        slice.save(&slice_path)?;
        sliced_paths.push(slice_path);

        y_start = y_end;
        part += 1;
    }

    info!("Smart sliced {} into {} parts", image_path.display(), sliced_paths.len());
    Ok(sliced_paths)
}
