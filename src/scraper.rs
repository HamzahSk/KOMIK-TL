use std::collections::HashMap;

use anyhow::{Context, Result};
use log::{debug, info, warn};
use reqwest::blocking::Client;
use reqwest::header;
use scraper::{Html, Selector};

use crate::config::Config;

const VYMANGA_URL: &str = "https://vymanga.com";
const BBATO_URL: &str = "https://bbato.com";
const USER_AGENT: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";

#[derive(Debug, Clone)]
pub struct ChapterInfo {
    pub url: String,
    pub name: String,
}

#[derive(Debug, Clone)]
pub struct PageInfo {
    pub index: usize,
    pub image_url: String,
}

#[derive(Debug, Clone)]
pub struct ScrapedChapter {
    pub pages: Vec<PageInfo>,
    pub manga_title: String,
    pub chapter_name: String,
}

fn detect_provider(url: &str) -> &str {
    if url.to_lowercase().contains("bbato") {
        "bbato"
    } else {
        "vymanga"
    }
}

fn build_client() -> Client {
    let mut headers = header::HeaderMap::new();
    headers.insert(
        header::USER_AGENT,
        header::HeaderValue::from_static(USER_AGENT),
    );
    Client::builder()
        .default_headers(headers)
        .timeout(std::time::Duration::from_secs(30))
        .build()
        .expect("Failed to build HTTP client")
}

fn fetch_with_fallback(client: &Client, url: &str, extra_headers: Option<&HashMap<String, String>>, cors_proxy: &str) -> Result<String> {
    let mut req = client.get(url);
    if let Some(headers) = extra_headers {
        for (k, v) in headers {
            req = req.header(k.as_str(), v.as_str());
        }
    }
    match req.send() {
        Ok(resp) => {
            if resp.status().is_success() {
                return resp.text().context("Failed to read response body");
            }
            warn!("Direct request to {} failed with status {}, trying CORS proxy", url, resp.status());
        }
        Err(e) => {
            warn!("Direct request to {} failed: {}. Trying CORS proxy...", url, e);
        }
    }
    let proxy_url = format!("{}{}", cors_proxy, url);
    debug!("Fetching via CORS proxy: {}", proxy_url);
    let mut req = client.get(&proxy_url);
    if let Some(headers) = extra_headers {
        for (k, v) in headers {
            req = req.header(k.as_str(), v.as_str());
        }
    }
    let resp = req.send().context("CORS proxy request failed")?;
    if !resp.status().is_success() {
        anyhow::bail!("CORS proxy returned status {}", resp.status());
    }
    resp.text().context("Failed to read CORS proxy response body")
}

pub fn get_chapter_list(manga_url: &str, config: &Config) -> Result<Vec<ChapterInfo>> {
    let client = build_client();
    let provider = detect_provider(manga_url);

    match provider {
        "vymanga" => {
            info!("Scraping chapter list from VyManga: {}", manga_url);
            let html = fetch_with_fallback(&client, manga_url, None, &config.cors_proxy)?;
            let document = Html::parse_document(&html);
            let selector = Selector::parse(".list-group > a")
                .map_err(|e| anyhow::anyhow!("Invalid CSS selector: {}", e))?;
            let span_selector = Selector::parse("span")
                .map_err(|e| anyhow::anyhow!("Invalid CSS selector: {}", e))?;

            let mut chapters = Vec::new();
            for element in document.select(&selector) {
                let href = element.value().attr("href").unwrap_or("");
                let name = if let Some(span) = element.select(&span_selector).next() {
                    span.text().collect::<String>().trim().to_string()
                } else {
                    "Unknown_Chapter".to_string()
                };
                if !href.is_empty() {
                    let full_url = url::Url::parse(VYMANGA_URL)
                        .and_then(|base| base.join(href))
                        .map(|u| u.to_string())
                        .unwrap_or_else(|_| format!("{}{}", VYMANGA_URL, href));
                    chapters.push(ChapterInfo { url: full_url, name });
                }
            }
            info!("Found {} chapters from VyManga", chapters.len());
            Ok(chapters)
        }
        _ => {
            info!("Scraping chapter list from BBato: {}", manga_url);
            let slug = manga_url.trim_end_matches('/').split('/').last()
                .unwrap_or("")
                .to_string();
            if slug.is_empty() {
                anyhow::bail!("Could not extract slug from BBato URL: {}", manga_url);
            }
            let api_url = format!("{}/get-chapter-list?slug={}", BBATO_URL, slug);
            let mut bbato_headers = HashMap::new();
            bbato_headers.insert("Accept".to_string(), "application/json, text/javascript, */*; q=0.01".to_string());
            bbato_headers.insert("X-Requested-With".to_string(), "XMLHttpRequest".to_string());
            bbato_headers.insert("Referer".to_string(), manga_url.to_string());

            let html = fetch_with_fallback(&client, &api_url, Some(&bbato_headers), &config.cors_proxy)?;
            let json: serde_json::Value = serde_json::from_str(&html)
                .context("Failed to parse BBato API JSON response")?;

            let mut chapters = Vec::new();
            if let Some(data) = json.get("data").and_then(|d| d.as_array()) {
                for ch in data {
                    let chapter_slug = ch.get("chapter_slug")
                        .and_then(|s| s.as_str())
                        .unwrap_or("");
                    let chapter_name = ch.get("chapter_name")
                        .and_then(|s| s.as_str())
                        .unwrap_or("Unknown_Chapter");
                    let ch_url = format!("{}/read/{}/{}", BBATO_URL, slug, chapter_slug);
                    chapters.push(ChapterInfo {
                        url: ch_url,
                        name: chapter_name.to_string(),
                    });
                }
            }
            info!("Found {} chapters from BBato", chapters.len());
            Ok(chapters)
        }
    }
}

