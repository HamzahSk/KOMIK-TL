use std::f32::consts::PI;

use anyhow::Result;
use image::DynamicImage;
use log::{debug, info};
use regex::Regex;

use leptess::{leptonica, tesseract};

#[derive(Debug, Clone)]
pub struct TextBlock {
    pub text: String,
    pub box_coords: [i32; 4],
    pub orig_line_height: f32,
    pub angle: f32,
    pub translated_text: Option<String>,
}

pub struct OCREngine {
    re_clean: Regex,
    re_keep: Regex,
}

impl OCREngine {
    pub fn new() -> Result<Self> {
        Ok(Self {
            re_clean: Regex::new("[^A-Z0-9\\s.,!?'\"~-]")?,
            re_keep: Regex::new("\\s+")?,
        })
    }

    pub fn detect_and_merge(&self, img_path: &str) -> Result<Vec<TextBlock>> {
        debug!("OCR processing: {}", img_path);

        let img = image::open(img_path)
            .map_err(|e| anyhow::anyhow!("Failed to open image {}: {}", img_path, e))?;
        let preprocessed = self.preprocess_for_ocr(&img);

        let temp_path = format!("/tmp/komik_tesseract_{}.png", std::process::id());
        preprocessed.save(&temp_path)
            .map_err(|e| anyhow::anyhow!("Failed to save temp image: {}", e))?;

        let raw_lines = self.run_tesseract_word_by_word(&temp_path)?;

        let _ = std::fs::remove_file(&temp_path);

        let cleaned = self.clean_text_blocks(&raw_lines);
        let cleaned_len = cleaned.len();
        let merged = self.merge_dialog_bubbles(cleaned);

        info!("OCR result: raw={} cleaned={} merged={}",
            raw_lines.len(), cleaned_len, merged.len());

        Ok(merged)
    }

    fn preprocess_for_ocr(&self, img: &DynamicImage) -> DynamicImage {
        let w = img.width() * 2;
        let h = img.height() * 2;
        let upscaled = img.resize_exact(w, h, image::imageops::FilterType::Lanczos3);

        let gray = upscaled.to_luma8();
        let enhanced = self.apply_clahe(&gray, 2.0, 8);

        DynamicImage::ImageLuma8(enhanced)
    }

    fn apply_clahe(&self, img: &image::GrayImage, clip_limit: f32, tile_size: u32) -> image::GrayImage {
        let (width, height) = img.dimensions();
        let tiles_x = (width + tile_size - 1) / tile_size;
        let tiles_y = (height + tile_size - 1) / tile_size;

        let mut tile_cdfs: Vec<Vec<f32>> = Vec::with_capacity((tiles_x * tiles_y) as usize);

        for ty in 0..tiles_y {
            for tx in 0..tiles_x {
                let x0 = tx * tile_size;
                let y0 = ty * tile_size;
                let x1 = (x0 + tile_size).min(width);
                let y1 = (y0 + tile_size).min(height);

                let mut hist = [0u32; 256];
                for y in y0..y1 {
                    for x in x0..x1 {
                        let p = img.get_pixel(x, y).0[0] as usize;
                        hist[p] += 1;
                    }
                }
                let total_pixels = ((x1 - x0) * (y1 - y0)) as f32;
                let clip_limit_pixels = (clip_limit * total_pixels / 256.0).ceil() as u32;

                let mut clipped = 0u32;
                for h in hist.iter_mut() {
                    if *h > clip_limit_pixels {
                        clipped += *h - clip_limit_pixels;
                        *h = clip_limit_pixels;
                    }
                }
                let redistribute = clipped / 256;
                for h in hist.iter_mut() {
                    *h += redistribute;
                }

                let mut cdf = Vec::with_capacity(256);
                let mut sum = 0u32;
                for &h in hist.iter() {
                    sum += h;
                    cdf.push(sum as f32 / total_pixels);
                }
                for v in cdf.iter_mut() {
                    *v = (*v * 255.0).round().min(255.0);
                }
                tile_cdfs.push(cdf);
            }
        }

        let tile_w = tile_size;
        let tile_h = tile_size;
        let mut output = image::GrayImage::new(width, height);

        for y in 0..height {
            for x in 0..width {
                let tx = (x / tile_w).min(tiles_x - 1);
                let ty = (y / tile_h).min(tiles_y - 1);
                let px = img.get_pixel(x, y).0[0] as usize;
                let mut val = tile_cdfs[(ty * tiles_x + tx) as usize][px];

                if tx > 0 && tx < tiles_x - 1 && ty > 0 && ty < tiles_y - 1 {
                    let x_ratio = (x % tile_w) as f32 / tile_w as f32;
                    let y_ratio = (y % tile_h) as f32 / tile_h as f32;
                    let v00 = tile_cdfs[(ty * tiles_x + tx) as usize][px];
                    let v10 = tile_cdfs[(ty * tiles_x + tx + 1) as usize][px];
                    let v01 = tile_cdfs[((ty + 1) * tiles_x + tx) as usize][px];
                    let v11 = tile_cdfs[((ty + 1) * tiles_x + tx + 1) as usize][px];
                    val = (1.0 - y_ratio) * ((1.0 - x_ratio) * v00 + x_ratio * v10)
                        + y_ratio * ((1.0 - x_ratio) * v01 + x_ratio * v11);
                }

                let val = val.round().min(255.0).max(0.0) as u8;
                output.put_pixel(x, y, image::Luma([val]));
            }
        }
        output
    }

