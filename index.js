const express = require('express');
const axios = require('axios');
const { DiceRoll } = require('@dice-roller/rpg-dice-roller');
const { Telegraf, Markup } = require('telegraf');
const fs = require('fs');

const BOT_TOKEN = process.env.BOT_TOKEN;
if (!BOT_TOKEN) throw new Error("⚠️ Defina BOT_TOKEN com o token do bot.");

const bot = new Telegraf(BOT_TOKEN);

// 📂 Banco de fichas
let fichas = {};
const FICHAS_FILE = './fichas.json';

function carregarFichas() {
  try {
    if (fs.existsSync(FICHAS_FILE)) {
      fichas = JSON.parse(fs.readFileSync(FICHAS_FILE, 'utf-8'));
      console.log("📂 Fichas carregadas.");
    }
  } catch (e) {
    console.error("❌ Erro ao carregar fichas:", e.message);
  }
}
function salvarFichas() {
  try {
    fs.writeFileSync(FICHAS_FILE, JSON.stringify(fichas, null, 2));
  } catch (e) {
    console.error("❌ Erro ao salvar fichas:", e.message);
  }
}
carregarFichas();

// 📌 Helpers
function getFicha(chatId, userId) {
  if (!fichas[chatId]) fichas[chatId] = {};
  return fichas[chatId][userId];
}
function setFicha(chatId, userId, ficha) {
  if (!fichas[chatId]) fichas[chatId] = {};
  fichas[chatId][userId] = ficha;
  salvarFichas();
}

//
// ▶️ /start
//
bot.start((ctx) => {
  ctx.reply(
    "🎲 Bem-vindo ao *RPG Bot*!\n\n" +
    "Crie personagens, role dados, consulte magias e monstros de D&D 5e.\n" +
    "Funciona em *PV* e em *grupos*, com fichas separadas para cada mesa.\n\n" +
    "📌 Use os botões ou digite /ajuda para ver o guia.",
    {
      parse_mode: "Markdown",
      ...Markup.inlineKeyboard([
        [Markup.button.callback("📜 Criar ficha", "CRIAR_FICHA")],
        [Markup.button.callback("👤 Ver ficha", "VER_FICHA")],
        [Markup.button.callback("🎲 Rolar dado", "ROLAR_DADO")],
        [Markup.button.callback("✨ Magia", "MAGIA"), Markup.button.callback("👹 Monstro", "MONSTRO")],
        [Markup.button.callback("❤️ Dano", "DANO"), Markup.button.callback("💊 Cura", "CURA")],
        [Markup.button.callback("🎭 Narrar", "NARRAR")],
        [Markup.button.callback("ℹ️ Ajuda", "AJUDA")]
      ])
    }
  );
});

//
// ❓ /ajuda
//
bot.command("ajuda", (ctx) => {
  ctx.replyWithMarkdown(
    "📖 *Guia do RPG Bot*\n\n" +
    "1️⃣ /criarficha <nome> → Cria seu personagem\n" +
    "2️⃣ /ficha → Mostra sua ficha\n" +
    "3️⃣ /additem <item> → Adiciona item ao inventário\n" +
    "4️⃣ /rolar 1d20+5 → Rola dados\n" +
    "5️⃣ /magia bola de fogo → Consulta magia\n" +
    "6️⃣ /monstro goblin → Consulta monstro\n" +
    "7️⃣ /dano 5 ou /cura 3 → Gerencia PV\n" +
    "8️⃣ /narrar <texto> → Mensagem destacada do Mestre\n\n" +
    "⚔️ Cada grupo tem suas próprias fichas.\n" +
    "✅ Assim você pode jogar em várias mesas sem misturar personagens."
  );
});

//
// 🎲 /rolar
//
bot.command('rolar', (ctx) => {
  const args = ctx.message.text.split(' ').slice(1).join(' ');
  if (!args) return ctx.reply("⚠️ Use assim: /rolar 1d20+5");
  try {
    const roll = new DiceRoll(args);
    ctx.reply(`🎲 Rolagem: *${args}*\nResultado: *${roll.total}*\n${roll.output}`, { parse_mode: 'Markdown' });
  } catch {
    ctx.reply("❌ Notação inválida. Exemplo: /rolar 2d6+3");
  }
});

//
// ✨ /magia
//
bot.command('magia', async (ctx) => {
  const name = ctx.message.text.split(' ').slice(1).join(' ');
  if (!name) return ctx.reply("⚠️ Use: /magia <nome>");
  try {
    const url = `https://www.dnd5eapi.co/api/spells/${name.toLowerCase().replace(/ /g, '-')}`;
    const { data } = await axios.get(url);
    ctx.replyWithMarkdown(`✨ *${data.name}*\nEscola: ${data.school.name}\n\n${data.desc.join('\n')}`);
  } catch {
    ctx.reply("❌ Magia não encontrada.");
  }
});

