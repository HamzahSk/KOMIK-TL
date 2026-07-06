# translator.py
import time
import re
import json
import random
import requests
import uuid
from datetime import datetime, timezone

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
        
        # Konfigurasi API Fallback 1 (DeepSeek Proxy)
        self.fallback_url = 'https://llmproxy.org/api/chat.php'
        
        # Konfigurasi API Fallback 2 (Unlimited AI)
        self.unliai_url = 'https://app.unlimitedai.chat/api/chat'
        self.unliai_device_id = str(uuid.uuid4()) # Generate random device ID per sesi bot
        
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
        """Membuat header dinamis dengan IP acak untuk Fallback 1 (DeepSeek)."""
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
        """Metode Fallback 1 menggunakan DeepSeek via llmproxy."""
        print("[System] Memulai sesi Fallback 1 via DeepSeek Proxy...")
        
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
            
    def _fallback_unliai_translate(self, prompt_text):
        """Metode Fallback 2 menggunakan Unlimited AI."""
        print("[System] Memulai sesi Fallback 2 via Unlimited AI...")
        
        chat_id = str(uuid.uuid4())
        # Format waktu ISO 8601 dengan akhiran Z
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        messages = [
            {
                "id": str(uuid.uuid4()),
                "content": prompt_text,
                "createdAt": now,
                "parts": [{"type": "text", "text": prompt_text}],
                "role": "user"
            },
            {
                "id": str(uuid.uuid4()),
                "content": "",
                "createdAt": now,
                "parts": [{"type": "text", "text": ""}],
                "role": "assistant"
            }
        ]
        
        payload = {
            "chatId": chat_id,
            "deviceId": self.unliai_device_id,
            "locale": "id",
            "messages": messages,
            "selectedCharacter": None,
            "selectedChatModel": "chat-model-reasoning",
            "selectedStory": None
        }
        
        headers = {
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://app.unlimitedai.chat',
            'referer': 'https://app.unlimitedai.chat/id',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'x-next-intl-locale': 'id'
        }
        
        try:
            response = requests.post(self.unliai_url, headers=headers, json=payload, stream=True, timeout=30)
            response.raise_for_status()
            
            full_reply = ""
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    try:
                        parsed = json.loads(line)
                        if parsed.get('type') == 'delta' and parsed.get('delta'):
                            full_reply += parsed['delta']
                    except json.JSONDecodeError:
                        continue
                        
            # Hapus tag <think> jika ada
            clean_content = re.sub(r'<think>.*?</think>', '', full_reply, flags=re.DOTALL | re.IGNORECASE).strip()
            return clean_content
            
        except Exception as e:
            print(f"[Error] Fallback 2 API Unlimited AI gagal: {e}")
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
                        raise ValueError(f"Format teks dari API Utama berantakan ({len(translations)} terjemahan vs {len(batch)} asli)")
                
                print("=== RESPON UTAMA SUKSES ===")
                
            except Exception as e:
                # 2. Jika API Utama Gagal, coba Fallback 1 (DeepSeek)
                print(f"[Warning] API Utama Bermasalah ({e}). Beralih ke Fallback 1 (DeepSeek Proxy)...")
                ai_response = self._fallback_translate(user_message)
                
                if not ai_response:
                    # 3. Jika Fallback 1 Gagal, coba Fallback 2 (Unlimited AI)
                    print(f"[Warning] Fallback 1 (DeepSeek) Bermasalah. Beralih ke Fallback 2 (Unlimited AI)...")
                    ai_response = self._fallback_unliai_translate(user_message)

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
                    print("[Error] Semua API (Utama, Fallback 1, Fallback 2) gagal merespon. Menggunakan teks asli.")
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
