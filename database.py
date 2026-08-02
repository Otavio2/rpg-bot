import os
from supabase import create_client

supabase = create_client(
    os.getenv("SUPABASE_URL"), 
    os.getenv("SUPABASE_KEY")
)

def save_message(user_id, chat_id, chat_type, chat_title, role, content, bot_id="hansel"):
    supabase.table("chat_history").insert({
        "user_id": user_id,
        "bot_id": bot_id,
        "chat_id": str(chat_id),
        "chat_type": chat_type,
        "chat_title": chat_title,
        "role": role,
        "content": content
    }).execute()

def save_memory(user_id, chat_id, role, content, bot_id="hansel"):
    supabase.table("chat_history").insert({
        "user_id": user_id,
        "bot_id": bot_id,
        "chat_id": str(chat_id),
        "role": role,
        "content": content
    }).execute()

def save_user_profile(user_id, data, bot_id="hansel"):
    supabase.table("user_profiles").upsert({
        "user_id": user_id,
        "bot_id": bot_id,
        **data
    }).execute()

def buscar_dados_usuario(user_id, bot_id="hansel"):
    try:
        res = supabase.table("user_profiles").select("*").eq("user_id", str(user_id)).eq("bot_id", bot_id).single().execute()
        return res.data if res.data else {}
    except:
        return {}

def limpar_dados_usuario(user_id, bot_id="hansel"):
    try:
        supabase.table("user_profiles").delete().eq("user_id", str(user_id)).eq("bot_id", bot_id).execute()
        supabase.table("memory").delete().eq("user_id", str(user_id)).eq("bot_id", bot_id).execute()
        supabase.table("chat_history").delete().eq("user_id", str(user_id)).eq("bot_id", bot_id).execute()
        return True
    except Exception as e:
        print(f"Erro ao limpar: {e}")
        return False

def resetar_banco():
    try:
        supabase.table("chat_history").delete().neq("id", 0).execute()
        supabase.table("memory").delete().neq("id", 0).execute()
        supabase.table("user_profiles").delete().neq("id", 0).execute()
        return True
    except Exception as e:
        print(f"Erro ao resetar: {e}")
        return False
