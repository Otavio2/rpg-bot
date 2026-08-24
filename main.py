import os, requests, threading, time, logging, base64, re
from datetime import datetime
import pytz
from collections import defaultdict, deque
from flask import Flask, request
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(levelname)s: %(message)s')

BOT_NAME = "Matheus"
CREATOR = "Kleber"
CREATOR_ID = "8398287578"
ADMINS = ["8398287578"]
TIMEZONE = "America/Fortaleza"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
RENDER_URL = "https://edu-bot-6yfa.onrender.com"
if not TELEGRAM_TOKEN: raise RuntimeError("TELEGRAM_TOKEN não configurado")
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

BOT_ID = None
BOT_USERNAME = None
BOT_INICIADO = False

# ========= MOTOR SÓ CLOUDFLARE + OPENROUTER (SEM GROQ) =========
PROVIDERS = {
    "groq": {
        "key": os.getenv("GROQ_API_KEY"), 
        "model_env": os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"), 
        "endpoint": "https://api.groq.com/openai/v1", 
        "models_fallback": ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "gemma2-9b-it", "meta-llama/llama-4-scout", "qwen/qwen3-32b"], 
        "format": "openai", 
        "timeout": 10
    },
    "cerebras": {
        "key": os.getenv("CEREBRAS_API_KEY"), 
        "model_env": os.getenv("CEREBRAS_MODEL", "llama-3.3-70b"), 
        "endpoint": "https://api.cerebras.ai/v1", 
        "models_fallback": ["llama3.1-8b", "llama-3.3-70b"], 
        "format": "openai", 
        "timeout": 10
    },
    "gemini": {
        "key": os.getenv("GEMINI_API_KEY"), 
        "model_env": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"), 
        "endpoint": "https://generativelanguage.googleapis.com/v1beta", 
        "models_fallback": ["gemini-2.0-flash", "gemini-1.5-flash-latest"], 
        "format": "gemini", 
        "timeout": 12
    },
    "cloudflare": {
        "key": os.getenv("CLOUDFLARE_API_TOKEN"),
        "model_env": os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct"),
        "endpoint": f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/ai/run/",
        "models_fallback": ["@cf/meta/llama-3.1-8b-instruct", "@cf/mistral/mistral-7b-instruct-v0.1"],
        "format": "cloudflare",
        "timeout": 12,
        "requires": ["CLOUDFLARE_ACCOUNT_ID"]
    },
    "openrouter": {
        "key": os.getenv("OPENROUTER_API_KEY"),
        "model_env": os.getenv("OPENROUTER_MODEL", "openai/gpt-oss-20b:free"),
        "endpoint": "https://openrouter.ai/api/v1",
        "models_fallback": ["openai/gpt-oss-20b:free", "meta-llama/llama-4-scout:free", "qwen/qwen3-32b:free"],
        "format": "openai",
        "timeout": 12
    },
    "mistral": {
        "key": os.getenv("MISTRAL_API_KEY"), 
        "model_env": os.getenv("MISTRAL_MODEL", "mistral-small-latest"), 
        "endpoint": "https://api.mistral.ai/v1", 
        "models_fallback": ["mistral-large-latest"], 
        "format": "openai", 
        "timeout": 10
    }
}
PROVIDERS = {k:v for k,v in PROVIDERS.items() if v["key"]}
print(f"[PROVIDERS ATIVOS] {list(PROVIDERS.keys())}")

AI_BLACKLIST = {}
ai_lock = threading.Lock()
thread_local = threading.local()
def get_session():
    if not hasattr(thread_local, "session"): thread_local.session = requests.Session()
    return thread_local.session
def _is_blacklisted(key):
    with ai_lock: return AI_BLACKLIST.get(key, 0) > time.time()
def _blacklist(key, seconds):
    with ai_lock: AI_BLACKLIST[key] = time.time() + seconds

def limpar_resposta_ia(resp):
    if not resp: return None
    resp = re.sub(r"<thinking>.*?</thinking>", "", str(resp), flags=re.DOTALL | re.IGNORECASE)
    return resp.strip()[:4000] or None