    fn run_tesseract_word_by_word(&self, img_path: &str) -> Result<Vec<(String, [i32; 4], f32)>> {
        let pix = leptonica::pix_read(std::path::Path::new(img_path))
            .map_err(|e| anyhow::anyhow!("Failed to read image for Tesseract: {:?}", e))?;

        let mut api = tesseract::TessApi::new(None, "eng")
            .map_err(|e| anyhow::anyhow!("Failed to initialize Tesseract: {:?}", e))?;

        api.set_image(&pix);
        api.recognize();

        let boxes = api.get_component_images(
            leptess::capi::TessPageIteratorLevel_RIL_WORD,
            true,
        );

        let mut results = Vec::new();

        let boxa = match boxes {
            Some(b) => b,
            None => return Ok(results),
        };

        for b in &boxa {
            let geom = b.get_geometry();
            let x = geom.x;
            let y = geom.y;
            let w = geom.w;
            let h = geom.h;

            if w < 3 || h < 3 {
                continue;
            }

            let tmp_pix = leptonica::pix_read(std::path::Path::new(img_path))
                .map_err(|e| anyhow::anyhow!("Failed to re-read image: {:?}", e))?;

            let mut tmp_api = tesseract::TessApi::new(None, "eng")
                .map_err(|e| anyhow::anyhow!("Failed to init Tesseract: {:?}", e))?;

            tmp_api.set_image(&tmp_pix);
            tmp_api.set_rectangle(x, y, w, h);
            tmp_api.recognize();

            let text = match tmp_api.get_utf8_text() {
                Ok(t) => t.trim().to_string(),
                Err(_) => continue,
            };

            if text.is_empty() || text.len() < 2 {
                continue;
            }

            let conf = tmp_api.mean_text_conf();
            if conf < 20 {
                debug!("Low confidence ({}) for text: {}", conf, text);
            }

            let box_coords = [x, y, x + w, y + h];
            let angle = if w > 0 {
                (h as f32).atan2(w as f32) * 180.0 / PI
            } else {
                0.0
            };

            results.push((text, box_coords, angle));
        }

        Ok(results)
    }

    fn clean_text_blocks(&self, raw_lines: &[(String, [i32; 4], f32)]) -> Vec<(String, [i32; 4], f32)> {
        raw_lines.iter().map(|(text, box_coords, angle)| {
            let fixed = text
                .replace('|', "I")
                .replace('[', "I")
                .replace(']', "I")
                .replace('{', "I")
                .replace('}', "I")
                .to_uppercase();

            let cleaned = self.re_clean.replace_all(&fixed, "").to_string();
            let cleaned = self.re_keep.replace_all(&cleaned, " ").trim().to_string();
            (cleaned, *box_coords, *angle)
        }).filter(|(t, _, _)| !t.is_empty() && t.len() >= 2)
        .collect()
    }

