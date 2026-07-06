import crypto from 'crypto';

const delay = ms => new Promise(r => setTimeout(r, ms));

// ================= KONFIGURASI =================
const CONFIG = {
  url: 'https://app.unlimitedai.chat/api/chat',
  deviceId: 'dc9fc5ff-18f2-40a6-b59c-9f975a252283',
  locale: 'id',
  model: 'chat-model-reasoning'
};

const HEADERS = {
  'accept': '*/*',
  'content-type': 'application/json',
  'origin': 'https://app.unlimitedai.chat',
  'referer': 'https://app.unlimitedai.chat/id',
  'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36',
  'x-next-intl-locale': 'id'
};

// ================= CLASS UNLIMITED AI =================
class UnlimitedAISession {
  constructor() {
    this.chatId = crypto.randomUUID();
    this.messages = [];
  }

  /**
   * Kirim pesan + streaming real-time + simpan history
   * @param {string} promptText - Pesan user
   * @returns {Promise<string>} - Jawaban lengkap AI
   */
  async sendMessage(promptText) {
    const now = new Date().toISOString();
    const userMsgId = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();

    // Tambahkan pesan user
    this.messages.push({
      id: userMsgId,
      content: promptText,
      createdAt: now,
      parts: [{ type: 'text', text: promptText }],
      role: 'user'
    });

    // Siapkan slot kosong untuk assistant
    const assistantSlot = {
      id: assistantMsgId,
      content: '',
      createdAt: now,
      parts: [{ type: 'text', text: '' }],
      role: 'assistant'
    };
    this.messages.push(assistantSlot);

    try {
      const body = {
        chatId: this.chatId,
        deviceId: CONFIG.deviceId,
        locale: CONFIG.locale,
        messages: this.messages,
        selectedCharacter: null,
        selectedChatModel: CONFIG.model,
        selectedStory: null
      };

      const res = await fetch(CONFIG.url, {
        method: 'POST',
        headers: HEADERS,
        body: JSON.stringify(body)
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);

      // Streaming dengan TextDecoderStream
      const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
      let fullReply = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        for (const line of value.split('\n').filter(Boolean)) {
          try {
            const parsed = JSON.parse(line);
            if (parsed.type === 'delta' && parsed.delta) {
              process.stdout.write(parsed.delta); // Stream real-time
              fullReply += parsed.delta;
            }
          } catch {}
        }
      }

      // Update slot assistant dengan jawaban lengkap
      assistantSlot.content = fullReply;
      assistantSlot.parts[0].text = fullReply;

      console.log('\n');
      return fullReply;

    } catch (error) {
      console.error('❌ Gagal:', error.message);
      this.messages.splice(-2); // Hapus slot gagal
      throw error;
    }
  }

  // Reset sesi (chatId + history baru)
  reset() {
    this.chatId = crypto.randomUUID();
    this.messages = [];
    console.log('🔄 Sesi di-reset.');
  }
}

// ================= CARA PENGGUNAAN =================
/*
  // Buat sesi baru
  const ai = new UnlimitedAISession();
  
  // Single chat
  await ai.sendMessage('Halo, apa kabar?');
  
  // Multi-turn chat (history otomatis tersimpan)
  await ai.sendMessage('Nama saya Budi');
  await ai.sendMessage('Siapa nama saya?'); // AI ingat
  
  // Reset sesi
  ai.reset();
  await ai.sendMessage('Siapa nama saya?'); // AI lupa
  
  // Chat dengan jeda natural
  const questions = ['Apa itu AI?', 'Contohnya?', 'Apakah berbahaya?'];
  for (const q of questions) {
    await ai.sendMessage(q);
    await delay(2000);
  }
*/

// ================= TESTING =================
async function runDemo() {
  const ai = new UnlimitedAISession();
  console.log(`[Sesi Dimulai] Chat ID: ${ai.chatId}\n`);

  const questions = [
    'Siapa penemu lampu pijar?',
    'Kapan dia lahir?',
    'Kenapa dia bisa kepikiran bikin itu?',
    'Dia berasal dari negara mana?',
    'Apa nama lengkapnya?'
  ];

  for (const q of questions) {
    console.log(`👤 User: ${q}`);
    process.stdout.write('🤖 AI  : ');
    await ai.sendMessage(q);
    await delay(1000 + Math.floor(Math.random() * 1000));
  }

  console.log('📊 Total History:', ai.messages.length, 'pesan');
}

runDemo();