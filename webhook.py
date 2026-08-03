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
# WEBHOOK - SÓ ENTREGA, NÃO DECIDE
# ==========================================================

def processar_webhook(
    data,
    process_message_func
):

    try:

        if not data:
            return "ok"

        # --------------------------------------------------
        # 1. EVITAR DUPLICAÇÃO
        # --------------------------------------------------

        update_id = data.get("update_id")

        if update_id in PROCESSED_UPDATES:
            logging.info(f"[WEBHOOK] Update duplicado: {update_id}")
            return "ok"

        if update_id is not None:
            PROCESSED_UPDATES.append(update_id)

        # --------------------------------------------------
        # 2. PEGAR MENSAGEM OU EVENTO
        # --------------------------------------------------

        msg = (
            data.get("message")
            or data.get("edited_message")
        )

        # Se não for mensagem de texto, verifica se é new_chat_members
        if not msg:
            # Pode ser callback, etc. Por enquanto ignora
            return "ok"

        # Log pra debug
        chat = msg.get("chat", {})
        chat_type = chat.get("type", "unknown")
        user = msg.get("from", {}).get("first_name", "Anon")

        logging.info(f"[WEBHOOK] Recebido de {user} em {chat_type}: {msg.get('text', '[midia]')[:50]}")

        # --------------------------------------------------
        # 3. ENTREGAR TUDO PRO MAIN.PY DECIDIR
        # --------------------------------------------------
        # O main.py agora decide se é menção, saudação, grupo, etc.
        # Assim não perdemos: new_chat_members, saudações, etc.

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
