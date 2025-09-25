const express = require("express");
const { Telegraf, Markup } = require("telegraf");
const axios = require("axios");

const BOT_TOKEN = process.env.BOT_TOKEN || "SEU_TOKEN_AQUI";
const RENDER_URL = process.env.RENDER_EXTERNAL_URL;

if (!BOT_TOKEN) {
  throw new Error("❌ BOT_TOKEN não configurado!");
}

const bot = new Telegraf(BOT_TOKEN);
const app = express();

// ===============================
// ARMAZENAMENTO SIMPLES
// ===============================
const fichas = {};
const combates = {};

// ===============================
// ROTA PRINCIPAL
// ===============================
app.get("/", (req, res) => {
  res.send("🤖 RPG Bot está rodando perfeitamente!");
});

// ===============================
// AJUDA INTERATIVA
// ===============================
bot.command("ajuda", (ctx) => {
  ctx.reply(
    "📖 *RPG Bot – Ajuda Interativa*\n\n" +
    "Escolha uma categoria para ver os comandos:",
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
      texto = "*📜 Ficha*\n" +
              "• /criarficha <nome> → Cria sua ficha\n" +
              "• /ficha → Mostra sua ficha atual";
      break;
    case "INV":
      texto = "*🎒 Inventário*\n" +
              "• /additem <item> → Adiciona item ao inventário";
      break;
    case "ROLAR":
      texto = "*🎲 Rolagens*\n" +
              "• /rolar <notação> → Rola dados (ex: 1d20+5)";
      break;
    case "MAGIA":
      texto = "*✨ Magias e Monstros*\n" +
              "• /magia <nome> → Consulta magia\n" +
              "• /monstro <nome> → Consulta monstro";
      break;
    case "PV":
      texto = "*❤️ PV – Dano e Cura*\n" +
              "• /dano <valor> → Aplica dano\n" +
              "• /cura <valor> → Recupera PV";
      break;
    case "COMBATE":
      texto = "*⚔️ Combate e Turnos*\n" +
              "• /iniciativa → Inicia combate\n" +
              "• /proximo → Passa para o próximo turno";
      break;
    case "NARRACAO":
      texto = "*🎭 Narração*\n" +
              "• /narrar <texto> → Mestre narra eventos";
      break;
  }

  ctx.editMessageText(texto, {
    parse_mode: "Markdown",
    ...Markup.inlineKeyboard([[Markup.button.callback("🔙 Voltar", "HELP_BACK")]])
  });
});

