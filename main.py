import logging
import os
import re
import time

import requests
from flask import Flask, request

from config import (
    BOT_NAME,
    CREATOR,
    BOT_ID,
    BOT_USERNAME,
    TELEGRAM_TOKEN,
    TELEGRAM_API_URL,
    TIMEOUT_API,
    BOT_TAG,
)

from ai import (
    call_ai_smart,
    extrair_dados_automaticos,
)

from database import (
    save_message,
    buscar_dados_usuario, # <- ADICIONADO
)

from media import (
    analisar_midia_com_gemini,
)

from commands import (
    handle_command,
)

from messages import (
    responder_saudacao,
    enviar_resposta,
)

from webhook import (
    processar_webhook,
)

# ==========================================================
# FLASK + CONFIG
# ==========================================================

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)

session = requests.Session()

COOLDOWN_SAUDACAO = 60 # segundos
COOLDOWN_BOAS_VINDAS = 120 # segundos

ultima_saudacao_grupo = {}
ultima_boas_vindas_grupo = {}

BOT_ID_INT = int(BOT_ID) if BOT_ID else None # Normaliza pra int

# ==========================================================
# FUNÇÕES AUXILIARES CORRIGIDAS
# ==========================================================

def safe_lower(text):
    return text.lower() if text else ""

def bot_foi_mencionado(msg):
    """Detecta nome, @username, mention e reply - sem falso positivo"""
    text = msg.get("text", "")
    texto_lower = safe_lower(text)
    
    # 1. Reply direto ao bot - NORMALIZADO
    if "reply_to_message" in msg:
        reply = msg["reply_to_message"]
        reply_id = reply.get("from", {}).get("id")
        if BOT_ID_INT and reply_id == BOT_ID_INT:
            logging.info(f"[REPLY] Resposta direta ao bot detectada")
            return True
    
    # 2. Menção via entities do Telegram - inclui text_mention
    if "entities" in msg:
        for entity in msg["entities"]:
            if entity["type"] in ["mention", "text_mention"]:
                if entity["type"] == "mention":
                    mention = text[entity["offset"]:entity["offset"]+entity["length"]]
                    if BOT_USERNAME and safe_lower(mention) == f"@{BOT_USERNAME.lower()}":
                        return True
                elif entity["type"] == "text_mention":
                    user = entity.get("user", {})
                    if user.get("id") == BOT_ID_INT:
                        return True
    
    # 3. Nome ou @username como palavra separada - SEM FALSO POSITIVO
    if BOT_NAME:
        pattern = rf"\b{re.escape(BOT_NAME)}\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
            
    if BOT_USERNAME:
        pattern = rf"@{re.escape(BOT_USERNAME)}\b"
        if re.search(pattern, text, flags=re.IGNORECASE):
            return True
    
    return False

def remover_chamada(user_text):
    """Remove só o nome/@ do texto - com escape seguro"""
    if not user_text: return ""
    patterns = []
    if BOT_NAME:
        patterns.append(rf"\b{re.escape(BOT_NAME)}\b")
    if BOT_USERNAME:
        patterns.append(rf"@{re.escape(BOT_USERNAME)}\b")
    
    if not patterns: return user_text
    
    full_pattern = "|".join(patterns)
    return re.sub(full_pattern, "", user_text, flags=re.IGNORECASE).strip(",. ").strip()

def pode_responder_saudacao(chat_id):
    agora = time.time()
    ultimo = ultima_saudacao_grupo.get(chat_id, 0)
    if agora - ultimo > COOLDOWN_SAUDACAO:
        ultima_saudacao_grupo[chat_id] = agora
        return True
    return False

def pode_responder_boas_vindas(chat_id):
    agora = time.time()
    ultimo = ultima_boas_vindas_grupo.get(chat_id, 0)
    if agora - ultimo > COOLDOWN_BOAS_VINDAS:
        ultima_boas_vindas_grupo[chat_id] = agora
        return True
    return False

# ==========================================================
# CONTEXTO
# ==========================================================

