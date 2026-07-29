mod config;
mod image_utils;
mod ocr;
mod scraper;
mod translator;

use std::fs;
use std::io::Write;
use std::path::PathBuf;

use anyhow::{Context, Result};
use log::{error, info, warn};
use rayon::prelude::*;
use regex::Regex;

use config::Config;
use image_utils::{download_page, merge_short_images, smart_slice_image, Typesetter};
use ocr::OCREngine;
use scraper::{get_chapter_list, scrape_chapter, ScrapedChapter};
use translator::{AiTranslator, apply_translations, filter_sfx_blocks};

fn sanitize_filename(s: &str, max_len: usize) -> String {
    let re = Regex::new(r"[^a-zA-Z0-9_\-\s]").unwrap();
    let s = re.replace_all(s, "_").to_string();
    let s = s.trim().to_string();
    if s.len() > max_len {
        s[..max_len].to_string()
    } else {
        s
    }
}

fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info"))
        .format(|buf, record| {
            use chrono::Local;
            writeln!(
                buf,
                "[{}] [{}] [{}:{}] {}",
                Local::now().format("%Y-%m-%d %H:%M:%S%.3f"),
                record.level(),
                record.file().unwrap_or("unknown"),
                record.line().unwrap_or(0),
                record.args()
            )
        })
        .init();

    info!("KOMIK-TL Rust v{} starting", env!("CARGO_PKG_VERSION"));

    let config = Config::load();
    info!("Configuration loaded");

    let mangas: Vec<String> = config.url_manga.iter()
        .filter(|u| !u.trim().is_empty())
        .cloned()
        .collect();
    let chapters: Vec<String> = config.url_chapter.iter()
        .filter(|u| !u.trim().is_empty())
        .cloned()
        .collect();

    if mangas.is_empty() && chapters.is_empty() {
        warn!("No URLs configured in config. Nothing to process.");
        return Ok(());
    }

    fs::create_dir_all(&config.output_dir)?;
    fs::create_dir_all(&config.ai_logs_dir)?;
    info!("Output directories created");

    let mut all_targets: Vec<String> = Vec::new();

    for manga_url in &mangas {
        info!("[Scraper] Fetching chapter list from: {}", manga_url);
        match get_chapter_list(manga_url, &config) {
            Ok(ch_list) => {
                for ch in ch_list {
                    if !all_targets.contains(&ch.url) {
                        all_targets.push(ch.url);
                    }
                }
            }
            Err(e) => {
                error!("[Scraper] Failed to get chapter list: {}", e);
            }
        }
    }

    for ch_url in &chapters {
        if !all_targets.contains(ch_url) {
            all_targets.push(ch_url.clone());
        }
    }

    info!("Total chapters to process: {}", all_targets.len());

    let ocr_engine = OCREngine::new()
        .context("Failed to initialize OCR engine")?;
    let mut translator = AiTranslator::new()
        .context("Failed to initialize translator")?;

    for ch_url in &all_targets {
        info!("================================================");
        info!("Processing chapter URL: {}", ch_url);
        info!("================================================");

        translator.reset_chapter_session();

        let scraped: ScrapedChapter = match scrape_chapter(ch_url, &config) {
            Ok(s) => s,
            Err(e) => {
                error!("[Scraper] Failed to scrape chapter: {}", e);
                continue;
            }
        };

        let manga_title_safe = sanitize_filename(&scraped.manga_title, 100);
        let chapter_name_safe = sanitize_filename(&scraped.chapter_name, 100);

        let manga_dir = config.output_dir.join(&manga_title_safe);
        let out_dir = manga_dir.join(&chapter_name_safe);
        fs::create_dir_all(&out_dir)?;

        info!("Manga: {}", manga_title_safe);
        info!("Chapter: {}", chapter_name_safe);
        info!("Pages to process: {}", scraped.pages.len());

        if scraped.pages.is_empty() {
            warn!("No pages found, skipping chapter");
            continue;
        }

        // Phase 1: Download all pages in parallel
        info!("[Phase 1] Downloading {} pages (workers={})...",
            scraped.pages.len(), config.download_workers);

        let downloaded: Vec<PathBuf> = scraped.pages.par_iter()
            .filter_map(|page| download_page(page, &out_dir, ch_url))
            .collect();

        let mut sorted_paths: Vec<PathBuf> = {
            let mut p: Vec<_> = downloaded.iter().cloned().collect();
            p.sort_by(|a, b| {
                let a_idx = a.file_stem().and_then(|s| s.to_str())
                    .and_then(|s| s.strip_prefix("raw_"))
                    .and_then(|s| s.parse::<usize>().ok())
                    .unwrap_or(0);
                let b_idx = b.file_stem().and_then(|s| s.to_str())
                    .and_then(|s| s.strip_prefix("raw_"))
                    .and_then(|s| s.parse::<usize>().ok())
                    .unwrap_or(0);
                a_idx.cmp(&b_idx)
            });
            p
        };

        info!("[Phase 2] Merging short images (target: {}px)...", config.merge_target_height);
        sorted_paths = match merge_short_images(&sorted_paths, config.merge_target_height, config.merge_workers) {
            Ok(paths) => paths,
            Err(e) => {
                error!("Merge failed: {}", e);
                sorted_paths
            }
        };

        info!("[Phase 2.5] Smart slicing (target: {}px)...", config.slice_target_height);
        let final_paths: Vec<PathBuf> = sorted_paths.par_iter()
            .flat_map(|path| {
                match smart_slice_image(path, config.slice_target_height, &out_dir) {
                    Ok(slices) => {
                        if slices.len() > 1 {
                            let _ = fs::remove_file(path);
                        }
                        slices
                    }
                    Err(e) => {
                        warn!("Smart slice failed for {:?}: {}", path, e);
                        vec![path.to_path_buf()]
                    }
                }
            })
            .collect();

        info!("[Phase 3] OCR text extraction from {} images...", final_paths.len());

        let mut page_blocks: Vec<(PathBuf, Vec<ocr::TextBlock>)> = Vec::new();
        let mut all_texts_for_ai = Vec::new();

        for path in &final_paths {
            let mut blocks = match ocr_engine.detect_and_merge(
                path.to_str().unwrap_or("")
            ) {
                Ok(b) => b,
                Err(e) => {
                    warn!("OCR failed for {:?}: {}", path, e);
                    Vec::new()
                }
            };

            if blocks.len() == 1 && blocks[0].text.split_whitespace().count() <= 1 {
                blocks.clear();
            }

            let texts = filter_sfx_blocks(&mut blocks, &config);

            for t in &texts {
                all_texts_for_ai.push(t.clone());
            }

            page_blocks.push((path.clone(), blocks));
        }

        info!("[Phase 4] AI translation of {} text blocks...", all_texts_for_ai.len());

        let translations = if !all_texts_for_ai.is_empty() {
            let tr = translator.translate_batch(&all_texts_for_ai, &config);

            // Save AI logs
            let input_log_path = config.ai_logs_dir
                .join(format!("input_{}_{}.json", manga_title_safe, chapter_name_safe));
            let output_log_path = config.ai_logs_dir
                .join(format!("output_{}_{}.json", manga_title_safe, chapter_name_safe));

            if let Ok(json) = serde_json::to_string_pretty(&all_texts_for_ai) {
                let _ = fs::write(&input_log_path, &json);
            }
            if let Ok(json) = serde_json::to_string_pretty(&tr) {
                let _ = fs::write(&output_log_path, &json);
            }
            info!("AI logs saved to ai_logs/");

            tr
        } else {
            Vec::new()
        };

        // Apply translations back to blocks
        for (_, blocks) in &mut page_blocks {
            apply_translations(blocks, &translations, &config);
        }

        info!("[Phase 5] Typesetting {} pages...", page_blocks.len());

        for (idx, (path, blocks)) in page_blocks.iter().enumerate() {
            let final_path = out_dir.join(format!("terjemahan_{:03}.webp", idx + 1));

            if blocks.is_empty() {
                match image::open(path) {
                    Ok(img) => {
                        let _ = img.save(&final_path);
                    }
                    Err(e) => warn!("Failed to open image {:?}: {}", path, e),
                }
                let _ = fs::remove_file(path);
                continue;
            }

            match image::open(path) {
                Ok(img) => {
                    match Typesetter::apply_text(
                        &img,
                        blocks,
                        &config.font_path,
                        &config.sfx_font_path,
                    ) {
                        Ok(result) => {
                            if let Err(e) = result.save(&final_path) {
                                warn!("Failed to save result for page {}: {}", idx + 1, e);
                            }
                        }
                        Err(e) => {
                            warn!("Typesetting failed for page {}: {}", idx + 1, e);
                            let _ = img.save(&final_path);
                        }
                    }
                }
                Err(e) => warn!("Failed to open image {:?}: {}", path, e),
            }

            let _ = fs::remove_file(path);
        }

        // Phase 6: CBZ archive
        let cbz_path = manga_dir.join(format!("{}.cbz", chapter_name_safe));
        info!("[Phase 6] Archiving to: {:?}", cbz_path);

        let mut files: Vec<_> = fs::read_dir(&out_dir)
            .unwrap_or_else(|_| fs::read_dir(".").unwrap())
            .filter_map(|e| e.ok())
            .filter(|e| e.path().is_file())
            .map(|e| e.path())
            .collect();
        files.sort();

        let cbz_file = fs::File::create(&cbz_path)?;
        let mut zip = zip::ZipWriter::new(cbz_file);

        for file_path in &files {
            let file_name = file_path.file_name()
                .and_then(|n| n.to_str())
                .unwrap_or("unknown");
            let data = std::fs::read(file_path)?;
            let options: zip::write::FileOptions<()> = zip::write::FileOptions::default()
                .compression_method(zip::CompressionMethod::Deflated);
            if let Err(e) = zip.start_file(file_name, options) {
                warn!("Failed to add {} to zip: {}", file_name, e);
                continue;
            }
            if let Err(e) = zip.write_all(&data) {
                warn!("Failed to write {} to zip: {}", file_name, e);
            }
        }

        zip.finish()?;

        // Cleanup temp files
        for file_path in &files {
            let _ = fs::remove_file(file_path);
        }
        let _ = fs::remove_dir(&out_dir);

        info!("[Done] Archived {} to {}/", chapter_name_safe, manga_title_safe);
    }

    info!("================================================");
    info!("All chapters processed successfully!");
    info!("================================================");

    Ok(())
}
