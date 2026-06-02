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
    "XRP": {"qty": 25142, "buy": 1.36},
    "SOL": {"qty": 201, "buy": 85.9},
    "ETH": {"qty": 10.52, "buy": 2117},
    "DOGE": {"qty": 31128, "buy": 0.10},
    "BNB": {"qty": 5.05, "buy": 590},
    "HBAR": {"qty": 14686, "buy": 0.07},
    "BONK": {"qty": 150804881, "buy": 0.000006},
    "SEI": {"qty": 13723, "buy": 0.40},
    "FET": {"qty": 3223, "buy": 0.21},
    "LUNA": {"qty": 9057, "buy": 0.50},
    "GRT": {"qty": 43036, "buy": 0.12},
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
    [KeyboardButton("📤 Piano Uscita"), KeyboardButton("🚨 Check Uscita")],
    [KeyboardButton("🤖 Chiedi AI"), KeyboardButton("📊 Il mio piano")],
    [KeyboardButton("💳 Abbonati"), KeyboardButton("🔗 Referral")],
    [KeyboardButton("📢 Condividi"), KeyboardButton("👥 Utenti")],
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
            [KeyboardButton("📤 Exit Plan"), KeyboardButton("🚨 Check Exit")],
            [KeyboardButton("🤖 Ask AI"), KeyboardButton("📊 My Plan")],
            [KeyboardButton("💳 Subscribe"), KeyboardButton("🔗 Referral")],
            [KeyboardButton("📢 Share"), KeyboardButton("👥 Users")],
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
            [KeyboardButton("📤 Plano de Saida"), KeyboardButton("🚨 Verificar Saida")],
            [KeyboardButton("🤖 Perguntar AI"), KeyboardButton("📊 Meu Plano")],
            [KeyboardButton("💳 Assinar"), KeyboardButton("🔗 Referral")],
            [KeyboardButton("📢 Compartilhar"), KeyboardButton("👥 Usuarios")],
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
            [KeyboardButton("📤 Piano Uscita"), KeyboardButton("🚨 Check Uscita")],
            [KeyboardButton("🤖 Chiedi AI"), KeyboardButton("📊 Il mio piano")],
            [KeyboardButton("💳 Abbonati"), KeyboardButton("🔗 Referral")],
            [KeyboardButton("📢 Condividi"), KeyboardButton("👥 Utenti")],
            [KeyboardButton("❓ Aiuto")],
        ], resize_keyboard=True)

def kb(uid):
    ud = load_user(uid)
    return get_keyboard(ud.get("lang", "it"))


ADMIN_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("👥 I miei Utenti"), KeyboardButton("📊 Stats Admin")],
    [KeyboardButton("💰 Ricavi"), KeyboardButton("🔙 Torna al Bot")],
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

def get_ohlc(symbol="BTCUSDT", limit=30):
    try:
        r = requests.get(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}", timeout=10)
        data = r.json()
        return [float(x[4]) for x in data], [float(x[5]) for x in data]
    except:
        return [], []

def calc_rsi(closes, period=14):
    if len(closes) < period + 1: return None
    s = pd.Series(closes)
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return round((100 - (100 / (1 + rs))).iloc[-1], 1)

