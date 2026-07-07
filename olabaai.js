import process from 'node:process';
import crypto from 'node:crypto';

// ================= KONFIGURASI =================
const PHPSESSID = crypto.randomBytes(13).toString('hex');
const HEADERS = {
  'referer': 'https://www.olabiba.com/',
  'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
  'cookie': `PHPSESSID=${PHPSESSID};`
};

// ================= API FUNCTIONS =================

async function kirimPesan(pesanText) {
  const formData = new FormData();
  formData.append('text', pesanText);
  formData.append('mood', 'funny');
  formData.append('lang', 'id');
  formData.append('adblock', 'No');
  formData.append('theme', 'light');

  const res = await fetch('https://cors-proxy-eight-ruddy.vercel.app/?url=https://www.olabiba.com/php/message.php', {
    method: 'POST',
    headers: HEADERS,
    body: formData
  });

  if (!res.ok) throw new Error(`Gagal inisiasi: HTTP ${res.status}`);
}

async function jalankanStream() {
  const res = await fetch('https://cors-proxy-eight-ruddy.vercel.app/?url=https://www.olabiba.com/php/stream.php', {
    method: 'GET',
    headers: { ...HEADERS, 'accept': 'text/event-stream' }
  });

  if (!res.ok) throw new Error(`Gagal stream: HTTP ${res.status}`);

  const decoder = new TextDecoder();
  let fullResponse = '';

  for await (const chunk of res.body) {
    const text = decoder.decode(chunk, { stream: true });
    const lines = text.split('\n');

    for (const line of lines) {
      if (line.startsWith('data:')) {
        const data = line.replace('data:', '').trim();
        if (data === '[DONE]') {
          // Stream selesai, lakukan pembersihan total
          tampilkanHasil(fullResponse);
          return;
        }
        fullResponse += data;
      }
    }
  }
}

function tampilkanHasil(text) {
  // Bersihkan semua elemen yang tidak diinginkan sekaligus
  const cleanText = text
    .replaceAll('&nbsp;', ' ')
    .replace(/\[ELABORATE\]|\[FOLLOWUP\].*|<!--.*?-->/g, '')
    .trim();

  console.log('AI Response: ' + cleanText + '\n');
}

// ================= FUNGSI UTAMA =================
async function prosesChat(pertanyaan) {
  console.log(`\n==========================================`);
  console.log(`User: ${pertanyaan}`);
  console.log(`==========================================`);

  try {
    await kirimPesan(pertanyaan);
    await jalankanStream();
  } catch (err) {
    console.error(`\n[Error] ${err.message}`);
  }
}

// ================= RUN =================
prosesChat("Halo, bisa ceritakan fakta unik tentang luar angkasa?");
