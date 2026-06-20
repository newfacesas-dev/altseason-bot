import asyncio
import logging
import requests
from openai import OpenAI
import redis as redis_lib
import pandas as pd
import time
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

# ============================================================
# CONFIGURAZIONE
# ============================================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ADMIN_ID = "670903243"

# ============================================================
# TRADUZIONI IT / EN / PT-BR
# ============================================================
T = {
    "it": {
        "welcome": lambda name: (
            "\U0001f44b *Benvenuto " + name + "!*\n\n"
            "\U0001f916 Sono il tuo *consulente AI nel mondo crypto*.\n\n"
            "Ecco cosa posso fare per te:\n\n"
            "\U0001f4ca *MERCATO* \u2014 Status, Fase, Fear&Greed, RSI\n"
            "\U0001f4bc *PORTFOLIO* \u2014 P&L in tempo reale\n"
            "\U0001f514 *ALERT* \u2014 Notifiche automatiche sui tuoi target\n"
            "\U0001f916 *AI* \u2014 Rispondo a qualsiasi domanda\n"
            "\U0001f4b1 *FOREX* \u2014 EUR/USD, oro, S&P500\n\n"
            "\U0001f193 *Piano attuale: Free*\n"
            "\u2022 5 messaggi AI al giorno\n"
            "\u2022 Tutti i dati di mercato inclusi\n\n"
            "\U0001f4a1 *Inizia subito:*\n"
            "1\u20e3 Premi \U0001f4ca *Status* per vedere il mercato\n"
            "2\u20e3 Premi \u2699\ufe0f *Setup Alert* per i 28 alert strategici\n"
            "3\u20e3 Scrivi qualsiasi domanda per parlare con l'AI\n\n"
            "\u26a0\ufe0f _Solo scopo informativo. Non e consulenza finanziaria._"
        ),
        "portfolio_empty": "\U0001f4bc Portfolio vuoto!\n\nUsa /add per aggiungere le tue coin\noppure /reset per caricare il portfolio di default",
        "status_loading": "\u23f3 Recupero dati...",
        "news_loading": "\u23f3 Recupero notizie...",
        "forex_loading": "\u23f3 Recupero dati forex...",
        "rsi_loading": "\u23f3 Calcolo indicatori...",
        "no_alerts": "Nessun alert. Usa /setup per impostare tutti",
        "alert_added": lambda s, t, d: "\u2705 Alert: *" + s + "* " + d + " `$" + "{:,.2f}".format(t) + "`",
        "alert_deleted": lambda s: "\u2705 Eliminato: " + s,
        "alert_invalid": "\u274c Numero non valido",
        "setup_done": lambda n: "\u2705 *" + str(n) + " alert impostati!*\n\nXRP: $3\u2192$5\u2192$8\u2192$12\nSOL: $200\u2192$350\u2192$500\u2192$800\nETH: $4k\u2192$6k\u2192$9k\u2192$14k",
        "reset_admin": lambda n: "\u2705 Portfolio admin caricato!\n" + str(n) + " coin \u2014 Piano Pro",
        "reset_user": "\u2705 Portfolio resettato!\nUsa /add per aggiungere le tue coin",
        "coin_added": lambda s, q, p, i: "\u2705 *" + s + " aggiunto!*\n\n\u2022 Quantita: `" + str(q) + "`\n\u2022 Prezzo: `$" + "{:,.4f}".format(p) + "`\n\u2022 Investito: `$" + "{:,.2f}".format(i) + "`\n\nScrivi /portfolio per vedere il P&L",
        "coin_removed": lambda s: "\u2705 " + s + " rimosso",
        "coin_not_found": lambda s: "\u274c " + s + " non trovato",
        "myplan_free_upgrade": "\u2b06\ufe0f *Vuoi piu messaggi AI?*\n\n\U0001f499 *Basic* \u20ac12.99/mese \u2192 50 msg/giorno\n\U0001f451 *Pro* \u20ac25.99/mese \u2192 Illimitati\n\nScrivi /upgrade per info",
        "ai_limit": lambda l: "\u26a0\ufe0f Hai usato tutti i " + str(l) + " messaggi AI del piano Free.\n\nUpgrada a Basic (50 msg) o Pro (illimitati)!\n\n/upgrade per info",
        "ai_thinking": lambda u, l: "\U0001f916 Sto analizzando... (" + str(u) + "/" + str(l) + ")",
        "above": "sale a", "below": "scende a",
        "news_empty": "\u274c Nessuna notizia disponibile al momento",
        "forex_empty": "\u274c Dati forex non disponibili",
        "plan_activated": lambda p: "\U0001f389 *Piano attivato!*\n\nIl tuo piano *" + p + "* e ora attivo!\n\nGrazie per esserti abbonato! \U0001f680",
        "quiet_on": "\U0001f319 No Disturb ATTIVO \u2014 nessuna notifica 23:00-08:00",
        "quiet_off": "\u2600\ufe0f No Disturb DISATTIVO",
        "wizard_select": "\U0001f4bc *AGGIUNGI AL PORTFOLIO*\n\nSeleziona la coin:",
        "wizard_qty": lambda c: "\u2705 Coin: *" + c + "*\n\nQuante ne hai?",
        "wizard_price": lambda q: "\u2705 Quantita: *" + str(q) + "*\n\nA quanto hai comprato in media ($)?\n(Scrivi 0 per usare il prezzo attuale)",
        "wizard_invalid_coin": lambda c, assets: "\u274c *" + c + "* non trovata.\nCoin disponibili: " + ", ".join(list(assets)[:10]) + "...",
        "wizard_cancel": "\u274c Operazione annullata",
        "access_denied": "\u274c Accesso negato",
    },
    "en": {
        "welcome": lambda name: (
            "\U0001f44b *Welcome " + name + "!*\n\n"
            "\U0001f916 I am your *personal AI advisor in the crypto world*.\n\n"
            "Here's what I can do for you:\n\n"
            "\U0001f4ca *MARKET* \u2014 Status, Phase, Fear&Greed, RSI\n"
            "\U0001f4bc *PORTFOLIO* \u2014 Real-time P&L\n"
            "\U0001f514 *ALERTS* \u2014 Automatic price notifications\n"
            "\U0001f916 *AI* \u2014 I answer any question\n"
            "\U0001f4b1 *FOREX* \u2014 EUR/USD, gold, S&P500\n\n"
            "\U0001f193 *Current plan: Free*\n"
            "\u2022 5 AI messages per day\n"
            "\u2022 All market data included\n\n"
            "\U0001f4a1 *Get started:*\n"
            "1\u20e3 Press \U0001f4ca *Status* to see the market\n"
            "2\u20e3 Press \u2699\ufe0f *Setup Alerts* for 28 strategic alerts\n"
            "3\u20e3 Write any question to talk to the AI\n\n"
            "\u26a0\ufe0f _For informational purposes only. Not financial advice._"
        ),
        "portfolio_empty": "\U0001f4bc Portfolio empty!\n\nUse /add to add your coins\nor /reset to load the default portfolio",
        "status_loading": "\u23f3 Fetching data...",
        "news_loading": "\u23f3 Fetching news...",
        "forex_loading": "\u23f3 Fetching forex data...",
        "rsi_loading": "\u23f3 Calculating indicators...",
        "no_alerts": "No alerts. Use /setup to set them all",
        "alert_added": lambda s, t, d: "\u2705 Alert: *" + s + "* " + d + " `$" + "{:,.2f}".format(t) + "`",
        "alert_deleted": lambda s: "\u2705 Deleted: " + s,
        "alert_invalid": "\u274c Invalid number",
        "setup_done": lambda n: "\u2705 *" + str(n) + " alerts set!*\n\nXRP: $3\u2192$5\u2192$8\u2192$12\nSOL: $200\u2192$350\u2192$500\u2192$800\nETH: $4k\u2192$6k\u2192$9k\u2192$14k",
        "reset_admin": lambda n: "\u2705 Admin portfolio loaded!\n" + str(n) + " coins \u2014 Pro plan",
        "reset_user": "\u2705 Portfolio reset!\nUse /add to add your coins",
        "coin_added": lambda s, q, p, i: "\u2705 *" + s + " added!*\n\n\u2022 Quantity: `" + str(q) + "`\n\u2022 Price: `$" + "{:,.4f}".format(p) + "`\n\u2022 Invested: `$" + "{:,.2f}".format(i) + "`\n\nType /portfolio to see your P&L",
        "coin_removed": lambda s: "\u2705 " + s + " removed",
        "coin_not_found": lambda s: "\u274c " + s + " not found",
        "myplan_free_upgrade": "\u2b06\ufe0f *Want more AI messages?*\n\n\U0001f499 *Basic* \u20ac12.99/month \u2192 50 msg/day\n\U0001f451 *Pro* \u20ac25.99/month \u2192 Unlimited\n\nType /upgrade for info",
        "ai_limit": lambda l: "\u26a0\ufe0f You've used all " + str(l) + " AI messages on the Free plan.\n\nUpgrade to Basic (50 msg) or Pro (unlimited)!\n\n/upgrade for info",
        "ai_thinking": lambda u, l: "\U0001f916 Analyzing... (" + str(u) + "/" + str(l) + ")",
        "above": "rises to", "below": "drops to",
        "news_empty": "\u274c No news available at the moment",
        "forex_empty": "\u274c Forex data unavailable",
        "plan_activated": lambda p: "\U0001f389 *Plan activated!*\n\nYour *" + p + "* plan is now active!\n\nThank you for subscribing! \U0001f680",
        "quiet_on": "\U0001f319 Do Not Disturb ON \u2014 no notifications 23:00-08:00",
        "quiet_off": "\u2600\ufe0f Do Not Disturb OFF",
        "wizard_select": "\U0001f4bc *ADD TO PORTFOLIO*\n\nSelect the coin:",
        "wizard_qty": lambda c: "\u2705 Coin: *" + c + "*\n\nHow many do you have?",
        "wizard_price": lambda q: "\u2705 Quantity: *" + str(q) + "*\n\nAverage buy price ($)?\n(Type 0 to use current price)",
        "wizard_invalid_coin": lambda c, assets: "\u274c *" + c + "* not found.\nAvailable: " + ", ".join(list(assets)[:10]) + "...",
        "wizard_cancel": "\u274c Operation cancelled",
        "access_denied": "\u274c Access denied",
    },
    "pt": {
        "welcome": lambda name: (
            "\U0001f44b *Bem-vindo " + name + "!*\n\n"
            "\U0001f916 Sou seu *consultor AI pessoal no mundo crypto*.\n\n"
            "Veja o que posso fazer por voce:\n\n"
            "\U0001f4ca *MERCADO* \u2014 Status, Fase, Fear&Greed, RSI\n"
            "\U0001f4bc *PORTFOLIO* \u2014 P&L em tempo real\n"
            "\U0001f514 *ALERTAS* \u2014 Notificacoes automaticas de preco\n"
            "\U0001f916 *AI* \u2014 Respondo qualquer pergunta\n"
            "\U0001f4b1 *FOREX* \u2014 EUR/USD, ouro, S&P500\n\n"
            "\U0001f193 *Plano atual: Gratuito*\n"
            "\u2022 5 mensagens AI por dia\n"
            "\u2022 Todos os dados de mercado incluidos\n\n"
            "\U0001f4a1 *Comece agora:*\n"
            "1\u20e3 Pressione \U0001f4ca *Status* para ver o mercado\n"
            "2\u20e3 Pressione \u2699\ufe0f *Setup Alert* para 28 alertas estrategicos\n"
            "3\u20e3 Escreva qualquer pergunta para falar com o AI\n\n"
            "\u26a0\ufe0f _Apenas informativo. Nao e aconselhamento financeiro._"
        ),
        "portfolio_empty": "\U0001f4bc Portfolio vazio!\n\nUse /add para adicionar suas moedas\nou /reset para carregar o portfolio padrao",
        "status_loading": "\u23f3 Buscando dados...",
        "news_loading": "\u23f3 Buscando noticias...",
        "forex_loading": "\u23f3 Buscando dados forex...",
        "rsi_loading": "\u23f3 Calculando indicadores...",
        "no_alerts": "Nenhum alerta. Use /setup para configurar todos",
        "alert_added": lambda s, t, d: "\u2705 Alerta: *" + s + "* " + d + " `$" + "{:,.2f}".format(t) + "`",
        "alert_deleted": lambda s: "\u2705 Deletado: " + s,
        "alert_invalid": "\u274c Numero invalido",
        "setup_done": lambda n: "\u2705 *" + str(n) + " alertas configurados!*\n\nXRP: $3\u2192$5\u2192$8\u2192$12\nSOL: $200\u2192$350\u2192$500\u2192$800\nETH: $4k\u2192$6k\u2192$9k\u2192$14k",
        "reset_admin": lambda n: "\u2705 Portfolio admin carregado!\n" + str(n) + " moedas \u2014 Plano Pro",
        "reset_user": "\u2705 Portfolio resetado!\nUse /add para adicionar suas moedas",
        "coin_added": lambda s, q, p, i: "\u2705 *" + s + " adicionado!*\n\n\u2022 Quantidade: `" + str(q) + "`\n\u2022 Preco: `$" + "{:,.4f}".format(p) + "`\n\u2022 Investido: `$" + "{:,.2f}".format(i) + "`\n\nDigite /portfolio para ver seu P&L",
        "coin_removed": lambda s: "\u2705 " + s + " removido",
        "coin_not_found": lambda s: "\u274c " + s + " nao encontrado",
        "myplan_free_upgrade": "\u2b06\ufe0f *Quer mais mensagens AI?*\n\n\U0001f499 *Basic* \u20ac12.99/mes \u2192 50 msg/dia\n\U0001f451 *Pro* \u20ac25.99/mes \u2192 Ilimitado\n\nDigite /upgrade para info",
        "ai_limit": lambda l: "\u26a0\ufe0f Voce usou todas as " + str(l) + " mensagens AI do plano Gratuito.\n\nFaca upgrade para Basic (50 msg) ou Pro (ilimitado)!\n\n/upgrade para info",
        "ai_thinking": lambda u, l: "\U0001f916 Analisando... (" + str(u) + "/" + str(l) + ")",
        "above": "sobe para", "below": "cai para",
        "news_empty": "\u274c Nenhuma noticia disponivel no momento",
        "forex_empty": "\u274c Dados forex indisponiveis",
        "plan_activated": lambda p: "\U0001f389 *Plano ativado!*\n\nSeu plano *" + p + "* esta ativo agora!\n\nObrigado por assinar! \U0001f680",
        "quiet_on": "\U0001f319 Nao Perturbe ATIVO \u2014 sem notificacoes 23:00-08:00",
        "quiet_off": "\u2600\ufe0f Nao Perturbe DESATIVADO",
        "wizard_select": "\U0001f4bc *ADICIONAR AO PORTFOLIO*\n\nSelecione a moeda:",
        "wizard_qty": lambda c: "\u2705 Moeda: *" + c + "*\n\nQuantas voce tem?",
        "wizard_price": lambda q: "\u2705 Quantidade: *" + str(q) + "*\n\nPreco medio de compra ($)?\n(Digite 0 para usar o preco atual)",
        "wizard_invalid_coin": lambda c, assets: "\u274c *" + c + "* nao encontrada.\nDisponiveis: " + ", ".join(list(assets)[:10]) + "...",
        "wizard_cancel": "\u274c Operacao cancelada",
        "access_denied": "\u274c Acesso negado",
    }
}

def t(uid, key, *args):
    ud = load_user(uid)
    lang = ud.get("lang", "it")
    val = T.get(lang, T["it"]).get(key, T["it"].get(key, key))
    if callable(val):
        return val(*args)
    return val


CHAT_ID = "670903243"
CHECK_INTERVAL = 1800
BTC_DOM_THRESHOLD = 52.0
BTC_DOM_WARNING = 48.0
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 70
VOLUME_SPIKE = 2.0
QUIET_START = 23
QUIET_END = 8
AI_LIMITS = {"free": 5, "basic": 50, "pro": 999}

ADMIN_PORTFOLIO = {
    # Coin con prezzo d'acquisto reale (P&L vero)
    "XRP": {"qty": 22573, "buy": 1.36},
    "SOL": {"qty": 208.33, "buy": 85.9},
    "ETH": {"qty": 10.45, "buy": 2117},
    "DOGE": {"qty": 31128.9, "buy": 0.10},
    "BNB": {"qty": 5.05, "buy": 590},
    "HBAR": {"qty": 14686.06, "buy": 0.07},
    "BONK": {"qty": 161816078, "buy": 0.000006},
    "SEI": {"qty": 13723.39, "buy": 0.40},
    "FET": {"qty": 3223.11, "buy": 0.21},
    "GRT": {"qty": 43036.4, "buy": 0.12},
    # Coin nuove: buy=None -> al /reset viene messo il prezzo attuale (P&L da zero)
    "ADA": {"qty": 4996.03, "buy": None},
    "AGIX": {"qty": 6900, "buy": None},
    "ALGO": {"qty": 14606.8, "buy": None},
    "MANA": {"qty": 1186.94, "buy": None},
    "NEAR": {"qty": 379.379, "buy": None},
    "POL": {"qty": 24281.1, "buy": None},
    "TRX": {"qty": 5437.16, "buy": None},
    "XLM": {"qty": 13136.3, "buy": None},
}

ASSETS = {
    "BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "SOL": "solana",
    "ADA": "cardano", "DOGE": "dogecoin", "BNB": "binancecoin",
    "HBAR": "hedera-hashgraph", "BONK": "bonk", "ALGO": "algorand",
    "XLM": "stellar", "POL": "polygon-ecosystem-token", "TRX": "tron",
    "GRT": "the-graph", "NEAR": "near", "FET": "fetch-ai",
    "SEI": "sei-network", "LUNA": "terra-luna-2", "MANA": "decentraland",
    "PEPE": "pepe", "SHIB": "shiba-inu", "AGIX": "singularitynet",
    "RENDER": "render-token", "INJ": "injective-protocol", "TIA": "celestia",
}

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)
_cache = {}
CACHE_TTL = 600

# ============================================================
# KEYBOARD
# ============================================================
KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("📊 Status"), KeyboardButton("🎯 Fase")],
    [KeyboardButton("😱 Fear & Greed"), KeyboardButton("📉 RSI & MACD")],
    [KeyboardButton("🏆 Top Performer"), KeyboardButton("💱 Forex & Indici")],
    [KeyboardButton("📰 News"), KeyboardButton("📅 Timeline")],
    [KeyboardButton("💼 Portfolio"), KeyboardButton("💹 Aggiungi Coin")],
    [KeyboardButton("🔔 I miei Alert"), KeyboardButton("⚙️ Setup Alert")],
    [KeyboardButton("📤 Piano Uscita"), KeyboardButton("📊 Sentiment & Contesto")],
    [KeyboardButton("🤖 Chiedi AI"), KeyboardButton("📊 Il mio piano")],
    [KeyboardButton("💳 Abbonati"), KeyboardButton("🔗 Referral")],
    [KeyboardButton("📢 Condividi"), KeyboardButton("🔧 Admin")],
    [KeyboardButton("❓ Aiuto")],
], resize_keyboard=True)

# ============================================================
# KEYBOARD MULTILINGUA
# ============================================================
def get_keyboard(lang="it"):
    if lang == "en":
        return ReplyKeyboardMarkup([
            [KeyboardButton("📊 Status"), KeyboardButton("🎯 Phase")],
            [KeyboardButton("😱 Fear & Greed"), KeyboardButton("📉 RSI & MACD")],
            [KeyboardButton("🏆 Top Performers"), KeyboardButton("💱 Forex & Indices")],
            [KeyboardButton("📰 News"), KeyboardButton("📅 Timeline")],
            [KeyboardButton("💼 Portfolio"), KeyboardButton("💹 Add Coin")],
            [KeyboardButton("🔔 My Alerts"), KeyboardButton("⚙️ Setup Alerts")],
            [KeyboardButton("📤 Exit Plan"), KeyboardButton("📊 Sentiment & Context")],
            [KeyboardButton("🤖 Ask AI"), KeyboardButton("📊 My Plan")],
            [KeyboardButton("💳 Subscribe"), KeyboardButton("🔗 Referral")],
            [KeyboardButton("📢 Share"), KeyboardButton("🔧 Admin")],
            [KeyboardButton("❓ Help")],
        ], resize_keyboard=True)
    elif lang == "pt":
        return ReplyKeyboardMarkup([
            [KeyboardButton("📊 Status"), KeyboardButton("🎯 Fase")],
            [KeyboardButton("😱 Fear & Greed"), KeyboardButton("📉 RSI & MACD")],
            [KeyboardButton("🏆 Top Performers"), KeyboardButton("💱 Forex & Indices")],
            [KeyboardButton("📰 Noticias"), KeyboardButton("📅 Timeline")],
            [KeyboardButton("💼 Portfolio"), KeyboardButton("💹 Adicionar Moeda")],
            [KeyboardButton("🔔 Meus Alertas"), KeyboardButton("⚙️ Config Alertas")],
            [KeyboardButton("📤 Plano de Saida"), KeyboardButton("📊 Sentimento & Contexto")],
            [KeyboardButton("🤖 Perguntar AI"), KeyboardButton("📊 Meu Plano")],
            [KeyboardButton("💳 Assinar"), KeyboardButton("🔗 Referral")],
            [KeyboardButton("📢 Compartilhar"), KeyboardButton("🔧 Admin")],
            [KeyboardButton("❓ Ajuda")],
        ], resize_keyboard=True)
    else:  # it default
        return ReplyKeyboardMarkup([
            [KeyboardButton("📊 Status"), KeyboardButton("🎯 Fase")],
            [KeyboardButton("😱 Fear & Greed"), KeyboardButton("📉 RSI & MACD")],
            [KeyboardButton("🏆 Top Performer"), KeyboardButton("💱 Forex & Indici")],
            [KeyboardButton("📰 News"), KeyboardButton("📅 Timeline")],
            [KeyboardButton("💼 Portfolio"), KeyboardButton("💹 Aggiungi Coin")],
            [KeyboardButton("🔔 I miei Alert"), KeyboardButton("⚙️ Setup Alert")],
            [KeyboardButton("📤 Piano Uscita"), KeyboardButton("📊 Sentiment & Contesto")],
            [KeyboardButton("🤖 Chiedi AI"), KeyboardButton("📊 Il mio piano")],
            [KeyboardButton("💳 Abbonati"), KeyboardButton("🔗 Referral")],
            [KeyboardButton("📢 Condividi"), KeyboardButton("🔧 Admin")],
            [KeyboardButton("❓ Aiuto")],
        ], resize_keyboard=True)

def kb(uid):
    ud = load_user(uid)
    return get_keyboard(ud.get("lang", "it"))


async def cmd_stato_dati(u, c):
    """Mostra lo stato della raccolta snapshot (sola lettura). Solo admin.
    Legge /data/snapshots.jsonl: quanti, primo, ultimo. Crash-safe."""
    uid = get_uid(u)
    if str(uid) != ADMIN_ID:
        await u.message.reply_text("Comando riservato.", reply_markup=kb(uid))
        return
    try:
        import json as _json
        path = "/data/snapshots.jsonl"
        if not os.path.exists(path):
            await u.message.reply_text("Nessuno snapshot ancora raccolto.", reply_markup=kb(uid))
            return
        n = 0
        primo = None
        ultimo = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                n += 1
                try:
                    d = _json.loads(line)
                    ts = d.get("timestamp_utc", "")
                    if ts:
                        if primo is None:
                            primo = ts
                        ultimo = ts
                except Exception:
                    continue
        def _fmt_ts(ts):
            try:
                from datetime import datetime as _dt
                dt = _dt.fromisoformat(ts)
                return dt.strftime("%d/%m/%Y %H:%M UTC")
            except Exception:
                return ts or "n/d"
        msg = (
            "STATO RACCOLTA DATI\n\n"
            f"Snapshot raccolti: {n}\n"
            f"Primo: {_fmt_ts(primo)}\n"
            f"Ultimo: {_fmt_ts(ultimo)}"
        )
        await u.message.reply_text(msg, reply_markup=kb(uid))
    except Exception as e:
        log.warning(f"cmd_stato_dati error: {e}")
        await u.message.reply_text("Errore lettura snapshot.", reply_markup=kb(uid))


ADMIN_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("👥 I miei Utenti"), KeyboardButton("📊 Stats Admin")],
    [KeyboardButton("💰 Ricavi"), KeyboardButton("🔙 Torna al Bot")],
    [KeyboardButton("📈 Stato Dati")],
], resize_keyboard=True)

# ============================================================
# REDIS / STORAGE
# ============================================================
def get_redis():
    try:
        url = os.environ.get("REDIS_URL", "")
        if url:
            return redis_lib.from_url(url, decode_responses=True)
    except: pass
    return None

def load_user(chat_id):
    try:
        r = get_redis()
        if r:
            data = r.get(f"user:{chat_id}")
            if data:
                return json.loads(data)
    except: pass
    return {"portfolio": {}, "alerts": [], "quiet_mode": False, "plan": "free", "ai_msgs": 0, "referrals": 0, "ref_earnings": 0.0}

def save_user(chat_id, data):
    try:
        r = get_redis()
        if r:
            r.set(f"user:{chat_id}", json.dumps(data))
    except Exception as e:
        log.error(f"Save error: {e}")

def list_users():
    try:
        r = get_redis()
        if r:
            keys = r.keys("user:*")
            return [k.replace("user:", "") for k in keys]
    except: pass
    return []

def get_uid(update):
    return str(update.message.chat_id)

# ============================================================
# API DATI
# ============================================================
def get_global():
    if 'g' in _cache and time.time() - _cache['g']['t'] < CACHE_TTL:
        return _cache['g']['d']
    try:
        time.sleep(1)
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        r.raise_for_status()
        d = r.json()["data"]
        tot = d["total_market_cap"]["usd"]
        btcm = d["market_cap_percentage"]["btc"] / 100 * tot
        ethm = d["market_cap_percentage"].get("eth", 0) / 100 * tot
        result = {"dom": d["market_cap_percentage"]["btc"], "dom_eth": d["market_cap_percentage"].get("eth", 0), "mcap": tot/1e12, "total2": (tot-btcm)/1e9, "total3": (tot-btcm-ethm)/1e9}
        _cache['g'] = {'d': result, 't': time.time()}
        return result
    except Exception as e:
        log.warning("get_global: errore CoinGecko (%s). Uso ultima cache se disponibile.", e)
        if 'g' in _cache:
            return _cache['g']['d']
        return {"dom": 58, "dom_eth": 0, "mcap": 2.5, "total2": 0, "total3": 0}

def get_prices():
    if 'p' in _cache and time.time() - _cache['p']['t'] < CACHE_TTL:
        return _cache['p']['d']
    try:
        time.sleep(2)
        ids = ",".join(ASSETS.values())
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true", timeout=10)
        r.raise_for_status()
        raw = r.json()
        result = {}
        for sym, cid in ASSETS.items():
            d = raw.get(cid, {})
            result[sym] = {"price": d.get("usd", 0), "ch": d.get("usd_24h_change", 0), "mcap": d.get("usd_market_cap", 0), "vol": d.get("usd_24h_vol", 0)}
        _cache['p'] = {'d': result, 't': time.time()}
        return result
    except Exception as e:
        log.warning("get_prices: errore CoinGecko (%s). Uso ultima cache se disponibile.", e)
        if 'p' in _cache:
            return _cache['p']['d']
        return {s: {"price": 0, "ch": 0, "mcap": 0, "vol": 0} for s in ASSETS}

def get_fg():
    if 'fg' in _cache and time.time() - _cache['fg']['t'] < CACHE_TTL:
        return _cache['fg']['d']
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        d = r.json()["data"][0]
        v = int(d["value"])
        em = "😱" if v <= 25 else "😰" if v <= 45 else "😐" if v <= 55 else "😊" if v <= 75 else "🤑"
        result = {"v": v, "lbl": d["value_classification"], "em": em}
        _cache['fg'] = {'d': result, 't': time.time()}
        return result
    except:
        return {"v": 50, "lbl": "Neutral", "em": "😐"}

