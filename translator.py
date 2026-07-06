# scraper_tl.py
import time
import re
import requests

class AiTranslator:
    def __init__(self):
        self.api_url = 'https://onlinechatbot.ai/wp-admin/admin-ajax.php'
        # CATATAN: Nonce ini dari WordPress dan bisa kedaluwarsa (biasanya per 12-24 jam).
        # Jika sewaktu-waktu error 400/403, perbarui nonce ini dari website aslinya.
        self.nonce = 'e82bmm7cf5'
        
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Accept': '*/*',
            'Origin': 'https://onlinechatbot.ai',
            'Referer': 'https://onlinechatbot.ai/chatbots/no-signup/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': 'snp_popup_seen=1'
        }
        
        self.MAX_CHARS = 1500
        self.SEPARATOR = '130495848'
        
        # Instruksi rahasia agar AI bertindak murni sebagai penerjemah komik
        self.instruction = (
            "Translate the text into natural, fluent Indonesian that sounds as if it were originally "
            "written in Indonesian. Avoid literal, awkward, overly formal, or machine-translated phrasing. "
            "Prioritize readability, immersion, and smooth flow while faithfully preserving the original "
            "meaning, tone, and context. Keep all names and special terms unchanged. Do not add any symbols, "
            "special characters, emojis, bullet points, numbering, decorative marks, or formatting that do "
            "not exist in the source text."
        )

    def _create_batches(self, texts):
        batches = []
        current_batch = []
        current_length = 0
        for text in texts:
            text_length = len(text)
            if current_length + text_length + len(self.SEPARATOR) > self.MAX_CHARS:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [text]
                current_length = text_length
            else:
                current_batch.append(text)
                current_length += text_length + len(self.SEPARATOR)
        if current_batch:
            batches.append(current_batch)
        return batches

    def _format_batch_text(self, batch_texts):
        return (
            "Berikut hasil OCR yang mungkin memiliki kata yang menempel."
            f"Sebagai penerjemah komik profesional, terjemahkan dialog berikut ke bahasa Indonesia percakapan yang natural dan mengalir. "
            f"ATURAN MUTLAK: Pisahkan tiap terjemahan HANYA dengan {self.SEPARATOR}. Dilarang keras menambah penjelasan atau basa-basi.\n\n"
            + f"\n{self.SEPARATOR}\n".join(batch_texts)
        )

    def translate_batch(self, texts):
        if not texts:
            return []
        
        batches = self._create_batches(texts)
        all_translations = []
        
        for batch_idx, batch in enumerate(batches):
            print(f"[Batch {batch_idx+1}/{len(batches)}] Menerjemahkan {len(batch)} teks via OnChatbot...")
            try:
                user_message = self._format_batch_text(batch)
                print(user_message)
                
                # Menyiapkan Form Data sesuai struktur JS
                payload = {
                    'action': 'do_chat_with_ai',
                    'ai_chatbot_nonce': self.nonce,
                    'ai_name': 'No Signup',
                    'origin': '',
                    'instruction': self.instruction,
                    'past_context': '',
                    'user_message': user_message,
                    'ai_message': "Zero registration required. I'm ready when you are. What can I do for you today?"
                }
                
                # Menggunakan parameter 'data' agar Python otomatis mengirimnya sebagai form-urlencoded
                response = requests.post(self.api_url, headers=self.headers, data=payload)
                response.raise_for_status()
                
                # Ekstrak dari JSON respons web
                data = response.json()
                if not data.get('success'):
                    print(f"[Error] API merespon gagal: {data}")
                    all_translations.extend(batch)
                    continue
                    
                ai_response = data.get('data', '')
                print("\n=== RAW RESPONSE ===")
                print(ai_response)
                
                # Ekstraksi hasil
                translations = self._extract_translations(ai_response)
                
                if len(translations) != len(batch):
                    print(f"[Warning] Jumlah terjemahan tidak selaras ({len(translations)} vs {len(batch)}). Mencoba pembersihan ekstra...")
                    
                    # Pembersihan ekstra dengan logika yang sama
                    raw_lines = [line.strip() for line in ai_response.split('\n') if line.strip() and self.SEPARATOR not in line]
                    if len(raw_lines) == len(batch):
                        translations = [self._clean_part(l) for l in raw_lines]
                    else:
                        print("[Warning] Pembersihan ekstra gagal. Menggunakan teks asli untuk batch ini.")
                        translations = batch
                        
                all_translations.extend(translations)
                time.sleep(1.5)
                
            except Exception as e:
                print(f"[Error] Gagal menerjemahkan batch: {e}")
                all_translations.extend(batch)
                
        return all_translations

    def _clean_part(self, text):
        """Fungsi pembantu untuk membersihkan satu bagian teks/baris."""
        cleaned = text.strip()
        # Hapus angka bullet di awal (misal "1. " atau "1) ")
        cleaned = re.sub(r'^\d+[\.\)]\s*', '', cleaned)
        
        # Cek jika ada tanda titik dua ':'
        if ':' in cleaned:
            # Pecah hanya di titik dua yang pertama
            prefix, suffix = cleaned.split(':', 1)
            
            # Cek apakah awalan mengandung kata 'terjemah' (case-insensitive)
            if 'terjemah' in prefix.lower():
                # Ambil teks setelah titik dua dan hapus spasi berlebih
                cleaned = suffix.strip()
                
        return cleaned

    def _extract_translations(self, response_text):
        if self.SEPARATOR in response_text:
            parts = response_text.split(self.SEPARATOR)
            translations = []
            for part in parts:
                cleaned = self._clean_part(part)
                if cleaned:
                    translations.append(cleaned)
            return translations
        
        # Fallback jika SEPARATOR tidak ditemukan
        lines = [line.strip() for line in response_text.split('\n') if line.strip()]
        translations = [self._clean_part(line) for line in lines]
        return translations if translations else [response_text]