pub fn scrape_chapter(chapter_url: &str, config: &Config) -> Result<ScrapedChapter> {
    let client = build_client();
    let provider = detect_provider(chapter_url);

    info!("Scraping chapter page: {}", chapter_url);

    let extra_headers = if provider == "bbato" {
        let mut h = HashMap::new();
        h.insert("Referer".to_string(), format!("{}/", BBATO_URL));
        Some(h)
    } else {
        None
    };

    let html = fetch_with_fallback(&client, chapter_url, extra_headers.as_ref(), &config.cors_proxy)?;
    let document = Html::parse_document(&html);

    let (manga_title, chapter_name) = get_chapter_name(&document, chapter_url, provider);

    let pages = match provider {
        "vymanga" => get_vymanga_pages(&document)?,
        _ => get_bbato_pages(&document)?,
    };

    info!("Scraped chapter: manga='{}', chapter='{}', {} pages", manga_title, chapter_name, pages.len());

    Ok(ScrapedChapter { pages, manga_title, chapter_name })
}

fn get_vymanga_pages(document: &Html) -> Result<Vec<PageInfo>> {
    let selector = Selector::parse("img.d-block")
        .map_err(|e| anyhow::anyhow!("Invalid CSS selector: {}", e))?;
    let mut pages = Vec::new();
    for (idx, img) in document.select(&selector).enumerate() {
        let img_url = img.value().attr("data-src")
            .or_else(|| img.value().attr("src"))
            .unwrap_or("");
        if !img_url.is_empty() {
            let full_url = url::Url::parse(VYMANGA_URL)
                .and_then(|base| base.join(img_url))
                .map(|u| u.to_string())
                .unwrap_or_else(|_| {
                    if img_url.starts_with("http") {
                        img_url.to_string()
                    } else {
                        format!("{}{}", VYMANGA_URL, img_url)
                    }
                });
            pages.push(PageInfo { index: idx, image_url: full_url });
        }
    }
    Ok(pages)
}

fn get_bbato_pages(document: &Html) -> Result<Vec<PageInfo>> {
    let selector = Selector::parse(".pages .page:not(.notice-page) img")
        .map_err(|e| anyhow::anyhow!("Invalid CSS selector: {}", e))?;
    let mut pages = Vec::new();
    for (idx, img) in document.select(&selector).enumerate() {
        let img_url = img.value().attr("data-src")
            .or_else(|| img.value().attr("src"))
            .unwrap_or("");
        if !img_url.is_empty() {
            let full_url = if img_url.starts_with("http") {
                img_url.to_string()
            } else {
                url::Url::parse(BBATO_URL)
                    .and_then(|base| base.join(img_url))
                    .map(|u| u.to_string())
                    .unwrap_or_else(|_| format!("{}{}", BBATO_URL, img_url))
            };
            pages.push(PageInfo { index: idx, image_url: full_url });
        }
    }
    Ok(pages)
}

fn get_chapter_name(document: &Html, _chapter_url: &str, provider: &str) -> (String, String) {
    let default = ("Unknown Title".to_string(), "Unknown Chapter".to_string());

    let parse_ld_json = |doc: &Html| -> Option<(String, String)> {
        let script_selector = Selector::parse("script[type=\"application/ld+json\"]").ok()?;
        for script in doc.select(&script_selector) {
            let json_text: String = script.text().collect();
            if json_text.trim().is_empty() { continue; }
            if let Ok(data) = serde_json::from_str::<serde_json::Value>(&json_text) {
                if data.get("@type").and_then(|t| t.as_str()) == Some("BreadcrumbList") {
                    if let Some(items) = data.get("itemListElement").and_then(|i| i.as_array()) {
                        if items.len() >= 2 {
                            let title = items[items.len() - 2]
                                .get("name").and_then(|n| n.as_str())
                                .unwrap_or("Unknown Title");
                            let ch_name = items[items.len() - 1]
                                .get("name").and_then(|n| n.as_str())
                                .unwrap_or("Unknown Chapter");
                            return Some((title.to_string(), ch_name.to_string()));
                        }
                    }
                }
            }
        }
        None
    };

    match provider {
        "bbato" => {
            if let Some(result) = parse_ld_json(document) {
                return result;
            }
            default
        }
        "vymanga" | _ => {
            if let Ok(info_selector) = Selector::parse("#chapter-info") {
                if let Some(info_div) = document.select(&info_selector).next() {
                    let text: String = info_div.text().collect();
                    let text = text.trim().to_string();
                    if let Some(pos) = text.find(':') {
                        let title = text[..pos].trim().to_string();
                        let ch_name = text[pos + 1..].trim().to_string();
                        return (title, ch_name);
                    }
                    return (text, "Unknown Chapter".to_string());
                }
            }
            if let Some(result) = parse_ld_json(document) {
                return result;
            }
            default
        }
    }
}
