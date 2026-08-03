import logging
import os
import re

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
    save_memory,
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
# FLASK
# ==========================================================

app = Flask(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s"
)

session = requests.Session()


# ==========================================================
# CONTEXTO
# ==========================================================

def montar_contexto(
    user_id,
    chat_id,
    chat_type,
    chat_title
):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    hora = datetime.now(
        ZoneInfo("America/Fortaleza")
    )

    dias = [
        "segunda-feira",
        "terça-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sábado",
        "domingo"
    ]

    meses = [
        "janeiro",
        "fevereiro",
        "março",
        "abril",
        "maio",
        "junho",
        "julho",
        "agosto",
        "setembro",
        "outubro",
        "novembro",
        "dezembro"
    ]

    dia_semana = dias[hora.weekday()]

    data_atual = (
        f"{hora.day} de "
        f"{meses[hora.month - 1]} de "
        f"{hora.year}"
    )

    hora_atual = hora.strftime("%H:%M")

    if hora.hour >= 18:
        saudacao = "Boa noite"
    elif hora.hour < 12:
        saudacao = "Bom dia"
    else:
        saudacao = "Boa tarde"

    prompt = f"""
Você é {BOT_NAME}, criado por {CREATOR}.

Data atual: {data_atual}
Dia da semana: {dia_semana}
Horário atual: {hora_atual}

Considere sempre a data, o dia da semana
e o horário acima ao responder.

Se receber uma descrição de sticker ou GIF,
entenda o conteúdo e responda somente com texto.

Seja humano, direto, natural e amigável.
Use gírias brasileiras leves quando combinarem.
Responda normalmente sem dizer que é um robô.

Saudação atual: {saudacao}
"""

    return {
        "prompt": prompt,
        "user_id": user_id,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "chat_title": chat_title,
    }


# ==========================================================
# ENVIO DE MENSAGEM
# ==========================================================

def send_message(
    chat_id,
    text,
    reply_to=None
):
    try:

        if not text:
            return False

        payload = {
            "chat_id": chat_id,
            "text": text,
        }

        if reply_to:
            payload[
                "reply_to_message_id"
            ] = reply_to

        response = session.post(
            f"{TELEGRAM_API_URL}/sendMessage",
            json=payload,
            timeout=TIMEOUT_API
        )

        if response.status_code != 200:

            logging.warning(
                f"[TELEGRAM] HTTP "
                f"{response.status_code}: "
                f"{response.text[:300]}"
            )

            return False

        return True

    except Exception as e:

        logging.exception(
            f"[SEND MESSAGE ERROR] {e}"
        )

        return False


# ==========================================================
# SUPABASE STATUS
# ==========================================================

def get_supabase_usage():
    try:

        from config import SUPABASE_SERVICE_KEY

        if not SUPABASE_SERVICE_KEY:

            return (
                "❌ SUPABASE_SERVICE_KEY "
                "não configurada."
            )

        headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization":
                f"Bearer {SUPABASE_SERVICE_KEY}",
        }

        response = session.post(
            f"{os.getenv('SUPABASE_URL')}"
            "/rest/v1/rpc/pg_database_size",
            headers=headers,
            json={"dbname": "postgres"},
            timeout=TIMEOUT_API
        )

        if response.status_code != 200:
            return "❌ Não foi possível consultar o banco."

        db_bytes = response.json()

        db_mb = (
            db_bytes / 1024 / 1024
        )

        return (
            f"📊 Banco: {db_mb:.2f} MB"
        )

    except Exception as e:

        logging.exception(
            f"[SUPABASE STATUS ERROR] {e}"
        )

        return "❌ Erro ao consultar o banco."


# ==========================================================
# PROCESSAMENTO PRINCIPAL
# ==========================================================

