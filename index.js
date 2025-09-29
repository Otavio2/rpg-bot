const { Telegraf, Markup } = require("telegraf");
const axios = require("axios");

// 🔑 Token do seu bot (substitua pelo seu)
const BOT_TOKEN = process.env.BOT_TOKEN || "COLOQUE_SEU_TOKEN_AQUI";
if (!BOT_TOKEN) {
  throw new Error("❌ BOT_TOKEN não configurado!");
}

const bot = new Telegraf(BOT_TOKEN);

// 🗂️ Memória temporária para fichas
const fichas = {};
let combate = { ordem: [], turno: 0 };

// ========================================================
// ▶️ Início
// ========================================================
bot.start((ctx) => {
  ctx.reply(
    "🎲 *Bem-vindo ao RPG Bot!*\n\n" +
    "Sou um bot para ajudar sua mesa de RPG.\n\n" +
    "👉 Digite /ajuda para ver todos os comandos.",
    { parse_mode: "Markdown" }
  );
});

// ========================================================
// ▶️ Ajuda Interativa
// ========================================================
bot.command("ajuda", (ctx) => {
  ctx.reply(
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

bot.action(/HELP_(\w+)/, (ctx) => {
  const cat = ctx.match[1];
  let texto = "";

  switch(cat) {
    case "FICHA":
      texto = "*📜 Ficha*\n" +
              "• `/criarficha <nome>` → cria sua ficha\n" +
              "• `/ficha` → mostra sua ficha atual";
      break;
    case "INV":
      texto = "*🎒 Inventário*\n" +
              "• `/additem <item>` → adiciona item à ficha";
      break;
    case "ROLAR":
      texto = "*🎲 Rolagens*\n" +
              "• `/rolar <notação>` → ex: `/rolar 1d20+5` ou `/rolar 2d6+3`";
      break;
    case "MAGIA":
      texto = "*✨ Magias e Monstros*\n" +
              "• `/magia <nome>` → busca magia (ex: `/magia fireball`)\n" +
              "• `/monstro <nome>` → busca monstro (ex: `/monstro goblin`)";
      break;
    case "PV":
      texto = "*❤️ PV – Dano e Cura*\n" +
              "• `/dano <valor>` → perde PV\n" +
              "• `/cura <valor>` → recupera PV";
      break;
    case "COMBATE":
      texto = "*⚔️ Combate e Turnos*\n" +
              "• `/iniciativa` → inicia combate com rolagem de iniciativa\n" +
              "• `/proximo` → passa para o próximo turno";
      break;
    case "NARRACAO":
      texto = "*🎭 Narração*\n" +
              "• `/narrar <texto>` → o Mestre narra eventos";
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

// ========================================================
// ▶️ Rolagens
// ========================================================
bot.command("rolar", (ctx) => {
  const input = ctx.message.text.split(" ")[1];
  if (!input) return ctx.reply("❌ Use: /rolar <notação>, ex: /rolar 1d20+5");

  const match = input.match(/(\d*)d(\d+)([+-]\d+)?/);
  if (!match) return ctx.reply("❌ Notação inválida.");

  let [ , qtd, faces, mod ] = match;
  qtd = parseInt(qtd) || 1;
  faces = parseInt(faces);
  mod = parseInt(mod) || 0;

  const rolls = [];
  for (let i = 0; i < qtd; i++) {
    rolls.push(Math.floor(Math.random() * faces) + 1);
  }
  const total = rolls.reduce((a, b) => a + b, 0) + mod;

  ctx.reply(`🎲 Rolagem: ${input}\nResultados: ${rolls.join(", ")}\nTotal: *${total}*`, { parse_mode: "Markdown" });
});

// ========================================================
// ▶️ Ficha do jogador
// ========================================================
bot.command("criarficha", (ctx) => {
  const nome = ctx.message.text.split(" ").slice(1).join(" ");
  if (!nome) return ctx.reply("❌ Use: /criarficha <nome>");

  fichas[ctx.from.id] = { nome, pv: 10, inventario: [] };
  ctx.reply(`✅ Ficha criada para *${nome}*!`, { parse_mode: "Markdown" });
});

bot.command("ficha", (ctx) => {
  const ficha = fichas[ctx.from.id];
  if (!ficha) return ctx.reply("❌ Você não tem ficha. Use /criarficha <nome>.");

  ctx.reply(
    `📜 *Ficha de ${ficha.nome}*\n❤️ PV: ${ficha.pv}\n🎒 Itens: ${ficha.inventario.join(", ") || "nenhum"}`,
    { parse_mode: "Markdown" }
  );
});

bot.command("additem", (ctx) => {
  const item = ctx.message.text.split(" ").slice(1).join(" ");
  const ficha = fichas[ctx.from.id];
  if (!ficha) return ctx.reply("❌ Crie uma ficha primeiro com /criarficha <nome>.");
  if (!item) return ctx.reply("❌ Use: /additem <item>");

  ficha.inventario.push(item);
  ctx.reply(`✅ Item *${item}* adicionado à ficha de ${ficha.nome}.`, { parse_mode: "Markdown" });
});

// ========================================================
// ▶️ PV, Dano e Cura
// ========================================================
bot.command("dano", (ctx) => {
  const valor = parseInt(ctx.message.text.split(" ")[1]);
  const ficha = fichas[ctx.from.id];
  if (!ficha) return ctx.reply("❌ Crie uma ficha primeiro.");
  if (!valor) return ctx.reply("❌ Use: /dano <valor>");

  ficha.pv -= valor;
  ctx.reply(`💔 ${ficha.nome} sofreu *${valor}* de dano. PV atual: ${ficha.pv}`, { parse_mode: "Markdown" });
});

bot.command("cura", (ctx) => {
  const valor = parseInt(ctx.message.text.split(" ")[1]);
  const ficha = fichas[ctx.from.id];
  if (!ficha) return ctx.reply("❌ Crie uma ficha primeiro.");
  if (!valor) return ctx.reply("❌ Use: /cura <valor>");

  ficha.pv += valor;
  ctx.reply(`💚 ${ficha.nome} recuperou *${valor}* PV. PV atual: ${ficha.pv}`, { parse_mode: "Markdown" });
});

// ========================================================
// ▶️ Magias e Monstros (API D&D 5e)
// ========================================================
bot.command("magia", async (ctx) => {
  const nome = ctx.message.text.split(" ").slice(1).join("-").toLowerCase();
  if (!nome) return ctx.reply("❌ Use: /magia <nome>");

  try {
    const { data } = await axios.get(`https://www.dnd5eapi.co/api/spells/${nome}`);
    ctx.reply(`✨ *${data.name}*\n${data.desc.join("\n")}`, { parse_mode: "Markdown" });
  } catch {
    ctx.reply("❌ Magia não encontrada.");
  }
});

bot.command("monstro", async (ctx) => {
  const nome = ctx.message.text.split(" ").slice(1).join("-").toLowerCase();
  if (!nome) return ctx.reply("❌ Use: /monstro <nome>");

  try {
    const { data } = await axios.get(`https://www.dnd5eapi.co/api/monsters/${nome}`);
    ctx.reply(
      `👹 *${data.name}*\nCA: ${data.armor_class[0].value}\nPV: ${data.hit_points}\nTipo: ${data.type}`,
      { parse_mode: "Markdown" }
    );
  } catch {
    ctx.reply("❌ Monstro não encontrado.");
  }
});

// ========================================================
// ▶️ Combate
// ========================================================
bot.command("iniciativa", (ctx) => {
  const ficha = fichas[ctx.from.id];
  if (!ficha) return ctx.reply("❌ Crie uma ficha primeiro.");

  const iniciativa = Math.floor(Math.random() * 20) + 1;
  combate.ordem.push({ jogador: ficha.nome, iniciativa });
  combate.ordem.sort((a, b) => b.iniciativa - a.iniciativa);

  ctx.reply(`⚔️ ${ficha.nome} rolou iniciativa: *${iniciativa}*`, { parse_mode: "Markdown" });
});

bot.command("proximo", (ctx) => {
  if (combate.ordem.length === 0) return ctx.reply("❌ Nenhum combate iniciado.");

  const atual = combate.ordem[combate.turno % combate.ordem.length];
  combate.turno++;
  ctx.reply(`👉 Turno de *${atual.jogador}* (Iniciativa: ${atual.iniciativa})`, { parse_mode: "Markdown" });
});

// ========================================================
// ▶️ Narração
// ========================================================
bot.command("narrar", (ctx) => {
  const texto = ctx.message.text.split(" ").slice(1).join(" ");
  if (!texto) return ctx.reply("❌ Use: /narrar <texto>");

  ctx.reply(`🎭 *Narrador*: ${texto}`, { parse_mode: "Markdown" });
});

// ========================================================
// ▶️ Webhook (Render)
// ========================================================
if (process.env.RENDER) {
  const express = require("express");
  const app = express();
  app.use(bot.webhookCallback(`/webhook/${BOT_TOKEN}`));
  app.get("/", (req, res) => res.send("RPG Bot ativo ✅"));
  app.listen(process.env.PORT || 3000, () => {
    bot.telegram.setWebhook(`${process.env.RENDER_EXTERNAL_URL}/webhook/${BOT_TOKEN}`);
    console.log("🚀 Bot rodando via Webhook");
  });
} else {
  bot.launch();
  console.log("🚀 Bot rodando em modo polling");
      }
