import * as cheerio from 'cheerio';

const action = process.argv[2];
const url = process.argv[3];

const HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
};
const CORS_PROXY = "https://cors-proxy1.rockyyrec.workers.dev/?url=";

async function fetchHtml(targetUrl) {
    try {
        let res = await fetch(targetUrl, { headers: HEADERS });
        if (!res.ok) throw new Error("Status: " + res.status);
        return await res.text();
    } catch (e) {
        let res = await fetch(CORS_PROXY + targetUrl, { headers: HEADERS });
        return await res.text();
    }
}

async function main() {
    try {
        const html = await fetchHtml(url);
        const $ = cheerio.load(html);
        let result = null;

        if (action === 'chapter_list') {
            const chapters = [];
            $('li.wp-manga-chapter').each((i, el) => {
                const title = $(el).find('a').text().trim();
                const link = $(el).find('a').attr('href');
                if (title && link) chapters.push({ title: title, url: link });
            });
            result = chapters;
        } 
        else if (action === 'chapter_info') {
            const rawHeading = $('h1#chapter-heading').text().trim();
            let mangaTitle = rawHeading;
            let chapterNumber = '';
            const match = rawHeading.match(/(.*?)\s*(?:Chapter|Chap|Bab)\s*(.*)/i);
            
            if (match) {
                mangaTitle = match[1].trim();
                chapterNumber = match[2].trim();
            }
            result = { title: mangaTitle, chapter_name: chapterNumber };
        } 
        else if (action === 'page_list') {
            const images = [];
            $('.page-break img.wp-manga-chapter-img').each((i, el) => {
                let src = $(el).attr('src') || $(el).attr('data-src');
                if (src) {
                    images.push({ index: i, url: src.trim() });
                }
            });
            result = images;
        }

        console.log(JSON.stringify(result));
    } catch (err) {
        console.log(JSON.stringify(null));
    }
}

main();
