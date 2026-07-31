# translator_local.py
import re
import os
import time
from huggingface_hub import hf_hub_download
from llama_cpp import Llama
import config

class AiTranslator:
    def __init__(self):
        self.MAX_CHARS = 1500
        self.SEPARATOR = '130495848'
        
        self.instruction = getattr(
            config, 
            "PROMPT_TRANSLATOR", 
            "You are a professional comic translator. Translate the following English comic text into natural, conversational Indonesian."
        )
        
        self.format_rules = getattr(
            config,
            "PROMPT_FORMAT_RULES",
            "Translate each line below and separate the translated lines using strictly '{separator}' without adding extra numbering or commentary."
        )
        
        # Inisialisasi model lokal LLaMA.cpp
        self.llm = self._load_local_model()

    def _load_local_model(self):
        """
        Mengunduh model Qwen2.5-1.5B-Instruct GGUF secara otomatis (jika belum ada)
        dan memuatnya ke memori CPU menggunakan llama.cpp.
        """
        print("[System] Memeriksa/Mengunduh model lokal Qwen2.5-1.5B-Instruct-GGUF...")
        
        # Repositori dan nama file model berukuran ~1B-1.5B yang sangat baik di Bahasa Indonesia
        repo_id = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
        filename = "qwen2.5-1.5b-instruct-q4_k_m.gguf" # Kuantisasi Q4_K_M (~1 GB RAM)
        
        model_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            cache_dir="./models"
        )
        
        print(f"[System] Memuat model ke llama.cpp dari: {model_path}")
        
        # Konfigurasi optimal untuk eksekusi CPU cepat
        llm = Llama(
            model_path=model_path,
            n_ctx=2048,          # Konteks token (cukup untuk batch komik)
            n_threads=os.cpu_count() or 4,  # Gunakan seluruh core CPU yang tersedia
            n_batch=512,         # Batch processing prompt
            verbose=False        # Ubah ke True jika ingin melihat log performa/kecepatan
        )
        return llm

    def reset_chapter_session(self):
        """Kompatibilitas dengan pipeline utama."""
        print("[System] Reset sesi chapter (Lokal Model siap digunakan).")

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
            
        raw_lines = [
            line.strip() for line in ai_response.split('\n') 
            if line.strip() and self.SEPARATOR not in line
        ]
        if len(raw_lines) == len(batch):
            return [self._clean_part(l) for l in raw_lines]
            
        return None

    def translate_batch(self, texts):
        if not texts:
            return []
        
        batches = self._create_batches(texts)
        all_translations = []
        
        for batch_idx, batch in enumerate(batches):
            print(f"\n[Batch {batch_idx+1}/{len(batches)}] Menerjemahkan {len(batch)} teks secara lokal...")
            
            rules_text = self.format_rules.format(separator=self.SEPARATOR)
            source_text_joined = f"\n{self.SEPARATOR}\n".join(batch)
            
            # Pengaturan prompt menggunakan System & User message standar model Instruct
            system_prompt = f"{self.instruction}\n{rules_text}"
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"SOURCE TEXT TO TRANSLATE:\n\n{source_text_joined}"}
            ]
            
            start_time = time.time()
            try:
                # Inferensi menggunakan llama-cpp-python
                response = self.llm.create_chat_completion(
                    messages=messages,
                    max_tokens=1024,
                    temperature=0.3, # Rendah agar hasilnya konsisten dan mematuhi format separator
                    top_p=0.85
                )
                
                ai_response_text = response["choices"][0]["message"]["content"]
                elapsed_time = time.time() - start_time
                print(f"[System] Selesai dalam {elapsed_time:.2f} detik.")
                
                translations = self._verify_and_clean(ai_response_text, batch)
                
                if translations:
                    all_translations.extend(translations)
                else:
                    print("[Warning] Format keluaran AI tidak selaras dengan jumlah input. Menggunakan teks asli.")
                    all_translations.extend(batch)
                    
            except Exception as e:
                print(f"[Error] Terjadi kesalahan pada proses inferensi lokal: {e}")
                all_translations.extend(batch)
                
        return all_translations
