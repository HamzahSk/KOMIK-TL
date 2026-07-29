# translator.py
import re
import time
from transformers import MarianMTModel, MarianTokenizer

class AiTranslator:
    def __init__(self):
        # Menggunakan model offline NMT Inggris -> Indonesia dari HuggingFace
        self.model_name = "Helsinki-NLP/opus-mt-en-id"
        self.tokenizer = None
        self.model = None
        self.BATCH_SIZE = 8  # Dibatasi 8 agar RAM 7GB GitHub Actions aman & cepat
        
        # Kamus SFX Tambahan (karena model NMT kurang gaul untuk bunyi-bunyian)
        self.SFX_MAP = {
            "BAM": "DOR", "THUMP": "DEG", "SLAM": "BRAK", 
            "GASP": "HAAH", "CREAK": "KRIET", "SPLASH": "BYUR",
            "CLICK": "KLIK", "ROAR": "ROAAR", "SIGH": "HAHH"
        }
        
        self._load_model()

    def _load_model(self):
        """Memuat tokenizer dan model NMT offline ke memori CPU."""
        print(f"[System] Memuat model offline: {self.model_name}...")
        start_time = time.time()
        try:
            self.tokenizer = MarianTokenizer.from_pretrained(self.model_name)
            self.model = MarianMTModel.from_pretrained(self.model_name)
            print(f"[System] Model offline sukses dimuat dalam {time.time() - start_time:.2f} detik!")
        except Exception as e:
            print(f"[Error] Gagal memuat model offline: {e}")

    def reset_chapter_session(self):
        """Fungsi kompatibilitas dengan main.py agar tidak error saat pindah chapter."""
        print("[System] Sesi chapter baru dimulai (Offline Mode).")

    def _preprocess_text(self, text):
        """Membersihkan teks sebelum masuk ke model agar hasil terjemahan lebih natural."""
        cleaned = text.strip()
        # Jika teks persis kata SFX bahasa Inggris, langsung ganti
        upper_text = re.sub(r'[^A-Z]', '', cleaned.upper())
        if upper_text in self.SFX_MAP and len(cleaned.split()) == 1:
            return self.SFX_MAP[upper_text], True
        return cleaned, False

    def _clean_output(self, text):
        """Merapikan spasi dan kapitalisasi standar setelah diterjemahkan."""
        cleaned = text.strip()
        # Perbaiki awalan karakter aneh jika ada
        cleaned = re.sub(r'^\W+', '', cleaned)
        return cleaned if cleaned else "-"

    def translate_batch(self, texts):
        if not texts:
            return []
            
        if not self.model or not self.tokenizer:
            print("[Warning] Model offline tidak tersedia, mengembalikan teks asli...")
            return texts

        print(f"\n[Offline NMT] Menerjemahkan {len(texts)} blok teks menggunakan CPU...")
        all_translations = []

        # Pisahkan menjadi batch-batch kecil agar tidak membebani RAM & CPU
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch_texts = texts[i : i + self.BATCH_SIZE]
            batch_results = []
            to_translate = []
            index_mapping = {}

            # Filter cepat untuk teks SFX / teks kosong
            for idx, text in enumerate(batch_texts):
                processed_text, is_sfx = self._preprocess_text(text)
                if is_sfx:
                    batch_results.append((idx, processed_text))
                else:
                    index_mapping[len(to_translate)] = idx
                    to_translate.append(processed_text)

            # Terjemahkan batch ke model HuggingFace / CTranslate2
            if to_translate:
                try:
                    encoded_input = self.tokenizer(
                        to_translate,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                        max_length=512
                    )
                    
                    # Generate terjemahan dengan CPU
                    translated_tokens = self.model.generate(**encoded_input)
                    decoded_texts = self.tokenizer.batch_decode(
                        translated_tokens, 
                        skip_special_tokens=True
                    )

                    for sub_idx, trans_text in enumerate(decoded_texts):
                        original_idx = index_mapping[sub_idx]
                        batch_results.append((original_idx, self._clean_output(trans_text)))

                except Exception as e:
                    print(f"[Error] Gagal menerjemahkan sub-batch: {e}")
                    for sub_idx, raw_text in enumerate(to_translate):
                        original_idx = index_mapping[sub_idx]
                        batch_results.append((original_idx, raw_text))

            # Urutkan kembali sesuai urutan halaman aslinya
            batch_results.sort(key=lambda x: x[0])
            all_translations.extend([item[1] for item in batch_results])

        return all_translations
