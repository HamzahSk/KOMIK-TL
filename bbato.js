import * as cheerio from 'cheerio';

const BASE_URL = "https://bbato.com"; // Ganti sesuai domain aktif jika berubah

// ============================== Helpers ==============================
function getHeaders(extraHeaders = {}) {
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': `${BASE_URL}/`, // Membypas blokir 403 CDN
        ...extraHeaders
    };
}

function getImageUrl($, element) {
    const src = $(element).attr('data-src') || $(element).attr('src');
    if (!src) return null;
    return src.startsWith('http') ? src : `${BASE_URL}${src}`;
}

function extractMangaData($, containerSelector) {
    const mangas = [];
    $(containerSelector).each((_, element) => {
        const poster = $(element).find('a.poster');
        const url = poster.attr('href') || '';
        const title = $(element).find('.info > a').text().trim();
        const thumbnail_url = getImageUrl($, poster.find('img').first());

        if (url) {
            mangas.push({ url, title, thumbnail_url });
        }
    });
    return mangas;
}

function hasNextPage($) {
    return $('.pagination a[rel=next]').length > 0;
}

// ============================== Popular ==============================
export async function getPopularManga() {
    const response = await fetch(BASE_URL, { headers: getHeaders() });
    const html = await response.text();
    const $ = cheerio.load(html);

    const mangas = [];
    const seenUrls = new Set();

    // Menggabungkan dan menghapus duplikat dari tab popular
    $('#most-viewed .tab-content .swiper-slide.unit').each((_, element) => {
        const aTag = $(element).find('a').first();
        const url = aTag.attr('href') || '';
        
        if (url && !seenUrls.has(url)) {
            seenUrls.add(url);
            mangas.push({
                url,
                title: $(element).find('span').text().trim(),
                thumbnail_url: getImageUrl($, $(element).find('img').first())
            });
        }
    });

    return { mangas, hasNext: false }; // Halaman utama tidak memiliki paginasi
}

// ============================== Latest ===============================
export async function getLatestUpdates(page = 1) {
    const path = page === 1 ? "/updated" : `/updated/page/${page}`;
    const response = await fetch(`${BASE_URL}${path}`, { headers: getHeaders() });
    const html = await response.text();
    const $ = cheerio.load(html);

    const mangas = extractMangaData($, '.original.card-lg .unit');
    const hasNext = hasNextPage($);

    return { mangas, hasNext };
}

// ============================== Search ===============================
export async function searchManga(page = 1, query = '', filters = {}) {
    const url = new URL(`${BASE_URL}/filter`);
    url.searchParams.append('keyword', query);
    
    if (page > 1) {
        url.searchParams.append('page', page.toString());
    }

    // Pemetaan filter dinamis
    ['type', 'genre', 'status', 'year'].forEach(key => {
        if (Array.isArray(filters[key])) {
            filters[key].forEach(val => url.searchParams.append(`${key}[]`, val));
        }
    });

    if (filters.minchap) url.searchParams.append('minchap', filters.minchap);
    if (filters.sort) url.searchParams.append('sort', filters.sort);

    const response = await fetch(url.toString(), { headers: getHeaders() });
    const html = await response.text();
    const $ = cheerio.load(html);

    const mangas = extractMangaData($, '.original.card-lg .unit');
    const hasNext = hasNextPage($);

    return { mangas, hasNext };
}

// ============================== Details ==============================
export async function getMangaDetails(mangaUrl) {
    const targetUrl = mangaUrl.startsWith('http') ? mangaUrl : `${BASE_URL}${mangaUrl}`;
    const response = await fetch(targetUrl, { headers: getHeaders() });
    const html = await response.text();
    const $ = cheerio.load(html);

    const statusText = $('.info > p').text().trim().toLowerCase();
    
    // Mapping status
    const statusMap = {
        'ongoing': 'ONGOING',
        'releasing': 'ONGOING',
        'completed': 'COMPLETED',
        'on hiatus': 'ON_HIATUS',
        'discontinued': 'CANCELLED',
        'cancelled': 'CANCELLED'
    };
    
    const status = statusMap[statusText] || 'UNKNOWN';

    return {
        title: $('h1[itemprop=name]').text().trim(),
        author: $('.meta div:contains("Author") a').map((_, el) => $(el).text()).get().join(', '),
        description: $('.description').text().trim(),
        genre: $('.meta div:contains("Genres") a').map((_, el) => $(el).text()).get().join(', '),
        status,
        thumbnail_url: getImageUrl($, $('.poster img').first())
    };
}

// ============================== Chapters ==============================
export async function getChapterList(mangaUrl) {
    const slug = mangaUrl.split('/').pop();
    const fullMangaUrl = mangaUrl.startsWith('http') ? mangaUrl : `${BASE_URL}${mangaUrl}`;
    
    const chapterHeaders = getHeaders({
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': fullMangaUrl
    });

    const response = await fetch(`${BASE_URL}/get-chapter-list?slug=${slug}`, { headers: chapterHeaders });
    const resDto = await response.json();
    
    if (!resDto.data || !Array.isArray(resDto.data)) return [];

    return resDto.data.map(ch => ({
        url: `/read/${slug}/${ch.chapter_slug}`,
        name: ch.chapter_name,
        date_upload: ch.updated_at ? new Date(ch.updated_at).getTime() : 0
    }));
}

// ============================== Pages ================================
export async function getPageList(chapterUrl) {
    const targetUrl = chapterUrl.startsWith('http') ? chapterUrl : `${BASE_URL}${chapterUrl}`;
    const response = await fetch(targetUrl, { headers: getHeaders() });
    const html = await response.text();
    const $ = cheerio.load(html);

    const pages = [];
    $('.pages .page:not(.notice-page) img').each((index, img) => {
        const imageUrl = getImageUrl($, img);
        if (imageUrl) {
            pages.push({ index, imageUrl });
        }
    });

    return pages;
}

// ============================== Testing ==============================
// Uncomment untuk testing
 getMangaDetails('https://bbato.com/manga/the-melting-season').then(data => console.log(data));