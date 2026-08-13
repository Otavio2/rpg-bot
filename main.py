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
from concurrent.futures import ThreadPoolExecutor # VOLTOU A SER USADO

app = Flask(__name__) # CORRIGIDO: era app = Flask(name)
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

# FALLBACK INTELIGENTE: 1 ROTEADOR + 1 MODELO FIXO
MODELOS = [
    "openrouter/free", # Tenta o roteador primeiro
    "google/gemini-2.0-flash-exp:free" # Se cair, usa 1 fixo só
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
COOLDOWN_SEGUNDOS_GRUPO = 5

MAX_REQUISICOES_POR_MINUTO = 30
JANELA_TEMPO = 60

# ========================================
# MEMÓRIA TEMPORÁRIA
# ========================================
HISTORICO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_USER))
HISTORICO_GRUPO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_GRUPO))
USER_COOLDOWN = {}
LOCK = threading.Lock()
PROCESSED_UPDATES = {}
UPDATE_EXPIRACAO = 3600

executor = ThreadPoolExecutor(max_workers=10) # CORRIGIDO: AGORA USA DE VERDADE
REQUISICOES_TIMES = deque()

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
    agora = time.time()
    with LOCK:
        for uid in list(PROCESSED_UPDATES.keys()):
            if agora - PROCESSED_UPDATES[uid] > UPDATE_EXPIRACAO:
                del PROCESSED_UPDATES[uid]
        if update_id in PROCESSED_UPDATES: return True
        PROCESSED_UPDATES[update_id] = agora
    return False

def get_datetime_info():
    tz = pytz.timezone(TIMEZONE)
    agora = datetime.now(tz)
    dias_semana = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    dia_semana = dias_semana[agora.weekday()]
    return {"dia_semana": dia_semana, "data": agora.strftime("%d/%m/%Y"), "hora": agora.strftime("%H:%M")}

def adicionar_historico(chat_id, user_id, role, content, is_group=False):
    with LOCK:
        msg = {"role": role, "content": content[:MAX_MSG_LENGTH]}
        if is_group: HISTORICO_GRUPO[str(chat_id)].append(msg)
        else: HISTORICO[str(user_id)].append(msg)

def get_historico(chat_id, user_id, is_group):
    with LOCK:
        return list(HISTORICO_GRUPO[str(chat_id)]) if is_group else list(HISTORICO[str(user_id)])

def limpar_historico(chat_id, user_id, is_group):
    with LOCK:
        if is_group: HISTORICO_GRUPO[str(chat_id)].clear()
        else: HISTORICO[str(user_id)].clear()

def montar_system_prompt(user_info):
    dt = get_datetime_info()
    identidade = f"Você está falando com {CREATOR}, o CRIADOR do bot. Seja familiar e zoeiro." if user_info["tipo"] == "criador" else f"Usuário: {user_info['nome']}"
    return f"""Você é {BOT_NAME}, assistente para Telegram. {identidade}
DATA ATUAL: {dt['dia_semana']}, {dt['data']} | HORA: {dt['hora']} | LOCAL: Sobral, Ceará
REGRAS: 1.Responda no idioma do usuário. 2.Seja direto, max 4 linhas. 3.Se perguntarem data/hora/dia, use a DATA ATUAL acima."""

def deve_responder(msg, chat_type):
    if chat_type == "private": return True
    texto = msg.get("text", "").lower() if msg.get("text") else ""
    if BOT_USERNAME and f"@{BOT_USERNAME}" in texto: return True
    if BOT_NAME.lower() in texto: return True
    if "reply_to_message" in msg and msg["reply_to_message"].get("from", {}).get("id") == BOT_ID: return True
    if any(k in msg for k in ["photo"]): return True
    return False

