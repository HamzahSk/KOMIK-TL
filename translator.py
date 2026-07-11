# translator.py
import time
import re
import random
import requests
import urllib.parse

class AiTranslator:
    def __init__(self):
        # Konfigurasi API Utama (Deepseek Custom Endpoint)
        self.main_api_base = 'http://78.154.103.34:13267/chat/deepseek'
        self.current_chat_id = None # Menyimpan ID sesi untuk 1 chapter
        
        # Konfigurasi API Fallback 1 (DeepSeek Proxy)
        self.fallback_url = 'https://llmproxy.org/api/chat.php'
        
        # Konfigurasi API Fallback 2 (TheTurboChat / Gemini)
        self.fallback_url_2 = 'https://theturbochat.com/api/chat/message'
        
        self.MAX_CHARS = 1500
        self.SEPARATOR = '130495848'
        
        self.instruction = (
            "Terjemahkan teks komik hasil OCR ini ke bahasa Indonesia yang natural, hidup, dan emosional, "
            "seolah komik ini aslinya berbahasa Indonesia. Dialog dan monolog harus mengalir seperti percakapan nyata, "
            "bukan textbook atau terjemahan kaku. Hindari kata 'lu/gue' atau slang berlebihan yang terkesan tidak profesional; "
            "gunakan 'aku/kamu/kau' atau 'saya/Anda' sesuai konteks karakter. SFX wajib diterjemahkan ke padanan alami Indonesia "
            "(contoh: BAM→DOR, THUMP→DEG, SLAM→BRAK, GASP→HAAH, CREAK→KRIET, SPLASH→BYUR). Jika ada typo atau teks rusak "
            "akibat OCR, tafsirkan maksudnya berdasarkan bunyi dan konteks panel, lalu terjemahkan maknanya. "
            "Nama tokoh dan istilah khusus jangan diubah. Jangan tambahkan simbol, emoji, atau format apa pun "
            "yang tidak ada di teks asli."
        )

    def reset_chapter_session(self):
        """Panggil ini setiap kali pindah chapter agar ID chat direset ke None."""
        self.current_chat_id = None
        print("[System] Sesi Chat ID Translator direset untuk chapter baru.")

    def _get_fallback_headers(self):
        """Membuat header dinamis dengan IP acak untuk fallback 1."""
        ip = f"{random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}"
        return {
            'Accept': '*/*',
            'Content-Type': 'application/json',
            'Origin': 'https://deep-seek.online',
            'Referer': 'https://deep-seek.online/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'X-Forwarded-For': ip,
            'X-Real-IP': ip,
            'CF-Connecting-IP': ip
        }

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

    # PERBAIKAN: Indentasi dimundurkan agar sejajar dengan fungsi lainnya
    def _format_batch_text(self, batch_texts):
        return (
            f"INSTRUCTION: {self.instruction}\n\n"
            f"ATURAN PENTING: Di bawah ini ada kumpulan teks komik yang dipisahkan oleh '{self.SEPARATOR}'. "
            f"Teks-teks ini bisa berupa dialog bubble, SFX, atau campuran dari beberapa panel. "
            f"Dialog antar bubble mungkin masih dalam satu percakapan yang sama—pastikan terjemahannya tetap nyambung "
            f"secara alur dan karakter. Cermati dan bedakan mana dialog dan mana SFX sebelum menerjemahkan. "
            f"Hasil akhir harus berupa teks terjemahan *BAHASA INDONESIA* yang dipisahkan oleh '{self.SEPARATOR}' tanpa tambahan "
            f"penjelasan, basa-basi, atau penomoran apa pun.\n\n"
            f"TEKS SUMBER:\n\n"
            + f"\n{self.SEPARATOR}\n".join(batch_texts)
        )

    def _fallback_translate(self, prompt_text):
        """Metode fallback 1 menggunakan DeepSeek via llmproxy."""
        print("[System] Memulai sesi Fallback 1 via DeepSeek...")
        
        payload = {
            "messages": [{"content": prompt_text, "role": "user"}],
            "model": "v3",
            "stream": False,
            "web_search": False
        }

        try:
            response = requests.post(
                self.fallback_url, 
                headers=self._get_fallback_headers(), 
                json=payload, 
                timeout=45
            )
            response.raise_for_status()
            data = response.json()
            
            content = data.get('content', '')
            clean_content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL | re.IGNORECASE).strip()
            return clean_content
            
        except Exception as e:
            print(f"[Error] Fallback 1 API DeepSeek gagal: {e}")
            return None

    def _fallback_translate_2(self, prompt_text):
        """Metode fallback 2 menggunakan Gemini via TheTurboChat."""
        print("[System] Memulai sesi Fallback 2 via TheTurboChat (Gemini)...")
        
        headers = {
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://theturbochat.com',
            'referer': 'https://theturbochat.com/gemini',
            'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36'
        }
        
        payload = {
            "runtime": "gemini",
            "message": prompt_text,
            "configuration": None,
            "history": [],
            "language": "en",
            "sourcePage": "/gemini"
        }

        try:
            response = requests.post(
                self.fallback_url_2, 
                headers=headers, 
                json=payload, 
                timeout=45
            )
            response.raise_for_status()
            data = response.json()
            
            return data.get('outputText', '')
            
        except Exception as e:
            print(f"[Error] Fallback 2 API TheTurboChat gagal: {e}")
            return None

    def _verify_and_clean(self, ai_response, batch):
        """Helper untuk mengekstrak dan memverifikasi keselarasan terjemahan."""
        if not ai_response:
            return None
            
        translations = self._extract_translations(ai_response)
        
        if len(translations) == len(batch):
            return translations
            
        raw_lines = [line.strip() for line in ai_response.split('\n') if line.strip() and self.SEPARATOR not in line]
        if len(raw_lines) == len(batch):
            return [self._clean_part(l) for l in raw_lines]
            
        return None

    def translate_batch(self, texts):
        if not texts:
            return []
        
        batches = self._create_batches(texts)
        all_translations = []
        
        for batch_idx, batch in enumerate(batches):
            print(f"\n[Batch {batch_idx+1}/{len(batches)}] Menerjemahkan {len(batch)} teks...")
            user_message = self._format_batch_text(batch)
            translations = []
            
            main_success = False
            for attempt in range(2): # Mencoba maksimal 2 kali
                try:
                    # 1. Coba API Utama (Custom Deepseek Endpoint)
                    encoded_query = urllib.parse.quote(user_message)
                    req_url = f"{self.main_api_base}?q={encoded_query}"
                    
                    # Tambahkan ID jika sudah ada dari batch sebelumnya (di chapter yang sama)
                    if self.current_chat_id:
                        req_url += f"&id={self.current_chat_id}"
                        
                    response = requests.get(req_url, timeout=45)
                    response.raise_for_status()
                    data = response.json()
                    
                    if data.get('status') != 'success':
                        raise ValueError(f"Status response API bukan success: {data}")
                        
                    ai_response_data = data.get('ai_response', {})
                    if not ai_response_data.get('status'):
                        raise ValueError(f"AI merespon dengan status false: {ai_response_data}")
                        
                    result_data = ai_response_data.get('data', {})
                    ai_response_text = result_data.get('message', '')
                    
                    # Simpan chat_id untuk request batch berikutnya di chapter yang sama
                    new_chat_id = result_data.get('id')
                    if new_chat_id:
                        self.current_chat_id = new_chat_id
                    
                    # Verifikasi hasil Utama
                    translations = self._verify_and_clean(ai_response_text, batch)
                    
                    if translations:
                        print(f"=== RESPON UTAMA SUKSES (Chat ID: {self.current_chat_id}) ===")
                        main_success = True
                        break # Jika sukses, keluar dari loop percobaan
                    else:
                        raise ValueError("Format teks dari API Utama berantakan.")
                    
                except Exception as e:
                    print(f"[Warning] API Utama Bermasalah di percobaan {attempt + 1} ({e}).")
                    if attempt == 0:
                        print("Mencoba ulang API Utama sekali lagi dalam 2 detik...")
                        time.sleep(2) # Jeda sebelum mencoba ulang
            
            # Jika setelah 2 kali coba masih gagal, jalankan Fallback
            if not main_success:
                print("[Warning] API Utama gagal setelah 2 kali percobaan. Beralih ke Fallback 1...")
                
                # 2. Fallback 1 (DeepSeek Proxy)
                ai_response = self._fallback_translate(user_message)
                translations = self._verify_and_clean(ai_response, batch)
                
                if translations:
                    print("=== RESPON FALLBACK 1 SUKSES ===")
                else:
                    print("[Warning] Fallback 1 Gagal atau Format Berantakan. Beralih ke Fallback 2...")
                    
                    # 3. Fallback 2 (TheTurboChat)
                    ai_response = self._fallback_translate_2(user_message)
                    translations = self._verify_and_clean(ai_response, batch)
                    
                    if translations:
                        print("=== RESPON FALLBACK 2 SUKSES ===")
                    else:
                        print("[Error] Semua API dan Fallback gagal. Menggunakan teks asli.")
                        translations = batch

            all_translations.extend(translations)
            time.sleep(1.5)
            
        return all_translations


    def _clean_part(self, text):
        cleaned = text.strip()
        cleaned = re.sub(r'^\d+[\.\)]\s*', '', cleaned)
        if ':' in cleaned:
            prefix, suffix = cleaned.split(':', 1)
            if 'terjemah' in prefix.lower():
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
        
        lines = [line.strip() for line in response_text.split('\n') if line.strip()]
        translations = [self._clean_part(line) for line in lines]
        return translations if translations else [response_text]
