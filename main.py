import os, requests, threading, time, logging, re, json
from collections import defaultdict, deque
from datetime import datetime, timedelta
from flask import Flask, request
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

# ========================================
# === CONFIG V1.1 CENTRALIZADA ===========
# ========================================
BOT_NAME = "SuperBot"
CREATOR = "Kleber"
CREATOR_ID = "8398287578" # TROCA PELO TEU ID
ADMINS = ["8398287578"]

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

BOT_ID = None
BOT_USERNAME = None

# MODELOS OPENROUTER
MODELOS = {
    "principal": "deepseek/deepseek-chat-v3.1", # Raciocínio + Geral
    "codigo": "qwen/qwen-2.5-coder-32b-instruct", # Programação
    "criativo": "google/gemini-2.0-flash-exp", # Criatividade + Rápido
    "resumo": "meta-llama/llama-3.1-8b-instruct", # Barato pra resumo/tradução
}
FALLBACK_MODELOS = [
    "deepseek/deepseek-chat-v3.1",
    "google/gemini-2.0-flash-exp",
    "meta-llama/llama-3.1-8b-instruct"
]

# LIMITES E PROTEÇÃO
MAX_TOKENS_RESPOSTA = 600
HISTORICO_LIMITE_USER = 12
HISTORICO_LIMITE_GRUPO = 8
MAX_MSG_LENGTH = 4000
TIMEOUT_API = 30
COOLDOWN_SEGUNDOS = 3 # Anti-spam por usuário

if not TELEGRAM_TOKEN: raise RuntimeError("TELEGRAM_TOKEN não configurado")
if not OPENROUTER_API_KEY: raise RuntimeError("OPENROUTER_API_KEY não configurado")

# ========================================
# === MEMÓRIA TEMPORÁRIA EM RAM ==========
# ========================================
HISTORICO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_USER))
HISTORICO_GRUPO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_GRUPO))
USER_COOLDOWN = {} # {user_id: timestamp}
LOCK = threading.Lock()
PROCESSED_UPDATES = set()

# THREAD POOL
executor = ThreadPoolExecutor(max_workers=10)

# ========================================
# === FUNÇÕES TELEGRAM ===================
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
    # Tenta com Markdown, se falhar manda texto simples
    for parse_mode in ["Markdown", None]:
        try:
            payload = {"chat_id": chat_id, "text": text[:4096]}
            if parse_mode: payload["parse_mode"] = parse_mode
            if reply_to: payload["reply_to_message_id"] = reply_to
            r = requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=TIMEOUT_API)
            if r.status_code == 200: return True
            if r.status_code == 400 and parse_mode: continue # Erro de markdown, tenta sem
        except Exception as e:
            logging.exception(f"[TELEGRAM ERROR] {e}")
            time.sleep(1)
    return False

def get_user_info(user):
    user_id = str(user["id"])
    nome = user.get("first_name", "usuário")
    username = user.get("username", "")

    if user_id == CREATOR_ID: tipo = "criador"
    elif user_id in ADMINS: tipo = "admin"
    else: tipo = "usuario"

    return {"id": user_id, "nome": nome, "username": username, "tipo": tipo}

def check_cooldown(user_id):
    agora = time.time()
    with LOCK:
        ultimo = USER_COOLDOWN.get(user_id, 0)
        if agora - ultimo < COOLDOWN_SEGUNDOS:
            return False
        USER_COOLDOWN[user_id] = agora
    return True

# ========================================
# === IA + ROTEADOR + FALLBACK ===========
# ========================================
def selecionar_modelo(intencao):
    mapa = {
        "PROGRAMACAO": "codigo",
        "CRIATIVIDADE": "criativo",
        "RESUMO": "resumo",
        "TRADUCAO": "resumo",
        "RACIOCINIO": "principal",
        "ESTUDO": "principal",
        "CONVERSA": "criativo"
    }
    return MODELOS.get(mapa.get(intencao, "principal"))

def call_openrouter(messages, modelo_primario, max_tokens=MAX_TOKENS_RESPOSTA, temperatura=0.7):
    modelos_tentar = [modelo_primario] + [m for m in FALLBACK_MODELOS if m!= modelo_primario]
    ultimo_erro = None

    for i, modelo_atual in enumerate(modelos_tentar):
        try:
            inicio = time.time()
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://superbot.telegram",
                "X-Title": BOT_NAME
            }
            payload = {
                "model": modelo_atual,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperatura,
            }
            r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                              headers=headers, json=payload, timeout=TIMEOUT_API)
            tempo = round(time.time() - inicio, 2)

            if r.status_code == 200:
                if i > 0: logging.info(f"[FALLBACK] Usado {modelo_atual} após falha. Tempo: {tempo}s")
                return r.json()["choices"][0]["message"]["content"], modelo_atual, tempo

            if r.status_code in [429, 500, 502, 503, 504, 408]:
                ultimo_erro = f"{r.status_code}"
                logging.warning(f"[OPENROUTER] {modelo_atual} falhou {r.status_code}. Tentando próximo...")
                continue

        except requests.Timeout:
            ultimo_erro = "timeout"
            logging.warning(f"[OPENROUTER] Timeout {modelo_atual}")
        except Exception as e:
            ultimo_erro = str(e)
            logging.exception(f"[OPENROUTER ERROR] {modelo_atual}: {e}")

    return f"Deu ruim em todos os modelos aqui 😅 Erro: {ultimo_erro}. Tenta de novo em 10s?", None, 0

