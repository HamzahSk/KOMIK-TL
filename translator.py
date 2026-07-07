# translator.py
import os
import re
import json
import time
import random

# Import client dari deepseek.py
from deepseek import deepseek_client

class AiTranslator:
    def __init__(self):
        # Ambil list Auth Keys dari Environment Variable (format JSON array)
        # Ganti nama ENV menjadi DEEPSEEK_AUTH_KEYS agar sesuai konteks
        keys_env = os.getenv('DEEPSEEK_AUTH_KEYS', '["fR3AbopXwzh9y9behMnDFGnTMf3p+NnKwhKh92h/gTOZKwXZED8yRx3WkdVJHaau"]')
        
        try:
            self.auth_keys = json.loads(keys_env)
        except json.JSONDecodeError:
            print("[Error] Format DEEPSEEK_AUTH_KEYS di env salah. Harus berupa JSON array.")
            self.auth_keys = []
        
        self.MAX_CHARS = 1500
        self.SEPARATOR = '130495848'
        
        # Variabel untuk menyimpan state session per chapter
        self.current_session_id = None
        self.current_auth_key = None
        
        self.instruction = (
            "Translate the text into natural, fluent Indonesian that sounds as if it were originally "
            "written in Indonesian. Avoid literal, awkward, overly formal, or machine-translated phrasing. "
            "Prioritize readability, immersion, and smooth flow while faithfully preserving the original "
            "meaning, tone, and context. Keep all names and special terms unchanged. Do not add any symbols, "
            "special characters, emojis, bullet points, numbering, decorative marks, or formatting that do "
            "not exist in the source text."
        )

    def start_new_chapter(self):
        """
        Dipanggil setiap kali berganti chapter. 
        Akan merotasi Auth Key secara acak dan membuat session ID baru.
        """
        if not self.auth_keys:
            print("[Error] List Auth Key DeepSeek kosong!")
            return False
            
        # Ganti key secara acak untuk chapter baru
        self.current_auth_key = random.choice(self.auth_keys)
        deepseek_client.bind(self.current_auth_key)
        
        print("[System] Memulai sesi DeepSeek baru untuk chapter ini...")
        
        # Buat sesi chat baru
        response = deepseek_client.new_chat()
        
        if response.get('status') and response.get('data'):
            self.current_session_id = response['data'].get('id')
            print(f"[System] Sukses membuat Session ID: {self.current_session_id}")
            return True
        else:
            print(f"[Error] Gagal membuat sesi baru: {response.get('msg')}")
            self.current_session_id = None
            return False

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

    def _verify_and_clean(self, ai_response, batch):
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
            
        # Antisipasi kalau lupa panggil start_new_chapter() dari main.py
        if not self.current_session_id:
            print("[Warning] Sesi belum diinisialisasi. Membuat sesi darurat...")
            self.start_new_chapter()
            
        batches = self._create_batches(texts)
        all_translations = []
        
        for batch_idx, batch in enumerate(batches):
            print(f"\n[Batch {batch_idx+1}/{len(batches)}] Menerjemahkan {len(batch)} teks via DeepSeek Session...")
            user_message = self._format_batch_text(batch)
            
            try:
                # Memanggil DeepSeek dengan Session ID chapter saat ini
                response = deepseek_client.chat(user_message, chat_id=self.current_session_id)
                
                if response.get('status') and response.get('data'):
                    ai_response = response['data'].get('message', '')
                    translations = self._verify_and_clean(ai_response, batch)
                    
                    if translations:
                        print("=== RESPON DEEPSEEK SUKSES ===")
                    else:
                        print("[Warning] Format respon berantakan atau jumlah baris beda. Memakai teks asli.")
                        translations = batch
                else:
                    print(f"[Error] Chat gagal: {response.get('msg')}. Memakai teks asli.")
                    translations = batch
                    
            except Exception as e:
                print(f"[Error] Sistem DeepSeek bermasalah ({e}). Memakai teks asli.")
                translations = batch

            all_translations.extend(translations)
            time.sleep(2) # Beri jeda sedikit agar sesi di server tidak di-spam
                
        return all_translations