def calc_macd(closes):
    if len(closes) < 26: return None, None, None
    s = pd.Series(closes)
    macd = s.ewm(span=12).mean() - s.ewm(span=26).mean()
    signal = macd.ewm(span=9).mean()
    hist = macd - signal
    return round(macd.iloc[-1], 2), round(signal.iloc[-1], 2), round(hist.iloc[-1], 2)

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
        comp.append(f"- BTC Dominance: {d}/40 (dominance {dom:.1f}%)")
    else:
        comp.append("- BTC Dominance: DATO NON DISPONIBILE")
    btc = p.get("BTC", {}).get("price", 0); eth = p.get("ETH", {}).get("price", 0)
    if btc and eth:
        ethbtc = eth / btc
        e = round(max(0, min(15, (ethbtc - 0.025) / (0.05 - 0.025) * 15)))
        score += e; disp += 1
        comp.append(f"- ETH/BTC: {e}/15 (ratio {ethbtc:.5f})")
    else:
        comp.append("- ETH/BTC: DATO NON DISPONIBILE")
    total2 = g.get("total2", 0)
    if total2:
        score += 8; disp += 1
        comp.append(f"- TOTAL2: 8/15 (${total2:,.0f}B, livello attuale)")
    else:
        comp.append("- TOTAL2: DATO NON DISPONIBILE")
    total3 = g.get("total3", 0)
    if total3:
        score += 5; disp += 1
        comp.append(f"- TOTAL3: 5/10 (${total3:,.0f}B, livello attuale)")
    else:
        comp.append("- TOTAL3: DATO NON DISPONIBILE")
    v = fg.get("v", 0)
    if v:
        s = round(v / 100 * 10)
        score += s; disp += 1
        comp.append(f"- Sentiment (F&G): {s}/10 (indice {v})")
    else:
        comp.append("- Sentiment (F&G): DATO NON DISPONIBILE")
    alts = [s for s in p if s != "BTC"]
    valid = [s for s in alts if p[s].get("price", 0) > 0]
    if valid:
        pos = sum(1 for s in valid if p[s].get("ch", 0) > 0)
        pct = pos / len(valid) * 100
        a = round(pct / 100 * 10)
        score += a; disp += 1
        comp.append(f"- Altcoin Strength: {a}/10 ({pct:.0f}% alt positive 24h)")
    else:
        comp.append("- Altcoin Strength: DATO NON DISPONIBILE")
    # 7 fattore: Stablecoin inflow (max 10 punti). INFLOW=10, NEUTRALE=5, OUTFLOW=0.
    if stable and stable.get('segnale') and stable.get('segnale') != 'DATO NON DISPONIBILE':
        seg = stable['segnale']
        st_pts = 10 if seg == 'INFLOW POSITIVO' else 5 if seg == 'NEUTRALE' else 0
        score += st_pts; disp += 1
        comp.append(f"- Stablecoin Inflow: {st_pts}/10 ({seg})")
    else:
        comp.append("- Stablecoin Inflow: DATO NON DISPONIBILE")
    conf = "ALTA" if disp >= 5 else "MEDIA" if disp >= 3 else "BASSA"
    return f"ALTSEASON SCORE: {score}/100 (calcolato su {disp}/7 fattori)\nConfidenza Analisi: {conf}\nALTSEASON SCORE COMPONENTI:\n" + "\n".join(comp)


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

ALTSEASON SCORE:
Calcola un punteggio sintetico basato solo sui dati disponibili e mostralo come ALTSEASON SCORE: X/100.
0-30 = mercato debole, nessuna rotazione
31-50 = accumulo, pre-rotazione
51-70 = rotazione iniziale
71-85 = altseason attiva
86-100 = fase euforica, rischio distribuzione
ALTSEASON SCORE COMPONENTI: mostra sempre il contributo di ogni fattore al punteggio, una voce per riga. Se un fattore non e' nei dati, scrivi DATO NON DISPONIBILE.
- BTC Dominance: contributo su 40
- ETH/BTC: contributo su 15
- TOTAL2: contributo su 15
- TOTAL3: contributo su 10
- Sentiment (Fear & Greed): contributo su 10
- Altcoin Strength: contributo su 10

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
Per ogni categoria presente nel portafoglio indica una azione tra: HOLD, ACCUMULA, MONITORA, RIDUCI PARZIALMENTE, ESCI, NESSUNA AZIONE.
Usa ESCLUSIVAMENTE gli asset realmente presenti nel portafoglio utente indicato sotto. Non elencare coin generiche o di esempio se non sono nel portafoglio. Se una categoria non ha asset nel portafoglio, scrivi: nessun asset in questa categoria.

ALERT LOGIC (classifica sempre il segnale):
MONITORA = condizione interessante ma non ancora operativa
AZIONE = condizione che richiede intervento: specifica coin, percentuale, motivo, finestra
ALERT CRITICO = condizione che richiede attenzione immediata