//
// 👹 /monstro
//
bot.command('monstro', async (ctx) => {
  const name = ctx.message.text.split(' ').slice(1).join(' ');
  if (!name) return ctx.reply("⚠️ Use: /monstro <nome>");
  try {
    const url = `https://www.dnd5eapi.co/api/monsters/${name.toLowerCase().replace(/ /g, '-')}`;
    const { data } = await axios.get(url);
    ctx.replyWithMarkdown(`👹 *${data.name}*\nTipo: ${data.type}\nPV: ${data.hit_points}\nCA: ${data.armor_class}`);
  } catch {
    ctx.reply("❌ Monstro não encontrado.");
  }
});

//
// 📝 /criarficha
//
bot.command('criarficha', (ctx) => {
  const chatId = ctx.chat.id;
  const userId = ctx.from.id;
  const nome = ctx.message.text.split(' ').slice(1).join(' ');
  if (!nome) return ctx.reply("⚠️ Use: /criarficha <nome>");
  setFicha(chatId, userId, {
    nome,
    pv: 10,
    forca: 10,
    destreza: 10,
    inteligencia: 10,
    inventario: []
  });
  ctx.reply(`📜 Ficha criada para *${nome}*! Digite /ficha para ver.`, { parse_mode: 'Markdown' });
});

//
// 📜 /ficha
//
bot.command('ficha', (ctx) => {
  const chatId = ctx.chat.id;
  const userId = ctx.from.id;
  const f = getFicha(chatId, userId);
  if (!f) return ctx.reply("❌ Você não tem uma ficha. Use /criarficha <nome>.");
  ctx.replyWithMarkdown(
    `📜 *Ficha de ${f.nome}*\n\n` +
    `❤️ PV: ${f.pv}\n💪 Força: ${f.forca}\n🏹 Destreza: ${f.destreza}\n🧠 Inteligência: ${f.inteligencia}\n\n` +
    `🎒 Inventário: ${f.inventario.length ? f.inventario.join(', ') : 'vazio'}`
  );
});

//
// 🎒 /additem
//
bot.command('additem', (ctx) => {
  const chatId = ctx.chat.id;
  const userId = ctx.from.id;
  const f = getFicha(chatId, userId);
  if (!f) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
  const item = ctx.message.text.split(' ').slice(1).join(' ');
  if (!item) return ctx.reply("⚠️ Use: /additem <item>");
  f.inventario.push(item);
  setFicha(chatId, userId, f);
  ctx.reply(`✅ Item *${item}* adicionado ao inventário de ${f.nome}.`, { parse_mode: 'Markdown' });
});

//
// ❤️ /dano
//
bot.command('dano', (ctx) => {
  const chatId = ctx.chat.id;
  const userId = ctx.from.id;
  const f = getFicha(chatId, userId);
  if (!f) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
  const valor = parseInt(ctx.message.text.split(' ')[1]);
  if (isNaN(valor) || valor <= 0) return ctx.reply("⚠️ Use: /dano <valor>");
  f.pv = Math.max(0, f.pv - valor);
  setFicha(chatId, userId, f);
  ctx.reply(`💔 ${f.nome} recebeu *${valor}* de dano.\nPV atual: *${f.pv}*`, { parse_mode: 'Markdown' });
});

//
// 💊 /cura
//
bot.command('cura', (ctx) => {
  const chatId = ctx.chat.id;
  const userId = ctx.from.id;
  const f = getFicha(chatId, userId);
  if (!f) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
  const valor = parseInt(ctx.message.text.split(' ')[1]);
  if (isNaN(valor) || valor <= 0) return ctx.reply("⚠️ Use: /cura <valor>");
  f.pv += valor;
  setFicha(chatId, userId, f);
  ctx.reply(`💖 ${f.nome} recuperou *${valor}* PV.\nPV atual: *${f.pv}*`, { parse_mode: 'Markdown' });
});

//
// 🎭 /narrar (Mestre)
//
bot.command('narrar', (ctx) => {
  const texto = ctx.message.text.split(' ').slice(1).join(' ');
  if (!texto) return ctx.reply("⚠️ Use: /narrar <texto>");
  ctx.replyWithMarkdown(
    `📢 *NARRAÇÃO*\n\n${texto}\n\n🎭 Mestre: ${ctx.from.first_name}`
  );
});

//
// 📌 Botões
//
bot.action("CRIAR_FICHA", (ctx) => ctx.reply("📜 Use: /criarficha <nome>"));
bot.action("VER_FICHA", (ctx) => ctx.reply("👤 Digite /ficha"));
bot.action("ROLAR_DADO", (ctx) => ctx.reply("🎲 Use: /rolar 1d20+5"));
bot.action("MAGIA", (ctx) => ctx.reply("✨ Use: /magia <nome>"));
bot.action("MONSTRO", (ctx) => ctx.reply("👹 Use: /monstro <nome>"));
bot.action("DANO", (ctx) => ctx.reply("💔 Use: /dano <valor>"));
bot.action("CURA", (ctx) => ctx.reply("💖 Use: /cura <valor>"));
bot.action("NARRAR", (ctx) => ctx.reply("🎭 Use: /narrar <texto>"));
bot.action("AJUDA", (ctx) => ctx.reply("ℹ️ Digite /ajuda"));

//
// ⚙️ Render
//
const app = express();
app.use(bot.webhookCallback('/webhook'));
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`🚀 Bot rodando na porta ${PORT}`));
