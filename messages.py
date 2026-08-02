import logging


# ==========================================================
# SAUDAÇÕES
# ==========================================================

def responder_saudacao(
    chat_id,
    message_id,
    send_message_func
):
    try:

        send_message_func(
            chat_id,
            "Olá! Como posso te ajudar?",
            reply_to=message_id
        )

        return True

    except Exception as e:

        logging.exception(
            f"[SAUDACAO ERROR] {e}"
        )

        return False


# ==========================================================
# RESPOSTA PADRÃO
# ==========================================================

def enviar_resposta(
    chat_id,
    resposta,
    message_id,
    send_message_func
):
    try:

        if not resposta:
            return False

        send_message_func(
            chat_id,
            resposta,
            reply_to=message_id
        )

        return True

    except Exception as e:

        logging.exception(
            f"[MESSAGE ERROR] {e}"
        )

        return False
