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

// 📂 Banco de iniciativas
let iniciativas = {};

// 📂 Tutorial
let tutorialUsuarios = {}; // chatId -> userId -> concluido

// 📌 Funções de persistência
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
function tutorialConcluido(chatId, userId) {
return tutorialUsuarios[chatId]?.[userId] === true;
}
function marcarTutorial(chatId, userId) {
if (!tutorialUsuarios[chatId]) tutorialUsuarios[chatId] = {};
tutorialUsuarios[chatId][userId] = true;
}

// ========================================================
// ▶️ Tutorial Interativo
// ========================================================
function iniciarTutorial(ctx) {
const chatId = ctx.chat.id;
const userId = ctx.from.id;
if (tutorialConcluido(chatId, userId)) return;

ctx.replyWithMarkdown(
"📖 Tutorial RPG Bot\n\nBem-vindo! Vamos aprender a jogar passo a passo.\nClique em Próximo para continuar.",
Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_1_${userId})]])
);
}

bot.action(/TUT_(\d+)_(\d+)/, (ctx) => {
const passo = parseInt(ctx.match[1]);
const userId = parseInt(ctx.match[2]);
const chatId = ctx.chat.id;

if (ctx.from.id !== userId) return ctx.answerCbQuery("Este tutorial não é seu!");

switch (passo) {
case 1:
ctx.editMessageText(
"1️⃣ Crie sua ficha de personagem:\n/criarficha NomeDoSeuPersonagem",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_2_${userId})]]) }
);
break;
case 2:
ctx.editMessageText(
"2️⃣ Veja sua ficha a qualquer momento com:\n/ficha\nInclui PV, atributos e inventário.",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_3_${userId})]]) }
);
break;
case 3:
ctx.editMessageText(
"3️⃣ Adicione itens ao seu inventário:\n/additem Espada\n/additem Poção",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_4_${userId})]]) }
);
break;
case 4:
ctx.editMessageText(
"4️⃣ Rolar dados:\n/rolar 1d20+5\n/rolar 2d6+3\nO bot mostra o resultado automaticamente.",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_5_${userId})]]) }
);
break;
case 5:
ctx.editMessageText(
"5️⃣ Consultar magias e monstros:\n/magia Bola de Fogo\n/monstro Goblin",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_6_${userId})]]) }
);
break;
case 6:
ctx.editMessageText(
"6️⃣ Controle de PV:\n/dano 3 → aplica 3 de dano\n/cura 5 → recupera 5 PV",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_7_${userId})]]) }
);
break;
case 7:
ctx.editMessageText(
"7️⃣ Mestre pode narrar eventos:\n/narrar O grupo entra na caverna escura...",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Próximo", TUT_8_${userId})]]) }
);
break;
case 8:
ctx.editMessageText(
"8️⃣ Combate e iniciativa:\n/iniciativa → inicia combate\n/proximo → passa para o próximo turno",
{ parse_mode: "Markdown", ...Markup.inlineKeyboard([[Markup.button.callback("Concluir Tutorial", TUT_END_${userId})]]) }
);
break;
}
});

bot.action(/TUT_END_(\d+)/, (ctx) => {
const userId = parseInt(ctx.match[1]);
const chatId = ctx.chat.id;
if (ctx.from.id !== userId) return ctx.answerCbQuery("Este tutorial não é seu!");
marcarTutorial(chatId, userId);
ctx.editMessageText("✅ Tutorial concluído! Agora você está pronto para jogar. Digite /ajuda para ver os comandos interativos.");
});

// ========================================================
// ▶️ /start
// ========================================================
bot.start((ctx) => {
ctx.reply(
"🎲 Bem-vindo ao RPG Bot!\nUse /ajuda para ver os comandos interativos.",
{ parse_mode: "Markdown" }
);
iniciarTutorial(ctx);
});

// ========================================================
// ▶️ /ajuda Interativo
// ========================================================
bot.command("ajuda", (ctx) => {
ctx.reply(
"📖 RPG Bot – Ajuda Interativa\n\nEscolha uma categoria para ver os comandos:",
{
parse_mode: "Markdown",
...Markup.inlineKeyboard([
[Markup.button.callback("📜 Ficha", "HELP_FICHA")],
[Markup.button.callback("🎒 Inventário", "HELP_INV")],
[Markup.button.callback("🎲 Rolagens", "HELP_ROLAR")],
[Markup.button.callback("✨ Magias/Monstros", "HELP_MAGIA")],
[Markup.button.callback("❤️ PV/Dano/Cura", "HELP_PV")],
[Markup.button.callback("⚔️ Combate", "HELP_COMBATE")],
[Markup.button.callback("🎭 Narração", "HELP_NARRACAO")]
])
}
);
});

