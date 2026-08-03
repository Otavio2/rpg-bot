import json
import logging
import requests
from config import BOT_NAME, GEMINI_API_KEYS, GEMINI_MODEL, GROQ_API_KEYS, GROQ_API_URL, GROQ_MODEL, TIMEOUT_API
from database import save_user_profile, save_memory, save_message, buscar_dados_usuario

session = requests.Session()
gemini_key_index = 0
GROQ_BLACKLIST = {}
CAMPOS_VALIDOS = ["nome", "apelido", "cidade", "profissao", "comida", "gostos"]

def call_gemini_rotacao(prompt):... # igual ao seu

def call_groq_multi(messages):... # igual ao seu

def extrair_dados_automaticos(user_id, texto):
    """Só roda se tiver gatilho. Só salva campos válidos"""
    gatilhos = ["meu nome", "me chama", "moro", "cidade", "trabalho", "profissao", "profissão", "gosto", "gosta"]
    if not any(g in texto.lower() for g in gatilhos): return

    prompt = f"""
Extraia APENAS estas informações do texto em JSON válido: {CAMPOS_VALIDOS}
Se não existir, retorne {{}}.
Não invente. Texto: {texto}
"""
    json_str = call_groq_multi([{"role": "user", "content": prompt}])
    if not json_str or "{" not in json_str: return

    try:
        dados = json.loads(json_str[json_str.find("{"):json_str.rfind("}") + 1])
        for categoria, valor in dados.items():
            if valor and categoria in CAMPOS_VALIDOS:
                save_memory(user_id, categoria, valor)
                save_user_profile(user_id, {categoria: valor})
    except Exception as e:
        logging.warning(f"[EXTRAÇÃO] Erro: {e}")

def call_ai_smart(pergunta, contexto, categoria):
    user_id = contexto["user_id"]

    # 1. BUSCAR MEMÓRIA
    dados_usuario = buscar_dados_usuario(user_id)
    memoria = dados_usuario.get("memories", {}) # AGORA É DICT

    # 2. MONTAR PROMPT COM MEMÓRIA
    prompt_sistema = contexto["prompt"]
    if memoria:
        memoria_str = "\n".join([f"- {k}: {v}" for k, v in memoria.items()]) # AGORA FUNCIONA
        prompt_sistema += f"\n\nO que você já sabe sobre o usuário:\n{memoria_str}"

    messages = [{"role": "system", "content": prompt_sistema}, {"role": "user", "content": pergunta}]

    # 3. CHAMAR IA
    resposta = call_groq_multi(messages) or call_gemini_rotacao(prompt_sistema + "\nPergunta: " + pergunta)
    if not resposta: return "Não sei ainda, me conta?"

    # 4. SALVAR RESPOSTA
    save_message(contexto["user_id"], contexto["chat_id"], contexto["chat_type"], contexto["chat_title"], "assistant", resposta)
    return resposta
