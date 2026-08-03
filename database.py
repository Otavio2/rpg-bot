import os
import logging
from supabase import create_client
from datetime import datetime

from config import BOT_ID_DATABASE

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")

supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
BOT_ID = BOT_ID_DATABASE or "matheus"

CAMPOS_VALIDOS = ["nome", "apelido", "cidade", "profissao", "comida", "gostos"]

def save_message(user_id, chat_id, chat_type, chat_title, role, content, bot_id=BOT_ID):
    try:
        supabase.table("chat_history").insert({
            "user_id": str(user_id), "bot_id": bot_id, "chat_id": str(chat_id),
            "chat_type": chat_type, "chat_title": chat_title, "role": role,
            "content": content, "created_at": datetime.utcnow().isoformat()
        }).execute()
    except Exception as e:
        logging.error(f"[SAVE MESSAGE ERROR] {e}")

def save_memory(user_id, categoria, valor, bot_id=BOT_ID):
    """Só salva se categoria for válida"""
    if categoria not in CAMPOS_VALIDOS:
        logging.warning(f"[SAVE MEMORY] Categoria inválida: {categoria}")
        return
    try:
        # Upsert: se já existir categoria pra esse user, atualiza
        supabase.table("memory").upsert({
            "user_id": str(user_id), "bot_id": bot_id, "categoria": categoria,
            "valor": valor, "updated_at": datetime.utcnow().isoformat()
        }, on_conflict="user_id,bot_id,categoria").execute()
        logging.info(f"[SAVE MEMORY] user={user_id} {categoria}={valor}")
    except Exception as e:
        logging.error(f"[SAVE MEMORY ERROR] {e}")

def save_user_profile(user_id, data, bot_id=BOT_ID):
    try:
        # Filtra só campos válidos
        data_validos = {k: v for k, v in data.items() if k in CAMPOS_VALIDOS}
        if not data_validos: return
        data_validos["updated_at"] = datetime.utcnow().isoformat()
        supabase.table("user_profiles").upsert({
            "user_id": str(user_id), "bot_id": bot_id, **data_validos
        }, on_conflict="user_id,bot_id").execute()
    except Exception as e:
        logging.error(f"[SAVE PROFILE ERROR] {e}")

def buscar_dados_usuario(user_id, bot_id=BOT_ID):
    """Retorna dict: {'nome': 'Joao', 'cidade': 'Fortaleza'}"""
    try:
        res_profile = supabase.table("user_profiles").select("*").eq("user_id", str(user_id)).eq("bot_id", bot_id).execute()
        profile = res_profile.data[0] if res_profile.data else {}

        res_memory = supabase.table("memory").select("categoria,valor").eq("user_id", str(user_id)).eq("bot_id", bot_id).execute()
        memories = {m["categoria"]: m["valor"] for m in res_memory.data} if res_memory.data else {}

        profile["memories"] = memories
        return profile
    except Exception as e:
        logging.error(f"[GET USER ERROR] {e}")
        return {}