def process_message(msg):

    try:

        chat = msg["chat"]

        chat_id = chat["id"]

        chat_type = chat["type"]

        chat_title = chat.get(
            "title",
            ""
        )

        user = msg["from"]

        user_id = str(
            user["id"]
        )

        message_id = msg[
            "message_id"
        ]

        user_text = msg.get(
            "text",
            ""
        )


        # ==================================================
        # STICKER
        # ==================================================

        if "sticker" in msg:

            file_id = msg[
                "sticker"
            ]["file_id"]

            descricao = (
                analisar_midia_com_gemini(
                    file_id,
                    "sticker"
                )
            )

            if descricao:

                user_text = (
                    "[Usuário enviou um "
                    f"sticker. Conteúdo: "
                    f"{descricao}]"
                )

            else:

                user_text = (
                    "[Usuário enviou um sticker]"
                )


        # ==================================================
        # GIF / ANIMATION
        # ==================================================

        elif "animation" in msg:

            file_id = msg[
                "animation"
            ]["file_id"]

            descricao = (
                analisar_midia_com_gemini(
                    file_id,
                    "gif"
                )
            )

            if descricao:

                user_text = (
                    "[Usuário enviou um GIF. "
                    f"Conteúdo: {descricao}]"
                )

            else:

                user_text = (
                    "[Usuário enviou um GIF]"
                )


        # ==================================================
        # GIF ENVIADO COMO DOCUMENTO
        # ==================================================

        elif (
            "document" in msg
            and msg["document"].get(
                "mime_type"
            ) == "image/gif"
        ):

            file_id = msg[
                "document"
            ]["file_id"]

            descricao = (
                analisar_midia_com_gemini(
                    file_id,
                    "gif"
                )
            )

            if descricao:

                user_text = (
                    "[Usuário enviou um GIF. "
                    f"Conteúdo: {descricao}]"
                )

            else:

                user_text = (
                    "[Usuário enviou um GIF]"
                )


        # ==================================================
        # MENSAGEM VAZIA
        # ==================================================

        if not user_text.strip():
            return


        texto_lower = (
            user_text.lower().strip()
        )


        # ==================================================
        # CHAMADA PELO NOME NO GRUPO - NOVO
        # ==================================================
        
        bot_foi_chamado = False
        
        if chat_type in ["group", "supergroup"]:
            if (
                BOT_NAME.lower() in texto_lower 
                or BOT_USERNAME.lower() in texto_lower
                or f"@{BOT_USERNAME.lower()}" in texto_lower
            ):
                bot_foi_chamado = True
                # remove o nome da mensagem pra IA não se confundir
                user_text = re.sub(
                    rf"{BOT_NAME}|@{BOT_USERNAME}", 
                    "", 
                    user_text, 
                    flags=re.IGNORECASE
                ).strip()
                
                if not user_text:
                    user_text = "oi"
                    
                texto_lower = user_text.lower().strip()


        # ==================================================
        # COMANDOS
        # ==================================================

        if re.match(
            r"^/\w+",
            texto_lower
        ) or bot_foi_chamado:

            executado = handle_command(
                chat_id,
                user_id,
                texto_lower,
                message_id,
                send_message,
                get_supabase_usage,
            )

            if executado:
                return


        # ==================================================
        # SAUDAÇÃO
        # ==================================================

        saudacoes = [
            "oi",
            "ola",
            "olá",
            "bom dia",
            "boa tarde",
            "boa noite",
            "eai",
            "fala"
        ]

        eh_saudacao = (
            any(
                texto_lower.startswith(s)
                for s in saudacoes
            )
            and len(texto_lower.split()) < 4
        )

        # Se foi chamado no grupo OU é saudação, responde
        if eh_saudacao or bot_foi_chamado:
            responder_saudacao(
                chat_id,
                message_id,
                send_message
            )
            return

        # ==================================================
        # SALVAR MENSAGEM
        # ==================================================

        save_message(
            user_id,
            chat_id,
            chat_type,
            chat_title,
            "user",
            user_text
        )


        # ==================================================
        # MEMÓRIA
        # ==================================================

        save_memory(
            user_id,
            chat_id,
            "user",
            user_text
        )


        # ==================================================
        # EXTRAÇÃO AUTOMÁTICA
        # ==================================================

        extrair_dados_automaticos(
            user_id,
            user_text
        )


        # ==================================================
        # CATEGORIA
        # ==================================================

        categoria = "conversa"

        mapa = {
            "nome": "nome",
            "apelido": "apelido",
            "me chama": "apelido",
            "moro": "cidade",
            "cidade": "cidade",
            "trabalho": "profissao",
            "profissao": "profissao",
            "profissão": "profissao",
            "gosto": "gosto",
            "favorito": "comida",
            "comida": "comida",
        }

        for palavra, cat in mapa.items():

            if palavra in texto_lower:

                categoria = cat
                break


        # ==================================================
        # CONTEXTO
        # ==================================================

        contexto = montar_contexto(
            user_id,
            chat_id,
            chat_type,
            chat_title
        )


        # ==================================================
        # IA
        # ==================================================

        resposta = call_ai_smart(
            user_text,
            contexto,
            categoria
        )


        # ==================================================
        # RESPOSTA
        # ==================================================

        enviar_resposta(
            chat_id,
            resposta,
            message_id,
            send_message
        )


    except Exception as e:

        logging.exception(
            f"[PROCESS ERROR] {e}"
        )


# ==========================================================
# WEBHOOK
# ==========================================================

@app.route(
    f"/{TELEGRAM_TOKEN}",
    methods=["POST"]
)
def webhook():

    data = request.get_json(
        silent=True
    )

    if not data:
        return "ok"


    # ======================================================
    # DELEGAR PARA WEBHOOK.PY
    # ======================================================

    return processar_webhook(
        data,
        process_message
    )


# ==========================================================
# HEALTH CHECK
# ==========================================================

@app.route("/health")
def health():

    return "ok", 200


# ==========================================================
# EXECUÇÃO LOCAL
# ==========================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "8080"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
                )