def adicionar_historico(chat_id, user_id, role, content, is_group=False):
    content = content[:MAX_MSG_LENGTH]
    with LOCK:
        msg = {"role": role, "content": content}
        if is_group:
            HISTORICO_GRUPO[str(chat_id)].append(msg)
        else:
            HISTORICO[str(user_id)].append(msg)

def get_historico(chat_id, user_id, is_group):
    with LOCK:
        if is_group:
            return list(HISTORICO_GRUPO[str(chat_id)])
        else:
            return list(HISTORICO[str(user_id)])

def montar_system_prompt(user_info, intencao):
    if user_info["tipo"] == "criador":
        identidade = f"Você está falando com KLEBER, o CRIADOR do bot. Seja familiar, zoeiro, pode chamar ele de Kleber."
    elif user_info["tipo"] == "admin":
        identidade = f"Usuário: {user_info['nome']} | Tipo: Administrador"
    else:
        identidade = f"Usuário: {user_info['nome']} | Tipo: Usuário comum"

    prompt = f"""Você é {BOT_NAME}, assistente inteligente para Telegram.
{identidade}
Intenção detectada: {intencao}

REGRAS CRÍTICAS:
1. Detecte o idioma da última mensagem do usuário e RESPONDA SEMPRE no mesmo idioma. Se o usuário pedir "fale em inglês" ou "responda em espanhol", priorize.
2. Entenda mensagens misturando idiomas.
3. Seja direto, max 4 linhas.
4. Se for código, use ```linguagem```. Se for lista, use - item.
5. Mantenha personalidade consistente em qualquer idioma.
6. Não invente informações."""
    return prompt

# ========================================
# === PROCESSAMENTO PRINCIPAL ============
# ========================================
def deve_responder(msg, chat_type):
    if chat_type == "private": return True

    texto = msg.get("text", "").lower()

    # 1. Verifica entities do Telegram
    for entity in msg.get("entities", []):
        if entity["type"] == "mention":
            mention = texto[entity["offset"]:entity["offset"]+entity["length"]]
            if mention == f"@{BOT_USERNAME}": return True

    # 2. Verifica nome do bot no texto
    if BOT_NAME.lower() in texto: return True

    # 3. Verifica reply usando BOT_ID REAL
    if "reply_to_message" in msg:
        replied = msg["reply_to_message"].get("from", {})
        if replied.get("id") == BOT_ID: return True

    return False

def processar_mensagem(msg):
    inicio_total = time.time()
    try:
        chat = msg["chat"]
        chat_id = chat["id"]
        chat_type = chat["type"]
        user = msg["from"]
        message_id = msg["message_id"]
        texto = msg.get("text", "").strip()

        if not texto or len(texto) > MAX_MSG_LENGTH: return

        user_info = get_user_info(user)
        is_group = chat_type in ["group", "supergroup"]

        # VERIFICAR SE DEVE RESPONDER
        if is_group and not deve_responder(msg, chat_type):
            return

        # ANTI-SPAM
        if not check_cooldown(user_info["id"]):
            return

        # HEURÍSTICA RÁPIDA PRA SELECIONAR MODELO SEM GASTAR TOKEN
        texto_lower = texto.lower()
        intencao = "CONVERSA"
        if "```" in texto or "def " in texto or "function" in texto or "error" in texto_lower:
            intencao = "PROGRAMACAO"
        elif "resuma" in texto_lower or "summary" in texto_lower or "resumo" in texto_lower:
            intencao = "RESUMO"
        elif "traduza" in texto_lower or "translate" in texto_lower:
            intencao = "TRADUCAO"
        elif "?" in texto and len(texto) > 100:
            intencao = "RACIOCINIO"
        elif "crie" in texto_lower or "história" in texto_lower or "ideia" in texto_lower:
            intencao = "CRIATIVIDADE"
        elif "explique" in texto_lower or "como funciona" in texto_lower:
            intencao = "ESTUDO"

        modelo = selecionar_modelo(intencao)

        # MONTAR CONTEXTO + CHAMAR IA
        historico = get_historico(chat_id, user_info["id"], is_group)
        system = montar_system_prompt(user_info, intencao)
        messages = [{"role": "system", "content": system}]
        messages.extend(historico)
        messages.append({"role": "user", "content": texto})

        # CHAMAR OPENROUTER COM FALLBACK
        adicionar_historico(chat_id, user_info["id"], "user", texto, is_group)
        resposta, modelo_usado, tempo_ia = call_openrouter(messages, modelo)
        adicionar_historico(chat_id, user_info["id"], "assistant", resposta, is_group)

        # LOG
        logging.info(f"[REQ] {user_info['nome']}({user_info['tipo']}) | {intencao} | Modelo: {modelo_usado} | {tempo_ia}s | Total: {round(time.time()-inicio_total,2)}s")

        # ENVIAR RESPOSTA
        send_message(chat_id, resposta, reply_to=message_id)

    except Exception as e:
        logging.exception(f"[PROCESS ERROR] {e}")

# ========================================
# === WEBHOOK FLASK ======================
# ========================================
@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data: return "ok"

    update_id = data.get("update_id")
    if update_id in PROCESSED_UPDATES: return "ok"
    PROCESSED_UPDATES.add(update_id)
    if len(PROCESSED_UPDATES) > 1000: PROCESSED_UPDATES.clear()

    msg = data.get("message")
    if not msg: return "ok"

    # Processa em thread pra webhook não travar
    executor.submit(processar_mensagem, msg)
    return "ok"

@app.route('/health')
def health(): return "ok", 200

if __name__ == '__main__':
    init_bot_info()
    app.run(host='0.0.0.0', port=8080)
