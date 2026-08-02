import logging
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor

from config import BOT_ID, BOT_NAME, BOT_USERNAME


# ==========================================================
# CONTROLE DE UPDATES
# ==========================================================

PROCESSED_UPDATES = deque(maxlen=1000)

executor = ThreadPoolExecutor(max_workers=10)


# ==========================================================
# VERIFICAR SE O BOT FOI MENCIONADO
# ==========================================================

def verificar_mencao(msg):
    user_text = msg.get("text", "").lower()

    # ------------------------------------------------------
    # Entidades do Telegram
    # ------------------------------------------------------

    if "entities" in msg:

        for entity in msg["entities"]:

            if entity.get("type") in [
                "mention",
                "text_mention"
            ]:
                return True


    # ------------------------------------------------------
    # @username ou nome do bot
    # ------------------------------------------------------

    if BOT_USERNAME:

        if f"@{BOT_USERNAME.lower()}" in user_text:
            return True


    if BOT_NAME:

        if re.search(
            rf"\b{re.escape(BOT_NAME.lower())}\b",
            user_text
        ):
            return True


    return False


# ==========================================================
# VERIFICAR SE É RESPOSTA AO BOT
# ==========================================================

def responder_ao_bot(msg):

    reply = msg.get("reply_to_message")

    if not reply:
        return False

    remetente = reply.get("from", {})

    bot_id = remetente.get("id")

    if BOT_ID is not None:

        return bot_id == BOT_ID

    return False


# ==========================================================
# DECIDIR SE O BOT DEVE RESPONDER
# ==========================================================

def deve_responder(msg):

    chat = msg.get("chat", {})

    chat_type = chat.get("type")

    # ------------------------------------------------------
    # Conversa privada
    # ------------------------------------------------------

    if chat_type == "private":
        return True


    # ------------------------------------------------------
    # Grupo / supergrupo
    # ------------------------------------------------------

    if verificar_mencao(msg):
        return True


    # ------------------------------------------------------
    # Usuário respondeu uma mensagem do bot
    # ------------------------------------------------------

    if responder_ao_bot(msg):
        return True


    return False


# ==========================================================
# WEBHOOK
# ==========================================================

def processar_webhook(
    data,
    process_message_func
):

    try:

        if not data:
            return "ok"


        # --------------------------------------------------
        # EVITAR DUPLICAÇÃO
        # --------------------------------------------------

        update_id = data.get("update_id")

        if update_id in PROCESSED_UPDATES:
            return "ok"

        if update_id is not None:
            PROCESSED_UPDATES.append(update_id)


        # --------------------------------------------------
        # PEGAR MENSAGEM
        # --------------------------------------------------

        msg = (
            data.get("message")
            or data.get("edited_message")
        )

        if not msg:
            return "ok"


        # --------------------------------------------------
        # DECIDIR SE RESPONDE
        # --------------------------------------------------

        if not deve_responder(msg):
            return "ok"


        # --------------------------------------------------
        # PROCESSAR EM SEGUNDO PLANO
        # --------------------------------------------------

        executor.submit(
            process_message_func,
            msg
        )


        return "ok"


    except Exception as e:

        logging.exception(
            f"[WEBHOOK ERROR] {e}"
        )

        return "ok"
