# translator.py
import time
import re
import json
import uuid
import requests
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
        
        # Konfigurasi API Fallback (Unlimited AI)
        self.unli_url = 'https://app.unlimitedai.chat/api/chat'
        self.unli_headers = {
            'accept': '*/*',
            'content-type': 'application/json',
            'origin': 'https://app.unlimitedai.chat',
            'referer': 'https://app.unlimitedai.chat/id',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'x-next-intl-locale': 'id'
        }
        
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
        """Metode fallback menggunakan Unlimited AI dengan model reasoning."""
        print("[System] Memulai sesi Fallback via Unlimited AI...")
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'
        
        user_msg_id = str(uuid.uuid4())
        assistant_msg_id = str(uuid.uuid4())
        
        messages = [
            {
                "id": user_msg_id,
                "content": prompt_text,
                "createdAt": now,
                "parts": [{"type": "text", "text": prompt_text}],
                "role": "user"
            },
            {
                "id": assistant_msg_id,
                "content": "",
                "createdAt": now,
                "parts": [{"type": "text", "text": ""}],
                "role": "assistant"
            }
        ]

        payload = {
            "chatId": str(uuid.uuid4()),
            "deviceId": "dc9fc5ff-18f2-40a6-b59c-9f975a252283",
            "locale": "id",
            "messages": messages,
            "selectedCharacter": None,
            "selectedChatModel": "chat-model-reasoning",
            "selectedStory": None
        }

        try:
            response = requests.post(self.unli_url, headers=self.unli_headers, json=payload, stream=True)
            response.raise_for_status()
            
            full_reply = ""
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    try:
                        data = json.loads(decoded_line)
                        if data.get('type') == 'delta' and data.get('delta'):
                            full_reply += data['delta']
                    except json.JSONDecodeError:
                        continue
            
            # Hapus tag <think>...</think> jika model memberikan proses penalaran
            full_reply = re.sub(r'<think>.*?</think>', '', full_reply, flags=re.DOTALL).strip()
            return full_reply
            
        except Exception as e:
            print(f"[Error] Fallback API Unlimited AI gagal: {e}")
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
                print("=== RESPON UTAMA SUKSES ===")
                
            except Exception as e:
                # 2. Jika Gagal, jalankan Fallback (Unlimited AI)
                print(f"[Warning] API Utama Gagal ({e}). Beralih ke Fallback...")
                ai_response = self._fallback_translate(user_message)
                
                if ai_response:
                    print("=== RESPON FALLBACK SUKSES ===")
                else:
                    print("[Error] Kedua API gagal. Menggunakan teks asli untuk batch ini.")
                    all_translations.extend(batch)
                    continue

            # 3. Ekstraksi hasil terjemahan dari respons
            translations = self._extract_translations(ai_response)
            
            if len(translations) != len(batch):
                print(f"[Warning] Jumlah terjemahan tidak selaras ({len(translations)} vs {len(batch)}). Mencoba pembersihan ekstra...")
                raw_lines = [line.strip() for line in ai_response.split('\n') if line.strip() and self.SEPARATOR not in line]
                if len(raw_lines) == len(batch):
                    translations = [self._clean_part(l) for l in raw_lines]
                else:
                    print("[Warning] Pembersihan ekstra gagal. Menggunakan teks asli.")
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
