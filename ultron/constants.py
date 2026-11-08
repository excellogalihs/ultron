"""Application-wide constants."""

APP_NAME = "ultron"
APP_VERSION = "0.1.0"

DEFAULT_MODEL = "gemma3:1b"

SUPPORTED_MODELS = (
    {
        "id": "gemma3:1b",
        "label": "gemma3 1B",
        "note": "Fast · low memory",
    },
    {
        "id": "gemma3:4b",
        "label": "gemma3 4B",
        "note": "Smarter · more RAM",
    },
)

SUPPORTED_MODEL_IDS = tuple(model["id"] for model in SUPPORTED_MODELS)

THEMES = ("dark", "oled", "light", "nord")
ACCENTS = ("violet", "emerald", "cyan", "amber", "rose", "monochrome")
FONTS = ("jetbrains", "sans", "plex")

DEFAULT_SETTINGS = {
    "operator_name": "Operator",
    "default_model": DEFAULT_MODEL,
    "ollama_url": "http://localhost:11434",
    "system_prompt": (
        "You are ultron, a local-first AI assistant running on the user's machine. "
        "Be concise, precise, and practical. Prefer plain language. "
        "If you do not know something, say so instead of inventing an answer."
    ),
    "use_memory": "1",
    "automatic_learning": "1",
    "memory_auto_extract": "1",
    "temperature": "0.7",
    "theme": "dark",
    "accent": "violet",
    "font": "jetbrains",
    "web_search_enabled": "1",
    "task_reminder_time": "09:00",
    "event_reminder_minutes": "10",
    "chat_send_key": "enter",
}

TASK_PRIORITIES = ("high", "normal", "low")
TASK_CATEGORIES = ("general", "work", "study", "personal", "health")
EVENT_CATEGORIES = ("general", "work", "study", "personal", "health")
DOCUMENT_FORMATS = ("markdown", "text")
MAX_CHAT_ATTACHMENT_LENGTH = 30000
MEMORY_CATEGORIES = ("general", "fact", "preference", "project")
