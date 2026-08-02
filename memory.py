import re
import hashlib
from datetime import datetime, timezone

from config import (
    BOT_TAG,
    PESO_CATEGORIA,
    SAUDACOES,
    MAPA_ASSUNTO,
)

from database import (
    supabase,
    call_db_with_retry,
    invalidate_cache,
    get_from_cache,
    set_cache,
)


# ==========================================================
# HASH DO CONTEÚDO
# ==========================================================

def get_content_hash(content):
    texto = re.sub(
        r"[^\w\s]",
        "",
        content.lower()
    )

    texto = re.sub(
        r"\s+",
        " ",
        texto
    ).strip()

    return hashlib.md5(
        texto.encode()
    ).hexdigest()


# ==========================================================
# CLASSIFICAR MEMÓRIA
# ==========================================================

def classificar_memoria(texto):

    texto = texto.lower().strip()

    # Comandos não entram na memória
    if re.match(r"^/\w+", texto):
        return "ignorar", "comando", 0

    # Saudações não entram na memória
    if any(
        saudacao in texto
        for saudacao in SAUDACOES
    ):
        return "ignorar", "saudacao", 0

    categoria = "geral"

    for palavra, cat in MAPA_ASSUNTO.items():

        if palavra in texto:
            categoria = cat
            break

    peso = PESO_CATEGORIA.get(
        categoria,
        10
    )

    if categoria in [
        "nome",
        "apelido",
        "cidade",
        "profissao"
    ]:
        return "permanente", categoria, peso

    if categoria in [
        "comida",
        "gosto",
        "objetivo",
        "projeto"
    ]:
        return "importante", categoria, peso

    return "temporaria", categoria, peso


# ==========================================================
# SALVAR MEMÓRIA
# ==========================================================

def save_memory(
    target_id,
    chat_id,
    role,
    content,
    is_permanent=False
):

    if len(content) > 500:
        content = content[:497] + "..."

    tipo, categoria, peso = classificar_memoria(
        content
    )

    # Não salva coisas irrelevantes
    if tipo == "ignorar":
        return

    # Não salva respostas do próprio bot
    if role == "assistant":
        return

    # Perguntas não são consideradas memória
    if content.endswith("?"):
        return

    # Memória permanente solicitada
    if is_permanent:
        tipo = "permanente"
        peso = 100

    content_hash = get_content_hash(
        content
    )

    # ======================================================
    # VERIFICAR SE JÁ EXISTE
    # ======================================================

    existente = call_db_with_retry(
        lambda: supabase
        .table("memories")
        .select("id, used_count")
        .eq("bot_id", BOT_TAG)
        .eq("user_id", str(target_id))
        .eq("categoria", categoria)
        .eq("content_hash", content_hash)
        .limit(1)
        .execute()
    )

    # ======================================================
    # MEMÓRIA JÁ EXISTENTE
    # ======================================================

    if existente.data:

        usado = existente.data[0].get(
            "used_count",
            0
        )

        call_db_with_retry(
            lambda: supabase
            .table("memories")
            .update({
                "used_count": usado + 1,
                "peso": peso,
                "last_used": datetime.now(
                    timezone.utc
                ).isoformat()
            })
            .eq(
                "bot_id",
                BOT_TAG
            )
            .eq(
                "id",
                existente.data[0]["id"]
            )
            .execute()
        )

        return

    # ======================================================
    # NOVA MEMÓRIA
    # ======================================================

    payload = {
        "bot_id": BOT_TAG,
        "user_id": str(target_id),
        "chat_id": str(chat_id),
        "role": role,
        "content": content,
        "content_hash": content_hash,
        "tipo": tipo,
        "categoria": categoria,
        "peso": peso,
        "used_count": 1,
        "last_used": datetime.now(
            timezone.utc
        ).isoformat(),
        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    call_db_with_retry(
        lambda: supabase
        .table("memories")
        .insert(payload)
        .execute()
    )

    invalidate_cache(
        target_id,
        chat_id
    )


# ==========================================================
# BUSCAR MEMÓRIA POR CATEGORIA
# ==========================================================

def buscar_memoria_por_categoria(
    categoria,
    user_id
):

    if (
        not categoria
        or categoria == "conversa"
    ):
        return []

    resultado = call_db_with_retry(
        lambda: supabase
        .table("memories")
        .select("*")
        .eq("bot_id", BOT_TAG)
        .eq("user_id", str(user_id))
        .eq("categoria", categoria)
        .order(
            "peso",
            desc=True
        )
        .order(
            "used_count",
            desc=True
        )
        .limit(3)
        .execute()
    )

    if not resultado.data:
        return []

    return [
        memoria["content"]
        for memoria in resultado.data
    ]


# ==========================================================
# CARREGAR MEMÓRIAS PERMANENTES
# ==========================================================

def get_memory(user_id, chat_id):

    cache_key = (
        f"{user_id}_{chat_id}"
    )

    cached = get_from_cache(
        # O cache de memória fica no database.py
        # nesta versão usamos somente consulta direta
        {},
        cache_key,
        "memory"
    )

    # ======================================================
    # BUSCAR MEMÓRIAS PERMANENTES
    # ======================================================

    resultado = call_db_with_retry(
        lambda: supabase
        .table("memories")
        .select("*")
        .eq("bot_id", BOT_TAG)
        .eq("user_id", str(user_id))
        .eq("tipo", "permanente")
        .order(
            "peso",
            desc=True
        )
        .limit(5)
        .execute()
    )

    if not resultado.data:
        return []

    return [
        {
            "role": memoria["role"],
            "content": memoria["content"],
            "peso": memoria["peso"],
            "tipo": memoria["tipo"]
        }
        for memoria in resultado.data
    ]