def montar_contexto(user_id, chat_id, chat_type, chat_title):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    hora = datetime.now(ZoneInfo("America/Fortaleza"))
    dias = ["segunda-feira","terça-feira","quarta-feira","quinta-feira","sexta-feira","sábado","domingo"]
    meses = ["janeiro","fevereiro","março","abril","maio","junho","julho","agosto","setembro","outubro","novembro","dezembro"]
    dia_semana = dias[hora.weekday()]
    data_atual = f"{hora.day} de {meses[hora.month - 1]} de {hora.year}"
    hora_atual = hora.strftime("%H:%M")

    if hora.hour >= 18: saudacao = "Boa noite"
    elif hora.hour < 12: saudacao = "Bom dia"
    else: saudacao = "Boa tarde"

    prompt = f"""
Você é {BOT_NAME}, criado por {CREATOR}.
Você está em um grupo chamado "{chat_title}".

Data: {data_atual} - {dia_semana} - {hora_atual}
Saudação atual: {saudacao}

REGRAS:
- Seja humano, direto, natural e amigável.
- Use gírias brasileiras leves quando combinarem.
- Não responda tudo. Só responda quando for chamado ou for relevante.
- Seja breve em conversas casuais.
- Não diga que é um robô.
"""
    return {"prompt": prompt, "user_id": user_id, "chat_id": chat_id, "chat_type": chat_type, "chat_title": chat_title}

# ==========================================================
# ENVIO DE MENSAGEM
# ==========================================================

def send_message(chat_id, text, reply_to=None):
    try:
        if not text: return False
        payload = {"chat_id": chat_id, "text": text}
        if reply_to: payload["reply_to_message_id"] = reply_to
        response = session.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload, timeout=TIMEOUT_API)
        if response.status_code != 200:
            logging.warning(f"[TELEGRAM] HTTP {response.status_code}: {response.text[:300]}")
            return False
        return True
    except Exception as e:
        logging.exception(f"[SEND MESSAGE ERROR] {e}")
        return False

# ==========================================================
# SUPABASE STATUS
# ==========================================================

