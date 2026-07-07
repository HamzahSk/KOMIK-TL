import * as cheerio from 'cheerio';

const BASE_URL = 'https://gpt.chat';
const API_URL = 'https://gpt.chat/api/chat';

// Ambil cookie & CSRF token dari halaman utama
async function getSessionData() {
  console.log('🔑 Mengambil session...');
  
  const response = await fetch(BASE_URL);
  if (!response.ok) throw new Error(`Gagal akses halaman: ${response.status}`);

  // Ekstrak cookie
  const cookieString = response.headers.getSetCookie()
    .map(c => c.split(';')[0])
    .join('; ');

  // Ekstrak CSRF token dengan Cheerio
  const html = await response.text();
  const $ = cheerio.load(html);
  const csrfToken = $('meta[name="csrf-token"]').attr('content');

  if (!csrfToken) throw new Error('CSRF Token tidak ditemukan');
  
  console.log('✅ Session didapat\n');
  return { cookieString, csrfToken };
}

// Kirim chat & streaming respons
async function sendChat(userMessage = 'Haloo', model = 'openai/gpt-5-mini') {
  try {
    const { cookieString, csrfToken } = await getSessionData();

    const headers = {
      'Accept': '*/*',
      'Content-Type': 'application/json',
      'Cookie': cookieString,
      'Origin': 'https://gpt.chat',
      'Referer': 'https://gpt.chat/chat',
      'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36',
      'X-Csrf-Token': csrfToken
    };

    console.log('📤 Mengirim chat...');
    const response = await fetch(API_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        model,
        messages: [{ role: 'user', content: userMessage }]
      })
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    console.log('📥 Respons AI:\n');
    
    // Streaming chunk
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    for await (const chunk of response.body) {
      buffer += decoder.decode(chunk, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // Simpan sisa tidak lengkap

      for (const line of lines) {
        if (!line.trim() || line.startsWith(':')) continue;
        if (!line.startsWith('data: ')) continue;

        const data = line.replace('data: ', '').trim();
        if (data === '[DONE]') break;

        try {
          const json = JSON.parse(data);
          const content = json.choices[0]?.delta?.content || '';
          if (content) process.stdout.write(content);
        } catch {} // Abaikan chunk rusak
      }
    }

    console.log('\n\n✅ Selesai');
  } catch (error) {
    console.error('❌ Error:', error.message);
  }
}

// ===== TESTING =====
console.log('🚀 Memulai testing GPT Chat...\n');

// Test 1: Default message
await sendChat('Bisa banntu translate novel gk');

// Test 2: Custom message
// await sendChat('Jelaskan tentang machine learning');

// Test 3: Custom message + model
// await sendChat('Buat puisi pendek', 'openai/gpt-4o-mini');