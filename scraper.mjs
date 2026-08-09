import fs from 'fs';
import path from 'path';
import { fileURLToPath, pathToFileURL } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const scrapersDir = path.join(__dirname, 'komik_scrape');

const CORS_PROXY = "https://cors-proxy1.rockyyrec.workers.dev/?url=";
const HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
};

const ACTIVE_SCRAPERS = {};

// ==========================================
// 1. FETCH SYSTEM DENGAN FALLBACK
// ==========================================
async function fetchWithFallback(url) {
    try {
        let res = await fetch(url, { headers: HEADERS });
        if (!res.ok) throw new Error(`Status: ${res.status}`);
        return await res.text();
    } catch (e) {
        let res = await fetch(CORS_PROXY + url, { headers: HEADERS });
        return await res.text();
    }
}

// ==========================================
// 2. AUTO-LOAD SEMUA MODULE DI FOLDER komik_scrape
// ==========================================
async function loadScrapers() {
    if (!fs.existsSync(scrapersDir)) {
        fs.mkdirSync(scrapersDir);
        return;
    }
    
    const files = fs.readdirSync(scrapersDir).filter(f => f.endsWith('.mjs'));
    for (const file of files) {
        try {
            const fullPath = path.join(scrapersDir, file);
            // Dynamic import ESM menggunakan path file absolute
            const module = await import(pathToFileURL(fullPath).href);
            
            if (module.DOMAINS) {
                for (const domain of module.DOMAINS) {
                    ACTIVE_SCRAPERS[domain] = module;
                }
            }
        } catch (err) {
            console.error(`Gagal meload module ${file}:`, err);
        }
    }
}

function getScraperModule(url) {
    for (const [domain, module] of Object.entries(ACTIVE_SCRAPERS)) {
        if (url.toLowerCase().includes(domain)) {
            return module;
        }
    }
    return null;
}

// ==========================================
// 3. FUNGSI UTAMA / JEMBATAN KE CLI PYTHON
// ==========================================
async function main() {
    await loadScrapers();
    
    const action = process.argv[2];
    const url = process.argv[3];
    
    if (!action || !url) return console.log(JSON.stringify(null));

    const scraper = getScraperModule(url);
    if (!scraper) return console.log(JSON.stringify(null));

    try {
        let result = null;
        
        // Panggil fungsi sesuai action dan module website spesifik
        if (action === 'chapter_list' && scraper.getChapterList) {
            result = await scraper.getChapterList(url, fetchWithFallback);
        } 
        else if (action === 'chapter_info' && scraper.getChapterName) {
            const html = await fetchWithFallback(url);
            result = await scraper.getChapterName(html);
        } 
        else if (action === 'page_list' && scraper.getPageList) {
            const html = await fetchWithFallback(url);
            result = await scraper.getPageList(html);
        }
        
        console.log(JSON.stringify(result));
    } catch (err) {
        console.log(JSON.stringify(null));
    }
}

main();