def call_provider(provider_name, messages):
    data = PROVIDERS[provider_name]
    modelos = [data["model_env"]] + data.get("models_fallback", [])
    for modelo in [m for m in modelos if m]:
        if _is_blacklisted(f"{provider_name}_{modelo}"): continue
        try:
            msgs_limpa = []
            for m in messages:
                if isinstance(m["content"], list):
                    msgs_limpa.append({"role": m["role"], "content": m["content"][0].get("text","")})
                else:
                    msgs_limpa.append(m)

            s = get_session()
            if data["format"] == "cloudflare":
                url = data["endpoint"].rstrip("/") + f"/{modelo}"
                headers = {"Authorization": f"Bearer {data['key']}"}
                payload = {"messages": msgs_limpa}
                r = s.post(url, headers=headers, json=payload, timeout=45)
                if r.status_code == 200:
                    j = r.json()
                    resp = j.get("result", {}).get("response", "") if isinstance(j.get("result"), dict) else j.get("result", "")
                    resp = limpar_resposta_ia(resp)
                    if resp: return resp, "ok"
            else:
                url = data["endpoint"] + "/chat/completions"
                headers = {"Authorization": f"Bearer {data['key']}", "Content-Type": "application/json"}
                payload = {"model": modelo, "messages": msgs_limpa, "max_tokens": 1024, "temperature": 0.7}
                r = s.post(url, headers=headers, json=payload, timeout=45)
                if r.status_code == 200:
                    resp = r.json()["choices"][0]["message"]["content"]
                    resp = limpar_resposta_ia(resp)
                    if resp: return resp, "ok"
            logging.warning(f"[FAIL] {provider_name}/{modelo} {r.status_code} {r.text[:500]}")
        except Exception as e:
            logging.error(f"[ERROR] {provider_name}/{modelo}: {e}")
    return None, "fail"

def call_ai_router(messages):
    for prov in PROVIDERS.keys():
        resp, _ = call_provider(prov, messages)
        if resp: return resp, 0, prov
    return "⚠️ IA offline. Cloudflare não respondeu. Verifica /test_cloudflare", 0, "error"

# ========= ROTAS DE TESTE =========
@app.route('/test_cloudflare')
def test_cloudflare():
    token = os.getenv("CLOUDFLARE_API_TOKEN")
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    model = os.getenv("CLOUDFLARE_MODEL", "@cf/meta/llama-3.1-8b-instruct")
    if not token or not account_id:
        return f"SEM TOKEN: token={bool(token)} account={bool(account_id)}"
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"messages": [{"role": "user", "content": "Oi, diga apenas OK"}]}
    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        return f"Model: {model}<br>Status: {r.status_code}<br><br>{r.text[:2000]}", r.status_code
    except Exception as e:
        return f"Erro Cloudflare: {e}"

@app.route('/debug')
def debug_route():
    return {"provedores": {k: "OK" if v["key"] else "SEM CHAVE" for k,v in PROVIDERS.items()}, "env": {"has_token": bool(os.getenv("CLOUDFLARE_API_TOKEN")), "has_account": bool(os.getenv("CLOUDFLARE_ACCOUNT_ID"))}}

@app.route('/')
def index(): return f"{BOT_NAME} online ✅ Cloudflare", 200

# ========= RESTO DO BOT (SEU CÓDIGO IGUAL) =========
MAX_TOKENS_RESPOSTA = 300
HISTORICO_LIMITE_USER = 6
HISTORICO_LIMITE_GRUPO = 4
MAX_MSG_LENGTH = 2000
TIMEOUT_API = 45
COOLDOWN_SEGUNDOS_PV = 3
COOLDOWN_SEGUNDOS_GRUPO = 10
MAX_REQUISICOES_POR_MINUTO = 5
JANELA_TEMPO = 60
MAX_REQUISICOES_POR_USER_HORA = 10
HISTORICO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_USER))
HISTORICO_GRUPO = defaultdict(lambda: deque(maxlen=HISTORICO_LIMITE_GRUPO))
USER_COOLDOWN = {}
USER_REQUEST_COUNT = defaultdict(lambda: deque())
LOCK = threading.Lock()
PROCESSED_UPDATES = {}
UPDATE_EXPIRACAO = 3600
executor = ThreadPoolExecutor(max_workers=3)
REQUISICOES_TIMES = deque()

def init_bot_info():
    global BOT_ID, BOT_USERNAME, BOT_INICIADO
    if BOT_INICIADO: return
    try:
        r = requests.get(f"{TELEGRAM_API_URL}/getMe", timeout=TIMEOUT_API)
        data = r.json()["result"]
        BOT_ID = data["id"]; BOT_USERNAME = data["username"].lower(); BOT_INICIADO = True
        logging.info(f"[BOT] @{BOT_USERNAME}")
    except Exception as e:
        logging.exception(f"[TELEGRAM ERROR] {e}")

