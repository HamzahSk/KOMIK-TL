# config.py
URLMANGA = [""] # https://bbato.com/manga/soulbound"] 
URLCHAPTER = [
    "https://kaliscan.com/manga/34425-reunion/chapter-18",
    "https://kaliscan.com/manga/34425-reunion/chapter-19",
    "https://kaliscan.com/manga/34425-reunion/chapter-20",
    "https://kaliscan.com/manga/34425-reunion/chapter-21",
    "https://kaliscan.com/manga/34425-reunion/chapter-22",
    "https://kaliscan.com/manga/34425-reunion/chapter-23",
    "https://kaliscan.com/manga/34425-reunion/chapter-24",
    "https://kaliscan.com/manga/34425-reunion/chapter-25",
    "https://kaliscan.com/manga/34425-reunion/chapter-26",
    "https://kaliscan.com/manga/34425-reunion/chapter-27",
    "https://kaliscan.com/manga/34425-reunion/chapter-28",
    "https://kaliscan.com/manga/34425-reunion/chapter-29",
    "https://kaliscan.com/manga/34425-reunion/chapter-30",
    "https://kaliscan.com/manga/34425-reunion/chapter-31",
    "https://kaliscan.com/manga/34425-reunion/chapter-32",
    "https://kaliscan.com/manga/34425-reunion/chapter-33",
    "https://kaliscan.com/manga/34425-reunion/chapter-34",
    "https://kaliscan.com/manga/34425-reunion/chapter-35",
    "https://kaliscan.com/manga/34425-reunion/chapter-36",
    "https://kaliscan.com/manga/34425-reunion/chapter-37",
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
