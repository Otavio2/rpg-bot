import base64
import logging
import requests

from config import (
    TELEGRAM_API_URL,
    TELEGRAM_TOKEN,
    GEMINI_API_KEYS,
    GEMINI_MODEL,
    TIMEOUT_API,
)


# ==========================================================
# SESSÃO HTTP
# ==========================================================

session = requests.Session()


# ==========================================================
# CONTROLE DA CHAVE GEMINI
# ==========================================================

gemini_key_index = 0


# ==========================================================
# BAIXAR ARQUIVO DO TELEGRAM
# ==========================================================

def baixar_arquivo_telegram(file_id):
    try:
        resposta = session.get(
            f"{TELEGRAM_API_URL}/getFile",
            params={"file_id": file_id},
            timeout=TIMEOUT_API
        )

        resposta.raise_for_status()

        dados = resposta.json()

        if not dados.get("ok"):
            return None

        file_path = dados["result"]["file_path"]

        arquivo = session.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}",
            timeout=TIMEOUT_API
        )

        arquivo.raise_for_status()

        return arquivo.content

    except Exception as e:
        logging.exception(
            f"[MEDIA DOWNLOAD ERROR] {e}"
        )
        return None


# ==========================================================
# ANALISAR STICKER / GIF COM GEMINI
# ==========================================================

def analisar_midia_com_gemini(
    file_id,
    tipo
):
    global gemini_key_index

    if not GEMINI_API_KEYS:
        logging.warning(
            "[MEDIA] Nenhuma chave Gemini configurada."
        )
        return None

    try:

        arquivo = baixar_arquivo_telegram(
            file_id
        )

        if not arquivo:
            return None

        # --------------------------------------------------
        # Escolher chave Gemini
        # --------------------------------------------------

        key = GEMINI_API_KEYS[
            gemini_key_index
        ]

        gemini_key_index = (
            gemini_key_index + 1
        ) % len(GEMINI_API_KEYS)

        # --------------------------------------------------
        # Tipo do arquivo
        # --------------------------------------------------

        if tipo == "sticker":
            mime_type = "image/webp"

        elif tipo == "gif":
            mime_type = "image/gif"

        else:
            mime_type = "application/octet-stream"

        # --------------------------------------------------
        # Prompt
        # --------------------------------------------------

        prompt = (
            f"Descreva esse {tipo} "
            "em uma frase curta e engraçada, "
            "estilo brasileiro. "
            "Máximo de 20 palavras."
        )

        # --------------------------------------------------
        # Payload Gemini
        # --------------------------------------------------

        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt
                        },
                        {
                            "inline_data": {
                                "mime_type": mime_type,
                                "data": base64.b64encode(
                                    arquivo
                                ).decode("utf-8")
                            }
                        }
                    ]
                }
            ]
        }

        url = (
            "https://generativelanguage.googleapis.com"
            f"/v1beta/models/{GEMINI_MODEL}"
            f":generateContent?key={key}"
        )

        resposta = session.post(
            url,
            json=payload,
            timeout=TIMEOUT_API
        )

        if resposta.status_code != 200:
            logging.warning(
                f"[MEDIA GEMINI] "
                f"HTTP {resposta.status_code}: "
                f"{resposta.text[:300]}"
            )
            return None

        dados = resposta.json()

        candidatos = dados.get(
            "candidates",
            []
        )

        if not candidatos:
            return None

        partes = candidatos[0].get(
            "content",
            {}
        ).get(
            "parts",
            []
        )

        if not partes:
            return None

        texto = partes[0].get(
            "text"
        )

        return texto.strip() if texto else None

    except Exception as e:

        logging.exception(
            f"[VISION ERROR] {e}"
        )

        return None


# ==========================================================
# IDENTIFICAR MÍDIA RECEBIDA
# ==========================================================

def extrair_midia(msg):

    # ------------------------------------------------------
    # STICKER
    # ------------------------------------------------------

    if "sticker" in msg:

        sticker = msg["sticker"]

        return {
            "tipo": "sticker",
            "file_id": sticker["file_id"]
        }

    # ------------------------------------------------------
    # GIF / ANIMATION
    # ------------------------------------------------------

    if "animation" in msg:

        animation = msg["animation"]

        return {
            "tipo": "gif",
            "file_id": animation["file_id"]
        }

    # ------------------------------------------------------
    # GIF ENVIADO COMO DOCUMENTO
    # ------------------------------------------------------

    if "document" in msg:

        document = msg["document"]

        mime_type = document.get(
            "mime_type",
            ""
        ).lower()

        if mime_type == "image/gif":

            return {
                "tipo": "gif",
                "file_id": document["file_id"]
            }

    return None


# ==========================================================
# TRANSFORMAR MÍDIA EM TEXTO PARA A IA
# ==========================================================

def interpretar_midia(msg):

    midia = extrair_midia(msg)

    if not midia:
        return None

    tipo = midia["tipo"]
    file_id = midia["file_id"]

    descricao = analisar_midia_com_gemini(
        file_id,
        tipo
    )

    if descricao:

        return (
            f"[usuário enviou um {tipo}: "
            f"{descricao}]"
        )

    return (
        f"[usuário enviou um {tipo}]"
      )
