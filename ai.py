import json
import logging

import requests

from config import (
    BOT_NAME,
    GEMINI_API_KEYS,
    GEMINI_MODEL,
    GROQ_API_KEYS,
    GROQ_API_URL,
    GROQ_MODEL,
    TIMEOUT_API,
)

from database import (
    save_user_profile,
    save_message,
    buscar_dados_usuario,
)


# ==========================================================
# SESSÃO HTTP
# ==========================================================

session = requests.Session()


# ==========================================================
# CONTROLE DAS CHAVES
# ==========================================================

gemini_key_index = 0
GROQ_BLACKLIST = {}


# ==========================================================
# GEMINI
# ==========================================================

def call_gemini_rotacao(prompt):
    global gemini_key_index

    if not GEMINI_API_KEYS:
        logging.warning(
            "[GEMINI] Nenhuma chave configurada."
        )
        return None

    for _ in range(len(GEMINI_API_KEYS)):

        key = GEMINI_API_KEYS[gemini_key_index]

        gemini_key_index = (
            gemini_key_index + 1
        ) % len(GEMINI_API_KEYS)

        try:

            url = (
                "https://generativelanguage.googleapis.com"
                f"/v1beta/models/{GEMINI_MODEL}"
                f":generateContent?key={key}"
            )

            payload = {
                "contents": [
                    {
                        "parts": [
                            {
                                "text": prompt
                            }
                        ]
                    }
                ]
            }

            response = session.post(
                url,
                json=payload,
                timeout=TIMEOUT_API
            )

            if response.status_code == 200:

                data = response.json()

                return (
                    data["candidates"][0]
                    ["content"]["parts"][0]["text"]
                )

            logging.warning(
                f"[GEMINI] HTTP {response.status_code}"
            )

        except Exception as e:

            logging.exception(
                f"[GEMINI ERROR] {e}"
            )

    return None


# ==========================================================
# GROQ
# ==========================================================

def call_groq_multi(messages):

    global GROQ_BLACKLIST

    if not GROQ_API_KEYS:
        logging.warning(
            "[GROQ] Nenhuma chave configurada."
        )
        return None

    from datetime import datetime, timedelta

    agora = datetime.now()

    GROQ_BLACKLIST = {
        key: validade
        for key, validade in GROQ_BLACKLIST.items()
        if validade > agora
    }

    chaves_disponiveis = [
        key
        for key in GROQ_API_KEYS
        if key not in GROQ_BLACKLIST
    ]

    for key in chaves_disponiveis:

        try:

            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": GROQ_MODEL,
                "messages": messages,
                "max_tokens": 150
            }

            response = session.post(
                GROQ_API_URL,
                headers=headers,
                json=payload,
                timeout=TIMEOUT_API
            )

            if response.status_code == 200:

                data = response.json()

                return (
                    data["choices"][0]
                    ["message"]["content"]
                )

            if response.status_code in [
                401,
                403,
                429
            ]:

                GROQ_BLACKLIST[key] = (
                    agora + timedelta(minutes=10)
                )

                logging.warning(
                    f"[GROQ] Chave temporariamente bloqueada: "
                    f"HTTP {response.status_code}"
                )

        except Exception as e:

            logging.exception(
                f"[GROQ ERROR] {e}"
            )

    return None


# ==========================================================
# REESCREVER RESPOSTA
# ==========================================================

def reescrever_com_ia(
    dados_encontrados,
    pergunta
):

    prompt = f"""
Você é {BOT_NAME}.

Seja zoeiro, humano e direto.
Use gírias brasileiras leves.
Responda no máximo em 2 linhas.

Dados encontrados:
{json.dumps(
    dados_encontrados,
    ensure_ascii=False
)}

Pergunta:
{pergunta}
"""

    resposta = call_groq_multi([
        {
            "role": "user",
            "content": prompt
        }
    ])

    if resposta:
        return resposta

    return call_gemini_rotacao(
        prompt
    )


# ==========================================================
# EXTRAÇÃO AUTOMÁTICA DE DADOS
# ==========================================================

def extrair_dados_automaticos(
    user_id,
    texto
):

    gatilhos = [
        "meu nome",
        "me chama",
        "moro",
        "cidade",
        "trabalho",
        "profissao",
        "profissão",
        "gosto"
    ]

    texto_lower = texto.lower()

    if not any(
        gatilho in texto_lower
        for gatilho in gatilhos
    ):
        return

    prompt = f"""
Extraia somente um JSON válido.

Campos permitidos:
nome
apelido
cidade
profissao
comida
gostos

Se alguma informação não existir,
não invente.

Texto:
{texto}
"""

    json_str = call_groq_multi([
        {
            "role": "user",
            "content": prompt
        }
    ])

    if not json_str:
        return

    if "{" not in json_str:
        return

    try:

        inicio = json_str.find("{")
        fim = json_str.rfind("}")

        dados = json.loads(
            json_str[inicio:fim + 1]
        )

        dados_validos = {
            chave: valor
            for chave, valor in dados.items()
            if valor
        }

        if dados_validos:
            save_user_profile(
                user_id,
                dados_validos
            )

    except Exception as e:

        logging.warning(
            f"[EXTRAÇÃO] JSON inválido: {e}"
        )


# ==========================================================
# IA PRINCIPAL
# ==========================================================

def call_ai_smart(
    pergunta,
    contexto,
    categoria
):

    dados = buscar_dados_usuario(
        contexto["user_id"],
        categoria,
        contexto["buscar_memoria_func"]
    )

    # ======================================================
    # SE ENCONTROU DADOS NA MEMÓRIA
    # ======================================================

    if dados:

        resposta = reescrever_com_ia(
            dados,
            pergunta
        )

        if not resposta:
            resposta = str(
                dados["valor"]
            )

        save_message(
            contexto["user_id"],
            contexto["chat_id"],
            contexto["chat_type"],
            contexto["chat_title"],
            "assistant",
            resposta,
            contexto["content_hash_func"]
        )

        return resposta

    # ======================================================
    # IA NORMAL
    # ======================================================

    messages = [
        {
            "role": "system",
            "content": contexto["prompt"]
        },
        {
            "role": "user",
            "content": pergunta
        }
    ]

    resposta = call_groq_multi(
        messages
    )

    # ======================================================
    # FALLBACK GEMINI
    # ======================================================

    if not resposta:

        resposta = call_gemini_rotacao(
            contexto["prompt"]
            + "\nPergunta: "
            + pergunta
        )

    # ======================================================
    # SEM RESPOSTA
    # ======================================================

    if not resposta:
        return "Não sei ainda, me conta?"

    # ======================================================
    # SALVAR RESPOSTA
    # ======================================================

    save_message(
        contexto["user_id"],
        contexto["chat_id"],
        contexto["chat_type"],
        contexto["chat_title"],
        "assistant",
        resposta,
        contexto["content_hash_func"]
    )

    return resposta