    fn merge_dialog_bubbles(&self, lines: Vec<(String, [i32; 4], f32)>) -> Vec<TextBlock> {
        if lines.is_empty() {
            return Vec::new();
        }

        let mut lines = lines;
        lines.sort_by(|a, b| {
            let cy_a = (a.1[1] + a.1[3]) as f32 / 2.0;
            let cy_b = (b.1[1] + b.1[3]) as f32 / 2.0;
            cy_a.partial_cmp(&cy_b).unwrap_or(std::cmp::Ordering::Equal)
        });

        let mut merged = Vec::new();
        let mut visited = vec![false; lines.len()];

        for i in 0..lines.len() {
            if visited[i] { continue; }
            visited[i] = true;

            let mut group_texts = vec![lines[i].0.clone()];
            let mut group_boxes = vec![lines[i].1];
            let mut group_angles = vec![lines[i].2];

            for j in i + 1..lines.len() {
                if visited[j] { continue; }

                let prev_box = group_boxes.last().unwrap();
                let next_box = &lines[j].1;

                let prev_h = prev_box[3] - prev_box[1];
                let next_h = next_box[3] - next_box[1];
                let min_h = prev_h.min(next_h);
                let max_h = prev_h.max(next_h);

                let is_horiz_overlap = (prev_box[2].min(next_box[2]) - prev_box[0].max(next_box[0])) > -5;
                let prev_cx = (prev_box[0] + prev_box[2]) as f32 / 2.0;
                let next_cx = (next_box[0] + next_box[2]) as f32 / 2.0;
                let max_w = (prev_box[2] - prev_box[0]).max(next_box[2] - next_box[0]) as f32;
                let is_center_aligned = (prev_cx - next_cx).abs() < (max_w * 0.6);
                let is_horiz_aligned = is_horiz_overlap && is_center_aligned;

                let vert_gap = next_box[1] - prev_box[3];
                let max_vert_gap = (10.0_f32).max(min_h as f32 * 0.8);
                let is_vert_close = (-min_h as f32 * 2.0) <= vert_gap as f32
                    && (vert_gap as f32) <= max_vert_gap;

                let is_height_similar = (max_h as f32 / min_h.max(1) as f32) < 3.0;
                let is_angle_similar = (lines[j].2 - group_angles.last().unwrap()).abs() < 12.0;

                if is_horiz_aligned && is_vert_close && is_height_similar && is_angle_similar {
                    group_texts.push(lines[j].0.clone());
                    group_boxes.push(lines[j].1);
                    group_angles.push(lines[j].2);
                    visited[j] = true;
                }
            }

            let min_x = group_boxes.iter().map(|b| b[0]).min().unwrap_or(0);
            let min_y = group_boxes.iter().map(|b| b[1]).min().unwrap_or(0);
            let max_x = group_boxes.iter().map(|b| b[2]).max().unwrap_or(0);
            let max_y = group_boxes.iter().map(|b| b[3]).max().unwrap_or(0);

            let combined = group_texts.join(" ");
            let letter_count = combined.chars().filter(|c| c.is_ascii_alphabetic()).count();

            if letter_count > 2 {
                let avg_height: f32 = group_boxes.iter()
                    .map(|b| (b[3] - b[1]) as f32)
                    .sum::<f32>() / group_boxes.len() as f32;
                let avg_angle: f32 = group_angles.iter().sum::<f32>() / group_angles.len() as f32;

                merged.push(TextBlock {
                    text: combined,
                    box_coords: [min_x, min_y, max_x, max_y],
                    orig_line_height: avg_height,
                    angle: avg_angle,
                    translated_text: None,
                });
            }
        }

        merged
    }
}
