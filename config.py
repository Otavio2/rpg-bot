import os


# ==========================================================
# CONFIGURAÇÕES PRINCIPAIS DO HANSEL
# ==========================================================

BOT_NAME = "Matheus"
CREATOR = "Kleber"
BOT_TAG = "matheus"

BOT_ID = "8722172648"
BOT_USERNAME = "NIOBIOchat_BOT"

# IDs dos administradores
ADMINS = ["8398287578"]


# ==========================================================
# TELEGRAM
# ==========================================================

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"


# ==========================================================
# SUPABASE
# ==========================================================

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL:
    raise RuntimeError("SUPABASE_URL não configurado")

if not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_KEY não configurado")


# ==========================================================
# GEMINI
# ==========================================================

GEMINI_API_KEYS = [
    key
    for key in [
        os.getenv(f"GEMINI_API_KEY_{i}")
        for i in range(1, 6)
    ]
    if key
]

# Compatibilidade com uma única chave
if not GEMINI_API_KEYS:
    chave_gemini = os.getenv("GEMINI_API_KEY")

    if chave_gemini:
        GEMINI_API_KEYS = [chave_gemini]

gemini_key_index = 0


# ==========================================================
# GROQ
# ==========================================================

GROQ_API_KEYS = [
    key
    for key in [
        os.getenv(f"GROQ_API_KEY_{i}")
        for i in range(1, 6)
    ]
    if key
]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

GROQ_BLACKLIST = {}


# ==========================================================
# SISTEMA
# ==========================================================

TIMEOUT_API = 20

MAX_WORKERS = 10

MAX_PROCESSED_UPDATES = 1000


# ==========================================================
# CACHE
# ==========================================================

CACHE_TIMEOUTS = {
    "profile": 1800,
    "memory": 600,
    "response": 600,
    "search": 300,
    "summary": 1800,
}


# ==========================================================
# CLASSIFICAÇÃO DE MEMÓRIA
# ==========================================================

PESO_CATEGORIA = {
    "nome": 100,
    "apelido": 95,
    "cidade": 90,
    "profissao": 90,
    "comida": 80,
    "gosto": 70,
    "preferencia": 70,
    "conversa": 5,
}


SAUDACOES = [
    "oi",
    "ola",
    "olá",
    "bom dia",
    "boa tarde",
    "boa noite",
    "eai",
    "fala",
]


MAPA_ASSUNTO = {
    "nome": "nome",
    "apelido": "apelido",
    "me chama": "apelido",
    "moro": "cidade",
    "cidade": "cidade",
    "trabalho": "profissao",
    "profissao": "profissao",
    "gosto": "gosto",
    "favorito": "comida",
    "comida": "comida",
}


# ==========================================================
# FUSO HORÁRIO
# ==========================================================

TIMEZONE_DEFAULT = "America/Fortaleza"


# ==========================================================
# MODELO GROQ
# ==========================================================

GROQ_MODEL = "llama-3.1-8b-instant"


# ==========================================================
# MODELO GEMINI
# ==========================================================

GEMINI_MODEL = "gemini-2.0-flash-exp"
