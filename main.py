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

# SÓ 1 MODELO. O openrouter/free já faz roteamento interno
MODELO = "openrouter/free"

# ========================================
# LIMITES E PROTEÇÃO - AGORA CONSERVADOR
# ========================================
MAX_TOKENS_RESPOSTA = 300 # Reduzi pra gastar menos token
HISTORICO_LIMITE_USER = 6 # Menos histórico = menos token
HISTORICO_LIMITE_GRUPO = 4
MAX_MSG_LENGTH = 2000
TIMEOUT_API = 45
COOLDOWN_SEGUNDOS_PV = 3
COOLDOWN_SEGUNDOS_GRUPO = 10 # 10s em grupo pra durar o dia

MAX_REQUISICOES_POR_MINUTO = 5 # CORREÇÃO 1: 5/min = 7200/dia. Ainda estoura, mas demora mais
JANELA_TEMPO = 60
MAX_REQUISICOES_POR_USER_HORA = 10 # CORREÇÃO 1.5: Anti 1 spammer

# ========================================
# MEMÓRIA TEMPORÁRIA
# ========================================
HISTORICO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_USER))
HISTORICO_GRUPO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_GRUPO))
USER_COOLDOWN = {}
USER_REQUEST_COUNT = defaultdict(lambda: deque()) # Conta reqs por user na última hora
LOCK = threading.Lock()
PROCESSED_UPDATES = {}
UPDATE_EXPIRACAO = 3600

executor = ThreadPoolExecutor(max_workers=3) # CORREÇÃO 3: 3 workers só. Menos 429
REQUISICOES_TIMES = deque()

# ========================================
# FUNÇÕES AUXILIARES
# ========================================
def check_user_rate_limit(user_id):
    agora = time.time()
    with LOCK:
        fila = USER_REQUEST_COUNT[user_id]
        while fila and fila[0] < agora - 3600:
            fila.popleft()
        if len(fila) >= MAX_REQUISICOES_POR_USER_HORA:
            return False
        fila.append(agora)
    return True

def check_global_rate_limit():
    agora = time.time()
    with LOCK:
        while REQUISICOES_TIMES and REQUISICOES_TIMES[0] < agora - JANELA_TEMPO:
            REQUISICOES_TIMES.popleft()
        if len(REQUISICOES_TIMES) >= MAX_REQUISICOES_POR_MINUTO:
            return False
        REQUISICOES_TIMES.append(agora)
    return True

#... resto das funções init_bot_info, send_message, get_file, get_user_info, is_update_processado, get_datetime_info, historico iguais...

def check_cooldown(user_id, is_group):
    cooldown = COOLDOWN_SEGUNDOS_GRUPO if is_group else COOLDOWN_SEGUNDOS_PV
    agora = time.time()
    with LOCK:
        if agora - USER_COOLDOWN.get(user_id, 0) < cooldown: return False
        USER_COOLDOWN[user_id] = agora
    return True

def montar_system_prompt(user_info):
    dt = get_datetime_info()
    identidade = f"Você está falando com {CREATOR}, o CRIADOR do bot. Seja familiar e zoeiro." if user_info["tipo"] == "criador" else f"Usuário: {user_info['nome']}"
    return f"""Você é {BOT_NAME}. {identidade}
DATA: {dt['dia_semana']}, {dt['data']} {dt['hora']} | Sobral-CE
REGRAS: 1.Responda no idioma do usuário. 2.Max 3 linhas. 3.Sejá direto."""

# ========================================
# COMANDOS - CORREÇÃO 2: ANTES DO COOLDOWN
# ========================================
def processar_comando(texto, chat_id, user_info, is_group):
    texto = texto.lower()
    if texto == "/start":
        return f"👋 Opa {user_info['nome']}! Eu sou o *{BOT_NAME}*\nUse `/ajuda`"
    if texto == "/ajuda":
        return "*COMANDOS:* `/start` `/ajuda` `/limpar` `/status` `/hora`"
    if texto == "/limpar":
        limpar_historico(chat_id, user_info["id"], is_group)
        return "🧹 Histórico limpo!"
    if texto == "/status":
        return f"✅ *{BOT_NAME} Online*\n👤 Users: {len(HISTORICO)}\n👥 Grupos: {len(HISTORICO_GRUPO)}"
    if texto == "/hora":
        dt = get_datetime_info()
        return f"📅 {dt['dia_semana']}, {dt['data']}\n🕐 {dt['hora']} Sobral/CE"
    if texto == "/admin" and user_info["tipo"] == "criador":
        return f"*PAINEL*\nUsers: {len(HISTORICO)}\nGrupos: {len(HISTORICO_GRUPO)}"
    return None