# ========================================
# COMANDOS - NÃO CONSOMEM RATE LIMIT
# ========================================
def processar_comando(texto, chat_id, user_info, is_group):
    texto = texto.lower()
    if texto == "/start":
        return f"👋 Opa {user_info['nome']}! Eu sou o *{BOT_NAME}*\nVamos conversar?. Use `/ajuda`"
    if texto == "/ajuda":
        return f"""*COMANDOS DO {BOT_NAME}*
`/start` - Boas vindas
`/ajuda` - Lista de comandos
`/limpar` - Limpa histórico
`/status` - Status do bot"""
    if texto == "/limpar":
        limpar_historico(chat_id, user_info["id"], is_group)
        return "🧹 Histórico limpo!"
    if texto == "/status":
        return f"""✅ *{BOT_NAME} Online*
👤 Usuários: {len(HISTORICO)}
👥 Grupos: {len(HISTORICO_GRUPO)}
🤖 Modelo: {MODELOS[0]}
🧠 Memória: Temporária
🔗 API: {'✅ OK' if OPENROUTER_API_KEY else '❌ FALTA'}"""
    if texto == "/hora":
        dt = get_datetime_info()
        return f"📅 Hoje é *{dt['dia_semana']}*, {dt['data']}\n🕐 Agora são *{dt['hora']}* em Sobral/CE"
    if texto == "/admin":
        if user_info["tipo"]!= "criador": return "❌ Você não tem permissão."
        return f"""*PAINEL ADMIN - {CREATOR}*
Users ativos: {len(HISTORICO)}
Grupos ativos: {len(HISTORICO_GRUPO)}"""
    return None

# ========================================
# OPENROUTER COM FALLBACK INTELIGENTE
# ========================================
def call_openrouter(messages):
    if not check_global_rate_limit(): # RATE LIMIT SÓ AQUI
        return "⏳ Tô recebendo muita mensagem agora. Tenta de novo em 30s.", 0, "rate_limit"

    for i, modelo in enumerate(MODELOS):
        try:
            headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "HTTP-Referer": RENDER_URL, "X-Title": BOT_NAME}
            payload = {"model": modelo, "messages": messages, "max_tokens": MAX_TOKENS_RESPOSTA}
            r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT_API)
            tempo = round(r.elapsed.total_seconds(), 2)

            if r.status_code == 200:
                resposta = r.json().get("choices", [{}])[0].get("message", {}).get("content")
                if i > 0: resposta = f"⚡ Usei modelo reserva.\n\n{resposta}"
                return resposta, tempo, modelo

            if r.status_code in [429, 500, 503]: # Só retry se for erro de servidor
                time.sleep(1)
                continue
            break # Se for 400/401 para
        except Exception as e:
            logging.exception(f"[OPENROUTER ERROR {modelo}]: {e}")
            time.sleep(1)
    return "⚠️ Todos os modelos estão offline agora. Tenta em 1 min.", 0, "nenhum"

# ========================================
# PROCESSAMENTO
# ========================================
def processar_mensagem(msg):
    try:
        chat = msg["chat"]; chat_id = chat["id"]; chat_type = chat["type"]
        user = msg["from"]; message_id = msg["message_id"]
        user_info = get_user_info(user)
        is_group = chat_type in ["group", "supergroup"]
        if is_group and not deve_responder(msg, chat_type): return
        if not check_cooldown(user_info["id"], is_group): return

        texto = msg.get("text", "").strip()
        has_media = "photo" in msg

        # 1. COMANDO - SAI ANTES DO RATE LIMIT
        if texto and texto.startswith("/"):
            resposta = processar_comando(texto, chat_id, user_info, is_group)
            if resposta:
                send_message(chat_id, resposta, reply_to=message_id)
                return

        # 2. MÍDIA
        if has_media:
            file_id = msg["photo"][-1]["file_id"]
            image_base64 = get_file_from_telegram(file_id)
            texto = msg.get("caption", "Descreva esta imagem em português e seja direto")
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
        executor.submit(processar_mensagem, msg) # CORRIGIDO: USA O THREADPOOL
    return "ok"

@app.route('/')
def index():
    return f"{BOT_NAME} online ✅", 200

@app.route('/health')
def health():
    return "ok", 200

init_bot_info()

if __name__ == '__main__': # CORRIGIDO: era if name == 'main'
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
