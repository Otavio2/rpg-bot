# 🤖 Matheus Bot - SuperBot Telegram + IA Gratuita

Bot de Telegram com IA usando `openrouter/free`. Roda 24/7 no Render, responde texto e imagem, tem memória e funciona em grupo e PV.

Criado por: **Kleber**  
Modelo: **Matheus v2.4**

## ✨ Funcionalidades

- **100% Gratuito**: Usa `openrouter/free`. Zero custo.
- **Memória**: Lembra das últimas 10 msgs no PV e 6 msgs por grupo
- **Modo Hansel Inteligente**: Em grupo só responde se for marcado, falar o nome ou responder ele
- **Visão**: Analisa e descreve fotos enviadas
- **Comandos**: /start /ajuda /limpar /status /hora /admin
- **Anti-spam**: Cooldown de 2s por usuário
- **Fuso Horário**: America/Fortaleza - Sobral/CE
- **Robusto**: Retry automático, anti-duplicado, logs completos

## 🚀 Deploy no Render

### 1. Requisitos
- Conta no Render.com
- Bot criado no @BotFather do Telegram
- Conta na OpenRouter.ai com API Key

### 2. Variáveis de Ambiente
No Render, vá em `Environment` e adicione:

| Variável | Valor | Onde pegar |
| --- | --- | --- |
| `TELEGRAM_TOKEN` | `12345:ABC...` | @BotFather |
| `OPENROUTER_API_KEY` | `sk-or-v1-...` | https://openrouter.ai/keys |

### 3. Config do Render
1.  **New +** > **Web Service**
2.  **Connect GitHub** e selecione o repo
