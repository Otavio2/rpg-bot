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
    # Por enquanto salva no mesmo chat_history
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
