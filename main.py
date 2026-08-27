import os, requests, threading, time, logging, base64, re, hashlib
from datetime import datetime, timezone, timedelta
import pytz
from collections import defaultdict, deque, OrderedDict
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

# ========= MOTOR IA V6.8 HANSEL - INICIO =========
PROVIDERS_RAW = {
    "groq": {"key_env": "GROQ_API_KEY", "endpoint": "https://api.groq.com/openai/v1", "format": "openai", "timeout": 6},
    "gemini": {"key_env": "GEMINI_API_KEY", "endpoint": "https://generativelanguage.googleapis.com/v1beta", "format": "gemini", "timeout": 8},
    "cerebras": {"key_env": "CEREBRAS_API_KEY", "endpoint": "https://api.cerebras.ai/v1", "format": "openai", "timeout": 6},
    "openrouter": {"key_env": "OPENROUTER_API_KEY", "endpoint": "https://openrouter.ai/api/v1", "format": "openai", "timeout": 8},
    "cloudflare": {"key_env": "CLOUDFLARE_API_TOKEN", "endpoint": f"https://api.cloudflare.com/client/v4/accounts/{os.getenv('CLOUDFLARE_ACCOUNT_ID')}/ai/run/", "format": "cloudflare", "timeout": 8, "requires": ["CLOUDFLARE_ACCOUNT_ID"]},
    "mistral": {"key_env": "MISTRAL_API_KEY", "endpoint": "https://api.mistral.ai/v1", "format": "openai", "timeout": 8},
}

def build_providers_dynamic():
    provs = {}
    for name, cfg in PROVIDERS_RAW.items():
        key = os.getenv(cfg["key_env"])
        if not key: continue
        if cfg.get("requires") and any(not os.getenv(r) for r in cfg["requires"]): continue
        if "None" in cfg["endpoint"]: continue
        provs[name] = {"key": key, "endpoint": cfg["endpoint"], "format": cfg["format"], "timeout": cfg["timeout"]}
    return provs

PROVIDERS = build_providers_dynamic()
ORDER_PREFERENCE = ["groq","gemini","cerebras","openrouter","cloudflare","mistral"]
AI_PRIORITY = [p for p in ORDER_PREFERENCE if p in PROVIDERS]
print(f"[PROVIDERS ATIVOS] {AI_PRIORITY}")

FALLBACK_MODELS = {
    "groq": ["openai/gpt-oss-120b","llama-3.3-70b-versatile","llama-3.1-8b-instant","openai/gpt-oss-20b"],
    "gemini": ["gemini-2.0-flash","gemini-1.5-flash-latest","gemini-1.5-flash"],
    "cerebras": ["llama-3.3-70b","llama3.1-8b"],
    "openrouter": ["openai/gpt-oss-20b:free","meta-llama/llama-4-scout:free","qwen/qwen3-32b:free","meta-llama/llama-3.1-8b-instruct:free"],
    "cloudflare": ["@cf/meta/llama-3.1-8b-instruct","@cf/mistral/mistral-7b-instruct-v0.1"],
    "mistral": ["mistral-small-latest","mistral-large-latest"]
}

MODEL_CACHE = {}; MODEL_CACHE_TTL = 1800
MODEL_CACHE_LOCK = threading.RLock()
AI_MODEL_BLACKLIST = {}; AI_PROVIDER_BLACKLIST = {}
AI_STATS = {"fallbacks":0,"total_calls":0,"attempts":0}
ai_lock = threading.RLock()
PROVIDERS_LOCK = threading.RLock()
BLACKLIST_LOCK = threading.RLock()

for prov in PROVIDERS.keys():
    AI_STATS[prov] = {"ok":0,"erro":0,"429":0,"401":0,"404":0,"5xx":0,"timeout":0,"vazio":0,"total_requests":0,"last_ok":None,"last_error":None,"last_model":None,"avg_ms":0,"total_ms":0}