# ========================================
# OPENROUTER
# ========================================
def call_openrouter(messages):
    if not check_global_rate_limit():
        return "⏳ Limite global atingido. Espera 1 min.", 0, "rate_limit"

    try:
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "HTTP-Referer": RENDER_URL, "X-Title": BOT_NAME}
        payload = {"model": MODELO, "messages": messages, "max_tokens": MAX_TOKENS_RESPOSTA}
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT_API)
        tempo = round(r.elapsed.total_seconds(), 2)

        if r.status_code == 200:
            resposta = r.json().get("choices", [{}])[0].get("message", {}).get("content")
            return resposta, tempo, MODELO

        if r.status_code == 429:
            return "⚠️ Cota da IA acabou por hoje. Volta amanhã.", 0, "quota"

        logging.error(f"[OPENROUTER] {r.status_code}: {r.text}")
    except Exception as e:
        logging.exception(f"[OPENROUTER ERROR]: {e}")

    return "⚠️ IA offline agora. Tenta em 1 min.", 0, "error"

# ========================================
# PROCESSAMENTO - ORDEM CORRIGIDA
# ========================================
def processar_mensagem(msg):
    try:
        chat = msg["chat"]; chat_id = chat["id"]; chat_type = chat["type"]
        user = msg["from"]; message_id = msg["message_id"]
        user_info = get_user_info(user)
        is_group = chat_type in ["group", "supergroup"]
        if is_group and not deve_responder(msg, chat_type): return

        texto = msg.get("text", "").strip()
        has_media = "photo" in msg

        # CORREÇÃO 2: COMANDO PRIMEIRO, SEMPRE
        if texto and texto.startswith("/"):
            resposta = processar_comando(texto, chat_id, user_info, is_group)
            if resposta:
                send_message(chat_id, resposta, reply_to=message_id)
            return

        # DEPOIS COOLDOWN E RATE LIMIT POR USER
        if not check_cooldown(user_info["id"], is_group): return
        if not check_user_rate_limit(user_info["id"]):
            send_message(chat_id, "⏳ Você atingiu o limite de 10 msgs/hora. Espera um pouco.", reply_to=message_id)
            return

        # 2. MÍDIA
        if has_media:
            file_id = msg["photo"][-1]["file_id"]
            image_base64 = get_file_from_telegram(file_id)
            texto = msg.get("caption", "Descreva esta imagem em português, direto")
            historico = get_historico(chat_id, user_info["id"], is_group)
            system = montar_system_prompt(user_info)
            messages = [{"role": "system", "content": system}] + historico
            messages.append({"role": "user", "content": [{"type": "text", "text": texto}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}]})
            adicionar_historico(chat_id, user_info["id"], "user", f"[IMAGEM] {texto}", is_group)
            resposta, tempo_ia, _ = call_openrouter(messages)
            adicionar_historico(chat_id, user_info["id"], "assistant", resposta, is_group)
            send_message(chat_id, resposta, reply_to=message_id)
            return

        # 3. TEXTO
        if not texto: return
        historico = get_historico(chat_id, user_info["id"], is_group)
        system = montar_system_prompt(user_info)
        messages = [{"role": "system", "content": system}] + historico + [{"role": "user", "content": texto}]
        adicionar_historico(chat_id, user_info["id"], "user", texto, is_group)
        resposta, tempo_ia, _ = call_openrouter(messages)
        adicionar_historico(chat_id, user_info["id"], "assistant", resposta, is_group)
        send_message(chat_id, resposta, reply_to=message_id)

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
    if is_update_processado(update_id): return "ok"
    if msg := data.get("message"):
        executor.submit(processar_mensagem, msg)
    return "ok"

@app.route('/')
def index(): return f"{BOT_NAME} online ✅", 200
@app.route('/health')
def health(): return "ok", 200

init_bot_info()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
