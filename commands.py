import logging

from config import BOT_NAME, ADMINS
from database import (
    limpar_dados_usuario,
    resetar_banco,
)


# ==========================================================
# VERIFICAR ADMIN
# ==========================================================

def is_admin(user_id):
    return str(user_id) in [
        str(admin)
        for admin in ADMINS
    ]


# ==========================================================
# COMANDOS
# ==========================================================

def handle_command(
    chat_id,
    user_id,
    command,
    message_id,
    send_message_func,
    get_supabase_usage_func,
):
    try:

        user_id_str = str(user_id)

        partes = command.strip().split()

        if not partes:
            return True

        cmd = partes[0].lower()


        # ==================================================
        # /start
        # ==================================================

        if cmd == "/start":

            send_message_func(
                chat_id,
                f"Olá! Eu sou o {BOT_NAME}.",
                reply_to=message_id
            )

            return True


        # ==================================================
        # /help
        # ==================================================

        if cmd == "/help":

            texto = (
                "📚 *Comandos públicos:*\n"
                "/start\n"
                "/help\n"
                "/ping\n\n"
                "🔐 *Comandos administrativos:*\n"
                "/status\n"
                "/limpar\n"
                "/resetar"
            )

            send_message_func(
                chat_id,
                texto,
                reply_to=message_id
            )

            return True


        # ==================================================
        # /ping
        # ==================================================

        if cmd == "/ping":

            send_message_func(
                chat_id,
                "Pong! 🏓",
                reply_to=message_id
            )

            return True


        # ==================================================
        # PROTEÇÃO DOS COMANDOS ADMINISTRATIVOS
        # ==================================================

        if not is_admin(user_id_str):

            send_message_func(
                chat_id,
                "❌ Sem permissão.",
                reply_to=message_id
            )

            return True


        # ==================================================
        # /status
        # ==================================================

        if cmd == "/status":

            resposta = get_supabase_usage_func()

            send_message_func(
                chat_id,
                resposta,
                reply_to=message_id
            )

            return True


        # ==================================================
        # /limpar
        # ==================================================

        if cmd == "/limpar":

            if len(partes) < 2:

                send_message_func(
                    chat_id,
                    "Uso: `/limpar user_id`",
                    reply_to=message_id
                )

                return True


            alvo = partes[1]

            resposta = limpar_dados_usuario(
                alvo
            )

            send_message_func(
                chat_id,
                resposta,
                reply_to=message_id
            )

            return True


        # ==================================================
        # /resetar
        # ==================================================

        if cmd == "/resetar":

            resposta = resetar_banco()

            send_message_func(
                chat_id,
                resposta,
                reply_to=message_id
            )

            return True


        # ==================================================
        # COMANDO DESCONHECIDO
        # ==================================================

        return False


    except Exception as e:

        logging.exception(
            f"[COMMAND ERROR] {e}"
        )

        return True
