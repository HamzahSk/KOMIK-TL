# translator.py
import time
import re
import json
import random
import requests

class AiTranslator:
    def __init__(self):
        # Konfigurasi API Utama (Flat AI)
        self.api_url = 'https://flatai.org/wp-admin/admin-ajax.php'
        self.nonce = '2aa8686f00'
        self.headers = {
            'Origin': 'https://flatai.org',
            'Referer': 'https://flatai.org/free-ai-chatbot-no-registration/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
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
                # 1. Coba API Utama (Flat AI)
                payload = {
                    'action': 'my_chatbot',
                    'nonce': self.nonce,
                    'model': 'default',
                    'system_message_content': self.instruction,
                    'messages': json.dumps([{'role': 'user', 'content': user_message}])
                }
                
                # Menggunakan stream=True untuk meniru behaviour Server-Sent Events dari Node.js
                response = requests.post(self.api_url, headers=self.headers, data=payload, stream=True, timeout=45)
                response.raise_for_status()
                
                ai_response = ""
                stop_streaming = False
                
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8').strip()
                        if decoded_line.startswith('data:'):
                            json_str = re.sub(r'^data:\s*', '', decoded_line)
                            
                            if not json_str or json_str == '[DONE]':
                                continue
                                
                            try:
                                parsed = json.loads(json_str)
                                content = parsed.get('choices', [{}])[0].get('delta', {}).get('content')
                                
                                if content:
                                    ai_response += content
                                    
                                    # Cek stop stream condition sama seperti di js
                                    match = re.search(r'<memory>|\[USER\]', ai_response)
                                    if match:
                                        ai_response = ai_response[:match.start()].rstrip()
                                        stop_streaming = True
                                        break
                                        
                            except json.JSONDecodeError:
                                pass # Abaikan jika gagal parse line ini
                                
                    if stop_streaming:
                        break

                ai_response = ai_response.strip()

                if not ai_response:
                    raise ValueError("API Utama merespon kosong.")
                    
                # Verifikasi hasil Utama
                translations = self._verify_and_clean(ai_response, batch)
                
                if translations:
                    print("=== RESPON UTAMA (FLAT AI) SUKSES ===")
                else:
                    raise ValueError("Format teks dari API Utama berantakan.")
                
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
