import os
import requests
import threading
import time
import logging
import base64
from datetime import datetime
import pytz
from collections import defaultdict, deque
from flask import Flask, request
from concurrent.futures import ThreadPoolExecutor
from queue import Queue # CORREÇÃO 1: FILA GLOBAL

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# ========================================
# CONFIGURAÇÃO
# ========================================
BOT_NAME = "Matheus"
CREATOR = "Kleber"
CREATOR_ID = "8398287578"
ADMINS = ["8398287578"]
TIMEZONE = "America/Fortaleza"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
RENDER_URL = "https://edu-bot-6yfa.onrender.com"

if not TELEGRAM_TOKEN: raise RuntimeError("TELEGRAM_TOKEN não configurado")
if not OPENROUTER_API_KEY: raise RuntimeError("OPENROUTER_API_KEY não configurada")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

BOT_ID = None
BOT_USERNAME = None

# FALLBACK COM 3 MODELOS FREE PRA NÃO ESTOURAR COTA
MODELOS = [
    "openrouter/free",
    "deepseek/deepseek-chat:free",
    "meta-llama/llama-3.1-8b-instruct:free"
]

# ========================================
# LIMITES E PROTEÇÃO
# ========================================
MAX_TOKENS_RESPOSTA = 500
HISTORICO_LIMITE_USER = 10
HISTORICO_LIMITE_GRUPO = 6
MAX_MSG_LENGTH = 4000
TIMEOUT_API = 60
COOLDOWN_SEGUNDOS_PV = 2
COOLDOWN_SEGUNDOS_GRUPO = 5 # CORREÇÃO 2: COOLDOWN MAIOR EM GRUPO

MAX_REQUISICOES_POR_MINUTO = 30 # CORREÇÃO 3: LIMITE GLOBAL ANTI-FLOOD
JANELA_TEMPO = 60

# ========================================
# MEMÓRIA TEMPORÁRIA
# ========================================
HISTORICO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_USER))
HISTORICO_GRUPO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_GRUPO))
USER_COOLDOWN = {}
LOCK = threading.Lock()

# CORREÇÃO 4: PROCESSED_UPDATES ROBUSTO COM TEMPO
PROCESSED_UPDATES = {} # {update_id: timestamp}
UPDATE_EXPIRACAO = 3600 # 1 hora. Depois disso esquece o update

# FILA GLOBAL PRA NÃO DERRUBAR
REQUEST_QUEUE = Queue()
executor = ThreadPoolExecutor(max_workers=20) # Aumentei pra 20
REQUISICOES_TIMES = deque() # Guarda timestamp das últimas reqs

# ========================================
# WORKER DA FILA
# ========================================
def worker_fila():
    while True:
        func, args = REQUEST_QUEUE.get()
        try:
            func(*args)
        except Exception as e:
            logging.exception(f"[WORKER ERROR] {e}")
        REQUEST_QUEUE.task_done()

threading.Thread(target=worker_fila, daemon=True).start()

# ========================================
# TELEGRAM
# ========================================
def init_bot_info():
    global BOT_ID, BOT_USERNAME
    try:
        r = requests.get(f"{TELEGRAM_API_URL}/getMe", timeout=TIMEOUT_API)
        r.raise_for_status()
        data = r.json()["result"]
        BOT_ID = data["id"]
        BOT_USERNAME = data["username"].lower()
        logging.info(f"[BOT] Iniciado como @{BOT_USERNAME} | ID: {BOT_ID}")
    except Exception as e:
        logging.exception(f"[TELEGRAM ERROR] Falha ao iniciar bot: {e}")
        raise

def send_message(chat_id, text, reply_to=None):
    if not text: text = "Não consegui gerar uma resposta agora."
    text = text[:4096]
    for parse_mode in ["Markdown", None]:
        try:
            payload = {"chat_id": chat_id, "text": text}
            if parse_mode: payload["parse_mode"] = parse_mode
            if reply_to: payload["reply_to_message_id"] = reply_to
            r = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=TIMEOUT_API)
            if r.status_code == 200: return True
            if r.status_code == 400 and parse_mode: continue
        except: time.sleep(1)
    return False

def get_file_from_telegram(file_id):
    r = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}")
    r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    img = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}")
    img.raise_for_status()
    return base64.b64encode(img.content).decode("utf-8")