REGOLE DECISIONALI (vincolanti):
Le azioni numeriche precise (percentuali tipo 'riduci BONK 20-25%', oppure 'compra XRP', 'vendi DOGE') sono ammesse SOLO se Confidenza Analisi e' ALTA.
Se Confidenza Analisi e' MEDIA o BASSA, oppure se mancano dati critici (Open Interest, Funding Rate, Stablecoin Inflow, Volumi reali): NON dare percentuali ne' ordini secchi di acquisto/vendita. Usa invece 👀 MONITORA oppure ⚠️ VALUTARE RIDUZIONE, con una breve spiegazione del perche' i dati non bastano per un'azione precisa.

FINESTRA OPERATIVA:
Indica il prossimo controllo critico (12h, 24h, 48h o 72h) e il livello di urgenza (BASSA, MEDIA, ALTA o CRITICA).

STRUTTURA RISPOSTA OBBLIGATORIA (usa questi titoli e questo ordine, apri con la data):
1. FASE MERCATO: stato ciclo, ALTSEASON SCORE, scenario principale / alternativo / avverso con probabilita
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
                            news_items.append((item_title, item_url, "CryptoPanic"))
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
                        if item_title and item_url and item_url not in seen_urls:
                            seen_urls.add(item_url)
                            news_items.append((item_title, item_url, source_name))
                except Exception as e:
                    log.warning(f"RSS news error {source_name}: {e}")

        if not news_items:
            await u.message.reply_text(empty, reply_markup=kb(uid))
            return

        lines = [title, ""]
        for item_title, item_url, source in news_items[:6]:
            clean_title = item_title.replace("\n", " ").strip()[:120]
            lines.append(f"• {clean_title}")
            lines.append(f"  Fonte: {source}")
            lines.append(f"  {item_url}")
            lines.append("")

        await u.message.reply_text(
            "\n".join(lines).strip(),
            reply_markup=kb(uid),
            disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"News command error: {e}")
        await u.message.reply_text(empty, reply_markup=kb(uid))

async def cmd_timeline(u, c):
    msg = """📅 *TIMELINE ALTSEASON 2026*

🌱 *GIUGNO-LUGLIO — ACCUMULO*
BTC Dom: 55-52% — Fear&Greed <40
→ TIENI tutto, non vendere nulla
→ ETH e SOL iniziano a salire

⚡ *AGOSTO-SETTEMBRE — ROTAZIONE*
BTC Dom <52% — Altcoin +300%
→ Vendi 25% al T1
→ Target: XRP $3, SOL $200, ETH $4k

🚀 *OTTOBRE-NOVEMBRE — EUFORIA*
Fear&Greed >80 — XRP pump tardivo
→ ESCI dal 50-75% di tutto
→ DOGE e BONK escono PRIMI

📉 *DICEMBRE — TOP CICLO*
Crollo -60/-80%
→ Chi è uscito accumula BTC

🎯 *TARGET FINALI*
XRP: $3→$5→$8→$12
SOL: $200→$350→$500→$800
ETH: $4k→$6k→$9k→$14k
BNB: $900→$1.2k→$1.5k→$2k

🚨 *SEGNALI DI TOP*
XRP +15% tardivo → ESCI 50%
Fear&Greed >85 tre giorni → ESCI
BTC Dom <48% → ESCI tutto"""
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

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
            lines.append(f"{a} *{sym}*: `{pct:+.1f}%` (`${pnl:+,.0f}`)")
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
        ud["portfolio"] = ADMIN_PORTFOLIO.copy()
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