def is_model_blocked(prov, model_id):
    with BLACKLIST_LOCK:
        info = AI_MODEL_BLACKLIST.get((prov, model_id))
        if not info: return False
        if time.time() < info["until"]: return True
        AI_MODEL_BLACKLIST.pop((prov, model_id),None); return False

def is_provider_blocked(prov):
    with BLACKLIST_LOCK:
        info = AI_PROVIDER_BLACKLIST.get(prov)
        if not info: return False, None
        if time.time() < info["until"]: return True, info["reason"]
        AI_PROVIDER_BLACKLIST.pop(prov,None); return False, None

def block_model(prov, model_id, sec=300, reason="fail"):
    with BLACKLIST_LOCK: AI_MODEL_BLACKLIST[(prov, model_id)] = {"until": time.time()+sec, "reason": reason}

def block_provider(prov, sec, reason=""):
    with BLACKLIST_LOCK: AI_PROVIDER_BLACKLIST[prov] = {"until": time.time()+sec, "reason": reason}

def get_dynamic_priority():
    with PROVIDERS_LOCK: ativos = [p for p in ORDER_PREFERENCE if p in PROVIDERS]
    with ai_lock: stats_copy = {k: dict(v) if isinstance(v, dict) else v for k,v in AI_STATS.items()}
    with BLACKLIST_LOCK: bl_copy = dict(AI_PROVIDER_BLACKLIST)
    def score(p):
        if bl_copy.get(p) and time.time() < bl_copy[p]["until"]: return 99999
        st = stats_copy.get(p, {})
        return st.get("erro",0)*1 + st.get("429",0)*3 + st.get("401",0)*10 + st.get("5xx",0)*2 + st.get("timeout",0)*2 + st.get("vazio",0)*1 + st.get("avg_ms",0)/500.0 - min(st.get("ok",0),20)*0.5
    return sorted(ativos, key=score)

