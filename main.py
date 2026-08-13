import os
import requests
import threading
import time
import logging
import base64
from collections import defaultdict, deque
from flask import Flask, request
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

BOT_NAME = "Matheus"
CREATOR = "Kleber"
CREATOR_ID = "8398287578"
ADMINS = ["8398287578"]

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
RENDER_URL = "https://edu-bot-6yfa.onrender.com"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

BOT_ID = None
BOT_USERNAME = None
MODELO_VISION = "google/gemini-2.0-flash-exp:free" # Tem vision e é free

MAX_TOKENS_RESPOSTA = 500
HISTORICO_LIMITE_USER = 10
HISTORICO_LIMITE_GRUPO = 6
MAX_MSG_LENGTH = 4000
TIMEOUT_API = 60
COOLDOWN_SEGUNDOS = 2 # Diminui pra ficar mais solto

HISTORICO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_USER))
HISTORICO_GRUPO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_GRUPO))
USER_COOLDOWN = {}
LOCK = threading.Lock()
PROCESSED_UPDATES = set()
executor = ThreadPoolExecutor(max_workers=5)

def init_bot_info():
    global BOT_ID, BOT_USERNAME
    r = requests.get(f"{TELEGRAM_API_URL}/getMe", timeout=TIMEOUT_API)
    data = r.json()["result"]
    BOT_ID = data["id"]
    BOT_USERNAME = data["username"].lower()
    logging.info(f"[BOT] @{BOT_USERNAME} online | ID: {BOT_ID}")

def send_message(chat_id, text, reply_to=None):
    if not text: text = "Deu ruim aqui, tenta de novo."
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
    file_path = r.json()["result"]["file_path"]
    img = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}")
    return base64.b64encode(img.content).decode("utf-8")

def get_user_info(user):
    user_id = str(user["id"])
    nome = user.get("first_name", "mano")
    tipo = "criador" if user_id == CREATOR_ID else "admin" if user_id in ADMINS else "usuario"
    return {"id": user_id, "nome": nome, "tipo": tipo}

def check_cooldown(user_id):
    agora = time.time()
    with LOCK:
        if agora - USER_COOLDOWN.get(user_id, 0) < COOLDOWN_SEGUNDOS: return False
        USER_COOLDOWN[user_id] = agora
    return True

def call_openrouter(messages):
    try:
        inicio = time.time()
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json", "HTTP-Referer": RENDER_URL, "X-Title": BOT_NAME}
        payload = {"model": MODELO_VISION, "messages": messages, "max_tokens": MAX_TOKENS_RESPOSTA, "temperature": 0.8}
        r = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=TIMEOUT_API)
        tempo = round(time.time() - inicio, 2)
        if r.status_code == 200:
            resposta = r.json().get("choices", [{}])[0].get("message", {}).get("content")
            return resposta, tempo
        if r.status_code == 402: return "Esgotou as requisições free de hoje. Volta amanhã.", tempo
        return f"Erro {r.status_code} na API", tempo
    except Exception as e:
        logging.exception(f"[OPENROUTER ERROR]: {e}")
        return "Bugou aqui. Tenta mandar de novo.", 0

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
    if user_info["tipo"] == "criador":
        personalidade = f"Você é {BOT_NAME}. Está falando com {CREATOR}, seu criador. Seja natural, direto, zoeiro e inteligente. Pode usar gírias."
    else:
        personalidade = f"Você é {BOT_NAME}, assistente no Telegram. Fale de forma natural, direta e humana. Como um amigo. Nome do usuário: {user_info['nome']}"
    return personalidade + "\nRegras: Responda no idioma da pessoa. Seja breve. Se for imagem, descreva com humor."

def deve_responder(msg, chat_type):
    if chat_type == "private": return True
    texto = msg.get("text", "").lower() if msg.get("text") else ""
    if BOT_USERNAME and f"@{BOT_USERNAME}" in texto: return True
    if BOT_NAME.lower() in texto: return True
    if "reply_to_message" in msg and msg["reply_to_message"].get("from", {}).get("id") == BOT_ID: return True
    return False

def processar_comando(texto, chat_id, user_info, is_group):
    texto = texto.lower()
    if texto == "/start":
        if user_info["tipo"] == "criador":
            return f"Eae chefe 👑\nManda o que quiser."
        else:
            return f"Eae {user_info['nome']}"

    if texto == "/ajuda":
        return f"Comandos:\n`/limpar` - limpa conversa\n`/status` - status\n`/admin` - só pro Kleber"

    if texto == "/limpar":
        limpar_historico(chat_id, user_info["id"], is_group)
        return "Zerei o histórico."

    if texto == "/status":
        return f"Online ✅\nModelo: Gemini Flash Free"

    if texto == "/admin":
        if user_info["tipo"]!= "criador":
            return "Tu não é o Kleber."
        return f"PAINEL\nUsers: {len(HISTORICO)}\nGrupos: {len(HISTORICO_GRUPO)}\nModelo: {MODELO_VISION}"

    return None

def processar_mensagem(msg):
    inicio_total = time.time()
    try:
        chat = msg["chat"]; chat_id = chat["id"]; chat_type = chat["type"]
        user = msg["from"]; message_id = msg["message_id"]
        user_info = get_user_info(user)
        is_group = chat_type in ["group", "supergroup"]
        if is_group and not deve_responder(msg, chat_type): return
        if not check_cooldown(user_info["id"]): return

        texto = msg.get("text", "").strip()
        has_image = "photo" in msg

        if texto and texto.startswith("/"):
            resposta = processar_comando(texto, chat_id, user_info, is_group)
            if resposta:
                send_message(chat_id, resposta, reply_to=message_id)
                return

        if has_image:
            file_id = msg["photo"][-1]["file_id"]
            image_base64 = get_file_from_telegram(file_id)
            texto = msg.get("caption", "O que tem nessa imagem?")

            historico = get_historico(chat_id, user_info["id"], is_group)
            system = montar_system_prompt(user_info)
            messages = [{"role": "system", "content": system}] + historico
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": texto},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            })
            adicionar_historico(chat_id, user_info["id"], "user", f"[IMAGEM] {texto}", is_group)
            resposta, tempo_ia = call_openrouter(messages)
            adicionar_historico(chat_id, user_info["id"], "assistant", resposta, is_group)
            logging.info(f"[IMG] {user_info['nome']} | {tempo_ia}s")
            send_message(chat_id, resposta, reply_to=message_id)
            return

        if not texto: return
        historico = get_historico(chat_id, user_info["id"], is_group)
        system = montar_system_prompt(user_info)
        messages = [{"role": "system", "content": system}] + historico + [{"role": "user", "content": texto}]
        adicionar_historico(chat_id, user_info["id"], "user", texto, is_group)
        resposta, tempo_ia = call_openrouter(messages)
        adicionar_historico(chat_id, user_info["id"], "assistant", resposta, is_group)
        logging.info(f"[TXT] {user_info['nome']} | {tempo_ia}s")
        send_message(chat_id, resposta, reply_to=message_id)

    except Exception as e:
        logging.exception(f"[PROCESS ERROR] {e}")

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    data = request.get_json()
    if not data: return "ok"
    update_id = data.get("update_id")
    with LOCK:
        if update_id in PROCESSED_UPDATES: return "ok"
        PROCESSED_UPDATES.add(update_id)
    if msg := data.get("message"): executor.submit(processar_mensagem, msg)
    return "ok"

@app.route('/')
def index():
    return f"{BOT_NAME} online", 200

@app.route('/health')
def health():
    return "ok", 200

init_bot_info()
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