bot.action("HELP_BACK", (ctx) => {
  ctx.editMessageText(
    "📖 *RPG Bot – Ajuda Interativa*\n\nEscolha uma categoria para ver os comandos:",
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

// ===============================
// FICHAS
// ===============================
bot.command("criarficha", (ctx) => {
  const userId = ctx.from.id;
  const nome = ctx.message.text.split(" ").slice(1).join(" ");
  if (!nome) return ctx.reply("❌ Use: /criarficha <nome>");
  fichas[userId] = { nome, pv: 100, inventario: [] };
  ctx.reply(`✅ Ficha criada para *${nome}* com 100 PV.`, { parse_mode: "Markdown" });
});

bot.command("ficha", (ctx) => {
  const userId = ctx.from.id;
  const ficha = fichas[userId];
  if (!ficha) return ctx.reply("❌ Você não tem uma ficha. Use /criarficha <nome>.");
  ctx.reply(
    `📜 *Ficha de ${ficha.nome}*\n❤️ PV: ${ficha.pv}\n🎒 Inventário: ${ficha.inventario.join(", ") || "vazio"}`,
    { parse_mode: "Markdown" }
  );
});

bot.command("additem", (ctx) => {
  const userId = ctx.from.id;
  const ficha = fichas[userId];
  if (!ficha) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
  const item = ctx.message.text.split(" ").slice(1).join(" ");
  if (!item) return ctx.reply("❌ Use: /additem <item>");
  ficha.inventario.push(item);
  ctx.reply(`🎒 Item *${item}* adicionado ao inventário.`, { parse_mode: "Markdown" });
});

// ===============================
// ROLAGEM DE DADOS
// ===============================
bot.command("rolar", (ctx) => {
  const input = ctx.message.text.split(" ")[1];
  if (!input) return ctx.reply("❌ Use: /rolar <notação>, ex: /rolar 1d20+5");

  const match = input.match(/(\d*)d(\d+)([+-]\d+)?/i);
  if (!match) return ctx.reply("❌ Notação inválida. Ex: 2d6+3");

  const qtd = parseInt(match[1]) || 1;
  const faces = parseInt(match[2]);
  const mod = parseInt(match[3]) || 0;

  let total = 0;
  let rolls = [];
  for (let i = 0; i < qtd; i++) {
    const r = Math.floor(Math.random() * faces) + 1;
    rolls.push(r);
    total += r;
  }
  total += mod;

  ctx.reply(`🎲 Rolagem: ${input}\n👉 [${rolls.join(", ")}] ${mod ? (mod > 0 ? "+"+mod : mod) : ""}\n✨ Total = *${total}*`, { parse_mode: "Markdown" });
});

// ===============================
// MAGIAS E MONSTROS (API aberta)
// ===============================
bot.command("magia", async (ctx) => {
  const nome = ctx.message.text.split(" ").slice(1).join(" ");
  if (!nome) return ctx.reply("❌ Use: /magia <nome da magia>");

  try {
    const res = await axios.get(`https://www.dnd5eapi.co/api/spells/${nome.toLowerCase()}`);
    ctx.reply(`✨ *${res.data.name}*\n\n${res.data.desc.join("\n")}`, { parse_mode: "Markdown" });
  } catch {
    ctx.reply("❌ Magia não encontrada.");
  }
});

bot.command("monstro", async (ctx) => {
  const nome = ctx.message.text.split(" ").slice(1).join(" ");
  if (!nome) return ctx.reply("❌ Use: /monstro <nome do monstro>");

  try {
    const res = await axios.get(`https://www.dnd5eapi.co/api/monsters/${nome.toLowerCase()}`);
    ctx.reply(`👹 *${res.data.name}*\n\nHP: ${res.data.hit_points}\nAC: ${res.data.armor_class[0].value}`, { parse_mode: "Markdown" });
  } catch {
    ctx.reply("❌ Monstro não encontrado.");
  }
});

// ===============================
// PV: DANO E CURA
// ===============================
bot.command("dano", (ctx) => {
  const userId = ctx.from.id;
  const ficha = fichas[userId];
  if (!ficha) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
  const valor = parseInt(ctx.message.text.split(" ")[1]);
  if (!valor) return ctx.reply("❌ Use: /dano <valor>");
  ficha.pv -= valor;
  if (ficha.pv < 0) ficha.pv = 0;
  ctx.reply(`💔 ${ficha.nome} recebeu ${valor} de dano. PV atual: ${ficha.pv}`);
});

bot.command("cura", (ctx) => {
  const userId = ctx.from.id;
  const ficha = fichas[userId];
  if (!ficha) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
  const valor = parseInt(ctx.message.text.split(" ")[1]);
  if (!valor) return ctx.reply("❌ Use: /cura <valor>");
  ficha.pv += valor;
  ctx.reply(`💚 ${ficha.nome} recuperou ${valor} PV. PV atual: ${ficha.pv}`);
});

// ===============================
// COMBATE: INICIATIVA
// ===============================
bot.command("iniciativa", (ctx) => {
  const chatId = ctx.chat.id;
  combates[chatId] = { ordem: [], turno: 0 };

  for (const uid in fichas) {
    const rolagem = Math.floor(Math.random() * 20) + 1;
    combates[chatId].ordem.push({ nome: fichas[uid].nome, valor: rolagem });
  }

  combates[chatId].ordem.sort((a, b) => b.valor - a.valor);
  ctx.reply("⚔️ Iniciativa:\n" + combates[chatId].ordem.map((p, i) => `${i+1}. ${p.nome} (${p.valor})`).join("\n"));
});

bot.command("proximo", (ctx) => {
  const chatId = ctx.chat.id;
  const combate = combates[chatId];
  if (!combate) return ctx.reply("❌ Nenhum combate em andamento. Use /iniciativa");

  const atual = combate.ordem[combate.turno];
  combate.turno = (combate.turno + 1) % combate.ordem.length;
  ctx.reply(`👉 Turno de *${atual.nome}*`, { parse_mode: "Markdown" });
});

// ===============================
// NARRAÇÃO
// ===============================
bot.command("narrar", (ctx) => {
  const texto = ctx.message.text.split(" ").slice(1).join(" ");
  if (!texto) return ctx.reply("❌ Use: /narrar <texto>");
  ctx.reply(`🎭 *NARRAÇÃO*\n${texto}`, { parse_mode: "Markdown" });
});

// ===============================
// WEBHOOK TELEGRAM
// ===============================
app.use(bot.webhookCallback("/webhook"));

if (RENDER_URL) {
  bot.telegram.setWebhook(`${RENDER_URL}/webhook`);
  console.log("✅ Webhook configurado:", `${RENDER_URL}/webhook`);
}

// ===============================
// INICIA SERVIDOR
// ===============================
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`🚀 Servidor rodando na porta ${PORT}`);
});