bot.action(/HELP_(\w+)/, (ctx) => {
const cat = ctx.match[1];
let texto = "";

switch(cat) {
case "FICHA":
texto = "📜 Ficha\n• /criarficha <nome>\n• /ficha";
break;
case "INV":
texto = "🎒 Inventário\n• /additem <item>";
break;
case "ROLAR":
texto = "🎲 Rolagens\n• /rolar <notação>";
break;
case "MAGIA":
texto = "✨ Magias/Monstros\n• /magia <nome>\n• /monstro <nome>";
break;
case "PV":
texto = "❤️ PV – Dano e Cura\n• /dano <valor>\n• /cura <valor>";
break;
case "COMBATE":
texto = "⚔️ Combate e Turnos\n• /iniciativa\n• /proximo";
break;
case "NARRACAO":
texto = "🎭 Narração\n• /narrar <texto>";
break;
}

ctx.editMessageText(texto, {
parse_mode: "Markdown",
...Markup.inlineKeyboard([[Markup.button.callback("🔙 Voltar", "HELP_BACK")]])
});
});

bot.action("HELP_BACK", (ctx) => {
ctx.editMessageText(
"📖 RPG Bot – Ajuda Interativa\n\nEscolha uma categoria para ver os comandos:",
{
parse_mode: "Markdown",
...Markup.inlineKeyboard([
[Markup.button.callback("📜 Ficha", "HELP_FICHA")],
[Markup.button.callback("🎒 Inventário", "HELP_INV")],
[Markup.button.callback("🎲 Rolagens", "HELP_ROLAR")],
[Markup.button.callback("✨ Magias/Monstros", "HELP_MAGIA")],
[Markup.button.callback("❤️ PV/Dano/Cura", "HELP_PV")],
[Markup.button.callback("⚔️ Combate", "HELP_COMBATE")],
[Markup.button.callback("🎭 Narração", "HELP_NARRACAO")]
])
}
);
});

// ========================================================
// 🎲 /rolar
// ========================================================
bot.command('rolar', (ctx) => {
const args = ctx.message.text.split(' ').slice(1).join(' ');
if (!args) return ctx.reply("⚠️ Use: /rolar 1d20+5");
try {
const roll = new DiceRoll(args);
ctx.reply(🎲 Rolagem: *${args}*\nResultado: *${roll.total}*\n${roll.output}, { parse_mode: 'Markdown' });
} catch {
ctx.reply("❌ Notação inválida. Exemplo: /rolar 2d6+3");
}
});

// ========================================================
// ✨ /magia
// ========================================================
bot.command('magia', async (ctx) => {
const name = ctx.message.text.split(' ').slice(1).join(' ');
if (!name) return ctx.reply("⚠️ Use: /magia <nome>");
try {
const url = https://www.dnd5eapi.co/api/spells/${name.toLowerCase().replace(/ /g, '-')};
const { data } = await axios.get(url);
ctx.replyWithMarkdown(✨ *${data.name}*\nEscola: ${data.school.name}\n\n${data.desc.join('\n')});
} catch {
ctx.reply("❌ Magia não encontrada.");
}
});

// ========================================================
// 👹 /monstro
// ========================================================
bot.command('monstro', async (ctx) => {
const name = ctx.message.text.split(' ').slice(1).join(' ');
if (!name) return ctx.reply("⚠️ Use: /monstro <nome>");
try {
const url = https://www.dnd5eapi.co/api/monsters/${name.toLowerCase().replace(/ /g, '-')};
const { data } = await axios.get(url);
ctx.replyWithMarkdown(👹 *${data.name}*\nTipo: ${data.type}\nPV: ${data.hit_points}\nCA: ${data.armor_class});
} catch {
ctx.reply("❌ Monstro não encontrado.");
}
});

// ========================================================
// 📝 /criarficha
// ========================================================
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
ctx.reply(📜 Ficha criada para *${nome}*! Digite /ficha para ver., { parse_mode: 'Markdown' });
iniciarTutorial(ctx);
});

