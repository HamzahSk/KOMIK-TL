use std::time::Duration;

use anyhow::Result;
use log::{debug, info, warn};
use rand::Rng;
use regex::Regex;
use reqwest::blocking::Client;
use serde_json::json;

use crate::config::Config;
use crate::ocr::TextBlock;

pub struct AiTranslator {
    client: Client,
    current_chat_id: Option<String>,
    re_think: Regex,
    re_number_prefix: Regex,
}

impl AiTranslator {
    pub fn new() -> Result<Self> {
        Ok(Self {
            client: Client::builder()
                .timeout(Duration::from_secs(60))
                .build()?,
            current_chat_id: None,
            re_think: Regex::new(r"(?is)<think>.*?</think>")?,
            re_number_prefix: Regex::new(r"^\d+[\.\)]\s*")?,
        })
    }

    pub fn reset_chapter_session(&mut self) {
        self.current_chat_id = None;
        info!("[Translator] Chat session reset for new chapter");
    }

    pub fn translate_batch(&mut self, texts: &[String], config: &Config) -> Vec<String> {
        if texts.is_empty() {
            return Vec::new();
        }

        let batches = self.create_batches(texts, config);
        let mut all_translations = Vec::new();

        for (batch_idx, batch) in batches.iter().enumerate() {
            info!("[Batch {}/{}] Translating {} texts ({} chars)",
                batch_idx + 1, batches.len(), batch.len(),
                batch.iter().map(|t| t.len()).sum::<usize>());

            let user_message = self.format_batch_text(batch, config);

            let translations = self.translate_with_fallback(&user_message, batch, config);

            let final_translations = match translations {
                Some(t) => {
                    info!("[Batch {}] Translation successful", batch_idx + 1);
                    t
                }
                None => {
                    warn!("[Batch {}] All APIs failed, using original text", batch_idx + 1);
                    batch.clone()
                }
            };

            all_translations.extend(final_translations);
            std::thread::sleep(Duration::from_millis(1500));
        }

        all_translations
    }

    fn translate_with_fallback(&mut self, prompt: &str, batch: &[String], config: &Config) -> Option<Vec<String>> {
        for attempt in 0..2 {
            info!("[Attempt {}/2] Trying main API...", attempt + 1);
            match self.main_translate(prompt, config) {
                Ok(response) => {
                    if let Some(translations) = self.verify_and_clean(&response, batch) {
                        return Some(translations);
                    }
                    warn!("Main API response format invalid, attempt {}/2", attempt + 1);
                }
                Err(e) => {
                    warn!("Main API error (attempt {}): {}", attempt + 1, e);
                }
            }
            if attempt == 0 {
                std::thread::sleep(Duration::from_secs(2));
            }
        }

        info!("[Fallback 1] Trying DeepSeek proxy...");
        match self.fallback_translate(prompt, config) {
            Ok(response) => {
                if let Some(translations) = self.verify_and_clean(&response, batch) {
                    info!("[Fallback 1] Successful");
                    return Some(translations);
                }
            }
            Err(e) => warn!("[Fallback 1] Failed: {}", e),
        }

        info!("[Fallback 2] Trying Gemini via TheTurboChat...");
        match self.fallback_translate_2(prompt, config) {
            Ok(response) => {
                if let Some(translations) = self.verify_and_clean(&response, batch) {
                    info!("[Fallback 2] Successful");
                    return Some(translations);
                }
            }
            Err(e) => warn!("[Fallback 2] Failed: {}", e),
        }

        None
    }

    fn main_translate(&mut self, prompt: &str, config: &Config) -> Result<String> {
        let encoded: String = url::form_urlencoded::byte_serialize(prompt.as_bytes()).collect();
        let mut url_str = format!("{}?q={}", config.main_api_base, encoded);
        if let Some(chat_id) = &self.current_chat_id {
            url_str.push_str(&format!("&id={}", chat_id));
        }

        debug!("Main API request URL (truncated): {}...", &url_str[..url_str.len().min(200)]);

        let resp = self.client.get(&url_str).send()?;
        let body: serde_json::Value = resp.json()?;

        let status = body.get("status")
            .and_then(|s| s.as_str())
            .unwrap_or("");

        if status != "success" {
            anyhow::bail!("API returned non-success status: {}", status);
        }

        let ai_response = body.get("ai_response")
            .and_then(|r| r.get("data"))
            .and_then(|d| d.get("message"))
            .and_then(|m| m.as_str())
            .unwrap_or("");

        let new_chat_id = body.get("ai_response")
            .and_then(|r| r.get("data"))
            .and_then(|d| d.get("id"))
            .and_then(|id| id.as_str())
            .map(|s| s.to_string());

        if let Some(id) = new_chat_id {
            self.current_chat_id = Some(id);
            debug!("Updated chat ID: {:?}", self.current_chat_id);
        }

        Ok(ai_response.to_string())
    }

    fn fallback_translate(&self, prompt: &str, config: &Config) -> Result<String> {
        let ip = format!("{}.{}.{}.{}",
            rand::thread_rng().gen_range(1..=255),
            rand::thread_rng().gen_range(0..=255),
            rand::thread_rng().gen_range(0..=255),
            rand::thread_rng().gen_range(0..=255));

        let payload = json!({
            "messages": [{"content": prompt, "role": "user"}],
            "model": "v3",
            "stream": false,
            "web_search": false
        });

        let resp = self.client
            .post(&config.fallback_url)
            .header("Accept", "*/*")
            .header("Content-Type", "application/json")
            .header("Origin", "https://deep-seek.online")
            .header("Referer", "https://deep-seek.online/")
            .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            .header("X-Forwarded-For", &ip)
            .header("X-Real-IP", &ip)
            .json(&payload)
            .send()?;

        let data: serde_json::Value = resp.json()?;
        let content = data.get("content")
            .and_then(|c| c.as_str())
            .unwrap_or("");

        let cleaned = self.re_think.replace_all(content, "").to_string();
        Ok(cleaned.trim().to_string())
    }

