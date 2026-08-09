import * as cheerio from 'cheerio';

// Wajib diexport agar bisa dideteksi oleh scraper.mjs
export const DOMAINS = ["manhuarmtl.com"];

export async function getChapterList(url, fetchFunc) {
    const html = await fetchFunc(url);
    const $ = cheerio.load(html);
    const chapters = [];
    
    $('li.wp-manga-chapter').each((i, el) => {
        const title = $(el).find('a').text().trim();
        const link = $(el).find('a').attr('href');
        // Simpan sebagai 'url' agar sesuai dengan Python main.py
        if (title && link) chapters.push({ title: title, url: link }); 
    });
    return chapters;
}

export async function getPageList(html) {
    const $ = cheerio.load(html);
    const images = [];
    
    $('.page-break img.wp-manga-chapter-img').each((i, el) => {
        let src = $(el).attr('src') || $(el).attr('data-src');
        if (src) {
            // Wajib menggunakan index agar terurut di Python
            images.push({ index: i, url: src.trim() });
        }
    });
    return images;
}

export async function getChapterName(html) {
    const $ = cheerio.load(html);
    const rawHeading = $('h1#chapter-heading').text().trim();
    let mangaTitle = rawHeading;
    let chapterNumber = '';
    
    const match = rawHeading.match(/(.*?)\s*(?:Chapter|Chap|Bab)\s*(.*)/i);
    if (match) {
        mangaTitle = match[1].trim();
        chapterNumber = match[2].trim();
    }
    
    return { title: mangaTitle, chapter_name: chapterNumber };
}
