use std::path::PathBuf;

#[derive(Debug, Clone)]
pub struct Config {
    pub url_manga: Vec<String>,
    pub url_chapter: Vec<String>,
    pub font_path: PathBuf,
    pub sfx_font_path: PathBuf,
    pub output_dir: PathBuf,
    pub ai_logs_dir: PathBuf,
    pub merge_target_height: u32,
    pub slice_target_height: u32,
    pub download_workers: usize,
    pub merge_workers: usize,
    pub translation_max_chars_per_batch: usize,
    pub translation_max_items_per_batch: usize,
    pub sfx_dict: Vec<(String, String)>,
    pub main_api_base: String,
    pub fallback_url: String,
    pub fallback_url_2: String,
    pub separator: String,
    pub instruction: String,
    pub cors_proxy: String,
}

impl Config {
    pub fn load() -> Self {
        let url_manga: Vec<String> = Vec::new();
        let url_chapter: Vec<String> = vec![
            "https://vymanga.com/read/reverse-thinking/2622560".to_string(),
        ];

        Config {
            url_manga,
            url_chapter,
            font_path: PathBuf::from("digistrip.ttf"),
            sfx_font_path: PathBuf::from("Dark Poestry.ttf"),
            output_dir: PathBuf::from("output"),
            ai_logs_dir: PathBuf::from("ai_logs"),
            merge_target_height: 2200,
            slice_target_height: 1300,
            download_workers: 4,
            merge_workers: 6,
            translation_max_chars_per_batch: 1000,
            translation_max_items_per_batch: 25,
            sfx_dict: vec![
                ("DROP", "JATUH"), ("BAM", "DUAG"), ("WHOOSH", "WUSSS"),
                ("SLAP", "PLAK"), ("SIGH", "HAHH"), ("UHH", "EHH"),
                ("SPRING", "SPRING"), ("SHOCKED", "KAGET"),
                ("DOR", "DOR"), ("BRAK", "BRAK"), ("DEG", "DEG"),
                ("SYUUUT", "SYUUUT"), ("HAAH", "HAAH"), ("KRIET", "KRIET"),
                ("BYUR", "BYUR"), ("SREET", "SREET"), ("DUAR", "DUAR"),
                ("GRESIK", "GRESIK"), ("PROK", "PROK"), ("TAP", "TAP"),
                ("NATAP", "NATAP"),
            ].into_iter().map(|(a,b)| (a.to_string(), b.to_string())).collect(),
            main_api_base: "http://185.211.103.141:3613/chat/deepseek".to_string(),
            fallback_url: "https://llmproxy.org/api/chat.php".to_string(),
            fallback_url_2: "https://theturbochat.com/api/chat/message".to_string(),
            separator: "130495848".to_string(),
            instruction: "Terjemahkan teks komik hasil OCR ini ke bahasa Indonesia yang natural, hidup, dan emosional, seolah komik ini aslinya berbahasa Indonesia. Dialog dan monolog harus mengalir seperti percakapan nyata, bukan textbook atau terjemahan kaku. Hindari kata 'lu/gue' atau slang berlebihan yang terkesan tidak profesional; gunakan 'aku/kamu/kau' atau 'saya/Anda' sesuai konteks karakter. SFX wajib diterjemahkan ke padanan alami Indonesia (contoh: BAM->DOR, THUMP->DEG, SLAM->BRAK, GASP->HAAH, CREAK->KRIET, SPLASH->BYUR). Jika ada typo atau teks rusak akibat OCR, tafsirkan maksudnya berdasarkan bunyi dan konteks panel, lalu terjemahkan maknanya. Nama tokoh dan istilah khusus jangan diubah. Jangan tambahkan simbol, emoji, atau format apa pun yang tidak ada di teks asli.".to_string(),
            cors_proxy: "https://cors-proxy1.rockyyrec.workers.dev/?url=".to_string(),
        }
    }
}
