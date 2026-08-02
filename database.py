import logging
import time
from datetime import datetime, timezone, timedelta

from supabase import create_client, Client

from config import (
    SUPABASE_URL,
    SUPABASE_KEY,
    BOT_TAG,
    CACHE_TIMEOUTS,
)


# ==========================================================
# SUPABASE
# ==========================================================

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)


# ==========================================================
# CACHE
# ==========================================================

CACHE_PROFILE = {}
CACHE_RESPONSE = {}
CACHE_SEARCH = {}
CACHE_SUMMARY = {}


# ==========================================================
# FUNÇÕES DE CACHE
# ==========================================================

def get_from_cache(cache, key, timeout_name):
    if key not in cache:
        return None

    data, timestamp = cache[key]

    if datetime.now() - timestamp < timedelta(
        seconds=CACHE_TIMEOUTS[timeout_name]
    ):
        return data

    cache.pop(key, None)
    return None


def set_cache(cache, key, data):
    cache[key] = (data, datetime.now())


def invalidate_cache(user_id, chat_id):
    CACHE_PROFILE.pop(user_id, None)

    keys_to_delete = [
        key
        for key in CACHE_RESPONSE
        if key.startswith(f"{user_id}_")
    ]

    for key in keys_to_delete:
        CACHE_RESPONSE.pop(key, None)


# ==========================================================
# RETRY DO SUPABASE
# ==========================================================

def call_db_with_retry(func, *args, retries=3, **kwargs):
    for tentativa in range(retries):
        try:
            return func(*args, **kwargs)

        except Exception as e:
            logging.exception(
                f"[SUPABASE ERROR] "
                f"Tentativa {tentativa + 1}: {e}"
            )

            if tentativa == retries - 1:
                raise

            time.sleep(0.5 * (2 ** tentativa))


# ==========================================================
# PERFIL DO USUÁRIO
# ==========================================================

def get_user_profile(user_id):
    cached = get_from_cache(
        CACHE_PROFILE,
        user_id,
        "profile"
    )

    if cached is not None:
        return cached

    resultado = call_db_with_retry(
        lambda: supabase
        .table("user_profiles")
        .select("*")
        .eq("bot_id", BOT_TAG)
        .eq("user_id", str(user_id))
        .limit(1)
        .execute()
    )

    profile = (
        resultado.data[0]
        if resultado.data
        else {}
    )

    set_cache(
        CACHE_PROFILE,
        user_id,
        profile
    )

    return profile


def save_user_profile(user_id, novos_dados):
    perfil_antigo = get_user_profile(user_id) or {}

    historico = perfil_antigo.get(
        "historico",
        {}
    )

    for chave, valor in novos_dados.items():

        if (
            chave in perfil_antigo
            and perfil_antigo.get(chave)
            and perfil_antigo[chave] != valor
        ):
            historico.setdefault(
                chave,
                []
            ).append({
                "de": perfil_antigo[chave],
                "para": valor,
                "data": datetime.now(
                    timezone.utc
                ).isoformat()
            })

    dados = {
        **perfil_antigo,
        **novos_dados,
        "historico": historico,
        "bot_id": BOT_TAG,
        "user_id": str(user_id),
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    call_db_with_retry(
        lambda: supabase
        .table("user_profiles")
        .upsert(
            dados,
            on_conflict="bot_id,user_id"
        )
        .execute()
    )

    set_cache(
        CACHE_PROFILE,
        user_id,
        dados
    )


# ==========================================================
# HISTÓRICO DE CHAT
# ==========================================================

def save_message(
    user_id,
    chat_id,
    chat_type,
    chat_title,
    role,
    content,
    content_hash_func
):
    if role == "user":

        content_hash = content_hash_func(
            content
        )

        cinco_minutos_atras = (
            datetime.now(timezone.utc)
            - timedelta(minutes=5)
        )

        existente = call_db_with_retry(
            lambda: supabase
            .table("chat_history")
            .select("id")
            .eq("bot_id", BOT_TAG)
            .eq("user_id", str(user_id))
            .eq("chat_id", str(chat_id))
            .eq("role", role)
            .eq("content_hash", content_hash)
            .gte(
                "created_at",
                cinco_minutos_atras.isoformat()
            )
            .limit(1)
            .execute()
        )

        if existente.data:
            logging.info(
                f"[DUPLICADO IGNORADO] "
                f"{content[:30]}"
            )
            return

    payload = {
        "bot_id": BOT_TAG,
        "user_id": str(user_id),
        "chat_id": str(chat_id),
        "chat_type": chat_type,
        "chat_title": chat_title,
        "role": role,
        "content": content[:500],
        "content_hash": content_hash_func(content),
        "created_at": datetime.now(
            timezone.utc
        ).isoformat()
    }

    call_db_with_retry(
        lambda: supabase
        .table("chat_history")
        .insert(payload)
        .execute()
    )


# ==========================================================
# LIMPEZA DE MEMÓRIA
# ==========================================================

def auto_limpar_memoria(user_id):

    limite_temporaria = (
        datetime.now(timezone.utc)
        - timedelta(days=7)
    )

    limite_importante = (
        datetime.now(timezone.utc)
        - timedelta(days=90)
    )

    call_db_with_retry(
        lambda: supabase
        .table("memories")
        .delete()
        .eq("user_id", str(user_id))
        .eq("tipo", "temporaria")
        .lt(
            "created_at",
            limite_temporaria.isoformat()
        )
        .execute()
    )

    call_db_with_retry(
        lambda: supabase
        .table("memories")
        .delete()
        .eq("user_id", str(user_id))
        .eq("tipo", "importante")
        .lt(
            "last_used",
            limite_importante.isoformat()
        )
        .execute()
    )


# ==========================================================
# DADOS DO USUÁRIO
# ==========================================================

def buscar_dados_usuario(
    user_id,
    categoria,
    buscar_memoria_func
):
    dados = {}

    profile = get_user_profile(user_id)

    if categoria in profile and profile[categoria]:

        dados["fonte"] = "perfil"
        dados["valor"] = profile[categoria]

        return dados

    mems = buscar_memoria_func(
        categoria,
        user_id
    )

    if mems:
        dados["fonte"] = "memoria"
        dados["valor"] = mems[:3]

        return dados

    return None


# ==========================================================
# LIMPAR DADOS DE UM USUÁRIO
# ==========================================================

def limpar_dados_usuario(user_id):

    call_db_with_retry(
        lambda: supabase
        .table("memories")
        .delete()
        .eq("bot_id", BOT_TAG)
        .eq("user_id", str(user_id))
        .execute()
    )

    call_db_with_retry(
        lambda: supabase
        .table("user_profiles")
        .delete()
        .eq("bot_id", BOT_TAG)
        .eq("user_id", str(user_id))
        .execute()
    )

    invalidate_cache(
        user_id,
        ""
    )

    return (
        f"✅ Dados do usuário "
        f"`{user_id}` apagados."
    )


# ==========================================================
# RESETAR BANCO
# ==========================================================

def resetar_banco():

    call_db_with_retry(
        lambda: supabase
        .table("memories")
        .delete()
        .eq("bot_id", BOT_TAG)
        .execute()
    )

    call_db_with_retry(
        lambda: supabase
        .table("user_profiles")
        .delete()
        .eq("bot_id", BOT_TAG)
        .execute()
    )

    CACHE_PROFILE.clear()
    CACHE_RESPONSE.clear()
    CACHE_SEARCH.clear()
    CACHE_SUMMARY.clear()

    return "⚠️ Banco resetado."
