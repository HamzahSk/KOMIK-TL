# config.py
URLMANGA = [""] # https://bbato.com/manga/soulbound"] 
URLCHAPTER = [
    "https://kaliscan.com/manga/34425-reunion/chapter-46.5",
    "https://kaliscan.com/manga/34425-reunion/chapter-50.1",
    "https://kaliscan.com/manga/34425-reunion/chapter-50.2",
    "https://kaliscan.com/manga/34425-reunion/chapter-58",
    "https://kaliscan.com/manga/34425-reunion/chapter-59",
    "https://kaliscan.com/manga/34425-reunion/chapter-60",
    "https://kaliscan.com/manga/34425-reunion/chapter-61",
    "https://kaliscan.com/manga/34425-reunion/chapter-62",
    "https://kaliscan.com/manga/34425-reunion/chapter-63",
    "https://kaliscan.com/manga/34425-reunion/chapter-64",
    "https://kaliscan.com/manga/34425-reunion/chapter-65",
    "https://kaliscan.com/manga/34425-reunion/chapter-66",
    "https://kaliscan.com/manga/34425-reunion/chapter-67",
    "https://kaliscan.com/manga/34425-reunion/chapter-68",
    "https://kaliscan.com/manga/34425-reunion/chapter-69",
    "https://kaliscan.com/manga/34425-reunion/chapter-70",
    "https://kaliscan.com/manga/34425-reunion/chapter-71",
    "https://kaliscan.com/manga/34425-reunion/chapter-72",
    "https://kaliscan.com/manga/34425-reunion/chapter-73",
    "https://kaliscan.com/manga/34425-reunion/chapter-74",
    "https://kaliscan.com/manga/34425-reunion/chapter-75",
    "https://kaliscan.com/manga/34425-reunion/chapter-76",
    "https://kaliscan.com/manga/34425-reunion/chapter-77",
]
 # ["https://vymanga.com/read/reverse-thinking/2853358"]  ["https://bbato.com/read/soulbound/chapter-0"] 
# https://vymanga.com/manga/reverse-thinking  https://kaliscan.com/manga/3172-radio-storm/chapter-2

FONT_PATH = "font"

FONT_NORMAL = "CC Wild Words Roman.ttf"
FONT_BOLD = "Wild Words Bold Bold.ttf"
FONT_ITALIC = "CC Wild Words Italic.ttf"
FONT_BOLD_ITALIC = "CC Wild Words Bold Italic.ttf"
FONT_SFX = "ComicNoteSmooth.ttf"
FONT_SISTEM = "Oxanium-Regular.ttf"
FONT_SISTEM_BOLD = "Oxanium-Bold.ttf"

PROMPT_TRANSLATOR = (
    "Terjemahkan teks komik hasil OCR ini ke bahasa Indonesia yang natural, hidup, dan emosional, "
    "seolah komik ini aslinya berbahasa Indonesia. Dialog dan monolog harus mengalir seperti percakapan nyata, "
    "bukan textbook atau terjemahan kaku. Hindari kata 'lu/gue' atau slang berlebihan yang terkesan tidak profesional; "
    "gunakan 'aku/kamu/kau' atau 'saya/Anda' sesuai konteks karakter. SFX wajib diterjemahkan ke padanan alami Indonesia "
    "(contoh: BAM→DOR, THUMP→DEG, SLAM→BRAK, GASP→HAAH, CREAK→KRIET, SPLASH→BYUR). Jika ada typo atau teks rusak "
    "akibat OCR, tafsirkan maksudnya berdasarkan bunyi dan konteks panel, lalu terjemahkan maknanya. "
    "Nama tokoh dan istilah khusus jangan diubah. Jangan tambahkan simbol, emoji, atau format apa pun "
    "yang tidak ada di teks asli."
)

# [BARU] Aturan format dan pemisahan batch untuk AI
PROMPT_FORMAT_RULES = (
    "Di bawah ini ada kumpulan teks komik yang dipisahkan oleh '{separator}'. "
    "Teks-teks ini bisa berupa dialog bubble, SFX, atau campuran dari beberapa panel. "
    "Dialog antar bubble mungkin masih dalam satu percakapan yang sama—pastikan terjemahannya tetap nyambung "
    "secara alur dan karakter. Cermati dan bedakan mana dialog dan mana SFX sebelum menerjemahkan. "
    "Hasil akhir harus berupa teks terjemahan *BAHASA INDONESIA* yang dipisahkan oleh '{separator}' tanpa tambahan "
    "penjelasan, basa-basi, atau penomoran apa pun."
)