def get_supabase_usage():
    try:
        from config import SUPABASE_SERVICE_KEY
        if not SUPABASE_SERVICE_KEY: return "❌ SUPABASE_SERVICE_KEY não configurada."
        headers = {"apikey": SUPABASE_SERVICE_KEY, "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}"}
        response = session.post(f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/pg_database_size", headers=headers, json={"dbname": "postgres"}, timeout=TIMEOUT_API)
        if response.status_code != 200: return "❌ Não foi possível consultar o banco."
        db_bytes = response.json()
        db_mb = db_bytes / 1024 / 1024
        return f"📊 Banco: {db_mb:.2f} MB"
    except Exception as e:
        logging.exception(f"[SUPABASE STATUS ERROR] {e}")
        return "❌ Erro ao consultar o banco."

# ==========================================================
# PROCESSAMENTO PRINCIPAL
# ==========================================================

def process_message(msg):
    try:
        chat = msg["chat"]
        chat_id = chat["id"]
        chat_type = chat["type"]
        chat_title = chat.get("title", "")
        user = msg["from"]
        user_id = str(user["id"])
        message_id = msg["message_id"]
        user_text = msg.get("text", "")

        logging.info(f"[MESSAGE] chat={chat_id} user={user_id} text={user_text[:50]}")

        # ==================================================
        # 1. NOVO MEMBRO - BOAS VINDAS
        # ==================================================
        if "new_chat_members" in msg:
            if chat_type in ["group", "supergroup"] and pode_responder_boas_vindas(chat_id):
                nomes = [m.get("first_name", "pessoa") for m in msg["new_chat_members"]]
                nomes_str = ", ".join(nomes)
                texto_boasvindas = f"👋 Seja bem-vindo(a) {nomes_str}! Eu sou o {BOT_NAME}. Fica à vontade por aqui 😎"
                send_message(chat_id, texto_boasvindas)
                logging.info(f"[WELCOME] {nomes_str} entrou no grupo {chat_id}")
            return

        # ==================================================
        # 2. STICKER / GIF
        # ==================================================
        if "sticker" in msg:
            descricao = analisar_midia_com_gemini(msg["sticker"]["file_id"], "sticker")
            user_text = f"[Usuário enviou um sticker. Conteúdo: {descricao}]" if descricao else "[Usuário enviou um sticker]"
        elif "animation" in msg:
            descricao = analisar_midia_com_gemini(msg["animation"]["file_id"], "gif")
            user_text = f"[Usuário enviou um GIF. Conteúdo: {descricao}]" if descricao else "[Usuário enviou um GIF]"
        elif "document" in msg and msg["document"].get("mime_type") == "image/gif":
            descricao = analisar_midia_com_gemini(msg["document"]["file_id"], "gif")
            user_text = f"[Usuário enviou um GIF. Conteúdo: {descricao}]" if descricao else "[Usuário enviou um GIF]"

        if not user_text.strip(): return
        texto_lower = safe_lower(user_text)

        # ==================================================
        # 3. DETECTAR CHAMADA
        # ==================================================
        foi_chamado = bot_foi_mencionado(msg)
        if foi_chamado:
            logging.info(f"[MENTION] Bot foi chamado no chat {chat_id}")
            user_text = remover_chamada(user_text)
            texto_lower = safe_lower(user_text)
            if not texto_lower:
                responder_saudacao(chat_id, message_id, send_message)
                return

        # ==================================================
        # 4. COMANDOS
        # ==================================================
        if re.match(r"^/\w+", texto_lower):
            logging.info(f"[COMMAND] {texto_lower}")
            executado = handle_command(chat_id, user_id, texto_lower, message_id, send_message, get_supabase_usage)
            if executado: return

        # ==================================================
        # 5. SAUDAÇÃO COM COOLDOWN
        # ==================================================
        saudacoes = ["oi","ola","olá","bom dia","boa tarde","boa noite","eai","e aí","fala"]
        eh_saudacao = any(texto_lower.startswith(s) for s in saudacoes) and len(texto_lower.split()) < 4

        if eh_saudacao:
            if chat_type == "private" or (chat_type in ["group","supergroup"] and pode_responder_saudacao(chat_id)):
                logging.info(f"[SAUDACAO] Respondendo em {chat_id}")
                responder_saudacao(chat_id, message_id, send_message)
                return
            else:
                logging.info(f"[SAUDACAO] Ignorado por cooldown em {chat_id}")
                return

        # ==================================================
        # 6. SE FOI CHAMADO OU REPLY, MANDA PRA IA
        # ==================================================
        if foi_chamado:
            logging.info(f"[AI] Enviando pra IA: {user_text}")
        else:
            if chat_type in ["group", "supergroup"]:
                logging.info(f"[IGNORE] Mensagem normal em grupo")
                return

        # ==================================================
        # 7. SALVAR + EXTRAIR MEMÓRIA + IA - CORRIGIDO
        # ==================================================
        try: 
            save_message(user_id, chat_id, chat_type, chat_title, "user", user_text)
        except Exception as e: 
            logging.error(f"[SAVE MESSAGE ERROR] {e}")

        # Só extrai se for info importante. Não salva conversa normal
        try: 
            extrair_dados_automaticos(user_id, user_text)
        except Exception as e: 
            logging.error(f"[EXTRAIR ERROR] {e}")

        contexto = montar_contexto(user_id, chat_id, chat_type, chat_title)
        
        # INJETAR MEMÓRIA NO PROMPT ANTES DE CHAMAR A IA
        dados_usuario = buscar_dados_usuario(user_id)
        if dados_usuario.get("memories"):
            memoria_str = "\n".join([f"- {k}: {v}" for k, v in dados_usuario["memories"].items()])
            contexto["prompt"] += f"\n\nIMPORTANTE: Use essas informações sobre o usuário para responder. Não pergunte de novo:\n{memoria_str}"

        resposta = call_ai_smart(user_text, contexto, "conversa")
        enviar_resposta(chat_id, resposta, message_id, send_message)

    except Exception as e:
        logging.exception(f"[PROCESS ERROR] {e}")

# ==========================================================
# WEBHOOK + HEALTH
# ==========================================================

@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data: return "ok"
    return processar_webhook(data, process_message)

@app.route("/health")
def health():
    return "ok", 200

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