_CG_OHLC_IDS = {"BTCUSDT": "bitcoin", "ETHUSDT": "ethereum", "SOLUSDT": "solana", "XRPUSDT": "ripple"}

def get_ohlc(symbol="BTCUSDT", limit=30):
    """Dati storici (close + volume) da CoinGecko market_chart.
    Binance e' geo-bloccato da Railway (451); CoinGecko no.
    Ritorna (closes, vols) come prima. Chiede 60gg per margine su RSI/MACD."""
    cg_id = _CG_OHLC_IDS.get(symbol)
    if not cg_id:
        return [], []
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=60&interval=daily"
        r = requests.get(url, timeout=12)
        r.raise_for_status()
        data = r.json()
        prices = data.get("prices", [])
        vols = data.get("total_volumes", [])
        closes = [float(p[1]) for p in prices if isinstance(p, (list, tuple)) and len(p) >= 2]
        volumes = [float(v[1]) for v in vols if isinstance(v, (list, tuple)) and len(v) >= 2]
        return closes, volumes
    except Exception as e:
        log.warning("get_ohlc: errore CoinGecko per %s (%s). Indicatori non disponibili.", symbol, e)
        return [], []

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    s = pd.Series(closes)
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return round(float((100 - (100 / (1 + rs))).iloc[-1]), 1)

def calc_macd(closes):
    if len(closes) < 26: return None, None, None
    s = pd.Series(closes)
    macd = s.ewm(span=12).mean() - s.ewm(span=26).mean()
    signal = macd.ewm(span=9).mean()
    hist = macd - signal
    return round(float(macd.iloc[-1]), 2), round(float(signal.iloc[-1]), 2), round(float(hist.iloc[-1]), 2)

# Cache in memoria per get_trend_7d (copre buchi di rate-limit CoinGecko).
# Additiva: se il calcolo riesce, comportamento identico a prima e aggiorna la cache.
# Se get_ohlc fallisce / dati insufficienti, riusa l'ultimo ethbtc valido (stale).
_TREND_CACHE = {"data": None, "ts": 0}
_TREND_CACHE_TTL = 3600  # 1h: oltre questo, lo stale e' troppo vecchio per essere usato

def get_trend_7d():
    """Trend a 7 giorni di ETH/BTC e dei prezzi principali, da get_ohlc (CoinGecko).
    Nessuna chiamata extra: riusa lo storico gia scaricato per RSI/MACD.
    Il trend dominance NON e incluso (storico globale CoinGecko a pagamento).
    CACHE: se il calcolo ethbtc riesce, aggiorna la cache. Se fallisce (rate-limit),
    riusa l'ultimo ethbtc valido dalla cache (marcato stale) entro _TREND_CACHE_TTL."""
    import time as _time
    out = {}
    try:
        btc_closes, _ = get_ohlc("BTCUSDT")
        eth_closes, _ = get_ohlc("ETHUSDT")
        if len(btc_closes) >= 8 and len(eth_closes) >= 8 and btc_closes[-1] and btc_closes[-8]:
            ratio_oggi = eth_closes[-1] / btc_closes[-1]
            ratio_7gg = eth_closes[-8] / btc_closes[-8]
            if ratio_7gg:
                var = (ratio_oggi - ratio_7gg) / ratio_7gg * 100
                desc = "in recupero" if var > 1.5 else "in calo" if var < -1.5 else "stabile"
                out["ethbtc"] = {"oggi": ratio_oggi, "var7d": var, "desc": desc}
        if len(btc_closes) >= 8 and btc_closes[-8]:
            out["btc"] = (btc_closes[-1] - btc_closes[-8]) / btc_closes[-8] * 100
        if len(eth_closes) >= 8 and eth_closes[-8]:
            out["eth"] = (eth_closes[-1] - eth_closes[-8]) / eth_closes[-8] * 100
    except Exception as e:
        log.warning(f"get_trend_7d error: {e}")

    # CACHE: se abbiamo ethbtc fresco, salviamo. Altrimenti proviamo il fallback stale.
    if out.get("ethbtc"):
        _TREND_CACHE["data"] = out["ethbtc"]
        _TREND_CACHE["ts"] = _time.time()
    else:
        # fallback: usa l'ultimo ethbtc valido se non troppo vecchio
        if _TREND_CACHE["data"] and (_time.time() - _TREND_CACHE["ts"]) < _TREND_CACHE_TTL:
            eb = dict(_TREND_CACHE["data"])
            eb["stale"] = True  # segnaliamo che e' un valore non fresco
            out["ethbtc"] = eb
    return out

def _fmt_trend(tr):
    """Formatta il trend 7gg per il contesto analisi."""
    if not tr:
        return "TREND 7 GIORNI: DATO NON DISPONIBILE"
    righe = ["TREND 7 GIORNI:"]
    if "ethbtc" in tr:
        e = tr["ethbtc"]
        if e["desc"] == "in recupero":
            nota = "(ETH guida su BTC, possibile rotazione alt)"
        elif e["desc"] == "in calo":
            nota = "(ETH non guida su BTC, rotazione alt lontana)"
        else:
            nota = "(nessuna direzione chiara)"
        righe.append(f"- ETH/BTC: {e['oggi']:.5f}, {e['desc']} ({e['var7d']:+.1f}% su 7gg) {nota}")
    if "btc" in tr:
        righe.append(f"- BTC prezzo: {tr['btc']:+.1f}% su 7gg")
    if "eth" in tr:
        righe.append(f"- ETH prezzo: {tr['eth']:+.1f}% su 7gg")
    return chr(10).join(righe)


def get_indicators():
    result = {}
    for sym, pair in [("BTC", "BTCUSDT"), ("ETH", "ETHUSDT")]:
        closes, vols = get_ohlc(pair)
        rsi = calc_rsi(closes)
        macd, signal, hist = calc_macd(closes)
        vol_spike = None
        if len(vols) >= 8:
            avg = sum(vols[-8:-1]) / 7
            if avg > 0 and vols[-1] > avg * VOLUME_SPIKE:
                vol_spike = round(vols[-1] / avg, 1)
        result[sym] = {"rsi": rsi, "macd": macd, "signal": signal, "hist": hist, "vol_spike": vol_spike}
    return result

def get_forex():
    if 'forex' in _cache and time.time() - _cache['forex']['t'] < 300:
        return _cache['forex']['d']
    try:
        symbols = {
            "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X",
            "USD/JPY": "JPY=X", "USD/CHF": "CHF=X",
            "AUD/USD": "AUDUSD=X", "XAU/USD": "GC=F",
            "XAG/USD": "SI=F", "S&P500": "^GSPC",
            "NASDAQ": "^IXIC", "DXY": "DX-Y.NYB",
        }
        result = {}
        for name, sym in symbols.items():
            try:
                r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2d", headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
                data = r.json()["chart"]["result"][0]
                closes = [c for c in data["indicators"]["quote"][0]["close"] if c is not None]
                if len(closes) >= 2:
                    price = closes[-1]
                    ch = ((price - closes[-2]) / closes[-2]) * 100
                    result[name] = {"price": price, "ch": ch}
            except: pass
        _cache['forex'] = {'d': result, 't': time.time()}
        return result
    except:
        return {}

def phase(dom):
    if dom < BTC_DOM_WARNING: return "🚨 USCITA", "TOP CICLO! Prendi profitto subito", "USCITA"
    if dom < BTC_DOM_THRESHOLD: return "⚡ ALTSEASON ATTIVA", "BTC Dom sotto 52% — ruota verso altcoin", "AZIONE"
    return "👀 ACCUMULO", f"BTC Dom {dom:.1f}% — tieni le posizioni", "MONITORA"