def get_user_info(user):
    user_id = str(user["id"])
    nome = user.get("first_name", "usuário")
    tipo = "criador" if user_id == CREATOR_ID else "admin" if user_id in ADMINS else "usuario"
    return {"id": user_id, "nome": nome, "tipo": tipo}

def check_global_rate_limit():
    # CORREÇÃO 3: CONTROLE GLOBAL
    agora = time.time()
    with LOCK:
        while REQUISICOES_TIMES and REQUISICOES_TIMES[0] < agora - JANELA_TEMPO:
            REQUISICOES_TIMES.popleft()
        if len(REQUISICOES_TIMES) >= MAX_REQUISICOES_POR_MINUTO:
            return False
        REQUISICOES_TIMES.append(agora)
    return True

def check_cooldown(user_id, is_group):
    cooldown = COOLDOWN_SEGUNDOS_GRUPO if is_group else COOLDOWN_SEGUNDOS_PV
    agora = time.time()
    with LOCK:
        if agora - USER_COOLDOWN.get(user_id, 0) < cooldown: return False
        USER_COOLDOWN[user_id] = agora
    return True

def is_update_processado(update_id):
    # CORREÇÃO 4: LIMPA UPDATES ANTIGOS DE 1H
    agora = time.time()
    with LOCK:
        # Limpa lixo antigo
        for uid in list(PROCESSED_UPDATES.keys()):
            if agora - PROCESSED_UPDATES[uid] > UPDATE_EXPIRACAO:
                del PROCESSED_UPDATES[uid]
        if update_id in PROCESSED_UPDATES: return True
        PROCESSED_UPDATES[update_id] = agora
    return False

#... resto das funções get_datetime_info, get_historico, etc ficam iguais...

# ========================================
# OPENROUTER COM FALLBACK DE MODELO
# ========================================
def call_openrouter(messages):
    for modelo in MODELOS: # Tenta 1 por 1
        for tentativa in range(2):
            try:
                headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "HTTP-Referer": RENDER_URL, "X-Title": BOT_NAME}
                payload = {"model": modelo, "messages": messages, "max_tokens": MAX_TOKENS_RESPOSTA}
                r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT_API)
                tempo = round(r.elapsed.total_seconds(), 2)

                if r.status_code == 200:
                    resposta = r.json().get("choices", [{}])[0].get("message", {}).get("content")
                    if modelo!= MODELOS[0]: resposta = f"⚡ Usei modelo reserva.\n\n{resposta}"
                    return resposta, tempo, modelo

                if r.status_code in [429, 500, 503]:
                    time.sleep(2 ** tentativa)
                    continue
                break # Se deu 400, não adianta tentar nesse modelo
            except Exception as e:
                logging.exception(f"[OPENROUTER ERROR {modelo}]: {e}")
                time.sleep(1)
    return "⚠️ Todos os modelos estão lotados. Tenta em 1 min.", 0, "nenhum"

# ========================================
# PROCESSAMENTO
# ========================================
def processar_mensagem(msg):
    try:
        if not check_global_rate_limit(): # BLOQUEIA SE ESTIVER LOTADO
            logging.warning("[RATE LIMIT] Fila lotada. Ignorando msg.")
            return

        chat = msg["chat"]; chat_id = chat["id"]; chat_type = chat["type"]
        user = msg["from"]; message_id = msg["message_id"]
        user_info = get_user_info(user)
        is_group = chat_type in ["group", "supergroup"]
        if is_group and not deve_responder(msg, chat_type): return
        if not check_cooldown(user_info["id"], is_group): return

        #... resto do processamento igual ao seu...
        # só troca a chamada de call_openrouter

    except Exception as e:
        logging.exception(f"[PROCESS ERROR] {e}")

# ========================================
# WEBHOOK
# ========================================
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data: return "ok"
    update_id = data.get("update_id")
    if is_update_processado(update_id): return "ok" # CORREÇÃO 4
    if msg := data.get("message"):
        REQUEST_QUEUE.put((processar_mensagem, (msg,))) # JOGA NA FILA
    return "ok"

@app.route('/')
def index():
    tamanho_fila = REQUEST_QUEUE.qsize()
    return f"{BOT_NAME} online ✅ | Fila: {tamanho_fila}", 200

@app.route('/health')
def health():
    return "ok", 200

init_bot_info()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