    fn fallback_translate_2(&self, prompt: &str, config: &Config) -> Result<String> {
        let payload = json!({
            "runtime": "gemini",
            "message": prompt,
            "configuration": null,
            "history": [],
            "language": "en",
            "sourcePage": "/gemini"
        });

        let resp = self.client
            .post(&config.fallback_url_2)
            .header("Accept", "*/*")
            .header("Content-Type", "application/json")
            .header("Origin", "https://theturbochat.com")
            .header("Referer", "https://theturbochat.com/gemini")
            .header("User-Agent", "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36")
            .json(&payload)
            .send()?;

        let data: serde_json::Value = resp.json()?;
        let output = data.get("outputText")
            .and_then(|o| o.as_str())
            .unwrap_or("");

        Ok(output.to_string())
    }

    fn create_batches(&self, texts: &[String], config: &Config) -> Vec<Vec<String>> {
        let mut batches = Vec::new();
        let mut current_batch = Vec::new();
        let mut current_len = 0usize;

        for text in texts {
            let text_len = text.len();
            if (current_len + text_len > config.translation_max_chars_per_batch)
                || current_batch.len() >= config.translation_max_items_per_batch
            {
                if !current_batch.is_empty() {
                    batches.push(std::mem::take(&mut current_batch));
                }
                current_len = 0;
            }
            current_batch.push(text.clone());
            current_len += text_len;
        }

        if !current_batch.is_empty() {
            batches.push(current_batch);
        }

        batches
    }

    fn format_batch_text(&self, batch: &[String], config: &Config) -> String {
        let sep = &config.separator;
        let instruction = &config.instruction;

        format!(
            "INSTRUCTION: {}\n\n\
             ATURAN PENTING: Di bawah ini ada kumpulan teks komik yang dipisahkan oleh '{}'. \
             Teks-teks ini bisa berupa dialog bubble, SFX, atau campuran dari beberapa panel. \
             Dialog antar bubble mungkin masih dalam satu percakapan yang sama—pastikan terjemahannya tetap nyambung \
             secara alur dan karakter. Cermati dan bedakan mana dialog dan mana SFX sebelum menerjemahkan. \
             Hasil akhir harus berupa teks terjemahan *BAHASA INDONESIA* yang dipisahkan oleh '{}' tanpa tambahan \
             penjelasan, basa-basi, atau penomoran apa pun.\n\n\
             TEKS SUMBER:\n\n{}",
            instruction,
            sep,
            sep,
            batch.join(&format!("\n{}\n", sep))
        )
    }

    fn verify_and_clean(&self, response: &str, batch: &[String]) -> Option<Vec<String>> {
        let translations = self.extract_translations(response);

        if translations.len() == batch.len() {
            return Some(translations);
        }

        let raw_lines: Vec<String> = response.lines()
            .map(|l| l.trim())
            .filter(|l| !l.is_empty() && !l.contains(&"130495848"))
            .map(|l| self.clean_part(l))
            .collect();

        if raw_lines.len() == batch.len() {
            return Some(raw_lines);
        }

        None
    }

    fn extract_translations(&self, response: &str) -> Vec<String> {
        let sep = "130495848";

        if response.contains(sep) {
            return response.split(sep)
                .map(|p| self.clean_part(p.trim()))
                .filter(|p| !p.is_empty())
                .collect();
        }

        let lines: Vec<String> = response.lines()
            .map(|l| self.clean_part(l.trim()))
            .filter(|l| !l.is_empty())
            .collect();

        if lines.is_empty() {
            vec![self.clean_part(response)]
        } else {
            lines
        }
    }

    fn clean_part(&self, text: &str) -> String {
        let mut cleaned = text.to_string();

        cleaned = self.re_number_prefix.replace_all(&cleaned, "").to_string();

        if let Some(pos) = cleaned.find(':') {
            let prefix = &cleaned[..pos].to_lowercase();
            if prefix.contains("terjemah") {
                cleaned = cleaned[pos + 1..].trim().to_string();
            }
        }

        cleaned.trim().to_string()
    }
}

pub fn filter_sfx_blocks(blocks: &mut Vec<TextBlock>, config: &Config) -> Vec<String> {
    let mut texts_for_ai = Vec::new();

    for block in blocks.iter_mut() {
        let upper = block.text.to_uppercase();
        let words: Vec<&str> = upper.split_whitespace().collect();

        if words.len() == 1 {
            let clean = upper.chars().filter(|c| c.is_ascii_alphabetic()).collect::<String>();
            if let Some(translation) = config.sfx_dict.iter()
                .find(|(k, _)| k.as_str() == clean)
                .map(|(_, v)| v.clone())
            {
                block.translated_text = Some(translation);
                continue;
            }
        }

        texts_for_ai.push(block.text.clone());
    }

    texts_for_ai
}

pub fn apply_translations(blocks: &mut [TextBlock], translations: &[String], _config: &Config) {
    let mut ai_idx = 0usize;

    for block in blocks.iter_mut() {
        if block.translated_text.is_some() {
            continue;
        }
        if ai_idx < translations.len() {
            block.translated_text = Some(translations[ai_idx].clone());
            ai_idx += 1;
        } else {
            block.translated_text = Some(block.text.clone());
        }
    }
}