def _fmt_vol(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "n/d"
    if v <= 0:
        return "n/d"
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    return f"${v/1e3:.0f}K"


def get_derivatives():
    """Funding rate + open interest da Bybit v5 per BTC/ETH/SOL/XRP.
    Cache + fallback. Se Bybit non risponde, ritorna {} e il ctx mostra N/D."""
    if 'deriv' in _cache and time.time() - _cache['deriv']['t'] < CACHE_TTL:
        return _cache['deriv']['d']
    symbols = {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', 'SOL': 'SOLUSDT', 'XRP': 'XRPUSDT'}
    result = {}
    try:
        for sym, pair in symbols.items():
            url = f'https://api.bybit.com/v5/market/tickers?category=linear&symbol={pair}'
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            lst = r.json().get('result', {}).get('list', [])
            if lst:
                d = lst[0]
                fr = d.get('fundingRate')
                oi = d.get('openInterest')
                result[sym] = {
                    'funding': float(fr) * 100 if fr not in (None, '') else None,
                    'oi': float(oi) if oi not in (None, '') else None,
                }
        if result:
            log.info('get_derivatives: fonte Bybit OK')
            _cache['deriv'] = {'d': result, 't': time.time()}
        return result
    except Exception as e:
        log.warning('get_derivatives: Bybit fallito (%s). Provo CoinGecko fallback.', e)
        try:
            cg = get_derivatives_coingecko()
            if cg:
                log.info('get_derivatives: fonte CoinGecko OK (fallback)')
                _cache['deriv'] = {'d': cg, 't': time.time()}
                return cg
            raise ValueError('CoinGecko vuoto')
        except Exception as e2:
            log.warning('get_derivatives: anche CoinGecko fallito (%s). Uso cache se disponibile.', e2)
            if 'deriv' in _cache:
                log.info('get_derivatives: uso CACHE')
                return _cache['deriv']['d']
            log.warning('get_derivatives: DATO NON DISPONIBILE')
            return {}


def get_derivatives_coingecko():
    """Fallback funding+OI da CoinGecko /derivatives (NON geo-bloccato).
    Prende il primo ticker perpetuo per BTC/ETH/SOL/XRP. OI in USD."""
    symbols = ('BTC', 'ETH', 'SOL', 'XRP')
    url = 'https://api.coingecko.com/api/v3/derivatives'
    r = requests.get(url, timeout=12)
    r.raise_for_status()
    data = r.json()
    result = {}
    for d in data:
        if not isinstance(d, dict) or d.get('contract_type') != 'perpetual':
            continue
        idx = str(d.get('index_id', '')).upper()
        if idx in symbols and idx not in result:
            fr = d.get('funding_rate'); oi = d.get('open_interest')
            try:
                fr_v = float(fr) if fr not in (None, '') else None
            except (ValueError, TypeError):
                fr_v = None
            try:
                oi_v = float(oi) if oi not in (None, '') else None
            except (ValueError, TypeError):
                oi_v = None
            result[idx] = {'funding': fr_v, 'oi': oi_v, 'oi_usd': True}
        if len(result) == len(symbols):
            break
    return result


def _fmt_deriv(dv):
    """Riga testuale dei derivati per il ctx."""
    if not dv:
        return 'Derivati (Funding/OI): DATO NON DISPONIBILE'
    parti = []
    fonte_usd = False
    for sym in ('BTC', 'ETH', 'SOL', 'XRP'):
        d = dv.get(sym)
        if not d:
            parti.append(f'{sym} n/d')
            continue
        fr = d.get('funding'); oi = d.get('oi')
        fr_t = f'{fr:+.4f}%' if fr is not None else 'n/d'
        if oi is None:
            oi_t = 'n/d'
        elif d.get('oi_usd'):
            fonte_usd = True
            oi_t = f'${oi/1e9:.2f}B' if oi >= 1e9 else f'${oi/1e6:.0f}M'
        else:
            oi_t = f'{oi:,.0f}'
        parti.append(f'{sym} funding {fr_t} OI {oi_t}')
    fonte = 'CoinGecko' if fonte_usd else 'Bybit'
    return f'Derivati ({fonte}) - ' + ', '.join(parti)


def get_stablecoins():
    """Stablecoin supply totale + segnale inflow/outflow da DefiLlama.
    Ritorna dict con mcap_b, var24, var7, segnale. Cache + fallback."""
    if 'stable' in _cache and time.time() - _cache['stable']['t'] < CACHE_TTL:
        return _cache['stable']['d']
    try:
        url = 'https://stablecoins.llama.fi/stablecoincharts/all'
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        chart = r.json()
        def val(punto):
            c = punto.get('totalCirculatingUSD', {})
            return float(c.get('peggedUSD', 0)) if isinstance(c, dict) else (float(c) if c else 0)
        if not isinstance(chart, list) or len(chart) < 2:
            raise ValueError('storico insufficiente')
        oggi = val(chart[-1])
        if oggi <= 0:
            raise ValueError('valore nullo')
        ieri = val(chart[-2]) if len(chart) >= 2 else 0
        var24 = ((oggi - ieri) / ieri * 100) if ieri > 0 else None
        sette = val(chart[-8]) if len(chart) >= 8 else 0
        var7 = ((oggi - sette) / sette * 100) if sette > 0 else None
        if var24 is not None and var7 is not None:
            combo = var24 * 0.5 + (var7 / 7) * 0.5
        elif var24 is not None:
            combo = var24
        elif var7 is not None:
            combo = var7 / 7
        else:
            combo = 0
        if combo > 0.15:
            seg = 'INFLOW POSITIVO'
        elif combo < -0.15:
            seg = 'OUTFLOW'
        else:
            seg = 'NEUTRALE'
        result = {'mcap_b': oggi / 1e9, 'var24': var24, 'var7': var7, 'segnale': seg}
        _cache['stable'] = {'d': result, 't': time.time()}
        return result
    except Exception as e:
        log.warning('get_stablecoins: errore DefiLlama (%s). Uso cache se disponibile.', e)
        if 'stable' in _cache:
            return _cache['stable']['d']
        return {}


def _fmt_stable(s):
    """Riga testuale stablecoin per il ctx."""
    if not s or not s.get('segnale'):
        return 'Stablecoin Supply/Inflow: DATO NON DISPONIBILE'
    mcap = s.get('mcap_b', 0)
    v24 = s.get('var24'); v7 = s.get('var7')
    v24_t = f'{v24:+.2f}%' if v24 is not None else 'n/d'
    v7_t = f'{v7:+.2f}%' if v7 is not None else 'n/d'
    return f"Stablecoin Supply: ${mcap:,.0f}B (24h {v24_t}, 7d {v7_t}) - Segnale: {s['segnale']}"


def compute_altseason_score(g, p, fg, stable=None):
    """ALTSEASON SCORE deterministico dai dati disponibili. Ritorna stringa formattata.
    Pesi: BTC Dom 40, ETH/BTC 15, TOTAL2 15, TOTAL3 10, Sentiment 10, AltStrength 10."""
    comp = []; score = 0; disp = 0
    dom = g.get("dom", 0)
    if dom:
        d = round(max(0, min(40, (65 - dom) / (65 - 40) * 40)))
        score += d; disp += 1
        comp.append(f"- BTC Dominance: {dom:.1f}%")
    else:
        comp.append("- BTC Dominance: DATO NON DISPONIBILE")
    btc = p.get("BTC", {}).get("price", 0); eth = p.get("ETH", {}).get("price", 0)
    if btc and eth:
        ethbtc = eth / btc
        e = round(max(0, min(15, (ethbtc - 0.025) / (0.05 - 0.025) * 15)))
        score += e; disp += 1
        comp.append(f"- ETH/BTC: {ethbtc:.5f}")
    else:
        comp.append("- ETH/BTC: DATO NON DISPONIBILE")
    total2 = g.get("total2", 0)
    if total2:
        score += 8; disp += 1
        comp.append(f"- TOTAL2: ${total2:,.0f}B")
    else:
        comp.append("- TOTAL2: DATO NON DISPONIBILE")
    total3 = g.get("total3", 0)
    if total3:
        score += 5; disp += 1
        comp.append(f"- TOTAL3: ${total3:,.0f}B")
    else:
        comp.append("- TOTAL3: DATO NON DISPONIBILE")
    v = fg.get("v", 0)
    if v:
        s = round(v / 100 * 10)
        score += s; disp += 1
        comp.append(f"- Sentiment (Fear & Greed): {v}")
    else:
        comp.append("- Sentiment (F&G): DATO NON DISPONIBILE")
    alts = [s for s in p if s != "BTC"]
    valid = [s for s in alts if p[s].get("price", 0) > 0]
    if valid:
        pos = sum(1 for s in valid if p[s].get("ch", 0) > 0)
        pct = pos / len(valid) * 100
        a = round(pct / 100 * 10)
        score += a; disp += 1
        comp.append(f"- Altcoin Strength: {pct:.0f}% alt positive 24h")
    else:
        comp.append("- Altcoin Strength: DATO NON DISPONIBILE")
    # 7 fattore: Stablecoin inflow (max 10 punti). INFLOW=10, NEUTRALE=5, OUTFLOW=0.
    if stable and stable.get('segnale') and stable.get('segnale') != 'DATO NON DISPONIBILE':
        seg = stable['segnale']
        st_pts = 10 if seg == 'INFLOW POSITIVO' else 5 if seg == 'NEUTRALE' else 0
        score += st_pts; disp += 1
        comp.append(f"- Stablecoin: {seg}")
    else:
        comp.append("- Stablecoin Inflow: DATO NON DISPONIBILE")
    conf = "ALTA" if disp >= 5 else "MEDIA" if disp >= 3 else "BASSA"
    return f"Confidenza Analisi: {conf} (basata su {disp}/7 dati disponibili)\nDATI DISPONIBILI PER FATTORE:\n" + "\n".join(comp)


def _pick_model(chat_id=None):
    """Sceglie il modello in base al piano utente.
    free -> gpt-5.4-mini, basic/pro -> gpt-5.4.
    Override: se OPENAI_MODEL e' impostata, vince lei."""
    forced = os.environ.get('OPENAI_MODEL', '')
    if forced:
        return forced
    try:
        plan = load_user(chat_id).get('plan', 'free') if chat_id else 'free'
    except Exception:
        plan = 'free'
    if plan in ('basic', 'pro'):
        return 'gpt-5.4'
    return 'gpt-5.4-mini'


def get_news_summary(blocco_notizie, lang="it"):
    """Sintesi giornalistica delle news. Chiamata OpenAI dedicata,
    SEPARATA da get_claude_response (che fa analisi di mercato)."""
    try:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return ""
        client = OpenAI(api_key=api_key)
        sys_prompt = {
            "it": "Sei un giornalista crypto. Riassumi i temi principali di queste notizie in 3-5 frasi discorsive, in italiano. NON fare analisi di mercato, NON usare sezioni o titoli, NON dare consigli operativi. Solo un breve riassunto dei temi. Basati solo su queste notizie, non inventare nulla.",
            "en": "You are a crypto journalist. Summarize the main themes of these news in 3-5 narrative sentences, English. NO market analysis, NO sections or headers, NO trading advice. Just a brief thematic summary. Only these news, invent nothing.",
            "pt": "Voce e jornalista crypto. Resuma os temas destas noticias em 3-5 frases, portugues. SEM analise de mercado, SEM secoes, SEM conselhos. Apenas um breve resumo. Somente estas noticias, nao invente.",
        }.get(lang, "Riassumi i temi di queste notizie in 3-5 frasi, niente analisi di mercato, solo un breve riassunto.")
        msg = client.responses.create(
            model="gpt-5.4-mini",
            instructions=sys_prompt,
            input=blocco_notizie,
            max_output_tokens=400
        )
        return msg.output_text
    except Exception as e:
        log.warning(f"get_news_summary error: {e}")
        return ""


# ============================================================
# ROTATION ENGINE (descrittivo, non segnale automatico di trading)
# ============================================================
# Coin capofila per categoria (proxy). ID CoinGecko standard.
_ROT_CATEGORIES = {
    "BTC": ["bitcoin"],
    "ETH": ["ethereum"],
    "LARGE": ["ripple", "solana", "binancecoin"],
    "MID": ["cardano", "hedera-hashgraph", "stellar"],
    "AI": ["fetch-ai", "singularitynet"],
    "MEME": ["dogecoin", "bonk", "book-of-meme"],
}
# Cache storici: { cg_id: (timestamp_epoch, closes_list) }
_rot_cache = {}
_ROT_CACHE_TTL = 43200  # 12 ore (>= 6h richiesto). Storici 7/30gg cambiano lentamente.

def _rot_get_history(cg_id):
    """Storico prezzi (closes) di una coin, con cache 12h e tolleranza errori.
    Ritorna lista closes oppure None. In caso di 429/errore usa cache se esiste."""
    import time as _t
    now = _t.time()
    # cache valida?
    cached = _rot_cache.get(cg_id)
    if cached and (now - cached[0]) < _ROT_CACHE_TTL:
        return cached[1]
    # scarico
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart?vs_currency=usd&days=30&interval=daily"
        r = requests.get(url, timeout=12)
        if r.status_code == 429:
            # rate limit: uso l'ultimo cached valido se esiste (anche se scaduto)
            if cached:
                return cached[1]
            return None
        r.raise_for_status()
        prices = r.json().get("prices", [])
        closes = [float(p[1]) for p in prices if isinstance(p, (list, tuple)) and len(p) >= 2]
        if len(closes) >= 8:
            _rot_cache[cg_id] = (now, closes)
            return closes
        # pochi dati: se ho cache vecchia, meglio quella
        if cached:
            return cached[1]
        return None
    except Exception:
        if cached:
            return cached[1]
        return None

def _rot_perf(closes, giorni):
    """Variazione % su 'giorni' (7 o 30). closes[-1]=oggi. None se dati insuff."""
    if not closes or len(closes) < giorni + 1:
        return None
    base = closes[-(giorni + 1)]
    if not base:
        return None
    return (closes[-1] - base) / base * 100

def _rot_category_strength(category_ids, giorni):
    """Forza media di una categoria su 'giorni'. Ritorna (media_perf, n_validi, n_totali).
    Salta le coin che falliscono (tolleranza errori)."""
    perfs = []
    for cg in category_ids:
        closes = _rot_get_history(cg)
        p = _rot_perf(closes, giorni)
        if p is not None:
            perfs.append(p)
    n_validi = len(perfs)
    n_totali = len(category_ids)
    media = sum(perfs) / n_validi if n_validi else None
    return media, n_validi, n_totali

def compute_rotation_state(g=None, trend=None, stable=None):
    """ROTATION ENGINE DETERMINISTICO (descrittivo, non trading automatico).

    SOGLIE: scelte ragionevoli ma NON validate statisticamente. Dichiarate qui.
    Lo stato e' un'indicazione descrittiva, sempre accompagnata da confidence.

    Ritorna dict: state, confidence, suggested_action, dettagli.
    Tollerante agli errori: coin/categorie mancanti -> saltate, confidence abbassata,
    dati mancanti elencati in dettagli['dati_mancanti'].
    """
    dettagli = {"forza_7d": {}, "forza_30d": {}, "dati_mancanti": [], "note": []}

    # --- 1) Raccolgo forza per categoria (7 e 30 giorni) ---
    forza7 = {}
    forza30 = {}
    categorie_complete = 0
    categorie_totali = len(_ROT_CATEGORIES)
    for cat, ids in _ROT_CATEGORIES.items():
        m7, v7, t7 = _rot_category_strength(ids, 7)
        m30, v30, t30 = _rot_category_strength(ids, 30)
        forza7[cat] = m7
        forza30[cat] = m30
        if m7 is not None:
            dettagli["forza_7d"][cat] = round(m7, 1)
        if m30 is not None:
            dettagli["forza_30d"][cat] = round(m30, 1)
        if v7 < t7:
            dettagli["dati_mancanti"].append(f"{cat}: {t7-v7}/{t7} coin senza dati 7gg")
        if m7 is not None:
            categorie_complete += 1

    # --- 2) Dati di contesto ---
    dom = None
    try:
        dom = g.get("dom") if g else None
    except Exception:
        dom = None
    ethbtc_desc = None
    ethbtc_var = None
    try:
        if trend and isinstance(trend, dict) and "ethbtc" in trend:
            ethbtc_desc = trend["ethbtc"].get("desc")
            ethbtc_var = trend["ethbtc"].get("var7d")
    except Exception:
        pass
    stable_sig = None
    try:
        if stable and isinstance(stable, dict):
            stable_sig = stable.get("segnale")
    except Exception:
        pass

    # --- 3) Euforia meme e % positive 7gg ---
    meme7 = forza7.get("MEME")
    euforia_meme = (meme7 is not None and meme7 > 25)  # soglia: meme +25% su 7gg = euforia
    # % categorie positive su 7gg
    valide7 = [v for v in forza7.values() if v is not None]
    pct_positive = (sum(1 for v in valide7 if v > 0) / len(valide7) * 100) if valide7 else None

    # --- 4) LOGICA DETERMINISTICA DEGLI STATI (soglie dichiarate) ---
    # Ordine di priorita': prima i segnali di rischio (distribuzione/risk-off), poi rotazioni.
    state = "BTC_LED"  # default prudente
    motivi = []

    btc7 = forza7.get("BTC")
    eth7 = forza7.get("ETH")
    large7 = forza7.get("LARGE")
    mid7 = forza7.get("MID")

    dom_su = (dom is not None and dom > 56)        # dominance alta (soglia indicativa)
    ethbtc_giu = (ethbtc_desc == "in calo")
    ethbtc_su = (ethbtc_desc == "in recupero")
    stable_outflow = (stable_sig == "OUTFLOW")

    # DISTRIBUTION_WARNING: euforia meme + dominance che risale + ETH/BTC che gira giu
    if euforia_meme and dom_su and ethbtc_giu:
        state = "DISTRIBUTION_WARNING"
        motivi.append("euforia meme + dominance alta + ETH/BTC in calo")
    # RISK_OFF: maggioranza negativa 7gg + ETH/BTC giu + stablecoin outflow
    elif (pct_positive is not None and pct_positive < 35) and ethbtc_giu and stable_outflow:
        state = "RISK_OFF"
        motivi.append("maggioranza categorie negative + ETH/BTC in calo + stablecoin outflow")
    # MEME_EUPHORIA: meme nettamente i piu forti
    elif euforia_meme and (meme7 is not None) and (btc7 is not None) and meme7 > btc7 + 15:
        state = "MEME_EUPHORIA"
        motivi.append("meme dominano la forza relativa (possibile fine ciclo)")
    # MID_CAP_ROTATION: mid cap sovraperformano large cap ed ETH
    elif (mid7 is not None and large7 is not None and eth7 is not None
          and mid7 > large7 + 5 and mid7 > eth7 + 5 and mid7 > 0):
        state = "MID_CAP_ROTATION"
        motivi.append("mid cap sovraperformano large cap ed ETH")
    # LARGE_CAP_ROTATION: large cap sovraperformano BTC ed ETH
    elif (large7 is not None and btc7 is not None and eth7 is not None
          and large7 > btc7 + 3 and large7 > eth7 + 3 and large7 > 0):
        state = "LARGE_CAP_ROTATION"
        motivi.append("large cap sovraperformano BTC ed ETH")
    # ETH_ROTATION: ETH/BTC in recupero + ETH sovraperforma BTC
    elif ethbtc_su and (eth7 is not None and btc7 is not None and eth7 > btc7):
        state = "ETH_ROTATION"
        motivi.append("ETH/BTC in recupero, ETH sovraperforma BTC")
    # BTC_LED: BTC guida o nessun segnale chiaro (default)
    else:
        state = "BTC_LED"
        if btc7 is not None and eth7 is not None and btc7 >= eth7:
            motivi.append("BTC guida o pari rispetto alle alt")
        else:
            motivi.append("nessuna rotazione chiara (default prudente)")

    # --- 5) CONFIDENCE: dipende da quanti dati + coerenza ---
    # Base sui dati disponibili
    copertura = categorie_complete / categorie_totali if categorie_totali else 0
    dati_contesto = sum(x is not None for x in [dom, ethbtc_desc, stable_sig])  # max 3
    if copertura >= 0.8 and dati_contesto >= 2 and len(dettagli["dati_mancanti"]) == 0:
        confidence = "HIGH"
    elif copertura >= 0.5 and dati_contesto >= 1:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"
    # Segnali contraddittori abbassano la confidence
    if state in ("DISTRIBUTION_WARNING", "RISK_OFF") and confidence == "HIGH":
        # questi stati richiedono piu' certezza: se i dati non sono pieni, scendo
        if len(dettagli["dati_mancanti"]) > 0:
            confidence = "MEDIUM"

    # --- 6) SUGGESTED_ACTION (sempre prudente, mai "tutto") ---
    action_map = {
        "BTC_LED": "HOLD",
        "ETH_ROTATION": "MONITORA",
        "LARGE_CAP_ROTATION": "MONITORA",
        "MID_CAP_ROTATION": "MONITORA",
        "MEME_EUPHORIA": "PREPARA_DISTRIBUZIONE",
        "DISTRIBUTION_WARNING": "PREPARA_DISTRIBUZIONE",
        "RISK_OFF": "ESCI_USDC",
    }
    suggested_action = action_map.get(state, "MONITORA")
    # Se confidence LOW, l'azione e' sempre piu' prudente (non spingere oltre MONITORA)
    if confidence == "LOW" and suggested_action in ("PREPARA_DISTRIBUZIONE", "ESCI_USDC"):
        dettagli["note"].append("confidence LOW: azione declassata a MONITORA per prudenza")
        suggested_action = "MONITORA"

    dettagli["motivi"] = motivi
    dettagli["euforia_meme"] = euforia_meme
    if pct_positive is not None:
        dettagli["pct_categorie_positive_7gg"] = round(pct_positive, 0)

    return {
        "state": state,
        "confidence": confidence,
        "suggested_action": suggested_action,
        "dettagli": dettagli,
    }

def _fmt_rotation(rot):
    """Formatta il Rotation Engine per il market_context. Dichiara SEMPRE i limiti."""
    if not rot:
        return "ROTATION ENGINE: DATO NON DISPONIBILE"
    d = rot.get("dettagli", {})
    righe = ["ROTATION ENGINE (descrittivo, non segnale automatico di trading):"]
    righe.append(f"Stato: {rot.get('state')}")
    righe.append(f"Confidenza motore: {rot.get('confidence')}")
    righe.append(f"Azione suggerita: {rot.get('suggested_action')}")
    f7 = d.get("forza_7d", {})
    if f7:
        parti = ", ".join(f"{k} {v:+.0f}%" for k, v in f7.items())
        righe.append(f"Forza relativa 7gg: {parti}")
    if d.get("motivi"):
        righe.append("Motivi: " + "; ".join(d["motivi"]))
    if d.get("dati_mancanti"):
        righe.append("Dati mancanti: " + "; ".join(d["dati_mancanti"]))
    if d.get("note"):
        righe.append("Note: " + "; ".join(d["note"]))
    return chr(10).join(righe)

# ============================================================
# PORTFOLIO CONTEXT ENGINE (descrittivo, non consulenza finanziaria)
# ============================================================
# Collega il portafoglio reale al Rotation Engine + indicatori per evidenziare
# concentrazioni, asset deboli/forti, aree di rotazione da studiare, rischi euforia.
# VINCOLI: nessuna percentuale operativa, nessun "vendi/compra", nessuna urgency,
# solo linguaggio descrittivo dal vocabolario consentito. Soglie dichiarate, non validate.

_PCTX_DISCLAIMER = "Modulo descrittivo, non consulenza finanziaria, non segnale automatico."
_PCTX_SOGLIA_CONCENTRAZIONE = 25.0  # % del portafoglio oltre cui una posizione e' "concentrata"
_PCTX_GIORNI_PERSISTENZA = 3        # snapshot consecutivi per confermare una rotazione

# Mappa coin -> categoria (coerente col Rotation Engine)
_PCTX_CAT = {
    "BTC": "BTC", "ETH": "ETH",
    "XRP": "LARGE", "SOL": "LARGE", "BNB": "LARGE",
    "ADA": "MID", "HBAR": "MID", "XLM": "MID", "POL": "MID", "ALGO": "MID",
    "TRX": "MID", "NEAR": "MID", "GRT": "MID",
    "FET": "AI", "AGIX": "AI",
    "DOGE": "MEME", "BONK": "MEME", "MANA": "MEME", "SEI": "MID",
}

def _pctx_pesi(portfolio, prices):
    """Calcola il peso % di ogni posizione sul totale. Fatto oggettivo, non consiglio.
    Ritorna (lista (sym, peso%, valore), valore_totale). Salta coin senza prezzo."""
    valori = []
    totale = 0.0
    for sym, pos in portfolio.items():
        try:
            pr = prices.get(sym, {}).get("price", 0)
            qty = pos.get("qty", 0)
            if pr and qty:
                val = qty * pr
                valori.append([sym, 0.0, val])
                totale += val
        except Exception:
            continue
    if totale > 0:
        for v in valori:
            v[1] = v[2] / totale * 100
    valori.sort(key=lambda x: x[1], reverse=True)
    return valori, totale

def _pctx_rotazione_persistente(stato_attuale, leggi_snapshot_func=None):
    """Verifica se lo stato del Rotation Engine e' confermato per piu' giorni (snapshot).
    Ritorna (confermato_bool, n_giorni_concordi, n_snapshot_disponibili, nota).
    Se snapshot insufficienti -> confermato=False + nota che abbassa confidence."""
    if not leggi_snapshot_func:
        return False, 0, 0, "persistenza non verificabile (storico non disponibile)"
    try:
        recenti = leggi_snapshot_func(_PCTX_GIORNI_PERSISTENZA)
    except Exception:
        return False, 0, 0, "persistenza non verificabile (errore lettura storico)"
    if not recenti:
        return False, 0, 0, "nessuno snapshot disponibile per la persistenza"
    stati = []
    for snap in recenti:
        try:
            rs = snap.get("rotation_state")
            if isinstance(rs, dict):
                stati.append(rs.get("state"))
        except Exception:
            continue
    n_disp = len(stati)
    if n_disp < _PCTX_GIORNI_PERSISTENZA:
        return False, 0, n_disp, f"snapshot insufficienti per confermare ({n_disp}/{_PCTX_GIORNI_PERSISTENZA} giorni)"
    concordi = sum(1 for s in stati[-_PCTX_GIORNI_PERSISTENZA:] if s == stato_attuale)
    confermato = (concordi >= _PCTX_GIORNI_PERSISTENZA)
    if confermato:
        nota = f"rotazione {stato_attuale} confermata per {concordi} giorni"
    else:
        nota = f"rotazione non ancora confermata ({concordi}/{_PCTX_GIORNI_PERSISTENZA} giorni concordi)"
    return confermato, concordi, n_disp, nota

def compute_portfolio_context(portfolio, rot=None, g=None, trend=None, stable=None, fg=None, prices=None, leggi_snapshot_func=None):
    """PORTFOLIO CONTEXT ENGINE (descrittivo). Restituisce osservazioni, MAI ordini.
    Nessuna percentuale operativa, nessun 'vendi/compra', nessuna urgency.
    """
    out = {
        "note": [],
        "concentrazioni": [],
        "asset_deboli": [],
        "asset_forti": [],
        "aree_rotazione": [],
        "rischio_euforia": False,
        "confidence": "LOW",
        "disclaimer": _PCTX_DISCLAIMER,
    }
    if not portfolio:
        out["note"].append("portafoglio vuoto o non disponibile")
        return out
    if prices is None:
        prices = {}

    # --- 1) Concentrazioni (fatto oggettivo: peso % sul totale) ---
    pesi, totale = _pctx_pesi(portfolio, prices)
    if totale <= 0:
        out["note"].append("valore portafoglio non calcolabile (prezzi mancanti)")
        return out
    for sym, peso, val in pesi:
        if peso >= _PCTX_SOGLIA_CONCENTRAZIONE:
            out["concentrazioni"].append({"sym": sym, "peso": round(peso, 1)})

    # --- 2) Forza relativa: asset deboli/forti rispetto al gruppo ---
    # Uso la forza 7gg delle categorie dal Rotation Engine, se disponibile.
    forza_cat = {}
    rot_state = None
    rot_conf = None
    try:
        if rot and isinstance(rot, dict):
            rot_state = rot.get("state")
            rot_conf = rot.get("confidence")
            forza_cat = rot.get("dettagli", {}).get("forza_7d", {}) or {}
    except Exception:
        pass

    for sym, peso, val in pesi:
        cat = _PCTX_CAT.get(sym)
        if cat is None:
            continue
        fcat = forza_cat.get(cat)
        if fcat is None:
            continue
        # debole: categoria nettamente negativa
        if fcat < -5:
            out["asset_deboli"].append({"sym": sym, "cat": cat, "forza": round(fcat, 1)})
        # forte: categoria nettamente positiva
        elif fcat > 8:
            out["asset_forti"].append({"sym": sym, "cat": cat, "forza": round(fcat, 1)})

    # --- 3) Aree di rotazione da studiare (con persistenza multi-giorno) ---
    confermato, concordi, n_disp, nota_pers = _pctx_rotazione_persistente(rot_state, leggi_snapshot_func)
    if rot_state in ("ETH_ROTATION", "LARGE_CAP_ROTATION", "MID_CAP_ROTATION"):
        # se il portafoglio e' concentrato in una categoria diversa da quella che ruota
        cat_che_ruota = {"ETH_ROTATION": "ETH", "LARGE_CAP_ROTATION": "LARGE", "MID_CAP_ROTATION": "MID"}.get(rot_state)
        concentrate_diverse = [c["sym"] for c in out["concentrazioni"] if _PCTX_CAT.get(c["sym"]) != cat_che_ruota]
        if concentrate_diverse:
            out["aree_rotazione"].append({
                "stato": rot_state,
                "confermato": confermato,
                "nota_persistenza": nota_pers,
                "posizioni_concentrate_altrove": concentrate_diverse,
            })

    # --- 4) Rischio euforia/distribuzione ---
    if rot_state in ("MEME_EUPHORIA", "DISTRIBUTION_WARNING"):
        # esposizione meme nel portafoglio?
        meme_pos = [s for s, _, _ in pesi if _PCTX_CAT.get(s) == "MEME"]
        if meme_pos:
            out["rischio_euforia"] = True

    # --- 5) Confidence del modulo ---
    # dipende da: dati Rotation disponibili + snapshot per persistenza
    if rot_state and rot_conf == "HIGH" and n_disp >= _PCTX_GIORNI_PERSISTENZA:
        out["confidence"] = "HIGH"
    elif rot_state and (rot_conf in ("MEDIUM", "HIGH") or n_disp >= 1):
        out["confidence"] = "MEDIUM"
    else:
        out["confidence"] = "LOW"

    # --- 6) Costruzione NOTE testuali (vocabolario consentito) ---
    note = []
    for c in out["concentrazioni"]:
        frase = f"{c['sym']} ha un peso rilevante ({c['peso']:.0f}% del portafoglio): posizione concentrata, da valutare se coerente con la tua strategia"
        note.append(frase)
    for a in out["asset_deboli"]:
        note.append(f"{a['sym']}: asset debole rispetto al gruppo, da monitorare")
    for a in out["asset_forti"]:
        note.append(f"{a['sym']}: asset forte da monitorare")
    for ar in out["aree_rotazione"]:
        if ar["confermato"]:
            note.append(f"possibile rotazione da studiare: {ar['stato']} ({ar['nota_persistenza']}). Le tue posizioni concentrate ({', '.join(ar['posizioni_concentrate_altrove'])}) sono in categorie diverse: da valutare se coerente con la tua strategia")
        else:
            note.append(f"possibile rotazione da studiare: {ar['stato']}, ma {ar['nota_persistenza']}. Fase non confermata")
    if out["rischio_euforia"]:
        note.append("fase di possibile euforia/distribuzione sul comparto meme: da osservare con prudenza, fase non confermata")
    if not note:
        note.append("nessuna azione necessaria al momento")

    out["note"] = note
    return out

def _fmt_portfolio_context(pctx):
    """Formatta la NOTA PORTAFOGLIO. Include SEMPRE il disclaimer. Mai linguaggio operativo."""
    if not pctx:
        return ""
    righe = ["NOTA PORTAFOGLIO (descrittiva):"]
    if pctx.get("confidence"):
        righe.append(f"Confidenza modulo: {pctx['confidence']}")
    for n in pctx.get("note", []):
        righe.append(f"- {n}")
    righe.append(pctx.get("disclaimer", _PCTX_DISCLAIMER))
    return chr(10).join(righe)

def _leggi_ultimi_snapshot(n=3):
    """Legge gli ultimi n snapshot da /data/snapshots.jsonl. Read-only, crash-safe.
    Ritorna lista di dict (i piu' recenti). Per la persistenza del Portfolio Context."""
    try:
        import json as _json
        path = "/data/snapshots.jsonl"
        if not os.path.exists(path):
            return []
        righe = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                righe.append(line)
        ultimi = righe[-n:] if len(righe) >= n else righe
        out = []
        for r in ultimi:
            try:
                out.append(_json.loads(r))
            except Exception:
                continue
        return out
    except Exception as e:
        log.warning(f"_leggi_ultimi_snapshot error: {e}")
        return []

# ============================================================
# STATE CHANGE ALERT (informativo, non operativo di trading)
# ============================================================
# Invia un alert Telegram all'admin SOLO quando il Rotation Engine cambia fase,
# o conferma una fase per >=3 giorni di calendario, o quando la confidence sale.
# Testo deterministico (frasi pre-approvate), nessun linguaggio operativo.
# Stato notificato persistito su /data/last_state_alert.json. Max 1/24h (eccezione DISTRIBUTION_WARNING).

_SCA_PATH = "/data/last_state_alert.json"
_SCA_GIORNI_CONFERMA = 3
_SCA_MIN_ORE = 24  # frequenza minima tra alert (eccetto DISTRIBUTION_WARNING)
_SCA_STATI_MONITORATI = {
    "RISK_OFF", "BTC_LED", "ETH_ROTATION", "LARGE_CAP_ROTATION",
    "MID_CAP_ROTATION", "MEME_EUPHORIA", "DISTRIBUTION_WARNING",
}

# Frasi di lettura APPROVATE (esatte). Non passano dall'AI: testo fisso.
_SCA_LETTURE = {
    "RISK_OFF": "Il quadro descrittivo segnala una fase di possibile riduzione del rischio sul mercato: il capitale sembra muoversi verso maggiore prudenza. Fase da osservare, nessuna azione automatica.",
    "BTC_LED": "Il quadro descrittivo indica che Bitcoin mantiene la leadership: la rotazione verso le altcoin non risulta confermata. Segnale informativo, fase da monitorare.",
    "ETH_ROTATION": "Il mercato mostra segnali di possibile rotazione verso Ethereum, che sembra guadagnare forza relativa su Bitcoin. Possibile rotazione, conferma da verificare.",
    "LARGE_CAP_ROTATION": "Il quadro descrittivo evidenzia una possibile rotazione verso le large cap, che mostrano forza relativa rispetto a Bitcoin ed Ethereum. Fase da osservare, conferma da verificare.",
    "MID_CAP_ROTATION": "Il quadro descrittivo segnala una possibile rotazione verso le mid cap, che mostrano forza relativa crescente. Fase da monitorare, conferma da verificare.",
    "MEME_EUPHORIA": "Il quadro descrittivo evidenzia forza marcata sul comparto meme, un segnale storicamente associato a fasi avanzate di mercato. Fase da osservare con attenzione, conferma da verificare.",
    "DISTRIBUTION_WARNING": "Il quadro descrittivo segnala possibili segni di distribuzione: euforia sui meme insieme a debolezza relativa nelle fasi guida. Attenzione alla distribuzione, fase da osservare, nessuna azione automatica.",
}

_SCA_CONF_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

def _sca_carica_stato_notificato():
    """Legge /data/last_state_alert.json. Ritorna dict o None. Crash-safe."""
    try:
        import json as _json
        if not os.path.exists(_SCA_PATH):
            return None
        with open(_SCA_PATH, encoding="utf-8") as f:
            return _json.load(f)
    except Exception as e:
        log.warning(f"_sca_carica_stato error: {e}")
        return None

def _sca_salva_stato_notificato(state, confidence, giorni):
    """Scrive lo stato notificato su /data/last_state_alert.json. Crash-safe."""
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        data = {
            "state": state,
            "confidence": confidence,
            "timestamp": _dt.now(_tz.utc).isoformat(),
            "giorni_conferma": giorni,
        }
        os.makedirs("/data", exist_ok=True)
        with open(_SCA_PATH, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False)
        return True
    except Exception as e:
        log.warning(f"_sca_salva_stato error (non bloccante): {e}")
        return False

def _sca_giorni_conferma(stato_attuale, leggi_snapshot_func, max_giorni=10):
    """Conta da quanti GIORNI DI CALENDARIO consecutivi lo stato e' lo stesso.
    Filtra gli snapshot per data (un rappresentante per giorno, il piu' recente).
    Ritorna il numero di giorni consecutivi (>=1 se oggi e' nello stato)."""
    try:
        snaps = leggi_snapshot_func(200)  # leggo abbastanza storia
    except Exception:
        return 0
    if not snaps:
        return 0
    # Raggruppo per giorno di calendario, tenendo lo stato dell'ultimo snapshot del giorno
    from datetime import datetime as _dt
    per_giorno = {}  # giorno (date) -> state
    for snap in snaps:
        try:
            ts = snap.get("timestamp_utc", "")
            rs = snap.get("rotation_state")
            if not ts or not isinstance(rs, dict):
                continue
            stato = rs.get("state")
            if not stato:
                continue
            giorno = _dt.fromisoformat(ts).date()
            # l'ultimo snapshot del giorno vince (gli snaps sono in ordine cronologico)
            per_giorno[giorno] = stato
        except Exception:
            continue
    if not per_giorno:
        return 0
    # Ordino i giorni dal piu' recente
    giorni_ordinati = sorted(per_giorno.keys(), reverse=True)
    # Conto da quanti giorni consecutivi (a ritroso) lo stato == stato_attuale
    conteggio = 0
    for g in giorni_ordinati:
        if per_giorno[g] == stato_attuale:
            conteggio += 1
        else:
            break
        if conteggio >= max_giorni:
            break
    return conteggio

def compute_state_change_alert(rot_attuale, leggi_snapshot_func):
    """Decide se inviare un State Change Alert. Restituisce dict:
    {invia: bool, tipo: str, stato: str, confidence: str, giorni: int, testo: str}
    Tollerante a errori. Non invia (e non crasha) se i dati mancano.
    """
    risultato = {"invia": False}
    try:
        if not rot_attuale or not isinstance(rot_attuale, dict):
            return risultato
        stato = rot_attuale.get("state")
        conf = rot_attuale.get("confidence")
        if stato not in _SCA_STATI_MONITORATI:
            return risultato

        # giorni di conferma (per calendario)
        giorni = _sca_giorni_conferma(stato, leggi_snapshot_func)

        # stato notificato precedente
        prec = _sca_carica_stato_notificato()
        prec_state = prec.get("state") if prec else None
        prec_conf = prec.get("confidence") if prec else None
        prec_ts = prec.get("timestamp") if prec else None
        prec_giorni = prec.get("giorni_conferma", 0) if prec else 0

        # --- Controllo frequenza: ore dall'ultimo alert ---
        ore_passate = None
        if prec_ts:
            try:
                from datetime import datetime as _dt, timezone as _tz
                t0 = _dt.fromisoformat(prec_ts)
                ore_passate = (_dt.now(_tz.utc) - t0).total_seconds() / 3600.0
            except Exception:
                ore_passate = None

        # --- Determino se c'e' un motivo per inviare ---
        motivo = None
        # 1) cambio stato
        if prec_state != stato:
            motivo = "cambio"
        # 2) stesso stato confermato >=3 giorni (e non gia' notificato come conferma a >=3)
        elif giorni >= _SCA_GIORNI_CONFERMA and prec_giorni < _SCA_GIORNI_CONFERMA:
            motivo = "conferma"
        # 3) confidence aumentata (LOW->MEDIUM/HIGH oppure MEDIUM->HIGH)
        elif prec_conf and conf and _SCA_CONF_RANK.get(conf, 0) > _SCA_CONF_RANK.get(prec_conf, 0):
            motivo = "confidence"

        if not motivo:
            return risultato

        # --- Limite frequenza 24h (eccezione DISTRIBUTION_WARNING) ---
        if stato != "DISTRIBUTION_WARNING":
            if ore_passate is not None and ore_passate < _SCA_MIN_ORE:
                return risultato  # troppo presto, non invio

        # --- Costruisco l'alert ---
        testo = _fmt_state_change_alert(prec_state, stato, conf, giorni, motivo)
        risultato = {
            "invia": True,
            "tipo": motivo,
            "stato": stato,
            "stato_precedente": prec_state,
            "confidence": conf,
            "giorni": giorni,
            "testo": testo,
        }
        return risultato
    except Exception as e:
        try:
            log.warning(f"compute_state_change_alert error (non bloccante): {e}")
        except Exception:
            pass
        return {"invia": False}

def _fmt_state_change_alert(stato_prec, stato_nuovo, conf, giorni, motivo):
    """Costruisce il messaggio dell'alert nel formato approvato. Testo fisso, prudente."""
    from datetime import datetime as _dt, timezone as _tz
    ts = _dt.now(_tz.utc).strftime("%d/%m/%Y %H:%M UTC")
    lettura = _SCA_LETTURE.get(stato_nuovo, "Quadro descrittivo aggiornato. Fase da osservare.")
    prec_txt = stato_prec if stato_prec else "(nessuno stato precedente registrato)"
    conf_txt = conf if conf else "n/d"
    if giorni and giorni >= 1:
        conferma_txt = f"{giorni} giorn{'o' if giorni == 1 else 'i'}"
    else:
        conferma_txt = "in valutazione"
    righe = [
        "\U0001f4c8 CAMBIO DI FASE",
        "",
        f"Data/Ora: {ts}",
        "",
        f"Stato precedente: {prec_txt}",
        f"Nuovo stato: {stato_nuovo}",
        f"Confidenza: {conf_txt}",
        f"Conferma: {conferma_txt}",
        "",
        "Lettura:",
        lettura,
        "",
        "Nota: Segnale descrittivo, non ordine operativo.",
    ]
    return chr(10).join(righe)

def salva_snapshot_auto(g, p, fg, stable, deriv, trend, market_context, analisi_ai):
    """Variante automatica di salva_snapshot: tipo_evento='automatico', nessun chat_id.
    Stessa logica crash-safe e append-only su /data/snapshots.jsonl."""
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        def _gp(d, k):
            try:
                return d.get(k)
            except Exception:
                return None
        try:
            _rot = compute_rotation_state(g, trend, stable)
        except Exception:
            _rot = None
        snap = {
            "timestamp_utc": _dt.now(_tz.utc).isoformat(),
            "tipo_evento": "automatico",
            "chat_id": None,
            "prezzi": {},
            "btc_dominance": _gp(g, "dom"),
            "total2": _gp(g, "total2"),
            "total3": _gp(g, "total3"),
            "fear_greed": _gp(fg, "v"),
            "ethbtc": None,
            "stablecoin": None,
            "derivati": None,
            "trend_7d": trend if isinstance(trend, dict) else None,
            "rotation_state": None,
            "market_context": market_context,
            "analisi_completa": analisi_ai,
        }
        try:
            for sym in ("BTC", "ETH", "XRP", "SOL", "BONK", "DOGE", "BNB"):
                if sym in p:
                    snap["prezzi"][sym] = {"price": _gp(p[sym], "price"), "ch": _gp(p[sym], "ch")}
        except Exception:
            pass
        try:
            btc_pr = p.get("BTC", {}).get("price", 0)
            eth_pr = p.get("ETH", {}).get("price", 0)
            if btc_pr and eth_pr:
                snap["ethbtc"] = eth_pr / btc_pr
        except Exception:
            pass
        try:
            if isinstance(stable, dict):
                snap["stablecoin"] = stable.get("segnale")
        except Exception:
            pass
        try:
            _json.dumps(deriv)
            snap["derivati"] = deriv
        except Exception:
            snap["derivati"] = None
        try:
            snap["rotation_state"] = _rot
        except Exception:
            pass
        os.makedirs("/data", exist_ok=True)
        with open("/data/snapshots.jsonl", "a", encoding="utf-8") as f:
            f.write(_json.dumps(snap, ensure_ascii=False) + chr(10))
    except Exception as e:
        log.warning(f"salva_snapshot_auto error (non bloccante): {e}")


def salva_snapshot(g, p, fg, stable, deriv, trend, market_context, analisi_ai, uid):
    """Registratore append-only su Railway Volume /data/snapshots.jsonl.
    Salva i dati grezzi strutturati + l'analisi AI come testo integrale (Opzione A).
    Crash-safe: se il salvataggio fallisce, logga e NON solleva (il bot prosegue)."""
    try:
        import json as _json
        from datetime import datetime as _dt, timezone as _tz
        # Estraggo i dati grezzi in modo difensivo (se manca qualcosa, None)
        def _gp(d, k):
            try:
                return d.get(k)
            except Exception:
                return None
        try:
            _rot = compute_rotation_state(g, trend, stable)
        except Exception:
            _rot = None
        snap = {
            "timestamp_utc": _dt.now(_tz.utc).isoformat(),
            "tipo_evento": "analisi_manuale",
            "chat_id": str(uid) if uid else None,
            "prezzi": {},
            "btc_dominance": _gp(g, "dom"),
            "total2": _gp(g, "total2"),
            "total3": _gp(g, "total3"),
            "fear_greed": _gp(fg, "v"),
            "ethbtc": None,
            "stablecoin": None,
            "derivati": None,
            "trend_7d": trend if isinstance(trend, dict) else None,
            "rotation_state": None,
            "market_context": market_context,
            "analisi_completa": analisi_ai,
        }
        # prezzi delle coin chiave
        try:
            for sym in ("BTC", "ETH", "XRP", "SOL", "BONK", "DOGE", "BNB"):
                if sym in p:
                    snap["prezzi"][sym] = {
                        "price": _gp(p[sym], "price"),
                        "ch": _gp(p[sym], "ch"),
                    }
        except Exception:
            pass
        # ETH/BTC ratio dai prezzi
        try:
            btc_pr = p.get("BTC", {}).get("price", 0)
            eth_pr = p.get("ETH", {}).get("price", 0)
            if btc_pr and eth_pr:
                snap["ethbtc"] = eth_pr / btc_pr
        except Exception:
            pass
        # stablecoin: salvo il segnale se presente
        try:
            if isinstance(stable, dict):
                snap["stablecoin"] = stable.get("segnale")
        except Exception:
            pass
        # derivati: salvo l'oggetto cosi com'e se serializzabile
        try:
            _json.dumps(deriv)
            snap["derivati"] = deriv
        except Exception:
            snap["derivati"] = None
        # scrittura append-only
        try:
            snap["rotation_state"] = _rot
        except Exception:
            pass
        os.makedirs("/data", exist_ok=True)
        with open("/data/snapshots.jsonl", "a", encoding="utf-8") as f:
            f.write(_json.dumps(snap, ensure_ascii=False) + chr(10))
        log.info("Snapshot salvato (analisi_manuale)")
    except Exception as e:
        log.warning(f"salva_snapshot error (non bloccante): {e}")


def get_claude_response(user_msg, market_context, chat_id=None):
    try:
        api_key = os.environ.get('OPENAI_API_KEY', '')
        if not api_key: return 'API key non configurata.'
        client = OpenAI(api_key=api_key)
        pf_str = str(load_user(chat_id).get('portfolio', {})) if chat_id else '{}'
        today = datetime.now().strftime('%d/%m/%Y')
        lang = load_user(chat_id).get("lang", "it") if chat_id else "it"
        lang_instructions = {
            "it": "Rispondi SEMPRE in italiano. Guida l'utente passo passo, fai domande di follow-up se necessario.",
            "en": "ALWAYS respond in English. Guide the user step by step, ask follow-up questions if needed.",
            "pt": "Responda SEMPRE em portugues brasileiro. Guie o usuario passo a passo, faca perguntas de acompanhamento se necessario.",
        }
        lang_block = lang_instructions.get(lang, lang_instructions["it"])
        system = f"""Sei un AI Strategic Market Operator specializzato in cicli crypto e Altseason. Oggi e {today} - MAGGIO 2026.

IDENTITA:
Non sei un chatbot che descrive il mercato. Sei un operatore professionale che lo interpreta e produce decisioni operative. Ragioni come un analista senior di un hedge fund crypto. Obiettivo: massimizzare il rendimento durante il ciclo e proteggere il capitale nelle fasi di distribuzione.

ISTRUZIONE MARKET STATE (CRITICA): nel contesto trovi un blocco "MARKET STATE" in cima.
Questo blocco e' la FONTE DI VERITA' definitiva, calcolato da moduli Python deterministici
(Market Score, Rotation Engine, Bias Engine, Trigger Checklist) - NON da te. Contiene gia'
il punteggio, la fase, lo stato di rotazione, il bias sintetico, la divergenza regime e lo
stato di tutti gli 8 trigger.

NON ricalcolare questi valori. NON contraddirli. NON riscriverli con numeri o stati diversi
da quelli forniti. Per le sezioni "1. STATO MERCATO" e "2. TRIGGER CHECKLIST", riporta i
valori di MARKET STATE cosi' come forniti, senza modificarli. Il tuo compito e' SOLO
interpretare narrativamente questo stato nelle sezioni 3 (Interpretazione del Contesto),
4 (Strategia Portafoglio) e 6 (Sintesi Finale) - non ridecidere i numeri, ma spiegarne il
significato nel contesto del mercato.

REGOLE GENERALI:
- Rispondi sempre in italiano
- Non fare mai domande finali
- Niente disclaimer da chatbot
- Non limitarti a riportare i dati: spiega cosa significano
- Ogni conclusione deve portare a una decisione concreta
- Tono terminale istituzionale, frasi operative, niente spiegazioni scolastiche

REGOLA ANTI-INVENZIONE (CRITICA):
- Usa SOLO i dati presenti nel contesto qui sotto.
- Se mancano TOTAL2, TOTAL3, ETH/BTC, stablecoin inflow, Funding Rate, Open Interest o volumi, scrivi DATO NON DISPONIBILE. Non stimarli e non inventarli.
- Se un prezzo risulta 0 o assente, trattalo come DATO NON DISPONIBILE e non usarlo.
- Se un dato chiave manca, ABBASSA la confidenza dello scenario.
- Mai garantire profitti.

CONFIDENZA ANALISI:
Riporta la Confidenza Analisi (ALTA / MEDIA / BASSA) fornita nei dati, che indica quanti dati reali sono disponibili. NON inventare un punteggio numerico /100: mostra solo i dati reali e la confidenza.
DATI DISPONIBILI PER FATTORE: per ogni fattore (BTC Dominance, ETH/BTC, TOTAL2, TOTAL3, Sentiment, Altcoin Strength, Stablecoin) indica il valore reale se presente, oppure DATO NON DISPONIBILE. Non assegnare punteggi o pesi.

REGOLA COERENZA TRIGGER CHECKLIST (CRITICA): ogni voce della checklist qui sotto deve rispecchiare ESATTAMENTE
lo stato indicato sopra in DATI DISPONIBILI PER FATTORE. Se un fattore risulta DATO NON DISPONIBILE,
il trigger corrispondente DEVE essere segnato 'mancante/non disponibile', MAI 'attivo' ne' 'parziale'.
Questa regola vale anche per la sezione INTERPRETAZIONE finale: non menzionare come dato positivo o in
espansione un fattore che risultava DATO NON DISPONIBILE.


AI ANALYSIS V3 — HARD TEMPLATE DEFINITIVO:
Obiettivo: report stabile, sintetico, coerente. Non generare testo libero fuori dallo schema.

REGOLE GLOBALI:
- Usa solo label leggibili per il Rotation Engine: BTC GUIDA, ROTAZIONE ETH, ROTAZIONE LARGE CAP, ROTAZIONE MID CAP, EUFORIA MEME, WARNING DISTRIBUZIONE, RISK OFF.
- Non mostrare codici interni: BTC_LED, ETH_ROTATION, LARGE_CAP_ROTATION, MID_CAP_ROTATION, MIDCAPROTATION, RUOTA_PARZIALE.
- Non usare: “Lettura operativa”, “Focus operativo”, “Azione operativa”, “Azione suggerita”.
- Usa solo: “Interpretazione del contesto”, “Focus di monitoraggio”, “Sintesi finale”.
- Non usare linguaggio esecutivo: compra, vendi, entra, esci, long, short, incremento aggressivo, ordine.
- Se un trigger è PARZIALE, non descriverlo come pienamente confermato.
- Se un trigger è MANCANTE/NON DISPONIBILE, non citarlo come supporto positivo.
- Per TOTAL2/TOTAL3: se disponibili ma senza conferma forte, scrivi “presenti ma non confermano da soli espansione strutturale”.
- Per ampiezza alt 24h: scrivi “ampiezza positiva sulle alt nelle 24h”, e specifica che non è conferma strutturale.
- Per EMERGENTI: se stablecoin è NEUTRALE/OUTFLOW oppure Bias è Neutral/Cautela/Bearish, usa MONITORA/HOLD, mai ACCUMULA.
- Se il quadro è costruttivo ma incompleto, la sintesi finale deve essere 👀 MONITORA.

FORMATO OBBLIGATORIO DEL REPORT:

### 1. STATO MERCATO
Stato ciclo: [valore]
Confidenza Analisi: [ALTA/MEDIA/BASSA]
Rotation Engine: [label leggibile] ([confidence])
Bias Attuale: [bias]

Scenario principale: [una riga, massimo 18 parole]
Scenario alternativo: [una riga, massimo 18 parole]
Scenario avverso: [una riga, massimo 18 parole]

### 2. TRIGGER CHECKLIST
- BTC Dominance sotto area critica: [attivo/parziale/mancante]
- ETH/BTC in breakout o recupero: [attivo/parziale/mancante]
- TOTAL2/TOTAL3 in espansione: [attivo/parziale/mancante]
- Altcoin principali che sovraperformano BTC: [attivo/parziale/mancante]
- Volumi reali sulle altcoin: [attivo/parziale/mancante]
- Stablecoin inflow positivo: [attivo/parziale/mancante]
- Sentiment da fear verso neutral o greed: [attivo/parziale/mancante]
- Meme o microcap in accelerazione controllata: [attivo/parziale/mancante]

### 3. INTERPRETAZIONE DEL CONTESTO
Supporta il quadro:
- [massimo 3 punti brevi]

Limita il quadro:
- [massimo 3 punti brevi]

Elementi da osservare:
- [massimo 3 punti brevi]

### 4. STRATEGIA PORTAFOGLIO
Blue chip: [HOLD/MONITORA]
Quasi blue chip: [HOLD/MONITORA]
Emergenti: [HOLD/MONITORA]
Meme/microcap: [HOLD/MONITORA]
Note concentrazione: [massimo 1 riga]

### 5. FINESTRA DI MONITORAGGIO
Prossimo controllo critico: [12h/24h/48h/72h]
Urgenza: [BASSA/MEDIA/ALTA]

### 6. SINTESI FINALE
👀 MONITORA
Focus di monitoraggio:
- [massimo 3 punti brevi]

Bias Attuale: [bias]

VIETATO:
- paragrafi lunghi nella sezione 1
- ripetere gli stessi dati in più sezioni
- aggiungere target price
- aggiungere percentuali operative
- usare “probabilità” numeriche
- usare “azione operativa”
- usare “lettura operativa”
- usare “focus operativo”


TRIGGER CHECKLIST — STATI CONSENTITI:
- ATTIVO = dato disponibile e trigger soddisfatto
- PARZIALE = dato disponibile ma conferma incompleta
- NON ATTIVO = dato presente ma trigger non soddisfatto
- MANCANTE/NON DISPONIBILE = dato assente

IMPORTANTE:
Usa MANCANTE solo quando il dato non esiste davvero.
Se il dato esiste ma il trigger è spento, usa NON ATTIVO.

TRIGGER CHECKLIST (segna ogni voce come attivo, parziale, o mancante/non disponibile):
- BTC Dominance sotto area critica
- ETH/BTC in breakout o recupero
- TOTAL2/TOTAL3 in espansione
- Altcoin principali che sovraperformano BTC
- Volumi reali sulle altcoin
- Stablecoin inflow positivo
- Sentiment da fear verso neutral o greed
- Meme o microcap in accelerazione controllata

CLASSIFICAZIONE PORTAFOGLIO:
BLUE CHIP: ETH, SOL, XRP, ADA, DOGE, BNB, BTC
QUASI BLUE CHIP: AVAX, DOT, NEAR, LINK, ATOM
EMERGENTI: SUI, APT, TIA, AR, RNDR, RENDER, FET, HBAR, SEI, GRT, INJ, ALGO, FXS
MEME / MICROCAP: DOGE, SHIB, PEPE, BONK, FLOKI, WIF, BOME, BUZZ, WEPE
(Se una coin non rientra, assegnala alla categoria piu vicina per market cap e rischio.)
Per ogni categoria presente nel portafoglio indica una azione tra: HOLD, MONITORA, ACCUMULA SELETTIVAMENTE, RIDUCI PARZIALMENTE, NESSUNA AZIONE.
Usa ESCLUSIVAMENTE gli asset realmente presenti nel portafoglio utente indicato sotto. Non elencare coin generiche o di esempio se non sono nel portafoglio. Se una categoria non ha asset nel portafoglio, scrivi: nessun asset in questa categoria.

REGOLE COERENZA PORTAFOGLIO:
- Se Rotation Engine e' BTC_LED, gli EMERGENTI devono essere MONITORA / HOLD, mai ACCUMULA.
- Se Bias Attuale e' Neutral, Cautela o Bearish, gli EMERGENTI devono essere MONITORA / HOLD.
- Se Stablecoin e' NEUTRALE o OUTFLOW, non usare accumulo aggressivo sugli EMERGENTI.
- Usa ACCUMULA SELETTIVAMENTE sugli EMERGENTI solo se la rotazione e' almeno ETH_ROTATION o LARGE_CAP_ROTATION, il Bias Attuale e' almeno Leggermente Bullish, e la liquidita' non e' negativa.
- Non usare ESCI come azione di portafoglio salvo DISTRIBUTION_WARNING o RISK_OFF con confidenza alta.

ALERT LOGIC (classifica sempre il segnale):
MONITORA = condizione interessante ma non ancora operativa
AZIONE = condizione che richiede intervento: specifica coin, percentuale, motivo, finestra
ALERT CRITICO = condizione che richiede attenzione immediata

REGOLE LINGUAGGIO OUTPUT (vincolanti):
- Non mostrare mai codici interni come RUOTA_PARZIALE all'utente finale. Se emerge un codice interno, rendilo come MONITORA.
- Usa sempre la formula 'Interpretazione del contesto' per descrivere il quadro di mercato.
- Mantieni il linguaggio descrittivo e prudente: nessun ordine automatico.

REGOLE DECISIONALI (vincolanti):
Le azioni numeriche precise (percentuali tipo 'riduci BONK 20-25%', oppure 'compra XRP', 'vendi DOGE') sono ammesse SOLO se Confidenza Analisi e' ALTA.
Se Confidenza Analisi e' MEDIA o BASSA, oppure se mancano dati critici (Open Interest, Funding Rate, Stablecoin Inflow, Volumi reali): NON dare percentuali ne' ordini secchi di acquisto/vendita. Usa invece 👀 MONITORA oppure ⚠️ VALUTARE RIDUZIONE, con una breve spiegazione del perche' i dati non bastano per un'azione precisa.

FINESTRA OPERATIVA:
Indica il prossimo controllo critico (12h, 24h, 48h o 72h) e il livello di urgenza (BASSA, MEDIA, ALTA o CRITICA).

STRUTTURA RISPOSTA OBBLIGATORIA (usa questi titoli e questo ordine, apri con la data):
1. FASE MERCATO: stato ciclo, Confidenza Analisi, scenario principale / alternativo / avverso con probabilita
2. TRIGGER CHECKLIST: trigger attivi, parziali e mancanti
3. INTERPRETAZIONE DATI: sintesi dei dati disponibili, dichiara i dati mancanti
4. STRATEGIA PORTAFOGLIO: Blue chip, Quasi blue chip, Emergenti, Meme/microcap con azione per categoria
5. FINESTRA OPERATIVA: prossimo controllo critico e urgenza
6. AZIONE OPERATIVA: MONITORA, AZIONE o ALERT CRITICO

DATI MERCATO:
{market_context}

PORTAFOGLIO UTENTE (base di ogni analisi):
{pf_str}

{lang_block}

ROTATION ENGINE: nel contesto trovi un blocco "ROTATION ENGINE (descrittivo...)". Usalo come DATO OGGETTIVO per arricchire la lettura della rotazione di mercato, citando stato, confidenza e azione suggerita. MA dichiara SEMPRE che e' un motore descrittivo e non un segnale automatico di trading: scrivi esplicitamente "Rotation Engine descrittivo, non segnale automatico". Non trasformare mai la sua azione suggerita in un ordine secco; resta su formulazioni prudenti (valutare, monitorare). Se la sua confidenza e' LOW, trattalo come indicazione debole.

NOTA PORTAFOGLIO: nel contesto puoi trovare un blocco NOTA PORTAFOGLIO (descrittiva) con osservazioni sul portafoglio reale dell utente (concentrazioni, asset deboli o forti, possibili aree di rotazione). Usalo come spunto descrittivo, MANTENENDO il linguaggio prudente: parla solo di da valutare, da monitorare, posizione concentrata, possibile rotazione da studiare. NON dare MAI percentuali operative, NON dire MAI vendi o compra, NON indicare quantita da spostare. Ricorda sempre che e un modulo descrittivo, non consulenza finanziaria, non segnale automatico.

Massimo 250-350 parole. Sii compatto e operativo. Non inventare dati: se mancano, dichiaralo. Mai garantire profitti."""
        msg = client.responses.create(
            model=_pick_model(chat_id),
            instructions=system,
            input=user_msg,
            max_output_tokens=2500
        )
        return msg.output_text
    except Exception as e:
        return f'Errore AI: {e}'

def check_alerts_user(chat_id, prices):
    ud = load_user(chat_id)
    triggered, remaining = [], []
    for a in ud.get("alerts", []):
        sym, target, above = a["sym"], a["price"], a["above"]
        cur = prices.get(sym, {}).get("price", 0)
        if cur == 0: remaining.append(a); continue
        hit = (above and cur >= target) or (not above and cur <= target)
        if hit:
            d = "↗️" if above else "↘️"
            triggered.append(f"🔔 *{sym}* {d} Target `${target:,.2f}` — ora `${cur:,.2f}`")
        else:
            remaining.append(a)
    if triggered:
        ud["alerts"] = remaining
        save_user(chat_id, ud)
    return triggered

# ============================================================
# COMANDI BOT
# ============================================================
async def cmd_start(u, c):
    # Mostra SEMPRE i 3 pulsanti lingua quando l'utente preme /start.
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇮🇹 Italiano", callback_data="lang_it"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇧🇷 Português", callback_data="lang_pt"),
        ]
    ])
    await u.message.reply_text(
        "👋 *Benvenuto / Welcome / Bem-vindo!*\n\n"
        "🌍 Scegli la tua lingua per continuare.\n"
        "Choose your language to continue.\n"
        "Escolha seu idioma para continuar.",
        parse_mode="Markdown",
        reply_markup=buttons
    )



