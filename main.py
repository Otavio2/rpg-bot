import os
import requests
import threading
import time
import logging
from collections import defaultdict, deque
from flask import Flask, request
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)

# ========================================
# CONFIGURAÇÃO
# ========================================

BOT_NAME = "NIOBIOchat_BOT"
CREATOR = "Kleber"
CREATOR_ID = "8398287578"
ADMINS = ["8398287578"]

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
RENDER_URL = "https://edu-bot-6yfa.onrender.com" # ATUALIZA COM TUA URL

if not TELEGRAM_TOKEN:
    raise RuntimeError("TELEGRAM_TOKEN não configurado")
if not OPENROUTER_API_KEY:
    raise RuntimeError("OPENROUTER_API_KEY não configurada")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

BOT_ID = None
BOT_USERNAME = None

# ========================================
# MODELO GRATUITO
# ========================================
# openrouter/free = modelo rotativo gratuito. Troca sozinho quando bate limite
MODELO_UNICO = "openrouter/free"

# ========================================
# LIMITES
# ========================================
MAX_TOKENS_RESPOSTA = 500 # Diminui pra gastar menos e durar mais
HISTORICO_LIMITE_USER = 10
HISTORICO_LIMITE_GRUPO = 6
MAX_MSG_LENGTH = 4000
TIMEOUT_API = 45 # Aumenta pq free é mais lento
COOLDOWN_SEGUNDOS = 3

# ========================================
# MEMÓRIA TEMPORÁRIA
# ========================================
HISTORICO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_USER))
HISTORICO_GRUPO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_GRUPO))
USER_COOLDOWN = {}
LOCK = threading.Lock()
PROCESSED_UPDATES = set()
executor = ThreadPoolExecutor(max_workers=5) # Diminui pra não estourar rate

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
            logging.error(f"[TELEGRAM] Erro {r.status_code}: {r.text}")
        except Exception as e:
            logging.exception(f"[TELEGRAM ERROR] {e}")
            time.sleep(1)
    return False

def get_user_info(user):
    user_id = str(user["id"])
    nome = user.get("first_name", "usuário")
    if user_id == CREATOR_ID: tipo = "criador"
    elif user_id in ADMINS: tipo = "admin"
    else: tipo = "usuario"
    return {"id": user_id, "nome": nome, "tipo": tipo}

def check_cooldown(user_id):
    agora = time.time()
    with LOCK:
        if agora - USER_COOLDOWN.get(user_id, 0) < COOLDOWN_SEGUNDOS: return False
        USER_COOLDOWN[user_id] = agora
    return True

# ========================================
# ROTEADOR
# ========================================
def detectar_intencao(texto):
    texto_lower = texto.lower()
    if any(x in texto_lower for x in ["```", "def ", "function", "python", "erro", "bug"]): return "PROGRAMACAO"
    if any(x in texto_lower for x in ["resuma", "resumo", "summary"]): return "RESUMO"
    if any(x in texto_lower for x in ["traduza", "translate"]): return "TRADUCAO"
    if any(x in texto_lower for x in ["crie", "historia", "ideia", "escreva"]): return "CRIATIVIDADE"
    if any(x in texto_lower for x in ["explique", "como funciona", "o que é"]): return "ESTUDO"
    if len(texto) > 100 and "?" in texto: return "RACIOCINIO"
    return "CONVERSA"

# ========================================
# OPENROUTER FREE
# ========================================
def call_openrouter(messages):
    ultimo_erro = "Desconhecido"
    try:
        inicio = time.time()
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": RENDER_URL,
            "X-Title": BOT_NAME
        }
        payload = {
            "model": MODELO_UNICO,
            "messages": messages,
            "max_tokens": MAX_TOKENS_RESPOSTA,
            "temperature": 0.7,
        }
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT_API)
        tempo = round(time.time() - inicio, 2)

        if r.status_code == 200:
            resposta = r.json().get("choices", [{}])[0].get("message", {}).get("content")
            if resposta: return resposta, MODELO_UNICO, tempo
            ultimo_erro = "Resposta vazia da API"

        erro_body = r.text
        ultimo_erro = f"{r.status_code}: {erro_body[:200]}"
        logging.error(f"[OPENROUTER] {MODELO_UNICO} falhou {r.status_code}. Body: {erro_body}")

        if r.status_code == 402:
            return "⚠️ Limite gratuito da OpenRouter atingido. Volta em algumas horas ou cria outra API Key.", None, tempo
        if r.status_code == 401:
            return "❌ API Key da OpenRouter inválida.", None, tempo
        if r.status_code == 429:
            return "⚠️ Muitas requisições. Espera 10s e tenta de novo.", None, tempo

    except requests.Timeout:
        ultimo_erro = "timeout"
        logging.warning(f"[OPENROUTER] Timeout")
    except Exception as e:
        ultimo_erro = str(e)
        logging.exception(f"[OPENROUTER ERROR]: {e}")

    return f"⚠️ Não consegui resposta da IA agora. Erro: {ultimo_erro}", None, 0

