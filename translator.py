# translator.py
import time
import re
import json
import random
import requests

class AiTranslator:
    def __init__(self):
        # Konfigurasi API Utama (OnChatbot)
        self.api_url = 'https://onlinechatbot.ai/wp-admin/admin-ajax.php'
        self.nonce = 'e82bmm7cf5'
        self.headers = {
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Accept': '*/*',
            'Origin': 'https://onlinechatbot.ai',
            'Referer': 'https://onlinechatbot.ai/chatbots/no-signup/',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Cookie': 'snp_popup_seen=1'
        }
        
        # Konfigurasi API Fallback (DeepSeek Proxy)
        self.fallback_url = 'https://llmproxy.org/api/chat.php'
        
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
        """Membuat header dinamis dengan IP acak untuk fallback."""
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
            "Berikut hasil OCR yang mungkin memiliki kata yang menempel. "
            "Sebagai penerjemah komik profesional, terjemahkan dialog berikut ke bahasa Indonesia percakapan yang natural dan mengalir. "
            f"ATURAN MUTLAK: Pisahkan tiap baris terjemahan HANYA dengan {self.SEPARATOR}. Dilarang keras menambah penjelasan, basa-basi, atau awalan angka.\n\n"
            + f"\n{self.SEPARATOR}\n".join(batch_texts)
        )

    def _fallback_translate(self, prompt_text):
        """Metode fallback menggunakan DeepSeek via llmproxy."""
        print("[System] Memulai sesi Fallback via DeepSeek...")
        
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
            print(f"[Error] Fallback API DeepSeek gagal: {e}")
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
                # 1. Coba API Utama (OnChatbot)
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
                
                response = requests.post(self.api_url, headers=self.headers, data=payload, timeout=20)
                response.raise_for_status()
                data = response.json()
                
                if not data.get('success'):
                    raise ValueError(f"API OnChatbot merespon gagal: {data}")
                    
                ai_response = data.get('data', '')
                
                # Ekstrak hasil API Utama
                translations = self._extract_translations(ai_response)
                
                # Cek apakah selaras
                if len(translations) != len(batch):
                    # Coba pembersihan ekstra
                    raw_lines = [line.strip() for line in ai_response.split('\n') if line.strip() and self.SEPARATOR not in line]
                    if len(raw_lines) == len(batch):
                        translations = [self._clean_part(l) for l in raw_lines]
                    else:
                        # JIKA MASIH GAGAL, PAKSA ERROR AGAR MASUK KE FALLBACK
                        raise ValueError(f"Format teks dari API Utama berantakan ({len(translations)} terjemahan vs {len(batch)} asli)")
                
                print("=== RESPON UTAMA SUKSES ===")
                
            except Exception as e:
                # 2. Jika Gagal API atau Format Salah, jalankan Fallback (DeepSeek)
                print(f"[Warning] API Utama Bermasalah ({e}). Beralih ke Fallback...")
                ai_response = self._fallback_translate(user_message)
                
                if ai_response:
                    # Ekstrak hasil Fallback
                    translations = self._extract_translations(ai_response)
                    
                    if len(translations) != len(batch):
                        print(f"[Warning] Jumlah terjemahan Fallback tidak selaras ({len(translations)} vs {len(batch)}). Mencoba pembersihan ekstra...")
                        raw_lines = [line.strip() for line in ai_response.split('\n') if line.strip() and self.SEPARATOR not in line]
                        if len(raw_lines) == len(batch):
                            translations = [self._clean_part(l) for l in raw_lines]
                        else:
                            print("[Error] Pembersihan ekstra Fallback gagal. Menggunakan teks asli.")
                            translations = batch
                    else:
                        print("=== RESPON FALLBACK SUKSES ===")
                else:
                    print("[Error] Fallback gagal/tidak merespon. Menggunakan teks asli.")
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