def send_message(chat_id, text, reply_to=None):
    text = (text or "Erro")[:4096]
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
    r = requests.get(f"{TELEGRAM_API_URL}/getFile?file_id={file_id}"); r.raise_for_status()
    file_path = r.json()["result"]["file_path"]
    img = requests.get(f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"); img.raise_for_status()
    return base64.b64encode(img.content).decode("utf-8")

def get_user_info(user):
    user_id = str(user["id"]); nome = user.get("first_name", "usuário")
    tipo = "criador" if user_id == CREATOR_ID else "usuario"
    return {"id": user_id, "nome": nome, "tipo": tipo}

def check_user_rate_limit(user_id):
    agora = time.time()
    with LOCK:
        fila = USER_REQUEST_COUNT[user_id]
        while fila and fila[0] < agora - 3600: fila.popleft()
        if len(fila) >= MAX_REQUISICOES_POR_USER_HORA: return False
        fila.append(agora)
    return True
def check_global_rate_limit():
    agora = time.time()
    with LOCK:
        while REQUISICOES_TIMES and REQUISICOES_TIMES[0] < agora - JANELA_TEMPO: REQUISICOES_TIMES.popleft()
        if len(REQUISICOES_TIMES) >= MAX_REQUISICOES_POR_MINUTO: return False
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
            if agora - PROCESSED_UPDATES[uid] > UPDATE_EXPIRACAO: del PROCESSED_UPDATES[uid]
        if update_id in PROCESSED_UPDATES: return True
        PROCESSED_UPDATES[update_id] = agora
    return False
def get_datetime_info():
    tz = pytz.timezone(TIMEZONE); agora = datetime.now(tz)
    dias = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
    return {"dia_semana": dias[agora.weekday()], "data": agora.strftime("%d/%m/%Y"), "hora": agora.strftime("%H:%M")}
def adicionar_historico(chat_id, user_id, role, content, is_group=False):
    with LOCK:
        msg = {"role": role, "content": content[:MAX_MSG_LENGTH]}
        if is_group: HISTORICO_GRUPO[str(chat_id)].append(msg)
        else: HISTORICO[str(user_id)].append(msg)
def get_historico(chat_id, user_id, is_group):
    with LOCK: return list(HISTORICO_GRUPO[str(chat_id)]) if is_group else list(HISTORICO[str(user_id)])
def limpar_historico(chat_id, user_id, is_group):
    with LOCK:
        if is_group: HISTORICO_GRUPO[str(chat_id)].clear()
        else: HISTORICO[str(user_id)].clear()
def montar_system_prompt(user_info):
    dt = get_datetime_info()
    return f"Você é {BOT_NAME}. Usuário: {user_info['nome']} DATA: {dt['dia_semana']}, {dt['data']} {dt['hora']}. Seja direto, max 3 linhas."
def deve_responder(msg, chat_type):
    if chat_type == "private": return True
    texto = msg.get("text", "").lower()
    if BOT_USERNAME and f"@{BOT_USERNAME}" in texto: return True
    if BOT_NAME.lower() in texto: return True
    if "reply_to_message" in msg and msg["reply_to_message"].get("from", {}).get("id") == BOT_ID: return True
    return False
def processar_comando(texto, chat_id, user_info, is_group):
    t = texto.lower()
    if t == "/start": return f"👋 Opa {user_info['nome']}! Eu sou o *{BOT_NAME}*"
    if t == "/limpar": limpar_historico(chat_id, user_info["id"], is_group); return "🧹 Histórico limpo!"
    if t == "/status": return f"✅ {BOT_NAME} Online\nProvedores: {list(PROVIDERS.keys())}"
    return None
def processar_mensagem(msg):
    try:
        chat = msg["chat"]; chat_id = chat["id"]; chat_type = chat["type"]
        user = msg["from"]; message_id = msg["message_id"]
        user_info = get_user_info(user); is_group = chat_type in ["group", "supergroup"]
        if is_group and not deve_responder(msg, chat_type): return
        texto = msg.get("text", "").strip()
        if texto.startswith("/"):
            resp = processar_comando(texto, chat_id, user_info, is_group)
            if resp: send_message(chat_id, resp, reply_to=message_id)
            return
        if not check_cooldown(user_info["id"], is_group): return
        if not texto: return
        historico = get_historico(chat_id, user_info["id"], is_group)
        system = montar_system_prompt(user_info)
        messages = [{"role": "system", "content": system}] + historico + [{"role": "user", "content": texto}]
        adicionar_historico(chat_id, user_info["id"], "user", texto, is_group)
        resposta, _, _ = call_ai_router(messages)
        adicionar_historico(chat_id, user_info["id"], "assistant", resposta, is_group)
        send_message(chat_id, resposta, reply_to=message_id)
    except Exception as e:
        logging.exception(f"[PROCESS ERROR] {e}")

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def webhook():
    if not BOT_INICIADO: init_bot_info()
    data = request.get_json()
    if not data: return "ok"
    if is_update_processado(data.get("update_id")): return "ok"
    if msg := data.get("message"): executor.submit(processar_mensagem, msg)
    return "ok"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
