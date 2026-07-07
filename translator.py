# translator.py
import time
import re
import random
import requests
import os

class AiTranslator:
    def __init__(self):
        # Konfigurasi API Utama (Olabiba)
        self.phpsessid = os.urandom(13).hex()
        self.olabiba_headers = {
            'referer': 'https://www.olabiba.com/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36',
            'cookie': f'PHPSESSID={self.phpsessid};'
        }
        
        # Konfigurasi API Fallback 1 (DeepSeek Proxy)
        self.fallback_url = 'https://llmproxy.org/api/chat.php'
        
        # Konfigurasi API Fallback 2 (TheTurboChat / Gemini)
        self.fallback_url_2 = 'https://cors-proxydev.wisp.uno/proxy?url=https://theturbochat.com/api/chat/message'
        
        self.MAX_CHARS = 1500
        self.SEPARATOR = '130495848'
        
        self.instruction = (
            "Translate the text into natural, fluent Indonesian that sounds as if it were originally "
            "written in Indonesian. Avoid literal, awkward, overly formal, or machine-translated phrasing. "
            "Prioritize readability, immersion, and smooth flow while faithfully preserving the original "
            "meaning, tone, and context. Keep all names and special terms unchanged. Do not add any symbols, "
            "special characters, emojis, bullet points, numbering, decorative marks, or formatting that do "
            "not exist in the source text."
        )

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

    def _format_batch_text(self, batch_texts):
        return (
            f"INSTRUCTION: {self.instruction}\n\n"
            f"ATURAN MUTLAK: Pisahkan tiap baris terjemahan HANYA dengan {self.SEPARATOR}. Dilarang keras menambah penjelasan, basa-basi, atau awalan angka."
            f"Berikut teks nya: \n\n"
            + f"\n{self.SEPARATOR}\n".join(batch_texts)
        )

    def _olabiba_translate(self, prompt_text):
        """Metode Utama menggunakan Olabiba Scraper."""
        print("[System] Memulai sesi API Utama via Olabiba...")
        
        # Tahap 1: Kirim Pesan (POST)
        payload = {
            'text': prompt_text,
            'mood': 'normal', # Diubah ke 'normal' agar terjemahan lebih natural dibanding 'funny'
            'lang': 'id',
            'adblock': 'No',
            'theme': 'light'
        }

        try:
            post_res = requests.post(
                'https://cors-proxy-eight-ruddy.vercel.app/?url=https://www.olabiba.com/php/message.php', 
                headers=self.olabiba_headers, 
                data=payload,
                timeout=20
            )
            post_res.raise_for_status()
            
            # Tahap 2: Terima Stream Pesan (GET)
            stream_headers = self.olabiba_headers.copy()
            stream_headers['accept'] = 'text/event-stream'
            
            stream_res = requests.get(
                'https://cors-proxy-eight-ruddy.vercel.app/?url=https://www.olabiba.com/php/stream.php',
                headers=stream_headers,
                stream=True,
                timeout=30
            )
            stream_res.raise_for_status()

            full_response = ""
            for line in stream_res.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data:'):
                        data_content = decoded_line.replace('data:', '', 1).strip()
                        if data_content == '[DONE]':
                            break
                        full_response += data_content

            # Tahap 3: Pembersihan respons seperti di olabaai.js
            clean_text = full_response.replace('&nbsp;', ' ')
            clean_text = re.sub(r'\[ELABORATE\]|\[FOLLOWUP\].*|', '', clean_text, flags=re.DOTALL)
            return clean_text.strip()

        except Exception as e:
            print(f"[Error] API Olabiba gagal: {e}")
            return None

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
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            content = data.get('content', '')
            
            # Hapus tag <think>...</think> jika ada
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
            "history": [],  # Dikosongkan agar tidak ada memori lintas-batch
            "language": "en",
            "sourcePage": "/gemini"
        }

        try:
            response = requests.post(
                self.fallback_url_2, 
                headers=headers, 
                json=payload, 
                timeout=30
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
        
        # Jika selaras, langsung kembalikan
        if len(translations) == len(batch):
            return translations
            
        # Jika tidak selaras, coba pembersihan ekstra
        raw_lines = [line.strip() for line in ai_response.split('\n') if line.strip() and self.SEPARATOR not in line]
        if len(raw_lines) == len(batch):
            return [self._clean_part(l) for l in raw_lines]
            
        # Jika tetap gagal, return None agar bisa dilanjut ke fallback berikutnya
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
            
            try:
                # 1. Coba API Utama (Olabiba)
                ai_response = self._olabiba_translate(user_message)
                translations = self._verify_and_clean(ai_response, batch)
                
                if translations:
                    print("=== RESPON UTAMA SUKSES ===")
                else:
                    raise ValueError("Format teks dari API Utama Olabiba berantakan.")
                
            except Exception as e:
                print(f"[Warning] API Utama Bermasalah ({e}). Beralih ke Fallback 1...")
                
                # 2. Fallback 1 (DeepSeek)
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
