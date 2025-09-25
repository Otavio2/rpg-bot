const express = require('express');
const axios = require('axios');
const { DiceRoll } = require('@dice-roller/rpg-dice-roller');
const { Telegraf } = require('telegraf');
const fs = require('fs');

const BOT_TOKEN = process.env.BOT_TOKEN;
if (!BOT_TOKEN) {
  throw new Error("⚠️ Defina a variável BOT_TOKEN com o token do seu bot do Telegram.");
}

const bot = new Telegraf(BOT_TOKEN);

// 📌 Carregar fichas do arquivo
let fichas = {};
const FICHAS_FILE = './fichas.json';

function carregarFichas() {
  try {
    if (fs.existsSync(FICHAS_FILE)) {
      fichas = JSON.parse(fs.readFileSync(FICHAS_FILE, 'utf-8'));
      console.log("📂 Fichas carregadas do arquivo.");
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

// ▶️ /start
bot.start((ctx) => {
  ctx.reply('🎲 Bem-vindo ao RPG Bot!\n\nComandos disponíveis:\n' +
            '/rolar <dado>\n/magia <nome>\n/monstro <nome>\n/ficha\n/criarficha <nome>\n/additem <item>');
});

// 🎲 /rolar
bot.command('rolar', (ctx) => {
  const args = ctx.message.text.split(' ').slice(1).join(' ');
  if (!args) return ctx.reply('Use: /rolar <notação>, ex: /rolar 1d20+5');
  try {
    const roll = new DiceRoll(args);
    ctx.reply(`🎲 Resultado: *${roll.total}*\nDetalhes: ${roll.output}`, { parse_mode: 'Markdown' });
  } catch {
    ctx.reply('❌ Notação inválida. Exemplo: /rolar 2d6+3');
  }
});

// ✨ /magia
bot.command('magia', async (ctx) => {
  const name = ctx.message.text.split(' ').slice(1).join(' ');
  if (!name) return ctx.reply('Use: /magia <nome da magia>');
  try {
    const url = `https://www.dnd5eapi.co/api/spells/${name.toLowerCase().replace(/ /g, '-')}`;
    const { data } = await axios.get(url);
    ctx.replyWithMarkdown(`✨ *${data.name}*\nEscola: ${data.school.name}\n\n${data.desc.join('\n')}`);
  } catch {
    ctx.reply('❌ Magia não encontrada.');
  }
});

// 👹 /monstro
bot.command('monstro', async (ctx) => {
  const name = ctx.message.text.split(' ').slice(1).join(' ');
  if (!name) return ctx.reply('Use: /monstro <nome do monstro>');
  try {
    const url = `https://www.dnd5eapi.co/api/monsters/${name.toLowerCase().replace(/ /g, '-')}`;
    const { data } = await axios.get(url);
    ctx.replyWithMarkdown(`👹 *${data.name}*\nTipo: ${data.type}\nPV: ${data.hit_points}\nCA: ${data.armor_class}`);
  } catch {
    ctx.reply('❌ Monstro não encontrado.');
  }
});

// 📝 /criarficha <nome>
bot.command('criarficha', (ctx) => {
  const userId = ctx.from.id;
  const nome = ctx.message.text.split(' ').slice(1).join(' ');
  if (!nome) return ctx.reply('Use: /criarficha <nome do personagem>');

  fichas[userId] = {
    nome,
    pv: 10,
    forca: 10,
    destreza: 10,
    inteligencia: 10,
    inventario: []
  };

  salvarFichas();
  ctx.reply(`📜 Ficha criada para *${nome}*! Use /ficha para ver seus status.`, { parse_mode: 'Markdown' });
});

// 📜 /ficha
bot.command('ficha', (ctx) => {
  const userId = ctx.from.id;
  if (!fichas[userId]) return ctx.reply('❌ Você não tem uma ficha. Use /criarficha <nome>.');

  const f = fichas[userId];
  ctx.replyWithMarkdown(
    `📜 *Ficha de ${f.nome}*\n` +
    `❤️ PV: ${f.pv}\n💪 Força: ${f.forca}\n🏹 Destreza: ${f.destreza}\n🧠 Inteligência: ${f.inteligencia}\n\n` +
    `🎒 Inventário: ${f.inventario.length ? f.inventario.join(', ') : 'vazio'}`
  );
});

// 🎒 /additem <item>
bot.command('additem', (ctx) => {
  const userId = ctx.from.id;
  if (!fichas[userId]) return ctx.reply('❌ Crie uma ficha primeiro com /criarficha <nome>.');

  const item = ctx.message.text.split(' ').slice(1).join(' ');
  if (!item) return ctx.reply('Use: /additem <nome do item>');

  fichas[userId].inventario.push(item);
  salvarFichas();
  ctx.reply(`✅ Item *${item}* adicionado ao inventário de ${fichas[userId].nome}.`, { parse_mode: 'Markdown' });
});

// ⚙️ Configuração para Render
const app = express();
app.use(bot.webhookCallback('/webhook'));

const PORT = process.env.PORT || 3000;
app.listen(PORT, async () => {
  const url = `https://${process.env.RENDER_EXTERNAL_URL || 'SEU-APP.onrender.com'}/webhook`;
  try {
    await bot.telegram.setWebhook(url);
    console.log(`🚀 Bot rodando na porta ${PORT}, webhook registrado em ${url}`);
  } catch (e) {
    console.error('❌ Erro ao registrar webhook:', e.message);
  }
});
