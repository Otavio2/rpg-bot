import os
import time
import requests
import langid
from flask import Flask
from threading import Thread
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# =====================
# CONFIG
# =====================
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN não definido")

TEMPO_MAX_SESSAO = 300  # 5 minutos
SESSOES = {}

# =====================
# FLASK (Render keep-alive)
# =====================
app = Flask(__name__)

@app.route("/")
def home():
    return "EduBot Universal Online ✅"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

# =====================
# UTILIDADES
# =====================
def detectar_idioma(texto: str) -> str:
    try:
        lang, _ = langid.classify(texto)
        return lang
    except:
        return "pt"

def dividir_texto(texto, limite=3800):
    return [texto[i:i + limite] for i in range(0, len(texto), limite)]

def limpar_sessao(user_id):
    if user_id in SESSOES:
        if time.time() - SESSOES[user_id]["ultimo_uso"] > TEMPO_MAX_SESSAO:
            del SESSOES[user_id]

def atualizar_sessao(user_id, tema):
    SESSOES[user_id] = {
        "tema": tema,
        "ultimo_uso": time.time()
    }

# =====================
# APIS
# =====================
def wikipedia_resumo(tema, lang):
    tema = tema.replace(" ", "_")
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{tema}"
    r = requests.get(url, timeout=8)

    if r.status_code != 200 and lang != "en":
        return wikipedia_resumo(tema, "en")

    if r.status_code != 200:
        return "❌ Conteúdo não encontrado."

    d = r.json()
    return f"📘 *{d['title']}*\n\n{d['extract']}"

def definir(palavra):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{palavra}"
    r = requests.get(url, timeout=8)

    if r.status_code != 200:
        return "❌ Definição não encontrada."

    d = r.json()[0]
    return f"📗 *{palavra.capitalize()}*\n\n{d['meanings'][0]['definitions'][0]['definition']}"

def geo(lugar):
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": lugar, "format": "json", "limit": 1}
    headers = {"User-Agent": "EduBot"}

    r = requests.get(url, params=params, headers=headers, timeout=8)
    if not r.json():
        return "❌ Local não encontrado."

    d = r.json()[0]
    return (
        f"🌍 *{d['display_name']}*\n"
        f"📍 Latitude: {d['lat']}\n"
        f"📍 Longitude: {d['lon']}"
    )

# =====================
# COMANDOS
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("START OK")
    await update.message.reply_text(
        "🎓 *EduBot Universal*\n\n"
        "Pergunte naturalmente em qualquer idioma:\n"
        "• o que é fotossíntese\n"
        "• explain gravity\n"
        "• onde fica japão\n\n"
        "Comandos:\n"
        "/explain tema\n"
        "/def palavra\n"
        "/geo lugar",
        parse_mode="Markdown"
    )

async def explain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tema = " ".join(context.args)
    if not tema:
        return

    resposta = wikipedia_resumo(tema, detectar_idioma(tema))
    for parte in dividir_texto(resposta):
        await update.message.reply_text(parte, parse_mode="Markdown")

async def cmd_def(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return
    await update.message.reply_text(definir(context.args[0]), parse_mode="Markdown")

async def cmd_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lugar = " ".join(context.args)
    if not lugar:
        return
    await update.message.reply_text(geo(lugar), parse_mode="Markdown")

# =====================
# AUTOMÁTICO
# =====================
async def automatico(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    texto = update.message.text.lower()

    limpar_sessao(user_id)

    gatilhos = [
        "o que é", "explique", "defina",
        "what is", "explain",
        "qué es", "concept of"
    ]

    if any(texto.startswith(g) for g in gatilhos):
        tema = texto.split(" ", 2)[-1]
        atualizar_sessao(user_id, tema)

        resposta = wikipedia_resumo(tema, detectar_idioma(texto))
        for parte in dividir_texto(resposta):
            await update.message.reply_text(parte, parse_mode="Markdown")

    elif texto.startswith("onde fica") or texto.startswith("where is"):
        tema = texto.split(" ", 2)[-1]
        atualizar_sessao(user_id, tema)
        await update.message.reply_text(geo(tema), parse_mode="Markdown")

# =====================
# MAIN
# =====================
def main():
    Thread(target=run_flask, daemon=True).start()

    app_bot = ApplicationBuilder().token(TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))
    app_bot.add_handler(CommandHandler("help", start))
    app_bot.add_handler(CommandHandler("explain", explain))
    app_bot.add_handler(CommandHandler("def", cmd_def))
    app_bot.add_handler(CommandHandler("geo", cmd_geo))
    app_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, automatico))

    app_bot.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