async def cmd_stoploss(u, c):
    try:
        p = get_prices(); g = get_global(); fg = get_fg()
        warnings = []
        if fg["v"] > 80:
            warnings.append(f"🔴 *BLOCCO 2 ATTIVO*\nFear&Greed `{fg['v']}` — Vendi 20-30% progressivamente")
        elif fg["v"] > 75:
            warnings.append(f"🟡 *BLOCCO 1 ATTIVO*\nFear&Greed `{fg['v']}` — Inizia a vendere 10-15%")
        if g["dom"] < 48:
            warnings.append(f"🔴 *BTC DOM CRITICA* `{g['dom']:.1f}%`\nZona storica top ciclo — accelera uscite!")
        memes = [(s, p[s]["ch"]) for s in ["DOGE","BONK","PEPE"] if p.get(s, {}).get("ch", 0) > 15]
        if memes:
            meme_str = ", ".join([f"{s} +{ch:.0f}%" for s,ch in memes])
            warnings.append(f"🎰 *MEME MANIA AVANZATA*\n{meme_str}\nSegnale top ciclo — ESCI dai meme!")
        if p.get("XRP", {}).get("ch", 0) > 15 and g["dom"] < 52:
            warnings.append(f"⚠️ *XRP PUMP TARDIVO* +{p['XRP']['ch']:.1f}%\nStoricamente indica TOP CICLO — Esci dal 50%!")
        if warnings:
            msg = "🚨 *ALERT PIANO DI USCITA*\n\n" + "\n\n".join(warnings)
        else:
            msg = f"✅ *Nessun segnale di uscita urgente*\n\nFear&Greed: `{fg['v']}` sotto soglia\nBTC Dom: `{g['dom']:.1f}%` nella norma\nNessuna meme mania in corso"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
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
        "📤 Piano Uscita": cmd_exit_plan, "🚨 Check Uscita": cmd_stoploss,
        "🤖 Chiedi AI": cmd_ai, "📊 Il mio piano": cmd_myplan,
        "💳 Abbonati": cmd_pay, "🔗 Referral": cmd_referral,
        "📢 Condividi": cmd_share, "❓ Aiuto": cmd_help,
        "👥 Utenti": cmd_users,
        # EN
        "🎯 Phase": cmd_phase, "🏆 Top Performers": cmd_top,
        "💱 Forex & Indices": cmd_forex, "💹 Add Coin": cmd_addwizard,
        "🔔 My Alerts": cmd_alerts, "⚙️ Setup Alerts": cmd_setup,
        "📤 Exit Plan": cmd_exit_plan, "🚨 Check Exit": cmd_stoploss,
        "🤖 Ask AI": cmd_ai, "📊 My Plan": cmd_myplan,
        "💳 Subscribe": cmd_pay, "📢 Share": cmd_share,
        "👥 Users": cmd_users, "❓ Help": cmd_help,
        # PT
        "📰 Noticias": cmd_news, "💹 Adicionar Moeda": cmd_addwizard,
        "🔔 Meus Alertas": cmd_alerts, "⚙️ Config Alertas": cmd_setup,
        "📤 Plano de Saida": cmd_exit_plan, "🚨 Verificar Saida": cmd_stoploss,
        "🤖 Perguntar AI": cmd_ai, "📊 Meu Plano": cmd_myplan,
        "💳 Assinar": cmd_pay, "📢 Compartilhar": cmd_share,
        "👥 Usuarios": cmd_users, "❓ Ajuda": cmd_help,
        # Admin
        "👥 I miei Utenti": cmd_users, "📊 Stats Admin": cmd_admin,
        "💰 Ricavi": cmd_admin, "🔙 Torna al Bot": None,
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
        response = get_claude_response(t, ctx, uid)
        # Add follow-up suggestions based on language
        lang = load_user(uid).get("lang", "it")
        followups = {
            "en": "\n\n\U0001f4ac _More questions? Feel free to ask!_",
            "pt": "\n\n\U0001f4ac _Mais perguntas? Pode me perguntar!_",
        }
        followup = ""
        await u.message.reply_text("\U0001f916 *AI Analysis*\n\n" + response + followup, parse_mode="Markdown", reply_markup=kb(uid))
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
                    users = list_users()
                    for cid in users:
                        ud = load_user(cid)
                        if not ud.get("quiet_mode", False):
                            try:
                                await app.bot.send_message(chat_id=int(cid), text=briefing, parse_mode="Markdown")
                            except: pass
                    log.info(f"Morning briefing inviato a {len(users)} utenti")
                except Exception as e:
                    log.error(f"Briefing error: {e}")
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
from alerts import start_alert_system, alert_loop


async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).post_init(start_alert_system).build()
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
        asyncio.create_task(alert_loop(app))
        log.info("Sistema alert avviato (alert_loop in background)")
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