async def cmd_language(u, c):
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇮🇹 Italiano", callback_data="lang_it"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇧🇷 Português", callback_data="lang_pt"),
        ]
    ])
    await u.message.reply_text(
        "🌍 *Scegli la lingua / Choose language / Escolha o idioma:*",
        parse_mode="Markdown",
        reply_markup=buttons
    )

async def lang_callback(update, context):
    query = update.callback_query
    await query.answer()
    uid = str(query.message.chat_id)
    lang = query.data.replace("lang_", "")
    ud = load_user(uid)
    ud["lang"] = lang
    ud["welcomed"] = True
    save_user(uid, ud)
    name = query.from_user.first_name or "amico"
    msg = t(uid, "welcome", name)
    await query.edit_message_text(msg, parse_mode="Markdown")
    await context.bot.send_message(chat_id=int(uid), text="✅", reply_markup=get_keyboard(lang))

async def cmd_help(u, c):
    msg = """👋 *ALTSEASON BOT 2026*

📊 *MERCATO*
/status — Report completo
/phase — Fase del ciclo
/feargreed — Sentiment
/rsimacd — RSI e MACD
/top — Top performer
/forex — Forex & Indici
/news — Ultime notizie
/language — Cambia lingua

💼 *PORTFOLIO*
/portfolio — P&L in tempo reale
/add — Aggiungi coin (wizard)
/addcoin SYM QTY PRICE — Aggiungi
/removecoin SYM — Rimuovi
/reset — Reset portfolio

🔔 *ALERT*
/alert XRP 3 — Alert prezzo
/alerts — Lista alert
/delalert 1 — Cancella alert
/setup — 28 alert strategia

📅 *STRATEGIA*
/timeline — Roadmap 2026
/exitplan — Piano uscita
/stoploss — Check uscita

💰 *ACCOUNT*
/myplan — Il tuo piano
/upgrade — Info piani
/pay — Abbonati
/referral — Tuo link referral
/share — Condividi bot
/admin — Pannello admin

🤖 Scrivi qualsiasi domanda per parlare con l'AI!"""
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_status(u, c):
    await u.message.reply_text("⏳ Recupero dati...", reply_markup=KEYBOARD)
    try:
        g = get_global(); p = get_prices(); fg = get_fg()
        ph, desc, level = phase(g["dom"])
        eth_btc = p["ETH"]["price"] / p["BTC"]["price"] if p["BTC"]["price"] else 0
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        msg = (f"*🤖 STATUS — {now}*\n\n{ph} (`{level}`)\n_{desc}_\n\n"
               f"📊 *MACRO*\n• BTC Dom: `{g['dom']:.2f}%`\n• ETH/BTC: `{eth_btc:.5f}`\n"
               f"• TOTAL3: `${g['total3']:.1f}B`\n• Fear&Greed: {fg['em']} `{fg['v']} — {fg['lbl']}`\n\n"
               f"💰 *PREZZI*\n• BTC: `${p['BTC']['price']:,.0f}` ({p['BTC']['ch']:+.1f}%)\n"
               f"• ETH: `${p['ETH']['price']:,.0f}` ({p['ETH']['ch']:+.1f}%)\n"
               f"• XRP: `${p['XRP']['price']:,.3f}` ({p['XRP']['ch']:+.1f}%)\n"
               f"• SOL: `${p['SOL']['price']:,.1f}` ({p['SOL']['ch']:+.1f}%)")
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_phase(u, c):
    try:
        g = get_global(); ph, desc, level = phase(g["dom"])
        actions = {
            "MONITORA": "1️⃣ Tieni tutto\n2️⃣ Aspetta BTC Dom <52%\n3️⃣ Non vendere ancora",
            "AZIONE": "1️⃣ Ruota verso altcoin\n2️⃣ Vendi 25% quando +100%\n3️⃣ Monitora XRP pump tardivo",
            "USCITA": "1️⃣ ESCI progressivamente\n2️⃣ Sposta in USDT\n3️⃣ DOGE e BONK escono primi",
        }
        msg = f"{ph}\n\n_{desc}_\n\nBTC Dom: `{g['dom']:.2f}%`\n\n📋 *Cosa fare ora:*\n{actions[level]}"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_feargreed(u, c):
    try:
        fg = get_fg(); v = fg["v"]
        desc = "Paura estrema — COMPRA 🛒" if v <= 25 else "Paura — Accumula" if v <= 45 else "Neutro" if v <= 55 else "Avidità — Attenzione" if v <= 75 else "Avidità estrema — VENDI ⚠️"
        msg = f"😱 *FEAR & GREED*\n\n{fg['em']} `{v}/100 — {fg['lbl']}`\n\n_{desc}_"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_rsimacd(u, c):
    await u.message.reply_text("⏳ Calcolo indicatori...", reply_markup=KEYBOARD)
    try:
        inds = get_indicators()
        lines = ["📉 *RSI & MACD*\n"]
        for sym in ["BTC", "ETH"]:
            ind = inds.get(sym, {})
            rsi = ind.get("rsi")
            hist = ind.get("hist", 0)
            trend = "↗️ Rialzista" if hist and hist > 0 else "↘️ Ribassista"
            if rsi is None:
                rsi_s = "⚪ Dati non disponibili"
            elif float(rsi) < RSI_OVERSOLD:
                rsi_s = "🟢 Oversold — COMPRA"
            elif float(rsi) > RSI_OVERBOUGHT:
                rsi_s = "🔴 Overbought — ATTENZIONE"
            else:
                rsi_s = "⚪ Neutro"
            spike = ind.get("vol_spike")
            lines += [f"*{sym}*", f"• RSI: `{rsi}` {rsi_s}", f"• MACD: {trend}", f"• Volume: {'🔊 SPIKE ' + str(spike) + 'x!' if spike else '✅ Normale'}", ""]
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_top(u, c):
    try:
        p = get_prices()
        s = sorted(p.items(), key=lambda x: x[1]["ch"], reverse=True)
        lines = ["🏆 *TOP PERFORMER 24h*\n"]
        for i, (sym, d) in enumerate(s[:5], 1):
            a = "🟢" if d["ch"] >= 0 else "🔴"
            lines.append(f"{i}. {a} *{sym}*: `{d['ch']:+.2f}%` — `${d['price']:,.4f}`")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_forex(u, c):
    await u.message.reply_text("⏳ Recupero dati forex...", reply_markup=KEYBOARD)
    try:
        data = get_forex()
        if not data:
            await u.message.reply_text("❌ Dati forex non disponibili", reply_markup=KEYBOARD)
            return
        lines = ["💱 *FOREX & INDICI*\n", "🌍 *Valute principali*"]
        for sym in ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD"]:
            if sym in data:
                d = data[sym]; a = "🟢" if d["ch"] >= 0 else "🔴"
                lines.append(f"{a} *{sym}*: `{d['price']:.4f}` ({d['ch']:+.2f}%)")
        lines.append("\n📈 *Indici & Commodities*")
        for sym in ["S&P500", "NASDAQ", "XAU/USD", "XAG/USD", "DXY"]:
            if sym in data:
                d = data[sym]; a = "🟢" if d["ch"] >= 0 else "🔴"
                pfmt = f"{d['price']:,.2f}" if d['price'] > 100 else f"{d['price']:.4f}"
                lines.append(f"{a} *{sym}*: `{pfmt}` ({d['ch']:+.2f}%)")
        lines.append("\n_Scrivi: Analizza EUR/USD per analisi AI_")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_news(u, c):
    uid = get_uid(u)
    lang = load_user(uid).get("lang", "it")
    loading = {
        "it": "⏳ Recupero notizie crypto...",
        "en": "⏳ Fetching crypto news...",
        "pt": "⏳ Buscando noticias crypto...",
    }.get(lang, "⏳ Recupero notizie crypto...")
    title = {
        "it": "📰 ULTIME NEWS CRYPTO",
        "en": "📰 LATEST CRYPTO NEWS",
        "pt": "📰 ULTIMAS NOTICIAS CRYPTO",
    }.get(lang, "📰 ULTIME NEWS CRYPTO")
    empty = {
        "it": "❌ Notizie non disponibili ora. Riprova tra qualche minuto.",
        "en": "❌ News unavailable right now. Try again in a few minutes.",
        "pt": "❌ Noticias indisponiveis agora. Tente novamente em alguns minutos.",
    }.get(lang, "❌ Notizie non disponibili ora. Riprova tra qualche minuto.")

    await u.message.reply_text(loading, reply_markup=kb(uid))

    try:
        news_items = []

        # 1) CryptoPanic: usa una API key vera se presente nelle variabili ambiente.
        cryptopanic_token = os.environ.get("CRYPTOPANIC_TOKEN", "").strip()
        if cryptopanic_token:
            try:
                url = (
                    "https://cryptopanic.com/api/v1/posts/"
                    f"?auth_token={cryptopanic_token}"
                    "&currencies=BTC,ETH,XRP,SOL&kind=news&public=true"
                )
                r = requests.get(url, timeout=10, headers={"User-Agent": "AltseasonBot/1.0"})
                if r.ok:
                    for item in r.json().get("results", [])[:6]:
                        item_title = (item.get("title") or "").strip()
                        item_url = (item.get("url") or "").strip()
                        if item_title and item_url:
                            news_items.append((item_title, item_url, "CryptoPanic", ""))
            except Exception as e:
                log.warning(f"CryptoPanic news error: {e}")

        # 2) Fallback RSS senza API key, cosi il bottone News risponde anche senza CryptoPanic.
        if len(news_items) < 6:
            import xml.etree.ElementTree as ET
            rss_sources = [
                ("Cointelegraph", "https://cointelegraph.com/rss"),
                ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
                ("Decrypt", "https://decrypt.co/feed"),
            ]
            seen_urls = {url for _, url, _ in news_items}
            for source_name, feed_url in rss_sources:
                if len(news_items) >= 6:
                    break
                try:
                    r = requests.get(feed_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                    if not r.ok:
                        continue
                    root = ET.fromstring(r.content)
                    for item in root.findall(".//item"):
                        if len(news_items) >= 6:
                            break
                        item_title = (item.findtext("title") or "").strip()
                        item_url = (item.findtext("link") or "").strip()
                        item_desc = (item.findtext("description") or "").strip()
                        if item_desc:
                            import re as _re
                            item_desc = _re.sub(r"<[^>]+>", "", item_desc)[:300]
                        if item_title and item_url and item_url not in seen_urls:
                            seen_urls.add(item_url)
                            news_items.append((item_title, item_url, source_name, item_desc))
                except Exception as e:
                    log.warning(f"RSS news error {source_name}: {e}")

        if not news_items:
            await u.message.reply_text(empty, reply_markup=kb(uid))
            return

        top_news = news_items[:6]
        sintesi = ""
        try:
            blocco = ""
            for it in top_news:
                t = it[0]
                d = it[3] if len(it) > 3 else ""
                blocco += f"- {t}"
                if d:
                    blocco += f" ({d})"
                blocco += "\n"
            sintesi = get_news_summary(blocco, lang)
            if sintesi and len(sintesi) > 900:
                sintesi = sintesi[:900].rsplit(".", 1)[0] + "."
        except Exception as e:
            log.warning(f"News sintesi AI error: {e}")
            sintesi = ""

        lines = [title, ""]
        if sintesi and sintesi.strip():
            lines.append(sintesi.strip())
            lines.append("")
            lines.append("───────")
            lines.append("")
        for it in top_news:
            item_title = it[0]; item_url = it[1]; source = it[2]
            clean_title = item_title.replace("\n", " ").strip()[:120]
            lines.append(f"• {clean_title}")
            lines.append(f"  Fonte: {source}")
            lines.append(f"  {item_url}")
            lines.append("")

        msg_finale = "\n".join(lines).strip()
        # Taglio di sicurezza: Telegram limita a 4096 caratteri.
        if len(msg_finale) > 3900:
            msg_finale = msg_finale[:3900].rsplit("\n", 1)[0] + "\n\n[...]"
        await u.message.reply_text(
            msg_finale,
            reply_markup=kb(uid),
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"News command error: {e}")
        await u.message.reply_text(empty, reply_markup=kb(uid))

# ============================================================
# TIMELINE - FASE ATTUALE (descrittivo, non previsione)
# ============================================================
# Refactor del vecchio cmd_timeline (che faceva previsioni/target/date).
# Ora legge lo stato ATTUALE del Rotation Engine e spiega la fase corrente.
# Frasi pre-approvate. Nessuna previsione, nessun target, nessuna data futura.

# Frasi di spiegazione APPROVATE (esatte). Una per stato del Rotation Engine.
_TIMELINE_FASI = {
    "BTC_LED": "Fase in cui Bitcoin mantiene la leadership e il capitale non si sposta ancora con decisione verso le altcoin. Da osservare: la BTC Dominance e la tenuta di ETH/BTC. Conferma da verificare nel tempo.",
    "ETH_ROTATION": "Fase in cui Ethereum mostra forza relativa rispetto a Bitcoin, spesso primo segnale di spostamento del capitale verso asset a maggior rischio. Da osservare: ETH/BTC e il comportamento delle large cap. Conferma da verificare.",
    "LARGE_CAP_ROTATION": "Fase in cui le large cap (oltre a ETH) mostrano forza relativa rispetto a Bitcoin ed Ethereum. Da osservare: se la forza si estende ad altri segmenti o resta circoscritta. Conferma da verificare.",
    "MID_CAP_ROTATION": "Fase in cui le mid cap mostrano forza relativa crescente rispetto alle large cap. Storicamente associata a una rotazione piu avanzata del capitale. Da osservare: ampiezza del movimento e sentiment. Conferma da verificare.",
    "MEME_EUPHORIA": "Fase in cui il comparto meme mostra forza marcata, storicamente associata a momenti avanzati e speculativi del ciclo. Da osservare con particolare attenzione: sentiment e sostenibilita del movimento. Conferma da verificare.",
    "DISTRIBUTION_WARNING": "Fase che combina euforia sui meme con debolezza relativa nelle aree guida: un quadro che storicamente segnala possibile distribuzione. Da osservare con attenzione: ETH/BTC e BTC Dominance. Conferma da verificare.",
    "RISK_OFF": "Fase in cui il capitale sembra muoversi verso la prudenza: debolezza diffusa e leadership difensiva. Da osservare: stabilizzazione del sentiment e tenuta dei livelli. Conferma da verificare. Nessuna azione automatica.",
}

def _fmt_timeline_fase(rot=None, fg=None, g=None, trend=None):
    """Compone il pannello TIMELINE - FASE ATTUALE (lettura del presente).
    Se lo stato del Rotation Engine non e' determinabile, lo dichiara invece di inventare.
    Tollerante a dati mancanti."""
    from datetime import datetime as _dt, timezone as _tz
    ts = _dt.now(_tz.utc).strftime("%d/%m/%Y %H:%M UTC")

    # Estrazione tollerante
    state = None
    conf = None
    try:
        if rot and isinstance(rot, dict):
            state = rot.get("state")
            conf = rot.get("confidence")
    except Exception:
        pass

    fg_val = None
    try:
        if fg and isinstance(fg, dict):
            fg_val = fg.get("v")
    except Exception:
        pass

    dom = None
    try:
        if g and isinstance(g, dict):
            dom = g.get("dom")
    except Exception:
        pass

    ethbtc = None
    try:
        if trend and isinstance(trend, dict) and "ethbtc" in trend:
            ethbtc = trend["ethbtc"].get("oggi")
    except Exception:
        pass

    fg_txt = str(fg_val) if fg_val is not None else "n/d"
    conf_txt = conf if conf else "n/d"
    dom_txt = f"{dom:.1f}%" if dom is not None else "n/d"
    ethbtc_txt = f"{ethbtc:.5f}" if ethbtc is not None else "n/d"

    # Spiegazione della fase, oppure "non determinabile"
    if state and state in _TIMELINE_FASI:
        state_txt = state
        spiegazione = _TIMELINE_FASI[state]
    else:
        state_txt = "non determinabile"
        spiegazione = "Fase non determinabile al momento, riprova tra qualche minuto."

    righe = [
        "\U0001f4c5 TIMELINE \u2014 FASE ATTUALE",
        "",
        f"\U0001f552 {ts}",
        f"Rotation Engine: {state_txt}",
        f"Confidence: {conf_txt}",
        f"Fear & Greed: {fg_txt}",
        f"BTC Dominance: {dom_txt}",
        f"ETH/BTC: {ethbtc_txt}",
        "",
        "Fase attuale:",
        spiegazione,
        "",
        "Nota: Lettura descrittiva del presente, non previsione ne ordine operativo.",
    ]
    return chr(10).join(righe)


# ============================================================
# AI ANALYSIS V3 — OUTPUT HARDENING / DISPLAY SANITIZER
# ============================================================

_ROTATION_DISPLAY_LABELS_V3 = {
    "BTC_LED": "BTC GUIDA",
    "ETH_ROTATION": "ROTAZIONE ETH",
    "LARGE_CAP_ROTATION": "ROTAZIONE LARGE CAP",
    "MID_CAP_ROTATION": "ROTAZIONE MID CAP",
    "MEME_EUPHORIA": "EUFORIA MEME",
    "DISTRIBUTION_WARNING": "WARNING DISTRIBUZIONE",
    "RISK_OFF": "RISK OFF",
    "MIDCAPROTATION": "ROTAZIONE MID CAP",
    "MID CAP ROTATION": "ROTAZIONE MID CAP",
    "ETHROTATION": "ROTAZIONE ETH",
    "ETH ROTATION": "ROTAZIONE ETH",
    "LARGECAPROTATION": "ROTAZIONE LARGE CAP",
    "LARGE CAP ROTATION": "ROTAZIONE LARGE CAP",
}

def _rotation_display_v3(value):
    try:
        if value is None:
            return "n/d"
        raw = str(value).strip()
        key = raw.upper().replace(" ", "_").replace("-", "_")
        compact = raw.upper().replace("_", "").replace(" ", "").replace("-", "")
        if key in _ROTATION_DISPLAY_LABELS_V3:
            return _ROTATION_DISPLAY_LABELS_V3[key]
        if compact in _ROTATION_DISPLAY_LABELS_V3:
            return _ROTATION_DISPLAY_LABELS_V3[compact]
        return raw
    except Exception:
        return str(value)

def _sanitize_ai_analysis_v3(report_text):
    """Pulizia finale deterministica del report AI Analysis.
    Non cambia i dati di mercato: normalizza solo codici interni, wording operativo
    e casi evidenti di incoerenza testuale.
    v4: fix regex \\1 mancante (Sentiment + Stablecoin), dedup Bias robusto
    (case-insensitive, tollerante a markdown/spazi/emoji), blocco Stablecoin
    unificato (no piu' ridondanza), wording extra (target price, long/short, compra/vendi).
    """
    try:
        txt = report_text or ""

        replacements = {
            "BTC_LED": "BTC GUIDA",
            "ETH_ROTATION": "ROTAZIONE ETH",
            "LARGE_CAP_ROTATION": "ROTAZIONE LARGE CAP",
            "MID_CAP_ROTATION": "ROTAZIONE MID CAP",
            "MIDCAPROTATION": "ROTAZIONE MID CAP",
            "ETHROTATION": "ROTAZIONE ETH",
            "LARGECAPROTATION": "ROTAZIONE LARGE CAP",
            "MEME_EUPHORIA": "EUFORIA MEME",
            "DISTRIBUTION_WARNING": "WARNING DISTRIBUZIONE",
            "RISK_OFF": "RISK OFF",
            "RUOTA_PARZIALE": "MONITORA",
        }
        for old, new in replacements.items():
            txt = txt.replace(old, new)

        wording = {
            "### 6. AZIONE OPERATIVA": "### 6. SINTESI FINALE",
            "**6. AZIONE OPERATIVA**": "**6. SINTESI FINALE**",
            "AZIONE OPERATIVA": "SINTESI FINALE",
            "Azione operativa": "Sintesi finale",
            "Lettura operativa:": "Interpretazione del contesto:",
            "**Lettura operativa:**": "**Interpretazione del contesto:**",
            "lettura operativa:": "interpretazione del contesto:",
            "Focus operativo:": "Focus di monitoraggio:",
            "**Focus operativo:**": "**Focus di monitoraggio:**",
            "focus operativo:": "focus di monitoraggio:",
            "azione operativa": "sintesi finale",
            "Azione Operativa": "Sintesi Finale",
            "azione suggerita": "indicazione descrittiva",
            "Azione suggerita": "Indicazione descrittiva",
            "incremento aggressivo": "espansione aggressiva",
            "Incremento aggressivo": "Espansione aggressiva",
            "evitare incremento aggressivo": "evitare espansione aggressiva",
            "Evitare incremento aggressivo": "Evitare espansione aggressiva",
            "breadth alt positiva": "ampiezza positiva sulle alt",
            "Breadth alt positiva": "Ampiezza positiva sulle alt",
        }
        for old, new in wording.items():
            txt = txt.replace(old, new)

        txt = txt.replace(
            "TOTAL2/TOTAL3 sono presenti",
            "TOTAL2/TOTAL3 sono presenti ma non confermano da soli espansione strutturale"
        )
        txt = txt.replace(
            "TOTAL2/TOTAL3 elevati e breadth positiva supportano accumulo selettivo",
            "TOTAL2/TOTAL3 presenti e ampiezza positiva sulle alt suggeriscono miglioramento interno, ma non confermano ancora espansione strutturale"
        )

        txt = re.sub(
            r"(?im)^(\s*[-•]?\s*\*{0,2}Emergenti[^:\n]*:\*{0,2}.*?)(ACCUMULA(?:\s+SELETTIVAMENTE)?)(.*)$",
            lambda m: m.group(1) + "MONITORA" + m.group(3),
            txt
        )

        txt = txt.replace("posizioni long", "posizioni da osservare")
        txt = txt.replace("Posizioni long", "Posizioni da osservare")
        txt = txt.replace("ordine secco", "indicazione secca")
        txt = txt.replace("ordine automatico", "segnale automatico")

        # --- FIX A (v4): regex con \1 corretto (prima perdevano il prefisso catturato) ---
        try:
            if re.search(r"(Fear\s*&\s*Greed|Sentiment)[^\d]{0,25}\d{1,3}", txt, re.I):
                txt = re.sub(
                    r"(Sentiment in zona di interesse contrarian:\s*)mancante",
                    r"\1non attivo",
                    txt,
                    flags=re.I
                )
        except Exception:
            pass

        # --- FIX C (v4): blocco Stablecoin UNIFICATO (sostituisce sia il vecchio blocco regex
        # sia il vecchio blocco "FIX 2" duplicato - una sola logica, piu' robusta, copre piu' varianti) ---
        try:
            if re.search(r"Stablecoin\s*:?\s*(NEUTRALE|NEUTRAL)\b", txt, re.I):
                txt = re.sub(
                    r"(Stablecoin\s+inflow\s+positivo\s*:\s*)mancante",
                    r"\1parziale",
                    txt,
                    flags=re.I
                )
        except Exception:
            pass

        # --- FIX B (v4): dedup Bias Attuale ROBUSTO (case-insensitive, tollerante a
        # markdown/spazi/emoji iniziali). Tiene solo l'ULTIMA occorrenza, la riappende in fondo. ---
        try:
            _bias_pat = re.compile(r'^\s*[*_🔴🟢🟡🟠🟣\s]*bias\s+attuale\s*:', re.I)
            righe = txt.split("\n")
            bias_lines = [r for r in righe if _bias_pat.match(r)]
            bias_finale = bias_lines[-1].strip() if bias_lines else None
            nuove = [r for r in righe if not _bias_pat.match(r)]
            # rimuovo eventuali righe vuote finali multiple lasciate dalla rimozione
            while nuove and nuove[-1].strip() == "":
                nuove.pop()
            if bias_finale:
                nuove.append("")
                nuove.append(bias_finale)
            txt = "\n".join(nuove)
        except Exception:
            pass

        # --- FIX D (v4): wording extra (target price, long/short, compra/vendi) ---
        try:
            txt = re.sub(r"\btarget\s+prices\b", "obiettivi prezzo", txt, flags=re.I)
            txt = re.sub(r"\btarget\s+price\b", "obiettivo prezzo", txt, flags=re.I)
            txt = re.sub(r"\blong\b", "da osservare", txt, flags=re.I)
            txt = re.sub(r"\bshort\b", "da osservare", txt, flags=re.I)
            txt = re.sub(r"\bcompra\b", "monitora", txt, flags=re.I)
            txt = re.sub(r"\bvendi\b", "monitora", txt, flags=re.I)
        except Exception:
            pass

        return txt
    except Exception:
        return report_text

async def cmd_timeline(u, c):
    """Pannello FASE ATTUALE (descrittivo): legge lo stato del Rotation Engine e spiega la fase corrente."""
    try:
        g = get_global(); fg = get_fg()
        _stable = get_stablecoins()
        _trend = get_trend_7d()
        _rot = compute_rotation_state(g, _trend, _stable)
        msg = _fmt_timeline_fase(rot=_rot, fg=fg, g=g, trend=_trend)
        await u.message.reply_text(msg, reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

def _fmt_qty(q):
    """Formatta la quantita in modo compatto: 161.8M, 22.6K, 10.45."""
    try:
        q = float(q)
    except Exception:
        return str(q)
    aq = abs(q)
    if aq >= 1_000_000_000:
        return f"{q/1_000_000_000:.1f}B"
    if aq >= 1_000_000:
        return f"{q/1_000_000:.1f}M"
    if aq >= 1_000:
        return f"{q/1_000:.1f}K"
    if aq >= 1:
        # numeri piccoli: max 2 decimali, senza decimali inutili
        return f"{q:.2f}".rstrip("0").rstrip(".")
    # micro (es. prezzi non quantita, ma per sicurezza)
    return f"{q:.4f}".rstrip("0").rstrip(".")

async def cmd_portfolio(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    pf = ud.get("portfolio", {})
    if not pf:
        await u.message.reply_text("💼 Portfolio vuoto!\n\nUsa /add per aggiungere le tue coin\noppure /reset per caricare il portfolio di default", reply_markup=KEYBOARD)
        return
    try:
        prices = get_prices()
        lines = ["💼 *PORTFOLIO*\n"]
        ti = tc = 0
        for sym, pos in sorted(pf.items()):
            pr = prices.get(sym, {}).get("price", 0)
            if pr == 0: continue
            qty, buy = pos["qty"], pos["buy"]
            inv, cur = qty * buy, qty * pr
            pnl = cur - inv
            pct = ((pr - buy) / buy * 100) if buy else 0
            a = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"{a} *{sym}*: `{_fmt_qty(qty)}` | `{pct:+.1f}%` (`${pnl:+,.0f}`)")
            ti += inv; tc += cur
        tp = tc - ti
        tpct = ((tc - ti) / ti * 100) if ti else 0
        a = "🟢" if tp >= 0 else "🔴"
        lines.append(f"\n💰 Investito: `${ti:,.0f}`")
        lines.append(f"💎 Attuale: `${tc:,.0f}`")
        lines.append(f"{a} *P&L TOT*: `{tpct:+.1f}%` (`${tp:+,.0f}`)")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_reset(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    if uid == ADMIN_ID:
        import copy as _copy
        _pf = _copy.deepcopy(ADMIN_PORTFOLIO)
        try:
            _prezzi = get_prices()
            for _sym, _pos in _pf.items():
                if _pos.get("buy") is None:
                    _pr = _prezzi.get(_sym, {}).get("price", 0)
                    _pos["buy"] = _pr if _pr else 0
        except Exception as _e:
            log.warning(f"reset: prezzi non recuperati per buy dinamico: {_e}")
            for _sym, _pos in _pf.items():
                if _pos.get("buy") is None:
                    _pos["buy"] = 0
        ud["portfolio"] = _pf
        ud["plan"] = "pro"
        ud["ai_msgs"] = 0
        save_user(uid, ud)
        await u.message.reply_text(f"✅ Portfolio admin caricato!\n{len(ADMIN_PORTFOLIO)} coin — Piano Pro", reply_markup=KEYBOARD)
    else:
        ud["portfolio"] = {}
        save_user(uid, ud)
        await u.message.reply_text("✅ Portfolio resettato!\nUsa /add per aggiungere le tue coin", reply_markup=KEYBOARD)

async def cmd_addcoin(u, c):
    if len(c.args) < 3:
        await u.message.reply_text("Uso: /addcoin BTC 0.5 95000", reply_markup=KEYBOARD)
        return
    s = c.args[0].upper()
    if s not in ASSETS:
        await u.message.reply_text("❌ Asset non valido", reply_markup=KEYBOARD)
        return
    try:
        qty = float(c.args[1])
        buy = float(c.args[2].replace(",", ""))
        uid = get_uid(u)
        ud = load_user(uid)
        ud["portfolio"][s] = {"qty": qty, "buy": buy}
        save_user(uid, ud)
        await u.message.reply_text(f"✅ *{s}*: `{qty}` @ `${buy:,.4f}`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except:
        await u.message.reply_text("❌ Valori non validi", reply_markup=KEYBOARD)

async def cmd_removecoin(u, c):
    if not c.args:
        await u.message.reply_text("Uso: /removecoin BTC", reply_markup=KEYBOARD)
        return
    s = c.args[0].upper()
    uid = get_uid(u)
    ud = load_user(uid)
    if s in ud.get("portfolio", {}):
        del ud["portfolio"][s]
        save_user(uid, ud)
        await u.message.reply_text(f"✅ {s} rimosso", reply_markup=KEYBOARD)
    else:
        await u.message.reply_text(f"❌ {s} non trovato", reply_markup=KEYBOARD)

async def cmd_alert(u, c):
    if len(c.args) < 2:
        await u.message.reply_text("Uso: /alert XRP 3 [down]", reply_markup=KEYBOARD)
        return
    s = c.args[0].upper()
    if s not in ASSETS:
        await u.message.reply_text("❌ Asset non valido", reply_markup=KEYBOARD)
        return
    try:
        t = float(c.args[1].replace(",", ""))
        above = not (len(c.args) >= 3 and c.args[2].lower() == "down")
        uid = get_uid(u)
        ud = load_user(uid)
        ud["alerts"].append({"sym": s, "price": t, "above": above})
        save_user(uid, ud)
        d = "sale a" if above else "scende a"
        await u.message.reply_text(f"✅ Alert: *{s}* {d} `${t:,.2f}`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except:
        await u.message.reply_text("❌ Errore", reply_markup=KEYBOARD)

async def cmd_alerts(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    al = ud.get("alerts", [])
    if not al:
        await u.message.reply_text(t(uid, "no_alerts"), reply_markup=KEYBOARD)
        return
    lines = ["🔔 *Alert Attivi*\n"]
    for i, a in enumerate(al, 1):
        d = "↗️" if a["above"] else "↘️"
        lines.append(f"{i}. *{a['sym']}* {d} `${a['price']:,.4f}`")
    lines.append("\n/delalert 1 per eliminare")
    await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_delalert(u, c):
    if not c.args:
        await u.message.reply_text("Uso: /delalert 1", reply_markup=KEYBOARD)
        return
    try:
        i = int(c.args[0]) - 1
        uid = get_uid(u)
        ud = load_user(uid)
        al = ud.get("alerts", [])
        if 0 <= i < len(al):
            r = al.pop(i)
            ud["alerts"] = al
            save_user(uid, ud)
            await u.message.reply_text(f"✅ Eliminato: {r['sym']}", reply_markup=KEYBOARD)
        else:
            await u.message.reply_text("❌ Numero non valido", reply_markup=KEYBOARD)
    except:
        await u.message.reply_text("❌ Errore", reply_markup=KEYBOARD)

async def cmd_setup(u, c):
    alerts = []
    targets = {
        "XRP": [3, 5, 8, 12], "SOL": [200, 350, 500, 800],
        "ETH": [4000, 6000, 9000, 14000], "BNB": [900, 1200, 1500, 2000],
        "DOGE": [0.30, 0.60, 1.00], "HBAR": [0.20, 0.40, 0.70], "SEI": [0.80, 1.50, 3.00],
    }
    for sym, prices in targets.items():
        for p in prices:
            alerts.append({"sym": sym, "price": p, "above": True})
    uid = get_uid(u)
    ud = load_user(uid)
    ud["alerts"] = alerts
    save_user(uid, ud)
    await u.message.reply_text(f"✅ *{len(alerts)} alert impostati!*\n\nXRP: $3→$5→$8→$12\nSOL: $200→$350→$500→$800\nETH: $4k→$6k→$9k→$14k\nBNB: $900→$1.2k→$1.5k→$2k", parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_exit_plan(u, c):
    msg = """📤 *PIANO DI USCITA GRADUALE*

🟡 *BLOCCO 1 — Inizio Euforia*
Trigger: Fear&Greed >75 per 2 giorni
Azione: Vendi 10-15% di tutto
Timing: 3-7 giorni graduali
Priority: Meme coin prima (DOGE, BONK)

🟠 *BLOCCO 2 — Mercato Accelerato*
Trigger: BTC Dom <50% + F&G >80
Azione: Vendi 20-30% aggiuntivo
Timing: 5-14 giorni graduali
Priority: AI speculative, meme, small cap

🔴 *BLOCCO 3 — Blow-off Top*
Trigger: XRP pump + meme isterici + retail impazzito
Azione: Vendi 30-40% aggiuntivo
Timing: 48h-7 giorni VELOCI

🚨 *STOP LOSS EMERGENZA*
Trigger: Mercato crolla -30% in 7 giorni
Azione: Esci dal 50% IMMEDIATAMENTE

💡 *REGOLE D'ORO*
- MAI vendere tutto in un giorno
- MAI rientrare per FOMO
- Preleva 30% profitti in fiat
- Bear market: accumula BTC gradualmente"""
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

# ============================================================
# SENTIMENT & MARKET CONTEXT (descrittivo, non operativo)
# ============================================================
# Refactor del vecchio Fear&Greed alert: invece di consigli di vendita operativi,
# legge il sentiment NEL contesto (Rotation Engine + dominance + ETH/BTC) e produce
# una lettura descrittiva. Frasi pre-approvate, zero linguaggio operativo.

# Frasi di interpretazione APPROVATE (esatte). Testo fisso, non passa dall'AI.
_SENT_FRASI = {
    "ACCUMULO": "Sentiment estremamente depresso, ma il contesto mostra primi segnali di rotazione verso asset di qualita. Questa combinazione (paura diffusa insieme a forza relativa nascente) descrive una possibile fase di accumulo selettivo, storicamente osservata in zone di minimo emotivo. Fase da osservare, conferma da verificare. Nessuna azione automatica.",
    "PANIC_RISK": "Sentiment estremamente negativo in un contesto ancora fragile: il capitale sembra muoversi verso la prudenza e la leadership resta difensiva. Il mercato appare in fase difensiva, senza segnali di rotazione confermati. Quadro descrittivo da monitorare con calma, conferma da verificare. Nessuna azione automatica.",
    "EUFORIA": "Sentiment in area di euforia accompagnato da segnali avanzati di ciclo nel contesto di mercato. Questa combinazione e storicamente associata a fasi mature, dove conviene mantenere lucidita. Fase da osservare con particolare attenzione, conferma da verificare. Nessuna azione automatica.",
    "NEUTRO": "Sentiment e contesto di mercato non mostrano combinazioni particolari al momento: nessuno scenario rilevante e attivo. Quadro descrittivo nella norma, fase da monitorare. Nessuna azione automatica.",
}

# Mappa nomi display per gli stati del Rotation Engine (leggibili)
_ROT_DISPLAY = {
    "BTC_LED": "BTC GUIDA",
    "ETH_ROTATION": "ROTAZIONE ETH",
    "LARGE_CAP_ROTATION": "ROTAZIONE LARGE CAP",
    "MID_CAP_ROTATION": "ROTAZIONE MID CAP",
    "MEME_EUPHORIA": "EUFORIA MEME",
    "DISTRIBUTION_WARNING": "AVVISO DISTRIBUZIONE",
    "RISK_OFF": "RISK-OFF",
}

# Mappa nomi display per gli scenari del Sentiment
_SCENARIO_DISPLAY = {
    "ACCUMULO": "ACCUMULO",
    "PANIC_RISK": "PANIC RISK",
    "EUFORIA": "EUFORIA",
    "NEUTRO": "NEUTRO",
}

# Soglia BTC Dominance "alta" per PANIC_RISK. Dichiarata, non validata.
_SENT_DOM_ALTA = 55.0

# ============================================================
# BIAS ENGINE (deterministico, non da AI)
# ============================================================
# Sintetizza in un'unica etichetta il quadro Scenario+Signal Strength+Rotation.
# Nessun linguaggio operativo. Solo lettura sintetica del quadro descrittivo.

_BIAS_SCENARI_VALIDI = ("ACCUMULO", "PANIC_RISK", "EUFORIA", "NEUTRO")

def _mid_cap_contesto_forte(fg_val, stable_flow):
    """Contesto forte per MID_CAP_ROTATION. SCELTA TEMPORANEA: il bot non ha ancora
    una metrica di breadth alt affidabile, quindi valutiamo solo sui 2 criteri disponibili
    (Fear & Greed > 20, Stablecoin Flow POSITIVE). Se ENTRAMBI veri -> forte.
    Da rivedere quando sara' disponibile una vera metrica di breadth."""
    fear_ok = (fg_val is not None and fg_val > 20)
    stable_ok = (stable_flow == "POSITIVE")
    return fear_ok and stable_ok

import re

def _data_availability_da_score_text(score_text, rot=None):
    """Deriva la disponibilita' dei fattori critici dal testo GIA' generato da
    compute_altseason_score (sezione 'DATI DISPONIBILI PER FATTORE'). Non ricalcola
    nulla: legge la stessa fonte di verita' che il prompt riceve, garantendo
    allineamento automatico (zero rischio di disallineamento tra le due).
    Aggiunge Rotation Engine separatamente (non incluso nello score)."""
    avail = {
        "TOTAL2/TOTAL3": "disponibile",
        "ETH/BTC": "disponibile",
        "Stablecoin": "disponibile",
        "Volumi": "mancante",  # non tracciato come fattore separato nel bot
        "Fear & Greed": "disponibile",
        "Rotation Engine": "disponibile",
    }
    testo = score_text or ""

    def _riga_mancante(nome_pattern):
        for riga in testo.split("\n"):
            if re.search(nome_pattern, riga, re.IGNORECASE):
                return "DATO NON DISPONIBILE" in riga
        return False  # se la riga non c'e' proprio, non possiamo dire nulla -> assume disponibile (conservativo)

    # TOTAL2/TOTAL3: mancante se ALMENO UNO dei due e' mancante nel testo
    total2_mancante = _riga_mancante(r"^- TOTAL2:")
    total3_mancante = _riga_mancante(r"^- TOTAL3:")
    avail["TOTAL2/TOTAL3"] = "mancante" if (total2_mancante or total3_mancante) else "disponibile"

    if _riga_mancante(r"^- ETH/BTC:"):
        avail["ETH/BTC"] = "mancante"

    if _riga_mancante(r"^- Stablecoin"):
        avail["Stablecoin"] = "mancante"

    if _riga_mancante(r"^- Sentiment"):
        avail["Fear & Greed"] = "mancante"

    rot_ok = False
    try:
        if rot and isinstance(rot, dict):
            rot_ok = bool(rot.get("state"))
    except Exception:
        pass
    avail["Rotation Engine"] = "disponibile" if rot_ok else "mancante"

    return avail

# ============================================================
# COHERENCE VALIDATOR (solo logging, MAI modifica il report)
# ============================================================
# Misura contraddizioni interne tra sezioni dello stesso report.
# Priorita': HIGH (Trigger/Interpretazione vs Data Availability),
# MEDIUM (Strategia Portafoglio vs Scenario), LOW (Bias vs report).

# Nomi/varianti testuali per ogni fattore critico, usati per il matching nel testo del report.
_COH_FATTORI_PATTERN = {
    "TOTAL2/TOTAL3": [r"TOTAL2", r"TOTAL3", r"TOTAL2/TOTAL3"],
    "ETH/BTC": [r"ETH/BTC", r"ETH\s*BTC"],
    "Stablecoin": [r"[Ss]tablecoin"],
    "Volumi": [r"[Vv]olum[ei]"],
    "Fear & Greed": [r"Fear\s*&?\s*Greed", r"Sentiment\s*\(F&G\)", r"F&G"],
    "Rotation Engine": [r"Rotation Engine", r"ROTATION ENGINE"],
}

# Parole che indicano "il fattore e' presente/attivo" in una riga di testo.
_COH_PAROLE_ATTIVO = [r"\bAttivo\b", r"\bParziale\b", r"in espansione", r"in crescita",
                      r"in calo\b", r"in recupero", r"in rialzo", r"confermat[oa]"]
# Parole che indicano correttamente "mancante" (queste NON devono generare warning)
_COH_PAROLE_MANCANTE = [r"DATO NON DISPONIBILE", r"non disponibile", r"mancante", r"n/d"]

def _estrai_sezione(report_text, nome_sezione, max_righe=15):
    """Estrae un blocco di testo a partire dalla riga che contiene nome_sezione,
    fino a max_righe righe dopo (o fino alla prossima intestazione numerata/##)."""
    if not report_text:
        return None
    righe = report_text.split("\n")
    start = None
    for i, r in enumerate(righe):
        if nome_sezione.lower() in r.lower():
            start = i
            break
    if start is None:
        return None
    blocco = righe[start:start + max_righe]
    return "\n".join(blocco)

def _fattore_marcato_attivo(sezione_text, fattore):
    """True se, nella sezione, il fattore compare con linguaggio 'attivo/disponibile'
    e NON e' accompagnato da linguaggio 'mancante' sulla stessa riga."""
    if not sezione_text:
        return False
    patterns = _COH_FATTORI_PATTERN.get(fattore, [])
    for riga in sezione_text.split("\n"):
        for pat in patterns:
            if re.search(pat, riga, re.IGNORECASE):
                # il fattore e' menzionato in questa riga
                ha_mancante = any(re.search(p, riga, re.IGNORECASE) for p in _COH_PAROLE_MANCANTE)
                if ha_mancante:
                    continue  # correttamente marcato mancante, nessun problema
                ha_attivo = any(re.search(p, riga, re.IGNORECASE) for p in _COH_PAROLE_ATTIVO)
                if ha_attivo:
                    return True
    return False


def _coherence_check_portfolio_strategy(report_text):
    """Logging-only: segnala incoerenze evidenti tra strategia portafoglio e quadro mercato."""
    try:
        txt = report_text or ""
        upper = txt.upper()
        bad_emergenti_accumula = ("EMERGENTI" in upper and "ACCUMULA" in upper)
        neutral_bias = ("BIAS ATTUALE: 🟡 NEUTRAL" in txt.upper()) or ("BIAS ATTUALE: NEUTRAL" in upper)
        btc_led = ("BTC_LED" in upper) or ("BTC GUIDA" in upper)
        if bad_emergenti_accumula and (neutral_bias or btc_led):
            log.warning(
                "COHERENCE WARNING field=Emergenti section_a=STRATEGIA_PORTAFOGLIO "
                "section_b=BIAS_ROTATION severity=MEDIUM timestamp=%s",
                datetime.now().isoformat()
            )
    except Exception as e:
        log.warning("COHERENCE WARNING validator portfolio failed: %s", e)

def log_coherence_warning(field, section_a, section_b, severity, ts):
    msg = f"COHERENCE WARNING field={field} section_a={section_a} section_b={section_b} severity={severity} timestamp={ts}"
    log.warning(msg)
    return msg  # ritorno il testo per i test, non altera nulla nel report

def _strategia_incoerente_con_scenario(sezione_strategia, scenario_attivo):
    """Euristica MEDIUM: scenario difensivo (PANIC_RISK) ma strategia con linguaggio
    di accumulo diffuso, o scenario di euforia/accumulo ma strategia con linguaggio
    difensivo diffuso su piu' categorie. Approssimativa per natura (solo logging)."""
    if not sezione_strategia or not scenario_attivo:
        return False
    testo = sezione_strategia.lower()
    n_accumula = len(re.findall(r"\bhold\b|\baccumula\b|\bmonitora\b.*hold", testo))
    n_riduci = len(re.findall(r"riduci|esci|distribuzione", testo))
    if scenario_attivo == "PANIC_RISK" and n_accumula >= 3 and n_riduci == 0:
        return True
    if scenario_attivo in ("EUFORIA",) and n_riduci == 0 and "monitora" not in testo and n_accumula >= 3:
        return True
    return False

def _bias_incoerente_con_report(report_text, bias_label):
    """Euristica LOW: bias bullish ma il report menziona ripetutamente parole
    negative diffuse (o viceversa). Molto approssimativa, solo logging."""
    if not report_text or not bias_label:
        return False
    testo = report_text.lower()
    n_neg = len(re.findall(r"\bfragile\b|\bdebole\b|\brischio\b|\bcrollo\b|\bnegativ[oi]\b", testo))
    n_pos = len(re.findall(r"\bforte\b|\bsolido\b|\bpositiv[oi]\b|\bespansione\b", testo))
    if bias_label in ("Bullish", "Leggermente Bullish") and n_neg >= 5 and n_pos == 0:
        return True
    if bias_label in ("Bearish",) and n_pos >= 5 and n_neg == 0:
        return True
    return False

def _coherence_check(report_text, availability, scenario_attivo=None, bias_label=None, now_iso_func=None):
    """Validator a posteriori. SOLO logging, NON modifica mai report_text.
    Ritorna la lista dei warning generati (per test/osservabilita'), il report_text
    restituito a chi chiama resta SEMPRE invariato (la funzione non lo tocca)."""
    warnings_emessi = []
    if now_iso_func:
        ts = now_iso_func()
    else:
        from datetime import datetime as _dt, timezone as _tz
        ts = _dt.now(_tz.utc).isoformat()

    if not report_text or not availability:
        return warnings_emessi

    sezione_trigger = _estrai_sezione(report_text, "TRIGGER CHECKLIST")
    sezione_interpretazione = (_estrai_sezione(report_text, "INTERPRETAZIONE")
                                or _estrai_sezione(report_text, "FASE MERCATO"))
    sezione_strategia = _estrai_sezione(report_text, "STRATEGIA PORTAFOGLIO")

    for fattore, stato in availability.items():
        if stato != "mancante":
            continue
        if sezione_trigger and _fattore_marcato_attivo(sezione_trigger, fattore):
            msg = log_coherence_warning(fattore, "TRIGGER_CHECKLIST", "DATA_AVAILABILITY", "HIGH", ts)
            warnings_emessi.append(msg)
        if sezione_interpretazione and _fattore_marcato_attivo(sezione_interpretazione, fattore):
            msg = log_coherence_warning(fattore, "INTERPRETAZIONE", "DATA_AVAILABILITY", "HIGH", ts)
            warnings_emessi.append(msg)

    if scenario_attivo and sezione_strategia:
        if _strategia_incoerente_con_scenario(sezione_strategia, scenario_attivo):
            msg = log_coherence_warning("Strategia/Scenario", "STRATEGIA_PORTAFOGLIO", "SCENARIO_ATTIVO", "MEDIUM", ts)
            warnings_emessi.append(msg)

    if bias_label and _bias_incoerente_con_report(report_text, bias_label):
        msg = log_coherence_warning("Bias/Report", "BIAS_FINALE", "REPORT_COMPLESSIVO", "LOW", ts)
        warnings_emessi.append(msg)

    return warnings_emessi

# ============================================================
# MARKET SCORE (deterministico, da dati grezzi - NON dal testo AI)
# ============================================================
# 8 fattori pesati. Coerente con le soglie gia' usate altrove nel bot
# (Sentiment Context, Rotation Engine) dove applicabile. Pesi/soglie
# dichiarati, NON validati statisticamente - indicatore interno, non segnale.

_MS_PESI = {
    "BTC Dominance": 20,
    "ETH/BTC": 20,
    "TOTAL2/TOTAL3": 15,
    "Alt Strength": 15,
    "Volumi Alt": 10,
    "Stablecoin Flow": 10,
    "Sentiment": 5,
    "Meme/Microcap": 5,
}
assert sum(_MS_PESI.values()) == 100

_MS_FASI = [
    (0, 30, "BEARISH"),
    (31, 45, "CAUTELA"),
    (46, 60, "ACCUMULO"),
    (61, 75, "ROTAZIONE ALT"),
    (76, 100, "ALTSEASON"),
]

_MS_MOLTIPLICATORE = {"ATTIVO": 1.0, "PARZIALE": 0.5, "NON ATTIVO": 0.0}

def _ms_stato_dominance(g):
    try:
        dom = g.get("dom") if g else None
    except Exception:
        dom = None
    if not dom:
        return "MANCANTE"
    if dom < 52:
        return "ATTIVO"
    if dom <= 55:
        return "PARZIALE"
    return "NON ATTIVO"

def _ms_stato_ethbtc(trend):
    try:
        eth = trend.get("ethbtc") if trend else None
        desc = eth.get("desc") if eth else None
    except Exception:
        desc = None
    if desc is None:
        return "MANCANTE"
    if desc in ("in recupero", "in rialzo"):
        return "ATTIVO"
    if desc == "stabile":
        return "PARZIALE"
    if desc == "in calo":
        return "NON ATTIVO"
    return "MANCANTE"

# ============================================================
# TOTAL2/TOTAL3 - delta 7 giorni (vera espansione, non disponibilita')
# ============================================================
# Sostituisce la vecchia logica "esiste il dato? -> ATTIVO" con una misura reale
# di direzione: variazione percentuale a 7 giorni di calendario, letta dagli
# snapshot gia' salvati (/data/snapshots.jsonl). Se lo storico e' insufficiente,
# il fattore risulta onestamente MANCANTE (mai un delta finto).

_MS_T23_SOGLIA_DEBOLE = -2.0  # soglia dichiarata, non validata: sotto questo = chiaramente negativo

def _ms_delta_total23_7d(leggi_snapshot_func):
    """Calcola la variazione % a 7 giorni di calendario di TOTAL2 e TOTAL3,
    leggendo gli snapshot storici gia' salvati. Ritorna (var_total2, var_total3)
    oppure (None, None) se lo storico e' insufficiente (mai un delta finto)."""
    if not leggi_snapshot_func:
        return None, None
    try:
        snaps = leggi_snapshot_func(200)
    except Exception:
        return None, None
    if not snaps:
        return None, None

    from datetime import datetime as _dt
    per_giorno = {}  # giorno (date) -> (total2, total3), tiene l'ultimo snapshot del giorno
    for snap in snaps:
        try:
            ts = snap.get("timestamp_utc", "")
            t2 = snap.get("total2")
            t3 = snap.get("total3")
            if not ts or t2 is None or t3 is None:
                continue
            giorno = _dt.fromisoformat(ts).date()
            per_giorno[giorno] = (t2, t3)
        except Exception:
            continue

    if len(per_giorno) < 5:  # storico insufficiente per un delta 7d affidabile
        return None, None

    giorni_ordinati = sorted(per_giorno.keys())
    oggi_giorno = giorni_ordinati[-1]
    t2_oggi, t3_oggi = per_giorno[oggi_giorno]

    # cerco il giorno con delta_giorni PIU' VICINO a 7 (tollerando un range 5-10
    # giorni per coprire eventuali buchi nello storico). Tra i candidati nel range,
    # scelgo quello con distanza minima da 7 (il piu' preciso disponibile).
    candidati = []
    for g in giorni_ordinati:
        delta_giorni = (oggi_giorno - g).days
        if 5 <= delta_giorni <= 10:
            candidati.append((abs(delta_giorni - 7), g))
    if not candidati:
        return None, None
    candidati.sort(key=lambda x: x[0])
    target = candidati[0][1]

    t2_old, t3_old = per_giorno[target]
    if not t2_old or not t3_old or not t2_oggi or not t3_oggi:
        return None, None

    var_t2 = (t2_oggi - t2_old) / t2_old * 100
    var_t3 = (t3_oggi - t3_old) / t3_old * 100
    return var_t2, var_t3

def _ms_stato_total23(g, leggi_snapshot_func=None):
    """Misura la vera espansione (delta 7d), non la disponibilita'.
    ATTIVO: TOTAL2 e TOTAL3 7d entrambi positivi.
    PARZIALE: segnali misti (almeno uno positivo, l'altro no).
    NON ATTIVO: nessuno dei due positivo.
    MANCANTE: storico insufficiente, o valori attuali assenti/0."""
    try:
        t2_now = g.get("total2") if g else None
        t3_now = g.get("total3") if g else None
    except Exception:
        t2_now = t3_now = None
    if not t2_now or not t3_now:
        return "MANCANTE"  # dato attuale assente/0, come prima

    var_t2, var_t3 = _ms_delta_total23_7d(leggi_snapshot_func)
    if var_t2 is None or var_t3 is None:
        return "MANCANTE"  # storico insufficiente: onesto, non inventiamo un delta

    t2_pos = var_t2 > 0
    t3_pos = var_t3 > 0

    if t2_pos and t3_pos:
        return "ATTIVO"
    if not t2_pos and not t3_pos:
        return "NON ATTIVO"
    return "PARZIALE"  # segnali misti: uno positivo, l'altro no

def _ms_stato_alt_strength(p):
    try:
        if not p:
            return "MANCANTE"
        alts = [s for s in p if s != "BTC"]
        valid = [s for s in alts if p[s].get("price", 0) > 0]
        if not valid:
            return "MANCANTE"
        pos = sum(1 for s in valid if p[s].get("ch", 0) > 0)
        pct = pos / len(valid) * 100
    except Exception:
        return "MANCANTE"
    if pct > 60:
        return "ATTIVO"
    if pct >= 40:
        return "PARZIALE"
    return "NON ATTIVO"

def _ms_stato_volumi_alt():
    # Il bot non traccia un aggregato di volumi alt come fattore isolato e affidabile.
    # Dichiarato MANCANTE sempre, in attesa di una fonte dati dedicata.
    return "MANCANTE"

def _ms_stato_stablecoin(stable):
    try:
        seg = stable.get("segnale") if stable else None
    except Exception:
        seg = None
    if not seg or seg == "DATO NON DISPONIBILE":
        return "MANCANTE"
    if seg == "INFLOW":
        return "ATTIVO"
    if seg == "NEUTRALE":
        return "PARZIALE"
    if seg == "OUTFLOW":
        return "NON ATTIVO"
    return "MANCANTE"

def _ms_stato_sentiment(fg):
    try:
        v = fg.get("v") if fg else None
    except Exception:
        v = None
    if v is None:
        return "MANCANTE"
    if v <= 25:
        return "ATTIVO"
    if v <= 50:
        return "PARZIALE"
    return "NON ATTIVO"

def _ms_stato_meme(p):
    # Stessa soglia (8%) gia' usata altrove nel bot per "meme mania" (DOGE/BONK/PEPE/SHIB).
    try:
        if not p:
            return "MANCANTE"
        memes = ["DOGE", "BONK", "PEPE", "SHIB"]
        valori = [p[s]["ch"] for s in memes if s in p and p[s].get("ch") is not None]
        if not valori:
            return "MANCANTE"
        media = sum(valori) / len(valori)
    except Exception:
        return "MANCANTE"
    if media > 8:
        return "ATTIVO"
    if media > 3:
        return "PARZIALE"
    return "NON ATTIVO"

# ============================================================
# TRIGGER CHECKLIST DETERMINISTICA + DIVERGENZA REGIME
# ============================================================
# Sostituisce la sezione 2 (scritta dall'AI) con gli STESSI stati gia'
# calcolati da compute_market_score. Nessun margine per l'AI di riscrivere
# questi stati. Principio: Python = numeri/stati/checklist/divergenze,
# AI = solo interpretazione narrativa.

_TC_ETICHETTE = [
    ("BTC Dominance", "BTC Dominance sotto area critica"),
    ("ETH/BTC", "ETH/BTC in breakout o recupero"),
    ("TOTAL2/TOTAL3", "TOTAL2/TOTAL3 in espansione"),
    ("Alt Strength", "Altcoin principali che sovraperformano BTC"),
    ("Volumi Alt", "Volumi reali sulle altcoin"),
    ("Stablecoin Flow", "Stablecoin inflow positivo"),
    ("Sentiment", "Sentiment in zona di interesse contrarian"),
    ("Meme/Microcap", "Forza comparto meme/microcap"),
]

def _fmt_trigger_checklist_deterministica(ms):
    """Costruisce il testo della Trigger Checklist usando ESATTAMENTE gli stati
    gia' calcolati da compute_market_score (ms['stati']). Deterministica al 100%,
    nessun testo generato dall'AI per questa sezione."""
    righe = ["2. TRIGGER CHECKLIST"]
    stati = (ms or {}).get("stati") or {}
    for chiave, etichetta in _TC_ETICHETTE:
        stato = stati.get(chiave, "MANCANTE")
        righe.append(f"- {etichetta}: {stato.lower()}")
    return chr(10).join(righe)

def _sostituisci_sezione_trigger_checklist(response, checklist_text):
    """Sostituisce l'INTERA sezione '2. TRIGGER CHECKLIST' (scritta dall'AI) con
    checklist_text (deterministica). Trova l'inizio della sezione 2 e la prossima
    intestazione numerata (3. ...) come fine. Tollerante a markdown/numerazione.
    Fallback: se la sezione 2 non si trova, la inserisce comunque (mai persa)."""
    if not response:
        return response
    pat_start = re.compile(r"^.*\b2\.\s*TRIGGER CHECKLIST\b.*$", re.IGNORECASE | re.MULTILINE)
    m_start = pat_start.search(response)
    if not m_start:
        # fallback: sezione non trovata, la appendo con un marcatore esplicito
        return response + "\n\n" + checklist_text
    pat_next = re.compile(r"^.*\b3\.\s*\S", re.IGNORECASE | re.MULTILINE)
    m_next = pat_next.search(response, m_start.end())
    fine = m_next.start() if m_next else len(response)
    return response[:m_start.start()] + checklist_text + "\n\n" + response[fine:]

# --- Divergenza regime (Market Score vs Rotation Engine, entrambi deterministici) ---

_TC_GRUPPI_COERENTI = {
    "BEARISH": ("RISK_OFF", "BTC_LED"),
    "CAUTELA": ("RISK_OFF", "BTC_LED"),
    "ACCUMULO": ("BTC_LED", "ETH_ROTATION", "LARGE_CAP_ROTATION"),
    "ROTAZIONE ALT": ("ETH_ROTATION", "LARGE_CAP_ROTATION", "MID_CAP_ROTATION"),
    "ALTSEASON": ("LARGE_CAP_ROTATION", "MID_CAP_ROTATION", "MEME_EUPHORIA"),
}

def _fmt_divergenza_regime(ms, rot_state):
    """Se la fase del Market Score e lo stato del Rotation Engine non sono
    in un gruppo coerente, genera una frase di divergenza da TEMPLATE FISSO
    (mai testo libero). Ritorna None se non c'e' divergenza o dati insufficienti."""
    fase = (ms or {}).get("fase")
    if not fase or not rot_state:
        return None
    gruppo = _TC_GRUPPI_COERENTI.get(fase, ())
    if rot_state in gruppo:
        return None  # coerente, nessuna divergenza
    rot_display = _ROT_DISPLAY.get(rot_state, rot_state) if "_ROT_DISPLAY" in globals() else rot_state
    return (
        f"Divergenza regime: il Market Score mostra pressione da {fase}, "
        f"ma il Rotation Engine resta in {rot_display} finche\u0027 BTC Dominance "
        f"e liquidita\u0027 non confermano."
    )

def _inserisci_divergenza_sezione1(response, divergenza_text):
    """Inserisce la frase di divergenza subito sotto l'intestazione '1. STATO MERCATO'
    (dopo l'eventuale Market Score gia' inserito li'). None-safe: se divergenza_text
    e' None, non fa nulla."""
    if not response or not divergenza_text:
        return response
    pattern = re.compile(r"^(.*\b1\.\s*STATO MERCATO\b.*)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(response)
    if not match:
        return divergenza_text + "\n\n" + response
    # inserisco dopo la riga di intestazione (prima riga del match), non dopo l'intero blocco Market Score
    fine_riga = response.find("\n", match.start())
    if fine_riga == -1:
        fine_riga = len(response)
    return response[:fine_riga] + "\n" + divergenza_text + response[fine_riga:]

def compute_market_score(g=None, fg=None, trend=None, stable=None, p=None, leggi_snapshot_func=None):
    """Market Score deterministico 0-100, calcolato SOLO da dati grezzi (non dal testo AI).
    Fattori MANCANTI esclusi dal denominatore (score ricalibrato sui disponibili).
    Pesi e soglie dichiarati, NON validati statisticamente."""
    stati = {
        "BTC Dominance": _ms_stato_dominance(g),
        "ETH/BTC": _ms_stato_ethbtc(trend),
        "TOTAL2/TOTAL3": _ms_stato_total23(g, leggi_snapshot_func),
        "Alt Strength": _ms_stato_alt_strength(p),
        "Volumi Alt": _ms_stato_volumi_alt(),
        "Stablecoin Flow": _ms_stato_stablecoin(stable),
        "Sentiment": _ms_stato_sentiment(fg),
        "Meme/Microcap": _ms_stato_meme(p),
    }

    punti_ottenuti = 0.0
    punti_disponibili = 0
    for fattore, stato in stati.items():
        peso = _MS_PESI[fattore]
        if stato == "MANCANTE":
            continue
        punti_disponibili += peso
        punti_ottenuti += peso * _MS_MOLTIPLICATORE.get(stato, 0.0)

    if punti_disponibili == 0:
        return {
            "score": None, "fase": None, "confidenza": None,
            "punti_disponibili": 0, "stati": stati,
        }

    score = round(punti_ottenuti / punti_disponibili * 100)
    score = max(0, min(100, score))  # clamp di sicurezza

    fase = None
    for lo, hi, nome in _MS_FASI:
        if lo <= score <= hi:
            fase = nome
            break

    if punti_disponibili >= 80:
        confidenza = "ALTA"
    elif punti_disponibili >= 50:
        confidenza = "MEDIA"
    else:
        confidenza = "BASSA"

    return {
        "score": score, "fase": fase, "confidenza": confidenza,
        "punti_disponibili": punti_disponibili, "stati": stati,
    }

def _fmt_market_score(ms):
    """Formatta la riga Market Score con disclaimer sempre visibile."""
    if not ms or ms.get("score") is None:
        return "Market Score: non calcolabile (dati insufficienti)\nPesi e soglie dichiarati, non validati statisticamente."
    return (
        f"Market Score: {ms['score']}/100 \u2192 {ms['fase']} (Confidenza: {ms['confidenza']})\n"
        f"Pesi e soglie dichiarati, non validati statisticamente."
    )

def _inserisci_market_score_sezione1(response, ms_text):
    """Inserisce il blocco Market Score subito sotto l'intestazione '1. STATO MERCATO'.
    Tollera varianti di markdown/numerazione. Fallback: lo antepone in cima al messaggio
    con un marcatore, mai perso silenziosamente."""
    if not response:
        return response
    pattern = re.compile(r"^(.*\b1\.\s*STATO MERCATO\b.*)$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(response)
    if match:
        riga_intestazione = match.group(1)
        inserimento = riga_intestazione + "\n" + ms_text
        return response[:match.start()] + inserimento + response[match.end():]
    # fallback: sezione non trovata, anteponi in cima (mai perso silenziosamente)
    return ms_text + "\n\n" + response

# ============================================================
# MARKET STATE (aggregatore puro, fonte di verita' unica per Claude)
# ============================================================
# NON ricalcola nulla: assembla output GIA' CALCOLATI da Market Score,
# Rotation Engine, Bias Engine, Divergenza Regime in un unico blocco
# compatto da iniettare nel ctx PRIMA della chiamata a Claude.

def compute_market_state(ms=None, rot=None, bias_emoji=None, bias_label=None, divergenza_text=None):
    """Aggrega gli output gia' calcolati a monte. Tollerante a input parziali/None.
    Ritorna un dizionario, mai un'eccezione."""
    stati = {}
    try:
        stati = (ms or {}).get("stati") or {}
    except Exception:
        stati = {}

    conteggio = {"ATTIVO": 0, "PARZIALE": 0, "NON ATTIVO": 0, "MANCANTE": 0}
    for stato in stati.values():
        if stato in conteggio:
            conteggio[stato] += 1

    market_score = None
    market_fase = None
    market_confidenza = None
    try:
        market_score = (ms or {}).get("score")
        market_fase = (ms or {}).get("fase")
        market_confidenza = (ms or {}).get("confidenza")
    except Exception:
        pass

    rotation_state = None
    rotation_confidence = None
    try:
        rotation_state = (rot or {}).get("state")
        rotation_confidence = (rot or {}).get("confidence")
    except Exception:
        pass

    return {
        "market_score": market_score,
        "market_fase": market_fase,
        "market_confidenza": market_confidenza,
        "rotation_state": rotation_state,
        "rotation_confidence": rotation_confidence,
        "bias_emoji": bias_emoji,
        "bias_label": bias_label,
        "divergenza_attiva": divergenza_text is not None,
        "divergenza_testo": divergenza_text,
        "trigger_summary": conteggio,
        "trigger_breakdown": dict(stati),
    }

def _fmt_market_state(market_state):
    """Formatta il blocco MARKET STATE da iniettare nel ctx per Claude.
    Deterministico, tollerante a dati mancanti (mostra 'n/d' invece di crashare)."""
    if not market_state:
        return "MARKET STATE: non disponibile (calcolo fallito, Claude procede con i dati grezzi)."

    ms_score = market_state.get("market_score")
    ms_fase = market_state.get("market_fase")
    score_txt = f"{ms_score} ({ms_fase})" if ms_score is not None and ms_fase else "n/d"

    rot_state = market_state.get("rotation_state")
    rot_conf = market_state.get("rotation_confidence")
    rot_disp = _ROT_DISPLAY.get(rot_state, rot_state) if rot_state else None
    rot_txt = f"{rot_disp} ({rot_conf})" if rot_disp and rot_conf else (rot_disp or "n/d")

    bias_emoji = market_state.get("bias_emoji")
    bias_label = market_state.get("bias_label")
    bias_txt = f"{bias_emoji} {bias_label}" if bias_label else "n/d"

    divergenza_txt = "TRUE" if market_state.get("divergenza_attiva") else "FALSE"

    summary = market_state.get("trigger_summary") or {}
    breakdown = market_state.get("trigger_breakdown") or {}

    righe = [
        "MARKET STATE",
        f"- Market Score: {score_txt}",
        f"- Rotation Engine: {rot_txt}",
        f"- Bias: {bias_txt}",
        f"- Divergenza regime: {divergenza_txt}",
        "- Trigger Summary:",
        f"  Attivi: {summary.get('ATTIVO', 0)}",
        f"  Parziali: {summary.get('PARZIALE', 0)}",
        f"  Non Attivi: {summary.get('NON ATTIVO', 0)}",
        f"  Mancanti: {summary.get('MANCANTE', 0)}",
        "Trigger Breakdown:",
    ]
    # Ordine fisso degli 8 fattori (stesso ordine della Trigger Checklist, per coerenza visiva)
    ordine_fattori = ["BTC Dominance", "ETH/BTC", "TOTAL2/TOTAL3", "Alt Strength",
                       "Volumi Alt", "Stablecoin Flow", "Sentiment", "Meme/Microcap"]
    for chiave in ordine_fattori:
        stato = breakdown.get(chiave, "MANCANTE")
        righe.append(f"- {chiave}: {stato}")
    return chr(10).join(righe)

def compute_bias(scenario, signal_strength, rot_state, fg_val, stable_flow):
    """Bias Engine deterministico. Ritorna (emoji, etichetta).
    Vincoli rispettati: MEME_EUPHORIA e DISTRIBUTION_WARNING non risultano MAI bullish.
    Scenari non riconosciuti (None o valori imprevisti) -> fallback sicuro Neutral."""
    if scenario not in _BIAS_SCENARI_VALIDI:
        return ("\U0001f7e1", "Neutral")  # fallback sicuro: scenario assente/sconosciuto

    if scenario == "EUFORIA":
        return ("\U0001f7e3", "Euforia Avanzata")

    if scenario == "ACCUMULO":
        if signal_strength is not None and signal_strength >= 4:
            return ("\U0001f7e2", "Bullish")
        if signal_strength == 3:
            return ("\U0001f7e2", "Leggermente Bullish")
        return ("\U0001f7e1", "Neutral")

    if scenario == "PANIC_RISK":
        if signal_strength is not None and signal_strength >= 4:
            return ("\U0001f534", "Bearish")
        return ("\U0001f7e0", "Cautela")

    # scenario == "NEUTRO" -> guarda il Rotation Engine
    if rot_state in ("RISK_OFF", "DISTRIBUTION_WARNING"):
        return ("\U0001f7e0", "Cautela")
    if rot_state in ("ETH_ROTATION", "LARGE_CAP_ROTATION"):
        return ("\U0001f7e2", "Leggermente Bullish")
    if rot_state == "MID_CAP_ROTATION":
        if _mid_cap_contesto_forte(fg_val, stable_flow):
            return ("\U0001f7e2", "Bullish")
        return ("\U0001f7e2", "Leggermente Bullish")

    # BTC_LED, MEME_EUPHORIA (in NEUTRO), None, qualsiasi altro -> fallback sicuro
    return ("\U0001f7e1", "Neutral")

def _sent_stable_flow(stable):
    """Mappa il segnale stablecoin -> POSITIVE/NEUTRAL/NEGATIVE. Tollerante."""
    try:
        if stable and isinstance(stable, dict):
            seg = stable.get("segnale")
            if seg == "INFLOW":
                return "POSITIVE"
            if seg == "OUTFLOW":
                return "NEGATIVE"
            if seg == "NEUTRALE":
                return "NEUTRAL"
    except Exception:
        pass
    return None

_SENT_DOM_ALTA = 55.0   # soglia dominance "alta" (sfavorevole accumulo) - dichiarata, non validata
_SENT_DOM_BASSA = 55.0  # soglia dominance "favorevole accumulo" (<55%) - stessa soglia, simmetrica

def _sent_signal_strength(scenario, fg_val, rot_state, ethbtc_desc, stable_flow, dom):
    """Signal Strength 0-5 RELATIVO allo scenario attivo (FIX: dominance ora guarda il VALORE reale,
    non duplica ethbtc_desc). Ritorna (score, etichetta) o (None, nota)."""
    if scenario == "NEUTRO" or not scenario:
        return None, "nessuno scenario attivo"
    fattori = 0

    if scenario == "ACCUMULO":
        # 1. Fear estremo
        if fg_val is not None and fg_val <= 20: fattori += 1
        # 2. Rotation favorevole
        if rot_state in ("ETH_ROTATION", "LARGE_CAP_ROTATION"): fattori += 1
        # 3. BTC Dominance favorevole (FIX: valore reale, soglia <55%, NON duplica ethbtc)
        if dom is not None and dom < _SENT_DOM_BASSA: fattori += 1
        # 4. ETH/BTC favorevole (in recupero/rialzo)
        if ethbtc_desc in ("in recupero", "in rialzo"): fattori += 1
        # 5. Stablecoin favorevole
        if stable_flow == "POSITIVE": fattori += 1
        return fattori, "supporto scenario ACCUMULO"

    if scenario == "PANIC_RISK":
        # 1. Fear estremo (molto basso)
        if fg_val is not None and fg_val <= 15: fattori += 1
        # 2. Rotation difensiva
        if rot_state in ("RISK_OFF", "BTC_LED"): fattori += 1
        # 3. BTC Dominance favorevole alla tesi (FIX: valore reale, soglia >55%)
        if dom is not None and dom > _SENT_DOM_ALTA: fattori += 1
        # 4. ETH/BTC debole
        if ethbtc_desc == "in calo": fattori += 1
        # 5. Stablecoin coerente (outflow)
        if stable_flow == "NEGATIVE": fattori += 1
        return fattori, "supporto scenario PANIC_RISK"

    if scenario == "EUFORIA":
        # 1. Fear estremo (molto alto)
        if fg_val is not None and fg_val >= 80: fattori += 1
        # 2. Rotation euforica
        if rot_state in ("MEME_EUPHORIA", "DISTRIBUTION_WARNING"): fattori += 1
        # 3. BTC Dominance favorevole a euforia (FIX: dominance bassa, capitale su alt/meme)
        if dom is not None and dom < _SENT_DOM_BASSA: fattori += 1
        # 4. ETH/BTC in movimento (recupero/rialzo)
        if ethbtc_desc in ("in recupero", "in rialzo"): fattori += 1
        # 5. Stablecoin favorevole
        if stable_flow == "POSITIVE": fattori += 1
        return fattori, "supporto scenario EUFORIA"

    return None, "scenario non riconosciuto"

_DRIVER_FRASI = {
    "ACCUMULO": {
        "fear": "Fear estremo",
        "rotation": "Rotation verso ETH/large cap confermata",
        "dominance": "BTC Dominance in calo",
        "ethbtc": "ETH in forza relativa",
        "stable": "Stablecoin in ingresso",
    },
    "PANIC_RISK": {
        "fear": "Fear estremo",
        "rotation": "Mercato in fase difensiva",
        "dominance": "BTC Dominance in salita",
        "ethbtc": "ETH/BTC in debolezza",
        "stable": "Stablecoin in uscita",
    },
    "EUFORIA": {
        "fear": "Sentiment in area di euforia",
        "rotation": "Rotazione su meme/distribuzione",
        "dominance": "BTC Dominance in calo (capitale su alt)",
        "ethbtc": "ETH/BTC in movimento",
        "stable": "Stablecoin in ingresso",
    },
}

def _sent_driver_principali(scenario, fg_val, rot_state, ethbtc_desc, stable_flow, dom):
    """Lista di driver DETERMINISTICI (frasi fisse) basati sugli stessi fattori del Signal Strength.
    Nessun testo libero/AI. Ritorna lista di stringhe (max 3, le piu' rilevanti)."""
    if scenario not in _DRIVER_FRASI:
        return []
    frasi = _DRIVER_FRASI[scenario]
    driver = []

    if scenario == "ACCUMULO":
        if fg_val is not None and fg_val <= 20: driver.append(frasi["fear"])
        if rot_state in ("ETH_ROTATION", "LARGE_CAP_ROTATION"): driver.append(frasi["rotation"])
        if dom is not None and dom < _SENT_DOM_BASSA: driver.append(frasi["dominance"])
        if ethbtc_desc in ("in recupero", "in rialzo"): driver.append(frasi["ethbtc"])
        if stable_flow == "POSITIVE": driver.append(frasi["stable"])
    elif scenario == "PANIC_RISK":
        if fg_val is not None and fg_val <= 15: driver.append(frasi["fear"])
        if rot_state in ("RISK_OFF", "BTC_LED"): driver.append(frasi["rotation"])
        if dom is not None and dom > _SENT_DOM_ALTA: driver.append(frasi["dominance"])
        if ethbtc_desc == "in calo": driver.append(frasi["ethbtc"])
        if stable_flow == "NEGATIVE": driver.append(frasi["stable"])
    elif scenario == "EUFORIA":
        if fg_val is not None and fg_val >= 80: driver.append(frasi["fear"])
        if rot_state in ("MEME_EUPHORIA", "DISTRIBUTION_WARNING"): driver.append(frasi["rotation"])
        if dom is not None and dom < _SENT_DOM_BASSA: driver.append(frasi["dominance"])
        if ethbtc_desc in ("in recupero", "in rialzo"): driver.append(frasi["ethbtc"])
        if stable_flow == "POSITIVE": driver.append(frasi["stable"])

    return driver[:3]  # max 3 driver principali, per leggibilita'

def _sent_setup_quality(signal_strength):
    """Mappa Signal Strength -> etichetta leggibile. Pura rappresentazione, non nuovo segnale."""
    if signal_strength is None:
        return None
    if signal_strength <= 2:
        return "DEBOLE"
    if signal_strength == 3:
        return "MODERATO"
    if signal_strength == 4:
        return "FORTE"
    return "MOLTO FORTE"  # 5

def _sent_data_quality(dati_mancanti, ethbtc_stale, fg_val, rot_state):
    """Valuta la qualita' dei dati. Ritorna (emoji, etichetta, note).
    LIVE = nessun dato mancante/stale. PARZIALE = almeno 1 da cache o secondario mancante.
    LIMITATA = manca un dato strutturale (Fear&Greed o Rotation Engine)."""
    note = []
    if ethbtc_stale:
        note.append("ETH/BTC da cache")
    # dati mancanti diversi da ETH/BTC (gia' coperto da stale) - es. dominance
    secondari_mancanti = [d for d in dati_mancanti if d not in ("ETH/BTC",)]
    for d in secondari_mancanti:
        if d not in ("Fear & Greed", "Rotation Engine"):
            note.append(f"{d} non disponibile")
    if "ETH/BTC" in dati_mancanti and not ethbtc_stale:
        note.append("ETH/BTC non disponibile")

    # LIMITATA: manca un dato strutturale
    if fg_val is None or rot_state is None:
        return "\U0001f534", "LIMITATA", note
    # PARZIALE: qualcosa stale o secondario mancante
    if note:
        return "\U0001f7e1", "PARZIALE", note
    # LIVE: tutto a posto
    return "\U0001f7e2", "LIVE", note

def compute_sentiment_context(fg=None, rot=None, g=None, trend=None, stable=None):
    """Sentiment & Market Context. FIX: Signal Strength dominance guarda il valore reale.
    Aggiunge Data Quality, Driver principali (deterministici), Setup Quality.
    PANIC_RISK opzione B + regola anti-ambiguita (gia' presenti, invariate)."""
    out = {
        "scenario": "NEUTRO", "interpretazione": _SENT_FRASI["NEUTRO"],
        "fg": None, "rot_state": None, "rot_conf": None, "dom": None, "ethbtc": None,
        "stable_flow": None, "signal_strength": None, "signal_label": None,
        "setup_quality": None, "driver_principali": [],
        "data_quality_emoji": None, "data_quality_label": None, "data_quality_note": [],
        "confidence_note": None, "dati_mancanti": [],
    }
    fg_val = None
    try:
        if fg and isinstance(fg, dict): fg_val = fg.get("v")
    except Exception: pass
    if fg_val is None: out["dati_mancanti"].append("Fear & Greed")

    rot_state = None; rot_conf = None
    try:
        if rot and isinstance(rot, dict):
            rot_state = rot.get("state"); rot_conf = rot.get("confidence")
    except Exception: pass
    if rot_state is None: out["dati_mancanti"].append("Rotation Engine")

    dom = None
    try:
        if g and isinstance(g, dict): dom = g.get("dom")
    except Exception: pass
    if dom is None: out["dati_mancanti"].append("BTC Dominance")

    ethbtc_desc = None; ethbtc_val = None; ethbtc_stale = False
    try:
        if trend and isinstance(trend, dict) and "ethbtc" in trend:
            ethbtc_desc = trend["ethbtc"].get("desc")
            ethbtc_val = trend["ethbtc"].get("oggi")
            ethbtc_stale = trend["ethbtc"].get("stale", False)
    except Exception: pass
    if ethbtc_val is None: out["dati_mancanti"].append("ETH/BTC")

    stable_flow = _sent_stable_flow(stable)

    out["fg"] = fg_val; out["rot_state"] = rot_state; out["rot_conf"] = rot_conf
    out["dom"] = dom; out["ethbtc"] = ethbtc_val; out["stable_flow"] = stable_flow

    ethbtc_su = (ethbtc_desc in ("in recupero", "in rialzo"))
    ethbtc_debole = (ethbtc_desc == "in calo")
    ethbtc_non_in_calo = (ethbtc_desc is not None and ethbtc_desc != "in calo")
    dom_alta = (dom is not None and dom > _SENT_DOM_ALTA)
    stable_outflow = (stable_flow == "NEGATIVE")

    # --- Valutazione scenari (INVARIATA) ---
    scenario = "NEUTRO"
    confidence_note = None
    if fg_val is not None and rot_state is not None:
        if fg_val >= 80 and rot_state in ("MEME_EUPHORIA", "DISTRIBUTION_WARNING"):
            scenario = "EUFORIA"
        elif fg_val <= 15 and rot_state in ("RISK_OFF", "BTC_LED"):
            conferme = []
            if ethbtc_debole: conferme.append("ETH/BTC in calo")
            if stable_outflow: conferme.append("stablecoin in uscita")
            if dom_alta: conferme.append("BTC Dominance alta")
            if ethbtc_su:
                scenario = "NEUTRO"
            elif len(conferme) >= 1:
                scenario = "PANIC_RISK"
                if ethbtc_val is None:
                    confidence_note = "confidenza ridotta: ETH/BTC non disponibile"
                elif len(conferme) == 1 and "BTC Dominance alta" in conferme:
                    confidence_note = "confidenza ridotta: conferma solo da dominance"
            else:
                scenario = "NEUTRO"
        elif fg_val <= 20 and rot_state in ("ETH_ROTATION", "LARGE_CAP_ROTATION") and ethbtc_non_in_calo:
            scenario = "ACCUMULO"
        else:
            scenario = "NEUTRO"

    out["scenario"] = scenario
    out["interpretazione"] = _SENT_FRASI[scenario]
    out["confidence_note"] = confidence_note
    if ethbtc_stale and not confidence_note:
        out["confidence_note"] = "ETH/BTC da cache (dato non aggiornato)"

    # Signal Strength (FIX dominance) + Setup Quality + Driver principali
    ss, lbl = _sent_signal_strength(scenario, fg_val, rot_state, ethbtc_desc, stable_flow, dom)
    out["signal_strength"] = ss; out["signal_label"] = lbl
    out["setup_quality"] = _sent_setup_quality(ss)
    out["driver_principali"] = _sent_driver_principali(scenario, fg_val, rot_state, ethbtc_desc, stable_flow, dom)

    # Data Quality
    dq_emoji, dq_label, dq_note = _sent_data_quality(out["dati_mancanti"], ethbtc_stale, fg_val, rot_state)
    out["data_quality_emoji"] = dq_emoji
    out["data_quality_label"] = dq_label
    out["data_quality_note"] = dq_note

    return out

def _fmt_sentiment_context(sc):
    """Formatta il quadro Sentiment & Market Context (con fix Signal Strength,
    Data Quality, Driver principali, Setup Quality). Sempre con nota."""
    from datetime import datetime as _dt, timezone as _tz
    ts = _dt.now(_tz.utc).strftime("%d/%m/%Y %H:%M UTC")
    fg_txt = str(sc.get("fg")) if sc.get("fg") is not None else "n/d"
    rot_state = sc.get("rot_state")
    rot_conf = sc.get("rot_conf")
    rot_disp = _ROT_DISPLAY.get(rot_state, rot_state) if rot_state else None
    if rot_disp and rot_conf:
        rot_txt = f"{rot_disp} ({rot_conf})"
    elif rot_disp:
        rot_txt = rot_disp
    else:
        rot_txt = "n/d"
    scenario = sc.get("scenario", "NEUTRO")
    scenario_disp = _SCENARIO_DISPLAY.get(scenario, scenario)
    ss = sc.get("signal_strength")
    ss_txt = f"{ss}/5" if ss is not None else "n/d"
    setup_q = sc.get("setup_quality")
    flow = sc.get("stable_flow")
    flow_txt = flow if flow else "n/d"
    dom_txt = f"{sc['dom']:.1f}%" if sc.get("dom") is not None else "n/d"
    ethbtc_txt = f"{sc['ethbtc']:.5f}" if sc.get("ethbtc") is not None else "n/d"

    righe = [
        "\U0001f4ca ALERT SENTIMENT & MARKET CONTEXT",
        "",
        f"\U0001f552 {ts}",
        f"Fear & Greed: {fg_txt}",
        f"Rotation Engine: {rot_txt}",
        f"Scenario Attivo: {scenario_disp}",
        f"Signal Strength: {ss_txt}",
    ]
    if setup_q:
        righe.append(f"Setup Quality: {setup_q}")
    righe += [
        f"BTC Dominance: {dom_txt}",
        f"ETH/BTC: {ethbtc_txt}",
        f"Stablecoin Flow: {flow_txt}",
    ]

    # Data Quality
    dq_emoji = sc.get("data_quality_emoji")
    dq_label = sc.get("data_quality_label")
    dq_note = sc.get("data_quality_note") or []
    if dq_emoji and dq_label:
        righe.append(f"Data Quality: {dq_emoji} {dq_label}")
        for n in dq_note:
            righe.append(f"\u2022 {n}")

    # Driver principali
    driver = sc.get("driver_principali") or []
    if driver:
        righe.append("Driver principali:")
        for d in driver:
            righe.append(f"\u2022 {d}")

    _bias_emoji, _bias_label = compute_bias(sc.get("scenario"), sc.get("signal_strength"), sc.get("rot_state"), sc.get("fg"), sc.get("stable_flow"))
    righe.append(f"Bias Attuale: {_bias_emoji} {_bias_label}")

    righe += [
        "",
        "Interpretazione:",
        sc.get("interpretazione", ""),
        "",
        "Nota: Segnale descrittivo, non ordine operativo.",
    ]
    if sc.get("dati_mancanti"):
        righe.insert(-2, "")
        righe.insert(-2, "Dati non disponibili: " + ", ".join(sc["dati_mancanti"]))
    return chr(10).join(righe)


async def cmd_stoploss(u, c):
    """Sentiment & Market Context (descrittivo, non operativo)."""
    try:
        g = get_global(); fg = get_fg()
        _stable = get_stablecoins()
        _trend = get_trend_7d()
        _rot = compute_rotation_state(g, _trend, _stable)
        sc = compute_sentiment_context(fg=fg, rot=_rot, g=g, trend=_trend, stable=_stable)
        msg = _fmt_sentiment_context(sc)
        await u.message.reply_text(msg, reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_ai(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    plan = ud.get("plan", "free")
    used = ud.get("ai_msgs", 0)
    limit = AI_LIMITS.get(plan, 5)
    remaining = max(0, limit - used)
    msg = (
        "🤖 *IL TUO CONSULENTE CRYPTO PERSONALE*\n\n"
        f"Messaggi rimasti oggi: `{remaining}/{limit}`\n\n"
        "Chiedimi qualsiasi cosa su:\n"
        "• 💼 Il tuo portfolio e P&L\n"
        "• 📊 Analisi delle tue coin\n"
        "• 🎯 Quando comprare e vendere\n"
        "• 💱 Forex e indici\n"
        "• 📅 Strategia altseason 2026\n\n"
        "💬 *Scrivi la tua domanda qui sotto!*"
    )
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_myplan(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    plan = ud.get("plan", "free")
    used = ud.get("ai_msgs", 0)
    limit = AI_LIMITS.get(plan, 5)
    remaining = max(0, limit - used)
    plan_emoji = {"free": "🆓", "basic": "💙", "pro": "👑"}.get(plan, "🆓")
    plan_name = {"free": "Free", "basic": "Basic", "pro": "Pro"}.get(plan, "Free")
    msg = (f"👤 *IL TUO PIANO*\n\n{plan_emoji} Piano: *{plan_name}*\n"
           f"🤖 Messaggi AI usati: `{used}/{limit}`\n"
           f"✅ Messaggi rimasti: `{remaining}`\n\n")
    if plan == "free":
        msg += "⬆️ *Vuoi più messaggi AI?*\n\n💙 *Basic* €12.99/mese → 50 msg/giorno\n👑 *Pro* €25.99/mese → Illimitati\n\nScrivi /upgrade per info"
    elif plan == "basic":
        msg += "👑 Upgrada a *Pro* per messaggi illimitati!\n/upgrade"
    else:
        msg += "🎉 Sei al piano massimo!"
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_upgrade(u, c):
    msg = ("💎 *PIANI DISPONIBILI*\n\n"
           "🆓 *Free* — Gratis\n• 5 messaggi AI al giorno\n\n"
           "💙 *Basic* — €12.99/mese\n• 50 messaggi AI al giorno\n• Portfolio completo\n\n"
           "👑 *Pro* — €25.99/mese\n• Messaggi AI illimitati\n• Alert illimitati\n• Tutto incluso\n\n"
           "Scrivi /pay per abbonartit")
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_pay(u, c):
    msg = ("💳 *ABBONATI AL BOT*\n\n"
           "💙 *Basic* — €12.99/mese\n• 50 messaggi AI al giorno\n\n"
           "👑 *Pro* — €25.99/mese\n• Messaggi AI illimitati\n• Tutto incluso\n\n"
           "━━━━━━━━━━━━━━━\n💰 *Come pagare:*\n\n"
           "💎 *USDT/USDC (TRC20 - Tron):*\n`TLAftNsWfrCHboFF3wHf8MbuDRsbSh516D`\n\n"
           "💎 *USDT/USDC/ETH (ERC20 - Ethereum):*\n`0x3EfB8Fdb87107555Bf46A46f7FB1e6eD0F51A2C4`\n\n"
           "━━━━━━━━━━━━━━━\n"
           "📩 Dopo il pagamento riceverai una notifica di attivazione automatica")
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_referral(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    ref_link = f"https://t.me/BullRunSignal_bot?start=ref_{uid}"
    ref_count = ud.get("referrals", 0)
    earnings = ud.get("ref_earnings", 0.0)
    msg = (f"🔗 *IL TUO LINK REFERRAL*\n\n`{ref_link}`\n\n"
           f"👥 Utenti invitati: `{ref_count}`\n"
           f"💰 Commissioni accumulate: `€{earnings:.2f}`\n\n"
           "💰 *Come funziona:*\n"
           "• Per ogni abbonato Basic: guadagni **€2.60/mese** (20%)\n"
           "• Per ogni abbonato Pro: guadagni **€5.20/mese** (20%)\n"
           "• Commissioni a vita!\n\n"
           "📤 Condividi su Telegram, WhatsApp, X!")
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_share(u, c):
    uid = get_uid(u)
    ref_link = f"https://t.me/BullRunSignal_bot?start=ref_{uid}"
    msg = (f"📢 *CONDIVIDI IL BOT*\n\n"
           "Copia e manda questo messaggio:\n\n"
           "━━━━━━━━━━━━━━━\n"
           "🤖 *Altseason Oracle Bot 2026*\n\n"
           "Il bot AI per la bull run crypto!\n\n"
           "✅ Prezzi in tempo reale\n"
           "✅ AI consulente personale\n"
           "✅ Alert automatici\n"
           "✅ Forex & Indici\n\n"
           f"👉 {ref_link}\n"
           "━━━━━━━━━━━━━━━")
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_quiet(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    ud["quiet_mode"] = not ud.get("quiet_mode", False)
    save_user(uid, ud)
    msg = "🌙 No Disturb ATTIVO — nessuna notifica 23:00-08:00" if ud["quiet_mode"] else "☀️ No Disturb DISATTIVO"
    await u.message.reply_text(msg, reply_markup=KEYBOARD)

async def cmd_price(u, c):
    if not c.args:
        await u.message.reply_text("Uso: /price BTC", reply_markup=KEYBOARD)
        return
    s = c.args[0].upper()
    if s not in ASSETS:
        await u.message.reply_text("❌ Asset non disponibile", reply_markup=KEYBOARD)
        return
    try:
        p = get_prices()[s]
        a = "🟢" if p["ch"] >= 0 else "🔴"
        msg = f"{a} *{s}*\n\n💵 `${p['price']:,.4f}`\n📈 24h: `{p['ch']:+.2f}%`\n💎 MCap: `${p['mcap']/1e9:.1f}B`"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

# ============================================================
# ADMIN COMANDI
# ============================================================
async def cmd_admin(u, c):
    uid = get_uid(u)
    if uid != ADMIN_ID:
        await u.message.reply_text("❌ Accesso negato", reply_markup=KEYBOARD)
        return
    try:
        users = list_users()
        total = len(users)
        free = basic = pro = 0
        for cid in users:
            plan = load_user(cid).get("plan", "free")
            if plan == "free": free += 1
            elif plan == "basic": basic += 1
            else: pro += 1
        ricavi = basic * 12.99 + pro * 25.99
        msg = (f"👑 *PANNELLO ADMIN*\n\n"
               f"👥 Utenti: `{total}` (Free: {free} | Basic: {basic} | Pro: {pro})\n"
               f"💰 Ricavi: `€{ricavi:.2f}/mese`\n\n"
               f"Comandi:\n`/setplan CHATID pro` — upgrade\n`/resetai CHATID` — reset AI\n`/users` — lista utenti")
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=ADMIN_KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_users(u, c):
    uid = get_uid(u)
    if uid != ADMIN_ID:
        await u.message.reply_text("❌ Accesso negato", reply_markup=KEYBOARD)
        return
    try:
        users = list_users()
        lines = [f"👥 *UTENTI TOTALI: {len(users)}*\n"]
        free = basic = pro = 0
        for cid in users[:30]:
            ud = load_user(cid)
            plan = ud.get("plan", "free")
            used = ud.get("ai_msgs", 0)
            pf = len(ud.get("portfolio", {}))
            emoji = {"free": "🆓", "basic": "💙", "pro": "👑"}.get(plan, "🆓")
            lines.append(f"{emoji} `{cid}` — {plan} | AI: {used} | Coins: {pf}")
            if plan == "free": free += 1
            elif plan == "basic": basic += 1
            else: pro += 1
        ricavi = basic * 12.99 + pro * 25.99
        lines.append(f"\n📊 Free: {free} | Basic: {basic} | Pro: {pro}")
        lines.append(f"💰 Ricavi: €{ricavi:.2f}/mese")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=ADMIN_KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_setplan(u, c):
    uid = get_uid(u)
    if uid != ADMIN_ID:
        await u.message.reply_text("❌ Accesso negato", reply_markup=KEYBOARD)
        return
    if len(c.args) < 2:
        await u.message.reply_text("Uso: /setplan CHATID free|basic|pro", reply_markup=KEYBOARD)
        return
    target, plan = c.args[0], c.args[1].lower()
    if plan not in ["free", "basic", "pro"]:
        await u.message.reply_text("❌ Piano non valido", reply_markup=KEYBOARD)
        return
    ud = load_user(target)
    ud["plan"] = plan
    ud["ai_msgs"] = 0
    save_user(target, ud)
    await u.message.reply_text(f"✅ Piano {plan} impostato per {target}", reply_markup=KEYBOARD)
    plan_name = {"free": "Free", "basic": "Basic €12.99/mese", "pro": "Pro €25.99/mese"}.get(plan, plan)
    try:
        await c.bot.send_message(chat_id=int(target), text=f"🎉 *Piano attivato!*\n\nIl tuo piano *{plan_name}* è ora attivo!\n\nGrazie per esserti abbonato! 🚀", parse_mode="Markdown")
    except: pass

async def cmd_resetai(u, c):
    uid = get_uid(u)
    if uid != ADMIN_ID:
        await u.message.reply_text("❌ Accesso negato", reply_markup=KEYBOARD)
        return
    if not c.args:
        await u.message.reply_text("Uso: /resetai CHAT_ID", reply_markup=KEYBOARD)
        return
    target = c.args[0]
    ud = load_user(target)
    ud["ai_msgs"] = 0
    save_user(target, ud)
    await u.message.reply_text(f"✅ Counter AI resettato per {target}", reply_markup=KEYBOARD)

async def cmd_initadmin(u, c):
    uid = get_uid(u)
    if uid != ADMIN_ID:
        await u.message.reply_text("❌ Accesso negato", reply_markup=KEYBOARD)
        return
    ud = load_user(uid)
    ud["portfolio"] = ADMIN_PORTFOLIO.copy()
    ud["plan"] = "pro"
    ud["ai_msgs"] = 0
    save_user(uid, ud)
    await u.message.reply_text(f"✅ *Portfolio Admin inizializzato!*\n{len(ADMIN_PORTFOLIO)} coin caricate\nPiano: Pro", parse_mode="Markdown", reply_markup=KEYBOARD)

# ============================================================
# WIZARD AGGIUNGI COIN
# ============================================================
WIZARD_COIN, WIZARD_QTY, WIZARD_PRICE = range(3)
POPULAR_COINS = [
    ["BTC", "ETH", "XRP", "SOL"],
    ["BNB", "ADA", "DOGE", "HBAR"],
    ["BONK", "SEI", "FET", "LUNA"],
    ["GRT", "ALGO", "XLM", "POL"],
]

def make_coin_keyboard():
    buttons = []
    for row in POPULAR_COINS:
        buttons.append([InlineKeyboardButton(c, callback_data=f"coin_{c}") for c in row])
    buttons.append([InlineKeyboardButton("✍️ Scrivi manualmente", callback_data="coin_MANUAL")])
    return InlineKeyboardMarkup(buttons)

async def cmd_addwizard(u, c):
    await u.message.reply_text("💼 *AGGIUNGI AL PORTFOLIO*\n\nSeleziona la coin:", parse_mode="Markdown", reply_markup=make_coin_keyboard())
    return WIZARD_COIN

async def wizard_coin_button(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data.replace("coin_", "")
    if data == "MANUAL":
        await query.edit_message_text("✍️ Scrivi il simbolo della coin (es. BTC, ETH, XRP):")
        return WIZARD_COIN
    context.user_data["wizard_coin"] = data
    await query.edit_message_text(f"✅ Coin: *{data}*\n\nQuante ne hai?", parse_mode="Markdown")
    return WIZARD_QTY

async def wizard_coin_text(update, context):
    coin = update.message.text.upper().strip()
    if coin not in ASSETS:
        await update.message.reply_text(f"❌ *{coin}* non trovata.\nCoin disponibili: {', '.join(list(ASSETS.keys())[:10])}...", parse_mode="Markdown")
        return WIZARD_COIN
    context.user_data["wizard_coin"] = coin
    await update.message.reply_text(f"✅ *{coin}* selezionata!\n\nQuante ne hai?", parse_mode="Markdown")
    return WIZARD_QTY

async def wizard_qty(update, context):
    try:
        qty = float(update.message.text.replace(",", "."))
        context.user_data["wizard_qty"] = qty
        coin = context.user_data["wizard_coin"]
        try:
            prices = get_prices()
            current = prices.get(coin, {}).get("price", 0)
            price_hint = f"\n\n💡 Prezzo attuale: `${current:,.4f}`" if current else ""
        except:
            price_hint = ""
        await update.message.reply_text(f"✅ Quantità: *{qty}*{price_hint}\n\nA quanto hai comprato in media ($)?\n(Scrivi 0 per usare il prezzo attuale)", parse_mode="Markdown")
        return WIZARD_PRICE
    except:
        await update.message.reply_text("❌ Scrivi un numero valido")
        return WIZARD_QTY

async def wizard_price(update, context):
    try:
        price_input = float(update.message.text.replace(",", ".").replace("$", ""))
        coin = context.user_data["wizard_coin"]
        qty = context.user_data["wizard_qty"]
        if price_input == 0:
            prices = get_prices()
            buy_price = prices.get(coin, {}).get("price", 0)
        else:
            buy_price = price_input
        if buy_price == 0:
            await update.message.reply_text("❌ Prezzo non valido", reply_markup=KEYBOARD)
            return ConversationHandler.END
        uid = str(update.message.chat_id)
        ud = load_user(uid)
        ud["portfolio"][coin] = {"qty": qty, "buy": buy_price}
        save_user(uid, ud)
        invested = qty * buy_price
        await update.message.reply_text(
            f"✅ *{coin} aggiunto!*\n\n• Quantità: `{qty}`\n• Prezzo: `${buy_price:,.4f}`\n• Investito: `${invested:,.2f}`\n\nScrivi /portfolio per vedere il P&L",
            parse_mode="Markdown", reply_markup=KEYBOARD
        )
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ Scrivi un numero valido")
        return WIZARD_PRICE

async def wizard_cancel(update, context):
    await update.message.reply_text("❌ Operazione annullata", reply_markup=KEYBOARD)
    return ConversationHandler.END

# ============================================================
# HANDLER MESSAGGI LIBERI (AI)
# ============================================================
async def handle_text(u, c):
    t = u.message.text
    uid = get_uid(u)
    handlers = {
        # IT
        "📊 Status": cmd_status, "🎯 Fase": cmd_phase,
        "😱 Fear & Greed": cmd_feargreed, "📉 RSI & MACD": cmd_rsimacd,
        "🏆 Top Performer": cmd_top, "💱 Forex & Indici": cmd_forex,
        "📰 News": cmd_news, "📅 Timeline": cmd_timeline,
        "💼 Portfolio": cmd_portfolio, "💹 Aggiungi Coin": cmd_addwizard,
        "🔔 I miei Alert": cmd_alerts, "⚙️ Setup Alert": cmd_setup,
        "📤 Piano Uscita": cmd_exit_plan, "📊 Sentiment & Contesto": cmd_stoploss,
        "🤖 Chiedi AI": cmd_ai, "📊 Il mio piano": cmd_myplan,
        "💳 Abbonati": cmd_pay, "🔗 Referral": cmd_referral,
        "📢 Condividi": cmd_share, "❓ Aiuto": cmd_help,
        "🔧 Admin": cmd_admin,
        # EN
        "🎯 Phase": cmd_phase, "🏆 Top Performers": cmd_top,
        "💱 Forex & Indices": cmd_forex, "💹 Add Coin": cmd_addwizard,
        "🔔 My Alerts": cmd_alerts, "⚙️ Setup Alerts": cmd_setup,
        "📤 Exit Plan": cmd_exit_plan, "📊 Sentiment & Context": cmd_stoploss,
        "🤖 Ask AI": cmd_ai, "📊 My Plan": cmd_myplan,
        "💳 Subscribe": cmd_pay, "📢 Share": cmd_share,
        "🔧 Admin": cmd_admin, "❓ Help": cmd_help,
        # PT
        "📰 Noticias": cmd_news, "💹 Adicionar Moeda": cmd_addwizard,
        "🔔 Meus Alertas": cmd_alerts, "⚙️ Config Alertas": cmd_setup,
        "📤 Plano de Saida": cmd_exit_plan, "📊 Sentimento & Contexto": cmd_stoploss,
        "🤖 Perguntar AI": cmd_ai, "📊 Meu Plano": cmd_myplan,
        "💳 Assinar": cmd_pay, "📢 Compartilhar": cmd_share,
        "🔧 Admin": cmd_admin, "❓ Ajuda": cmd_help,
        # Admin
        "👥 I miei Utenti": cmd_users, "📊 Stats Admin": cmd_admin,
        "💰 Ricavi": cmd_admin, "🔙 Torna al Bot": None,
        "📈 Stato Dati": cmd_stato_dati,
    }
    if t in handlers:
        fn = handlers[t]
        if fn is None:
            await u.message.reply_text("✅", reply_markup=kb(uid))
        else:
            await fn(u, c)
        return
    # AI risponde a messaggi liberi
    try:
        uid = get_uid(u)
        ud = load_user(uid)
        limit = AI_LIMITS.get(ud.get("plan", "free"), 5)
        used = ud.get("ai_msgs", 0)
        if used >= limit:
            await u.message.reply_text(f"⚠️ Hai usato tutti i {limit} messaggi AI del piano Free.\n\nUpgrada a Basic (50 msg) o Pro (illimitati)!\n\n/upgrade per info", reply_markup=KEYBOARD)
            return
        ud["ai_msgs"] = used + 1
        save_user(uid, ud)
        await u.message.reply_text(f"🤖 Sto analizzando... ({used+1}/{limit})", reply_markup=KEYBOARD)
        g = get_global(); p = get_prices(); fg = get_fg()
        ph, desc, level = phase(g["dom"])
        ctx = (f"Fase: {ph} ({level})\nBTC Dom: {g['dom']:.2f}%\n"
               f"Fear&Greed: {fg['v']} {fg['lbl']}\n"
               f"BTC: ${p['BTC']['price']:,.0f} ({p['BTC']['ch']:+.1f}%)\n"
               f"ETH: ${p['ETH']['price']:,.0f} ({p['ETH']['ch']:+.1f}%)\n"
               f"XRP: ${p['XRP']['price']:,.4f} ({p['XRP']['ch']:+.1f}%)\n"
               f"SOL: ${p['SOL']['price']:,.1f} ({p['SOL']['ch']:+.1f}%)\n"
               f"BONK: ${p['BONK']['price']:.8f} ({p['BONK']['ch']:+.1f}%)\n"
               f"DOGE: ${p['DOGE']['price']:.4f} ({p['DOGE']['ch']:+.1f}%)\n"
               f"Volumi 24h: BTC {_fmt_vol(p['BTC']['vol'])}, ETH {_fmt_vol(p['ETH']['vol'])}, SOL {_fmt_vol(p['SOL']['vol'])}, XRP {_fmt_vol(p['XRP']['vol'])}, DOGE {_fmt_vol(p['DOGE']['vol'])}, BNB {_fmt_vol(p['BNB']['vol'])}, BONK {_fmt_vol(p['BONK']['vol'])}"
               + chr(10) +
               f"Data: {datetime.now().strftime('%d/%m/%Y')} MAGGIO 2026")
        _stable = get_stablecoins()
        ctx = compute_altseason_score(g, p, fg, _stable) + chr(10) + chr(10) + ctx
        ctx = ctx + chr(10) + _fmt_stable(_stable)
        ctx = ctx + chr(10) + _fmt_deriv(get_derivatives())
        ctx = ctx + chr(10) + _fmt_trend(get_trend_7d())
        ctx = ctx + chr(10) + _fmt_rotation(compute_rotation_state(g, get_trend_7d(), _stable))
        try:
            _pctx = compute_portfolio_context(load_user(uid).get("portfolio", {}), rot=compute_rotation_state(g, get_trend_7d(), _stable), g=g, trend=get_trend_7d(), stable=_stable, fg=fg, prices=p, leggi_snapshot_func=_leggi_ultimi_snapshot)
            ctx = ctx + chr(10) + chr(10) + chr(128204) + " " + _fmt_portfolio_context(_pctx)
        except Exception as _e_pctx:
            log.warning(f"Portfolio context error (non bloccante): {_e_pctx}")
        # --- MARKET STATE (Fase 1): calcolo anticipato, fonte di verita per Claude ---
        # Riusa gli stessi moduli deterministici gia esistenti, calcolati PRIMA della
        # chiamata AI. Se fallisce, MARKET STATE non viene iniettato (fallback sicuro:
        # il bot continua con il comportamento attuale, nessun crash).
        try:
            _rot_pre = compute_rotation_state(g, get_trend_7d(), _stable)
            _sc_pre = compute_sentiment_context(fg=fg, rot=_rot_pre, g=g, trend=get_trend_7d(), stable=_stable)
            _bias_emoji_pre, _bias_label_pre = compute_bias(_sc_pre.get("scenario"), _sc_pre.get("signal_strength"), _sc_pre.get("rot_state"), _sc_pre.get("fg"), _sc_pre.get("stable_flow"))
            _ms_pre = compute_market_score(g=g, fg=fg, trend=get_trend_7d(), stable=_stable, p=p, leggi_snapshot_func=_leggi_ultimi_snapshot)
            _div_text_pre = _fmt_divergenza_regime(_ms_pre, _rot_pre.get("state") if _rot_pre else None)
            _market_state_pre = compute_market_state(ms=_ms_pre, rot=_rot_pre, bias_emoji=_bias_emoji_pre, bias_label=_bias_label_pre, divergenza_text=_div_text_pre)
            ctx = _fmt_market_state(_market_state_pre) + chr(10) + chr(10) + ctx
        except Exception as _e_mkstate:
            log.warning(f"MARKET STATE error (non bloccante, fallback a comportamento attuale): {_e_mkstate}")
        response = get_claude_response(t, ctx, uid)
        try:
            _rot_bias = compute_rotation_state(g, get_trend_7d(), _stable)
            _sc_bias = compute_sentiment_context(fg=fg, rot=_rot_bias, g=g, trend=get_trend_7d(), stable=_stable)
            _b_emoji, _b_label = compute_bias(_sc_bias.get("scenario"), _sc_bias.get("signal_strength"), _sc_bias.get("rot_state"), _sc_bias.get("fg"), _sc_bias.get("stable_flow"))
            response = response + chr(10) + chr(10) + f"Bias Attuale: {_b_emoji} {_b_label}"
        except Exception as _e_bias:
            log.warning(f"Bias Engine error (non bloccante): {_e_bias}")
        try:
            _score_text = compute_altseason_score(g, p, fg, _stable)
            _avail = _data_availability_da_score_text(_score_text, rot=_rot_bias)
            _coherence_check(response, _avail, scenario_attivo=_sc_bias.get("scenario"), bias_label=_b_label)
        except Exception as _e_coh:
            log.warning(f"Coherence check error (non bloccante): {_e_coh}")
        # Add follow-up suggestions based on language
        lang = load_user(uid).get("lang", "it")
        followups = {
            "en": "\n\n\U0001f4ac _More questions? Feel free to ask!_",
            "pt": "\n\n\U0001f4ac _Mais perguntas? Pode me perguntar!_",
        }
        followup = ""
        response = _sanitize_ai_analysis_v3(response)
        try:
            _ms = compute_market_score(g=g, fg=fg, trend=get_trend_7d(), stable=_stable, p=p, leggi_snapshot_func=_leggi_ultimi_snapshot)
            _ms_text = _fmt_market_score(_ms)
            response = _inserisci_market_score_sezione1(response, _ms_text)
        except Exception as _e_ms:
            log.warning(f"Market Score error (non bloccante): {_e_ms}")
            _ms = None
        try:
            _checklist_det = _fmt_trigger_checklist_deterministica(_ms)
            response = _sostituisci_sezione_trigger_checklist(response, _checklist_det)
        except Exception as _e_tc:
            log.warning(f"Trigger Checklist deterministica error (non bloccante): {_e_tc}")
        try:
            _rot_div = compute_rotation_state(g, get_trend_7d(), _stable)
            _div_text = _fmt_divergenza_regime(_ms, _rot_div.get("state") if _rot_div else None)
            response = _inserisci_divergenza_sezione1(response, _div_text)
        except Exception as _e_div:
            log.warning(f"Divergenza regime error (non bloccante): {_e_div}")
        _full_msg = "\U0001f916 *AI Analysis*\n\n" + response + followup
        try:
            await u.message.reply_text(_full_msg, parse_mode="Markdown", reply_markup=kb(uid))
        except Exception as _e_md:
            log.warning(f"Markdown analisi fallito, invio testo semplice: {_e_md}")
            try:
                await u.message.reply_text("\U0001f916 AI Analysis\n\n" + response + followup, reply_markup=kb(uid))
            except Exception as _e_plain:
                log.error(f"Invio analisi fallito anche in testo semplice: {_e_plain}")
        salva_snapshot(g, p, fg, _stable, get_derivatives(), get_trend_7d(), ctx, response, uid)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

# ============================================================
# MONITOR AUTOMATICO
# ============================================================
async def auto_monitor(app):
    await asyncio.sleep(10)
    last_phase = None
    last_reset_day = -1
    last_briefing_day = -1
    last_snapshot_day = -1
    while True:
        try:
            now = datetime.now()
            today = now.day
            hour = now.hour
            
            if today != last_reset_day:
                users = list_users()
                for cid in users:
                    ud = load_user(cid)
                    if ud.get("ai_msgs", 0) > 0:
                        ud["ai_msgs"] = 0
                        save_user(cid, ud)
                log.info(f"Reset giornaliero AI: {len(users)} utenti")
                last_reset_day = today

            # Morning briefing alle 8:00
            if hour == 8 and today != last_briefing_day:
                last_briefing_day = today
                try:
                    g = get_global()
                    p = get_prices()
                    fg = get_fg()
                    ph, desc, level = phase(g["dom"])
                    date_str = now.strftime("%d/%m/%Y")
                    dom = g['dom']
                    btc_p = p['BTC']['price']
                    btc_c = p['BTC']['ch']
                    eth_p = p['ETH']['price']
                    eth_c = p['ETH']['ch']
                    xrp_p = p['XRP']['price']
                    xrp_c = p['XRP']['ch']
                    sol_p = p['SOL']['price']
                    sol_c = p['SOL']['ch']
                    fg_v = fg['v']
                    fg_lbl = fg['lbl']
                    fg_em = fg['em']
                    lines = [
                        "\u2600 *BUONGIORNO - " + date_str + "*",
                        "",
                        ph,
                        "_" + desc + "_",
                        "",
                        "\U0001f4ca *MERCATO*",
                        "\u2022 BTC Dom: `" + "{:.2f}".format(dom) + "%`",
                        "\u2022 Fear&Greed: " + fg_em + " `" + str(fg_v) + " - " + fg_lbl + "`",
                        "",
                        "\U0001f4b0 *PREZZI*",
                        "\u2022 BTC: `$" + "{:,.0f}".format(btc_p) + "` (" + "{:+.1f}".format(btc_c) + "%)",
                        "\u2022 ETH: `$" + "{:,.0f}".format(eth_p) + "` (" + "{:+.1f}".format(eth_c) + "%)",
                        "\u2022 XRP: `$" + "{:,.4f}".format(xrp_p) + "` (" + "{:+.1f}".format(xrp_c) + "%)",
                        "\u2022 SOL: `$" + "{:,.1f}".format(sol_p) + "` (" + "{:+.1f}".format(sol_c) + "%)",
                        "",
                        "\U0001f4a1 Scrivi qualsiasi domanda al tuo AI consulente!",
                    ]
                    briefing = "\n".join(lines)
                    _briefing_admin = briefing
                    try:
                        _pf_admin = load_user(ADMIN_ID).get("portfolio", {})
                        if _pf_admin:
                            _pctx_b = compute_portfolio_context(_pf_admin, rot=compute_rotation_state(g, get_trend_7d(), get_stablecoins()), g=g, trend=get_trend_7d(), stable=get_stablecoins(), fg=fg, prices=p, leggi_snapshot_func=_leggi_ultimi_snapshot)
                            _briefing_admin = briefing + "\n\n" + chr(128204) + " " + _fmt_portfolio_context(_pctx_b)
                    except Exception as _e_nb:
                        log.warning("Nota portafoglio briefing error: " + str(_e_nb))
                    users = list_users()
                    for cid in users:
                        ud = load_user(cid)
                        if not ud.get("quiet_mode", False):
                            try:
                                _txt = _briefing_admin if str(cid) == ADMIN_ID else briefing
                                await app.bot.send_message(chat_id=int(cid), text=_txt, parse_mode="Markdown")
                            except: pass
                    log.info(f"Morning briefing inviato a {len(users)} utenti")
                except Exception as e:
                    log.error(f"Briefing error: {e}")
            # Snapshot automatico giornaliero alle 9:00 (per validazione statistica)
            if hour == 9 and today != last_snapshot_day:
                last_snapshot_day = today
                try:
                    sg = get_global(); sp = get_prices(); sfg = get_fg()
                    s_stable = get_stablecoins()
                    s_ctx = compute_altseason_score(sg, sp, sfg, s_stable)
                    s_ctx = s_ctx + chr(10) + _fmt_stable(s_stable)
                    s_ctx = s_ctx + chr(10) + _fmt_deriv(get_derivatives())
                    s_ctx = s_ctx + chr(10) + _fmt_trend(get_trend_7d())
                    s_ctx = s_ctx + chr(10) + _fmt_rotation(compute_rotation_state(sg, get_trend_7d(), s_stable))
                    s_resp = get_claude_response("Analisi automatica giornaliera", s_ctx, ADMIN_ID)
                    salva_snapshot_auto(sg, sp, sfg, s_stable, get_derivatives(), get_trend_7d(), s_ctx, s_resp)
                    log.info("Snapshot automatico giornaliero salvato")
                except Exception as e:
                    log.error(f"Snapshot automatico error: {e}")
            g = get_global(); p = get_prices(); fg = get_fg()
            ph, desc, level = phase(g["dom"])
            # Check alerts per ogni utente
            users = list_users()
            for cid in users:
                triggered = check_alerts_user(cid, p)
                for msg in triggered:
                    try:
                        await app.bot.send_message(chat_id=int(cid), text=msg, parse_mode="Markdown")
                    except: pass
            # Notifica cambio fase
            if level != last_phase:
                msg = f"🚨 *CAMBIO FASE!*\n\n{ph} (`{level}`)\n_{desc}_\n\nBTC Dom: `{g['dom']:.2f}%`\nFear&Greed: {fg['em']} `{fg['v']}`"
                try:
                    await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
                except: pass
                last_phase = level
            # Meme mania alert
            memes = [s for s in ["DOGE","BONK","PEPE","SHIB"] if p.get(s, {}).get("ch", 0) > 8]
            if len(memes) >= 2:
                try:
                    await app.bot.send_message(chat_id=CHAT_ID, text=f"🎰 *MEME MANIA!* {', '.join(memes)} tutti >8%\n⚠️ Segnale euforia!", parse_mode="Markdown")
                except: pass
            # State Change Alert (informativo, solo admin, max 1/24h)
            try:
                _rot_sca = compute_rotation_state(g, get_trend_7d(), get_stablecoins())
                _sca = compute_state_change_alert(_rot_sca, _leggi_ultimi_snapshot)
                if _sca.get("invia"):
                    try:
                        await app.bot.send_message(chat_id=CHAT_ID, text=_sca["testo"])
                        _sca_salva_stato_notificato(_sca["stato"], _sca["confidence"], _sca["giorni"])
                        log.info(f"State Change Alert inviato: {_sca['stato']} ({_sca['tipo']})")
                    except Exception as _e_send:
                        log.error(f"State Change Alert invio fallito: {_e_send}")
            except Exception as _e_sca:
                log.warning(f"State Change Alert error (non bloccante): {_e_sca}")
        except Exception as e:
            log.error(f"Monitor error: {e}")
        await asyncio.sleep(CHECK_INTERVAL)

# ============================================================
# WEB SERVER
# ============================================================
DASHBOARD_PWD = os.environ.get("DASHBOARD_PWD", "Stratega2026!!")

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        if path == "/" or path == "/dashboard":
            # Serve dashboard HTML
            dashboard_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
            if os.path.exists(dashboard_path):
                with open(dashboard_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"<h1>Altseason Bot 2026 - Online</h1>")
        
        elif path == "/admin/users":
            # API per lista utenti
            pwd = params.get("pwd", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                users_list = list_users()
                free = basic = pro = 0
                users_data = []
                for cid in users_list:
                    ud = load_user(cid)
                    plan = ud.get("plan", "free")
                    if plan == "free": free += 1
                    elif plan == "basic": basic += 1
                    else: pro += 1
                    users_data.append({
                        "id": cid,
                        "plan": plan,
                        "ai_msgs": ud.get("ai_msgs", 0),
                        "coins": len(ud.get("portfolio", {})),
                        "alerts": len(ud.get("alerts", [])),
                    })
                result = json.dumps({
                    "total": len(users_list),
                    "free": free, "basic": basic, "pro": pro,
                    "ricavi": round(basic * 12.99 + pro * 25.99, 2),
                    "users": users_data
                })
                self.wfile.write(result.encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        elif path == "/admin/setplan":
            uid = params.get("uid", [""])[0]
            plan = params.get("plan", ["free"])[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                if uid:
                    ud = load_user(uid)
                    ud["plan"] = plan
                    ud["ai_msgs"] = 0
                    save_user(uid, ud)
                self.wfile.write(json.dumps({"ok": True}).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        elif path == "/admin/resetai":
            uid = params.get("uid", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                if uid:
                    ud = load_user(uid)
                    ud["ai_msgs"] = 0
                    save_user(uid, ud)
                else:
                    for cid in list_users():
                        ud = load_user(cid)
                        ud["ai_msgs"] = 0
                        save_user(cid, ud)
                self.wfile.write(json.dumps({"ok": True}).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")
    
    def log_message(self, *a): pass

def start_web():
    port = int(os.environ.get('PORT', 8080))
    HTTPServer(('', port), WebHandler).serve_forever()

# ============================================================
# MAIN
# ============================================================
# alerts.py (sistema alert operativo legacy) DISATTIVATO: sostituito da
# State Change Alert + Sentiment & Market Context + Rotation Engine + Portfolio Context.
# from alerts import start_alert_system, alert_loop


async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    cmds = [
        ("start", cmd_start), ("help", cmd_help), ("status", cmd_status),
        ("phase", cmd_phase), ("feargreed", cmd_feargreed), ("rsimacd", cmd_rsimacd),
        ("top", cmd_top), ("forex", cmd_forex), ("news", cmd_news),
        ("timeline", cmd_timeline), ("price", cmd_price),
        ("portfolio", cmd_portfolio), ("reset", cmd_reset),
        ("addcoin", cmd_addcoin), ("removecoin", cmd_removecoin),
        ("alert", cmd_alert), ("alerts", cmd_alerts),
        ("delalert", cmd_delalert), ("setup", cmd_setup),
        ("exitplan", cmd_exit_plan), ("stoploss", cmd_stoploss),
        ("ai", cmd_ai), ("myplan", cmd_myplan),
        ("upgrade", cmd_upgrade), ("pay", cmd_pay),
        ("referral", cmd_referral), ("share", cmd_share),
        ("quiet", cmd_quiet), ("language", cmd_language), ("lingua", cmd_language), ("admin", cmd_admin),
        ("users", cmd_users), ("setplan", cmd_setplan),
        ("resetai", cmd_resetai), ("initadmin", cmd_initadmin),
        ("add", cmd_addwizard),
    ]
    for cmd, fn in cmds:
        app.add_handler(CommandHandler(cmd, fn))
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_addwizard)],
        states={
            WIZARD_COIN: [CallbackQueryHandler(wizard_coin_button, pattern="^coin_"), MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_coin_text)],
            WIZARD_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_qty)],
            WIZARD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_price)],
        },
        fallbacks=[CommandHandler("cancel", wizard_cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(lang_callback, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(wizard_coin_button, pattern="^coin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    threading.Thread(target=start_web, daemon=True).start()
    log.info("🚀 Altseason Bot V2 online!")
    try:
        await app.bot.send_message(chat_id=CHAT_ID, text="✅ *Altseason Bot V2 Online!* 🚀\n\n/initadmin per caricare il tuo portfolio\n/help per la guida completa", parse_mode="Markdown")
    except: pass
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
    PORT = int(os.environ.get("PORT", 8080))
    async with app:
        await app.start()
        if WEBHOOK_URL:
            await app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
            await app.updater.start_webhook(listen="0.0.0.0", port=PORT, url_path="/webhook", webhook_url=f"{WEBHOOK_URL}/webhook")
            log.info(f"Webhook: {WEBHOOK_URL}/webhook")
        else:
            await app.updater.start_polling()
            log.info("Polling attivo")
        asyncio.create_task(auto_monitor(app))
        # alert_loop (sistema alert operativo legacy) DISATTIVATO - vedi nota import sopra
        log.info("Sistema alert legacy disattivato (alerts.py non avviato)")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
