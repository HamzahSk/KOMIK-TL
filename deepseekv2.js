const data = JSON.stringify({
  "model": "deepseek/deepseek-chat-v3-0324",
  "messages": [
    {
      "role": "user",
      "content": "Tulis haiku tentang teknologi"
    }
  ]
});

const options = {
  method: 'POST',
  headers: {
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Content-Type': 'application/json',
    'Origin': 'https://chatai.org',
    'Referer': 'https://chatai.org/deepseek/chat'
  },
  body: data
};

async function fetchChatStream() {
  try {
    const response = await fetch('https://chatai.org/api/chat', options);
    
    // Pastikan respons adalah stream
    if (!response.body) throw new Error('ReadableStream tidak didukung.');

    const reader = response.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let isDone = false;

    console.log('--- Mulai Stream ---\n');

    while (!isDone) {
      const { value, done } = await reader.read();
      isDone = done;
      
      if (value) {
        // Decode chunk data berupa Uint8Array menjadi teks
        const chunkString = decoder.decode(value, { stream: true });
        // Pisahkan berdasarkan baris baru karena satu chunk bisa berisi beberapa baris "data: "
        const lines = chunkString.split('\n');
        
        for (const line of lines) {
          // Hanya proses baris yang diawali dengan "data: "
          if (line.startsWith('data: ')) {
            const jsonStr = line.replace('data: ', '').trim();
            
            // Hentikan proses jika stream mengirim tanda selesai
            if (jsonStr === '[DONE]') {
              console.log('\n\n--- Stream Selesai ---');
              return;
            }
            
            // Parsing JSON dan ambil isinya
            try {
              const parsed = JSON.parse(jsonStr);
              const content = parsed.choices[0]?.delta?.content || '';
              
              // Cetak ke terminal tanpa baris baru (newline) agar teksnya menyambung
              process.stdout.write(content);
            } catch (err) {
              // Abaikan error JSON.parse jika ada chunk yang terpotong di tengah jalan
            }
          }
        }
      }
    }
  } catch (error) {
    console.error('\nTerjadi kesalahan:', error);
  }
}

fetchChatStream();
