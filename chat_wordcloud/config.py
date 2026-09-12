"""WordCloud configuration for Fissure Bot - styled after OpenDota."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

WORDCLOUD_FONT_PATH = BASE_DIR / "assets" / "fonts" / "NotoSans-Regular.ttf"

WORDCLOUD_DEBUG = False

WORDCLOUD_WIDTH = 800
WORDCLOUD_HEIGHT = 800
WORDCLOUD_BACKGROUND_COLOR = "#171f37"
WORDCLOUD_MIN_FONT_SIZE = 14
WORDCLOUD_MAX_FONT_SIZE = 90
WORDCLOUD_RELATIVE_SCALING = 0.5
WORDCLOUD_GENERATION_TIMEOUT = 30
WORDCLOUD_RESULT_TIMEOUT = 5
WORDCLOUD_WORKER_NICE = 10
WORDCLOUD_MAX_WORDS = 120
WORDCLOUD_MIN_WORD_FREQUENCY = 1
WORDCLOUD_RANDOM_STATE = 42
WORDCLOUD_PERIOD_DAYS = 365
WORDCLOUD_MESSAGE_LIMIT = 10000
WORDCLOUD_CACHE_TTL = 900
WORDCLOUD_PREFER_HORIZONTAL = 0.90
WORDCLOUD_MARGIN = 6
WORDCLOUD_SCALE = 1.0
WORDCLOUD_SAFE_MARGIN = 30
WORDCLOUD_LIGHT_COLORS = [
    "#FFFFFF",
    "#F5F5F5",
    "#B2EBF2",
]

WORDCLOUD_BRIGHT_COLORS = [
    "#FFEB3B",
    "#00BCD4",
    "#6A1B9A",
    "#FF4081",
    "#4CAF50",
]

WORDCLOUD_TOXIC_COLORS = [
    "#39FF14",
    "#00FF00",
    "#FF073A",
    "#FF3B30",
    "#FF8C00",
    "#FFEA00",
    "#FF10F0",
    "#00FFFF",
]

WORDCLOUD_COLORS = WORDCLOUD_LIGHT_COLORS + WORDCLOUD_BRIGHT_COLORS + WORDCLOUD_TOXIC_COLORS

WORDCLOUD_WORD_PADDING = 5

# Disable mask path - use solid fill like OpenDota
WORDCLOUD_MASK_PATH = None

STOP_WORDS_RU = {
    "и", "а", "в", "во", "на", "с", "со", "к", "у", "из", "за", "по", "для",
    "от", "до", "о", "об", "не", "ни", "но", "же", "бы", "ли", "это", "этот",
    "эта", "эти", "что", "как", "так", "там", "тут", "уже", "еще", "ещё", "я",
    "ты", "он", "она", "мы", "вы", "они", "мне", "тебе", "его", "ее", "их",
    "мой", "твой", "свой", "наш", "ваш", "их", "который", "которая", "которые",
    "где", "когда", "почему", "зачем", "сколько", "вот", "тут", "там", "есть",
    "быть", "будет", "было", "был", "была", "были", "буду", "будешь", "будем", "будете", "будут",
    "твоя", "своя",
    "да", "нет", "ну", "все", "всё", "всего", "только", "просто", "уже", "ещё",
    "совсем", "вообще", "типа", "короче", "слушай", "смотри", "значит", "нужно",
    "надо", "может", "можно", "ещё", "тоже", "также", "очень", "более",
    "менее", "самый", "самая", "самое", "самые", "другой", "другая", "другое",
    "км", "см", "мм",
    "ссср",
    "фиссура", "профиль", "бота", "игры", "середина",
    "восстанавливается", "восстановить", "проверка", "отправлено", "ошибка", "успешно",
    "рейтинг", "ран", "ранг", "ммр", "стeam", "steam",
    "кнопка", "меню", "главное",
    "чат", "сообщение", "сообщения",
}

STOP_WORDS_EN = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "are",
    "it", "this", "that", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "could", "should", "may",
    "might", "must", "can", "i", "you", "he", "she", "we", "they", "me", "him",
    "her", "us", "them", "my", "your", "his", "its", "our", "their", "what",
    "which", "who", "whom", "whose", "when", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no", "nor",
    "not", "only", "own", "same", "so", "than", "too", "very", "just", "because",
    "but", "if", "or", "while", "about", "against", "between", "into", "through",
    "during", "before", "after", "above", "below", "from", "up", "down", "out",
    "off", "over", "under", "again", "further", "then", "once", "here", "there",
    "rank", "mmr", "steam", "button", "menu", "chat", "message", "error", "success",
    "recovered", "refresh", "update", "profile", "fissure",
}

STOP_WORDS = STOP_WORDS_RU | STOP_WORDS_EN
