# translator.py
import time
import re
import random
import requests
import urllib.parse
import config

class AiTranslator:
    def __init__(self):
        # Konfigurasi API Utama (Bluesminds - gpt-5-mini) -> Tanpa Sesi
        self.main_api_url = 'https://api.bluesminds.com/v1/chat/completions'
        self.main_api_key = 'sk-zJct6jIkvGNYSMyK9ETsitpaBa3DE23ftQI5n4VgQmYEKxWh'
        self.main_model = 'gpt-5-mini'
        
        # Konfigurasi API Fallback 1 (Deepseek Custom Endpoint / Vercel)
        self.fallback_url_1 = 'https://ai-seerver.vercel.app/chat/deepseek'
        
        # Konfigurasi API Fallback 2 (TheTurboChat / Gemini)
        self.fallback_url_2 = 'https://theturbochat.com/api/chat/message'
        
        self.MAX_CHARS = 1500
        self.SEPARATOR = '130495848'
        
        self.instruction = getattr(
            config, 
            "PROMPT_TRANSLATOR", 
            "Terjemahkan teks komik ini ke bahasa Indonesia yang natural dan tidak kaku."
        )
        
        self.format_rules = getattr(
            config,
            "PROMPT_FORMAT_RULES",
            "Terjemahkan teks di bawah ini dan pisahkan dengan '{separator}'."
        )
        
    def reset_chapter_session(self):
        """
        Dibiarkan agar tidak error jika dipanggil oleh file main,
        tapi tidak lagi menyimpan ID sesi untuk menghemat token.
        """
        print("[System] Pindah Chapter (Sesi utama bersifat stateless/hemat token).")

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
        rules_text = self.format_rules.format(separator=self.SEPARATOR)
        
        return (
            f"INSTRUCTION: {self.instruction}\n\n"
            f"ATURAN PENTING: {rules_text}\n\n"
            f"TEKS SUMBER:\n\n"
            + f"\n{self.SEPARATOR}\n".join(batch_texts)
        )

    def _main_translate(self, prompt_text):
        """Metode API Utama menggunakan Bluesminds (stateless / tanpa session)."""
        headers = {
            "Authorization": f"Bearer {self.main_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.main_model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt_text
                }
            ],
            "temperature": 0.7
        }

        response = requests.post(
            self.main_api_url, 
            headers=headers, 
            json=payload, 
            timeout=45
        )
        response.raise_for_status()
        data = response.json()
        
        choices = data.get('choices', [])
        if not choices:
            raise ValueError("Respons dari Bluesminds tidak memiliki 'choices'.")
            
        content = choices[0].get('message', {}).get('content', '')
        return content

    def _fallback_translate_1(self, prompt_text):
        """Metode Fallback 1 menggunakan Deepseek Vercel (sebelumnya API Utama)."""
        print("[System] Memulai sesi Fallback 1 via DeepSeek Vercel...")
        
        encoded_query = urllib.parse.quote(prompt_text)
        req_url = f"{self.fallback_url_1}?q={encoded_query}"
        
        try:
            response = requests.get(req_url, timeout=45)
            response.raise_for_status()
            data = response.json()
            
            if data.get('status') != 'success':
                raise ValueError(f"Status response API bukan success: {data}")
                
            ai_response_data = data.get('ai_response', {})
            if not ai_response_data.get('status'):
                raise ValueError(f"AI merespon dengan status false: {ai_response_data}")
                
            result_data = ai_response_data.get('data', {})
            return result_data.get('message', '')
            
        except Exception as e:
            print(f"[Error] Fallback 1 API DeepSeek Vercel gagal: {e}")
            return None

    def _fallback_translate_2(self, prompt_text):
        """Metode Fallback 2 menggunakan Gemini via TheTurboChat."""
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
                    # 1. Coba API Utama (Bluesminds)
                    ai_response_text = self._main_translate(user_message)
                    
                    # Verifikasi hasil Utama
                    translations = self._verify_and_clean(ai_response_text, batch)
                    
                    if translations:
                        print("=== RESPON UTAMA SUKSES ===")
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
                
                # 2. Fallback 1 (DeepSeek Vercel)
                ai_response = self._fallback_translate_1(user_message)
                translations = self._verify_and_clean(ai_response, batch)
                
                if translations:
                    print("=== RESPON FALLBACK 1 SUKSES ===")
                else:
                    print("[Warning] Fallback 1 Gagal atau Format Berantakan. Beralih ke Fallback 2...")
                    
                    # 3. Fallback 2 (TheTurboChat - Gemini)
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