// ========================================================
// 📜 /ficha
// ========================================================
bot.command('ficha', (ctx) => {
const chatId = ctx.chat.id;
const userId = ctx.from.id;
const f = getFicha(chatId, userId);
if (!f) return ctx.reply("❌ Você não tem uma ficha. Use /criarficha <nome>.");
ctx.replyWithMarkdown(
📜 *Ficha de ${f.nome}*\n❤️ PV: ${f.pv}\n💪 Força: ${f.forca}\n🏹 Destreza: ${f.destreza}\n🧠 Inteligência: ${f.inteligencia}\n🎒 Inventário: ${f.inventario.length ? f.inventario.join(', ') : 'vazio'}
);
});

// ========================================================
// 🎒 /additem
// ========================================================
bot.command('additem', (ctx) => {
const chatId = ctx.chat.id;
const userId = ctx.from.id;
const f = getFicha(chatId, userId);
if (!f) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
const item = ctx.message.text.split(' ').slice(1).join(' ');
if (!item) return ctx.reply("⚠️ Use: /additem <item>");
f.inventario.push(item);
setFicha(chatId, userId, f);
ctx.reply(✅ Item *${item}* adicionado ao inventário de ${f.nome}., { parse_mode: 'Markdown' });
});

// ========================================================
// ❤️ /dano
// ========================================================
bot.command('dano', (ctx) => {
const chatId = ctx.chat.id;
const userId = ctx.from.id;
const f = getFicha(chatId, userId);
if (!f) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
const valor = parseInt(ctx.message.text.split(' ')[1]);
if (isNaN(valor) || valor <= 0) return ctx.reply("⚠️ Use: /dano <valor>");
f.pv = Math.max(0, f.pv - valor);
setFicha(chatId, userId, f);
ctx.reply(💔 ${f.nome} recebeu *${valor}* de dano.\nPV atual: *${f.pv}*, { parse_mode: 'Markdown' });
});

// ========================================================
// 💊 /cura
// ========================================================
bot.command('cura', (ctx) => {
const chatId = ctx.chat.id;
const userId = ctx.from.id;
const f = getFicha(chatId, userId);
if (!f) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
const valor = parseInt(ctx.message.text.split(' ')[1]);
if (isNaN(valor) || valor <= 0) return ctx.reply("⚠️ Use: /cura <valor>");
f.pv += valor;
setFicha(chatId, userId, f);
ctx.reply(💖 ${f.nome} recuperou *${valor}* PV.\nPV atual: *${f.pv}*, { parse_mode: 'Markdown' });
});

// ========================================================
// 🎭 /narrar
// ========================================================
bot.command('narrar', (ctx) => {
const texto = ctx.message.text.split(' ').slice(1).join(' ');
if (!texto) return ctx.reply("⚠️ Use: /narrar <texto>");
ctx.replyWithMarkdown(📢 *NARRAÇÃO*\n\n${texto}\n\n🎭 Mestre: ${ctx.from.first_name});
});

// ========================================================
// ⚔️ /iniciativa
// ========================================================
bot.command('iniciativa', (ctx) => {
const chatId = ctx.chat.id;
if (!fichas[chatId] || Object.keys(fichas[chatId]).length === 0) {
return ctx.reply("❌ Nenhuma ficha encontrada no grupo. Jogadores precisam criar ficha primeiro.");
}

const ordens = [];
for (const userId in fichas[chatId]) {
const f = fichas[chatId][userId];
const roll = new DiceRoll('1d20+' + f.destreza);
ordens.push({ nome: f.nome, userId, total: roll.total });
}

ordens.sort((a, b) => b.total - a.total);
iniciativas[chatId] = { ordem: ordens, index: 0 };

let msg = "🎲 Iniciativa do Combate:\n";
ordens.forEach((j, i) => { msg += ${i + 1}️⃣ ${j.nome} → ${j.total}\n; });
msg += "\n➡️ Use /proximo para passar o turno.";
ctx.reply(msg, { parse_mode: 'Markdown' });
});

// ========================================================
// ⏭️ /proximo
// ========================================================
bot.command('proximo', (ctx) => {
const chatId = ctx.chat.id;
const ini = iniciativas[chatId];
if (!ini) return ctx.reply("❌ Nenhuma iniciativa ativa. Use /iniciativa primeiro.");
const jogadorAtual = ini.ordem[ini.index];
ctx.replyWithMarkdown(🔹 Turno de *${jogadorAtual.nome}*);
ini.index = (ini.index + 1) % ini.ordem.length;
});

// ========================================================
// ⚙️ Render Webhook
// ========================================================
const app = express();
app.use(bot.webhookCallback('/webhook'));
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(🚀 Bot rodando na porta ${PORT}));

Ajusta ele nesse código

  