# ========================================
# HISTÓRICO
# ========================================
def adicionar_historico(chat_id, user_id, role, content, is_group=False):
    content = content[:MAX_MSG_LENGTH]
    with LOCK:
        msg = {"role": role, "content": content}
        if is_group: HISTORICO_GRUPO[str(chat_id)].append(msg)
        else: HISTORICO[str(user_id)].append(msg)

def get_historico(chat_id, user_id, is_group):
    with LOCK:
        return list(HISTORICO_GRUPO[str(chat_id)]) if is_group else list(HISTORICO[str(user_id)])

# ========================================
# PERSONALIDADE
# ========================================
def montar_system_prompt(user_info):
    if user_info["tipo"] == "criador":
        identidade = f"Você está falando com {CREATOR}, o CRIADOR do bot. Seja familiar e zoeiro."
    else:
        identidade = f"Usuário: {user_info['nome']}"
    return f"""Você é {BOT_NAME}, assistente para Telegram. {identidade}
REGRAS: 1.Responda no idioma do usuário. 2.Seja direto, max 4 linhas. 3.Use ``` para código."""

# ========================================
# VERIFICAR SE DEVE RESPONDER
# ========================================
def deve_responder(msg, chat_type):
    if chat_type == "private": return True
    texto = msg.get("text", "").lower()
    if BOT_USERNAME and f"@{BOT_USERNAME}" in texto: return True
    if BOT_NAME.lower() in texto: return True
    if "reply_to_message" in msg and msg["reply_to_message"].get("from", {}).get("id") == BOT_ID: return True
    return False

# ========================================
# PROCESSAMENTO
# ========================================
def processar_mensagem(msg):
    inicio_total = time.time()
    try:
        chat = msg["chat"]; chat_id = chat["id"]; chat_type = chat["type"]
        user = msg["from"]; message_id = msg["message_id"]
        texto = msg.get("text", "").strip()
        if not texto or len(texto) > MAX_MSG_LENGTH: return

        user_info = get_user_info(user)
        is_group = chat_type in ["group", "supergroup"]
        if is_group and not deve_responder(msg, chat_type): return
        if not check_cooldown(user_info["id"]): return

        intencao = detectar_intencao(texto)
        historico = get_historico(chat_id, user_info["id"], is_group)
        system = montar_system_prompt(user_info)
        messages = [{"role": "system", "content": system}] + historico + [{"role": "user", "content": texto}]

        adicionar_historico(chat_id, user_info["id"], "user", texto, is_group)
        resposta, modelo_usado, tempo_ia = call_openrouter(messages)
        adicionar_historico(chat_id, user_info["id"], "assistant", resposta, is_group)

        logging.info(f"[REQ] {user_info['nome']}({user_info['tipo']}) | {intencao} | {tempo_ia}s | Total: {round(time.time()-inicio_total,2)}s")
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
    with LOCK:
        if update_id in PROCESSED_UPDATES: return "ok"
        PROCESSED_UPDATES.add(update_id)
        if len(PROCESSED_UPDATES) > 1000: PROCESSED_UPDATES.clear()
    if msg := data.get("message"): executor.submit(processar_mensagem, msg)
    return "ok"

@app.route('/')
def index(): return f"{BOT_NAME} online ✅", 200
@app.route('/health')
def health(): return "ok", 200

# INICIALIZAÇÃO PRA GUNICORN
init_bot_info()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