def descobrir_modelos_provider(prov, key):
    try:
        if prov=="groq":
            r=requests.get("https://api.groq.com/openai/v1/models",headers={"Authorization":f"Bearer {key}"},timeout=8)
            if r.status_code==200: return [m["id"] for m in r.json().get("data",[]) if "whisper" not in m["id"].lower()]
        elif prov=="gemini":
            r=requests.get(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",timeout=8)
            if r.status_code==200: return [m["name"].replace("models/","") for m in r.json().get("models",[]) if "generateContent" in str(m.get("supportedGenerationMethods",[]))][:10]
        elif prov=="cerebras":
            r=requests.get("https://api.cerebras.ai/v1/models",headers={"Authorization":f"Bearer {key}"},timeout=8)
            if r.status_code==200: return [m["id"] for m in r.json().get("data",[])][:6]
        elif prov=="openrouter":
            r=requests.get("https://openrouter.ai/api/v1/models",headers={"Authorization":f"Bearer {key}"},timeout=8)
            if r.status_code==200: return [m["id"] for m in r.json().get("data",[]) if ":free" in m["id"]][:10]
        elif prov=="cloudflare": return FALLBACK_MODELS["cloudflare"]
        elif prov=="mistral":
            r=requests.get("https://api.mistral.ai/v1/models",headers={"Authorization":f"Bearer {key}"},timeout=8)
            if r.status_code==200: return [m["id"] for m in r.json().get("data",[])][:6]
    except: pass
    return []

def atualizar_catalogo_background():
    provs = build_providers_dynamic()
    with PROVIDERS_LOCK: PROVIDERS.clear(); PROVIDERS.update(provs)
    for prov, cfg in list(provs.items()):
        novos = descobrir_modelos_provider(prov, cfg["key"]) or FALLBACK_MODELS.get(prov, [])
        if novos:
            with MODEL_CACHE_LOCK: MODEL_CACHE[prov]={"models":sorted(list(set(novos))),"updated":time.time()}

def model_catalog_loop():
    global AI_PRIORITY
    atualizar_catalogo_background()
    AI_PRIORITY = get_dynamic_priority()
    while True:
        time.sleep(MODEL_CACHE_TTL)
        atualizar_catalogo_background()
        AI_PRIORITY = get_dynamic_priority()
        logging.info(f"[PRIORIDADE] {AI_PRIORITY}")
threading.Thread(target=model_catalog_loop,daemon=True).start()

def get_modelos_para_uso(prov):
    with MODEL_CACHE_LOCK:
        base = MODEL_CACHE.get(prov,{}).get("models") or FALLBACK_MODELS.get(prov,[])
    disp = [m for m in base if not is_model_blocked(prov, m)]
    return disp or base

TOTAL_AI_TIMEOUT = 14; MAX_AI_ATTEMPTS = 10
thread_local=threading.local()
def get_session():
    if not hasattr(thread_local,"session"): thread_local.session=requests.Session()
    return thread_local.session

def limpar_resposta_ia(texto):
    if not texto: return None
    t = str(texto).strip()
    t = re.sub(r"<thinking>.*?</thinking>","",t,flags=re.DOTALL|re.I)
    t = re.sub(r"<think>.*?</think>","",t,flags=re.DOTALL|re.I)
    return t.strip()[:4000] or None

def call_provider(provider_name, cfg, messages, time_left_fn):
    if is_provider_blocked(provider_name)[0]: return None, "blocked_provider"
    modelos = get_modelos_para_uso(provider_name)
    if not modelos: return None, "no_models"
    sess=get_session()
    for modelo in modelos:
        if time_left_fn() <= 2: break
        if is_model_blocked(provider_name, modelo): continue
        t0=time.time()
        try:
            if cfg["format"]=="openai":
                url=f"{cfg['endpoint'].rstrip('/')}/chat/completions"
                headers={"Authorization":f"Bearer {cfg['key']}","Content-Type":"application/json"}
                timeout=min(cfg.get("timeout",6), max(2, int(time_left_fn()-1)))
                payload={"model":modelo,"messages":messages,"temperature":1.0,"max_tokens":800}
                r=sess.post(url,json=payload,headers=headers,timeout=timeout)
                elapsed=int((time.time()-t0)*1000)
                with ai_lock: AI_STATS[provider_name]["total_requests"]+=1; AI_STATS[provider_name]["total_ms"]+=elapsed; AI_STATS[provider_name]["avg_ms"]=AI_STATS[provider_name]["total_ms"]//AI_STATS[provider_name]["total_requests"]
                if r.status_code==200:
                    content=r.json()["choices"][0]["message"]["content"]
                    if content and len(content.strip())>=2: return content, modelo
                    with ai_lock: AI_STATS[provider_name]["vazio"]+=1
                    block_model(provider_name,modelo,120,"vazio"); continue
                else:
                    with ai_lock:
                        if r.status_code==429: AI_STATS[provider_name]["429"]+=1
                        elif r.status_code in (401,403): AI_STATS[provider_name]["401"]+=1
                        elif r.status_code==404: AI_STATS[provider_name]["404"]+=1
                        elif r.status_code>=500: AI_STATS[provider_name]["5xx"]+=1
                        else: AI_STATS[provider_name]["erro"]+=1
                        AI_STATS[provider_name]["last_error"]=f"{r.status_code} {modelo}"
                    if r.status_code==429: block_provider(provider_name,180,f"429 {modelo}"); block_model(provider_name,modelo,300,"429"); break
                    elif r.status_code in (401,403): block_provider(provider_name,1800,f"{r.status_code}"); break
                    elif r.status_code==404: block_model(provider_name,modelo,3600,"404"); continue
                    else: block_model(provider_name,modelo,180,f"{r.status_code}"); continue
            elif cfg["format"]=="gemini":
                system_texts=[m["content"] for m in messages if m["role"]=="system"]
                chat_msgs=[m for m in messages if m["role"]!="system"]
                gemini_contents=[]
                if system_texts:
                    combined="\n\n".join(system_texts)
                    gemini_contents.append({"role":"user","parts":[{"text":f"SISTEMA: {combined}"}]})
                    gemini_contents.append({"role":"model","parts":[{"text":"Entendido."}]})
                for m in chat_msgs:
                    role="user" if m["role"]=="user" else "model"
                    if gemini_contents and gemini_contents[-1]["role"]==role: gemini_contents[-1]["parts"][0]["text"]+=f"\n\n{m['content']}"
                    else: gemini_contents.append({"role":role,"parts":[{"text":m["content"]}]})
                url=f"{cfg['endpoint'].rstrip('/')}/models/{modelo}:generateContent?key={cfg['key']}"
                r=sess.post(url,json={"contents":gemini_contents},timeout=min(8, max(2, int(time_left_fn()-1))))
                elapsed=int((time.time()-t0)*1000)
                with ai_lock: AI_STATS[provider_name]["total_requests"]+=1; AI_STATS[provider_name]["total_ms"]+=elapsed; AI_STATS[provider_name]["avg_ms"]=AI_STATS[provider_name]["total_ms"]//AI_STATS[provider_name]["total_requests"]
                if r.status_code==200:
                    try:
                        txt=r.json()["candidates"][0]["content"]["parts"][0]["text"]
                        if txt and len(txt.strip())>=2: return txt, modelo
                        with ai_lock: AI_STATS[provider_name]["vazio"]+=1; continue
                    except:
                        with ai_lock: AI_STATS[provider_name]["vazio"]+=1; continue
                else:
                    with ai_lock:
                        if r.status_code==429: AI_STATS[provider_name]["429"]+=1
                        elif r.status_code in (401,403): AI_STATS[provider_name]["401"]+=1
                        elif r.status_code==404: AI_STATS[provider_name]["404"]+=1
                        else: AI_STATS[provider_name]["erro"]+=1
                        AI_STATS[provider_name]["last_error"]=f"{r.status_code} {modelo}"
                    if r.status_code==429: block_provider(provider_name,180,"429"); block_model(provider_name,modelo,300,"429"); break
                    elif r.status_code in (401,403): block_provider(provider_name,1800,f"{r.status_code}"); break
                    elif r.status_code==404: block_model(provider_name,modelo,3600,"404"); continue
                    else: block_model(provider_name,modelo,180,f"{r.status_code}"); continue
            elif cfg["format"]=="cloudflare":
                url=f"{cfg['endpoint'].rstrip('/')}/{modelo}"; headers={"Authorization":f"Bearer {cfg['key']}","Content-Type":"application/json"}
                prompt="\n".join([f"{m['role']}: {m['content']}" for m in messages])
                r=sess.post(url,json={"prompt":prompt},headers=headers,timeout=min(8, max(2, int(time_left_fn()-1))))
                elapsed=int((time.time()-t0)*1000)
                with ai_lock: AI_STATS[provider_name]["total_requests"]+=1; AI_STATS[provider_name]["total_ms"]+=elapsed; AI_STATS[provider_name]["avg_ms"]=AI_STATS[provider_name]["total_ms"]//AI_STATS[provider_name]["total_requests"]
                if r.status_code==200:
                    resp=r.json().get("result",{}).get("response") or r.json().get("result")
                    if resp: return resp, modelo
                    with ai_lock: AI_STATS[provider_name]["vazio"]+=1; continue
                else:
                    with ai_lock:
                        if r.status_code>=500: AI_STATS[provider_name]["5xx"]+=1
                        elif r.status_code in (401,403): AI_STATS[provider_name]["401"]+=1
                        else: AI_STATS[provider_name]["erro"]+=1
                    block_model(provider_name,modelo,180,f"{r.status_code}"); continue
        except requests.exceptions.Timeout:
            with ai_lock: AI_STATS[provider_name]["timeout"]+=1; AI_STATS[provider_name]["total_requests"]+=1; AI_STATS[provider_name]["last_error"]=f"timeout {modelo}"
            block_model(provider_name,modelo,180,"timeout"); continue
        except Exception as e:
            with ai_lock: AI_STATS[provider_name]["erro"]+=1; AI_STATS[provider_name]["last_error"]=f"{type(e).__name__} {modelo}"
            block_model(provider_name,modelo,180,type(e).__name__); continue
    return None, "all_failed"

def call_ai_router(messages):
    global AI_PRIORITY
    start=time.time(); attempts_local=0
    def time_left(): return TOTAL_AI_TIMEOUT - (time.time()-start)
    with ai_lock: AI_STATS["total_calls"]+=1
    prioridade = get_dynamic_priority()
    for provider_name in prioridade:
        if time_left() <= 2.5 or attempts_local >= MAX_AI_ATTEMPTS: break
        with PROVIDERS_LOCK: cfg=PROVIDERS.get(provider_name)
        if not cfg or is_provider_blocked(provider_name)[0]: continue
        texto, modelo_usado = call_provider(provider_name, cfg, messages, time_left)
        attempts_local+=1
        with ai_lock:
            AI_STATS["attempts"]+=1
            if texto is None: AI_STATS["fallbacks"]+=1
        if texto:
            limpo=limpar_resposta_ia(texto)
            if limpo:
                with ai_lock: AI_STATS[provider_name]["ok"]+=1; AI_STATS[provider_name]["last_model"]=modelo_usado; AI_STATS[provider_name]["last_ok"]=datetime.now(timezone.utc).isoformat()
                AI_PRIORITY = get_dynamic_priority()
                logging.info(f"[IA OK] {provider_name}/{modelo_usado}")
                return limpo, 0, provider_name
    return "⚠️ IA offline. Tenta de novo em 30s.", 0, "error"
# ========= MOTOR IA V6.8 HANSEL - FIM =========

# ========= RESTO DO BOT (SUA ESTRUTURA IGUAL) =========
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
    return f"Você é {BOT_NAME}. Criado por {CREATOR}. Usuário: {user_info['nome']} DATA: {dt['dia_semana']}, {dt['data']} {dt['hora']}. Seja direto, engraçado, fala como jovem brasileiro, max 3 linhas."

def deve_responder(msg, chat_type):
    if chat_type == "private": return True
    texto = msg.get("text", "").lower()
    if BOT_USERNAME and f"@{BOT_USERNAME}" in texto: return True
    if BOT_NAME.lower() in texto: return True
    if "reply_to_message" in msg and msg["reply_to_message"].get("from", {}).get("id") == BOT_ID: return True
    # Gatilho de dúvida em grupo
    if chat_type in ["group","supergroup"]:
        if re.search(r"\b(alguem sabe|alguém sabe|quem|como|onde|cade|cadê|alguém|alguem)\b.*\?", texto):
            return True
    return False

def processar_comando(texto, chat_id, user_info, is_group):
    t = texto.lower().split()[0]
    t = re.sub(r"@\w+", "", t)
    if t == "/start": return f"👋 Opa {user_info['nome']}! Eu sou o *{BOT_NAME}* V6.8"
    if t == "/limpar": limpar_historico(chat_id, user_info["id"], is_group); return "🧹 Histórico limpo!"
    if t == "/status": return f"✅ {BOT_NAME} Online\nOrdem: {get_dynamic_priority()}\nStats: {AI_STATS['fallbacks']} fallbacks"
    if t == "/resetai" and user_info["id"] in ADMINS:
        with BLACKLIST_LOCK: AI_MODEL_BLACKLIST.clear(); AI_PROVIDER_BLACKLIST.clear()
        with MODEL_CACHE_LOCK: MODEL_CACHE.clear()
        return "♻️ IA resetada! Catálogo vai atualizar sozinho."
    if t == "/ping": return f"Pong! {get_dynamic_priority()}"
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
    return {
        "provedores_ordem": get_dynamic_priority(),
        "ativos": list(PROVIDERS.keys()),
        "stats": AI_STATS,
        "bl_models": len(AI_MODEL_BLACKLIST),
        "bl_provs": len(AI_PROVIDER_BLACKLIST),
        "cache": {k: len(v.get("models",[])) for k,v in MODEL_CACHE.items()}
    }

@app.route('/health')
def health(): return "ok", 200

@app.route('/')
def index(): return f"{BOT_NAME} V6.8 HANSEL MOTOR online ✅ {AI_PRIORITY}", 200

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
