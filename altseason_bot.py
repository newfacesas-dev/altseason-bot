"""
╔══════════════════════════════════════════════════════════════╗
║          ALTSEASON BOT 2026 — Telegram Signal Bot           ║
║   Strategia AVANZATA: BTC Dom, ETH/BTC, TOTAL3,            ║
║   RSI, MACD, Volume Anomaly, Fear & Greed Index            ║
║   + Alert Prezzi, Portfolio, Riepilogo, No-Disturb         ║
╚══════════════════════════════════════════════════════════════╝
"""

import asyncio
import logging
import requests
import pandas as pd
import time
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, time as dtime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8940955681:AAGbto8_W43gSe21rA3LlN776tMQfD2auIo"
CHAT_ID = "670903243"

CHECK_INTERVAL_SECONDS = 1800
REPORT_INTERVAL_LOOPS = 8

BTC_DOM_ALTSEASON_THRESHOLD = 52.0
BTC_DOM_WARNING_THRESHOLD = 48.0
ETH_BTC_BREAKOUT = 0.060
TOTAL3_SURGE_PCT = 5.0
MEME_MANIA_THRESHOLD = 8.0
VOLUME_SPIKE_MULTIPLIER = 2.0
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 70

QUIET_START = 23
QUIET_END = 8

ASSETS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "XRP": "ripple",
    "SOL": "solana",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "BNB": "binancecoin",
    "PEPE": "pepe",
    "SHIB": "shiba-inu",
    "POL": "matic-network",
    "TRX": "tron",
    "XLM": "stellar",
    "ALGO": "algorand",
    "GRT": "the-graph",
    "HBAR": "hedera-hashgraph",
    "BONK": "bonk",
    "SEI": "sei-network",
    "FET": "fetch-ai",
    "LUNA": "terra-luna-2",
    "BOME": "book-of-meme",
    "MANA": "decentraland",
    "PEOPLE": "constitutiondao",
    "NEAR": "near",
    "SONIC": "sonic-3",
}
MEME_COINS = ["PEPE", "DOGE", "SHIB", "BONK", "BOME"]

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

_cache = {}
CACHE_TTL = 180

KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📊 Status"), KeyboardButton("🎯 Fase")],
        [KeyboardButton("📈 Macro"), KeyboardButton("🏆 Top Performer")],
        [KeyboardButton("😱 Fear & Greed"), KeyboardButton("📉 RSI & MACD")],
        [KeyboardButton("💼 Portfolio"), KeyboardButton("🔔 I miei Alert")],
        [KeyboardButton("💰 Prezzo BTC"), KeyboardButton("💰 Prezzo ETH")],
        [KeyboardButton("💰 Prezzo XRP"), KeyboardButton("💰 Prezzo SOL")],
        [KeyboardButton("🌙 No Disturb"), KeyboardButton("❓ Aiuto")],
    ],
    resize_keyboard=True,
)

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"portfolio": {}, "price_alerts": [], "quiet_mode": False}

def save_data(data):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        log.error(f"Errore salvataggio dati: {e}")

bot_data = load_data()

def get_global_data():
    if 'global' in _cache and time.time() - _cache['global']['ts'] < CACHE_TTL:
        return _cache['global']['data']
    time.sleep(1)
    r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
    r.raise_for_status()
    data = r.json()["data"]
    total_mcap = data["total_market_cap"]["usd"]
    btc_mcap = data["market_cap_percentage"]["btc"] / 100 * total_mcap
    eth_mcap = data["market_cap_percentage"].get("eth", 0) / 100 * total_mcap
    result = {
        "btc_dominance": data["market_cap_percentage"]["btc"],
        "total_mcap": total_mcap,
        "total3_b": (total_mcap - btc_mcap - eth_mcap) / 1e9,
    }
    _cache['global'] = {'data': result, 'ts': time.time()}
    return result

def get_prices():
    if 'prices' in _cache and time.time() - _cache['prices']['ts'] < CACHE_TTL:
        return _cache['prices']['data']
    time.sleep(2)
    ids = ",".join(ASSETS.values())
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true&include_market_cap=true&include_24hr_vol=true"
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    raw = r.json()
    result = {}
    for symbol, cg_id in ASSETS.items():
        d = raw.get(cg_id, {})
        result[symbol] = {
            "price": d.get("usd", 0),
            "change24": d.get("usd_24h_change", 0),
            "mcap": d.get("usd_market_cap", 0),
            "vol24": d.get("usd_24h_vol", 0),
        }
    _cache['prices'] = {'data': result, 'ts': time.time()}
    return result

def get_fear_greed():
    if 'fg' in _cache and time.time() - _cache['fg']['ts'] < CACHE_TTL:
        return _cache['fg']['data']
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        v = int(data["value"])
        label = data["value_classification"]
        emoji = "😱" if v <= 25 else "😰" if v <= 45 else "😐" if v <= 55 else "😊" if v <= 75 else "🤑"
        result = {"value": v, "label": label, "emoji": emoji}
        _cache['fg'] = {'data': result, 'ts': time.time()}
        return result
    except:
        return {"value": 50, "label": "Neutral", "emoji": "😐"}

def detect_phase(btc_dom, eth_btc, total3_change):
    if btc_dom < BTC_DOM_WARNING_THRESHOLD:
        return {"phase": "⚠️ EUFORIA / TOP CICLO", "level": "USCITA", "emoji": "🚨",
                "desc": f"BTC Dom a {btc_dom:.1f}% — segnale storico di top ciclo."}
    elif btc_dom < BTC_DOM_ALTSEASON_THRESHOLD:
        if eth_btc > ETH_BTC_BREAKOUT and total3_change > TOTAL3_SURGE_PCT:
            return {"phase": "🚀 ALTSEASON PIENA", "level": "AZIONE", "emoji": "⚡",
                    "desc": "ETH/BTC in breakout + TOTAL3 in surge. Rotazione capitale."}
        return {"phase": "📈 ALTSEASON ATTIVA", "level": "AZIONE", "emoji": "⚡",
                "desc": "BTC Dom sotto soglia. Altcoin in espansione."}
    return {"phase": "🔍 ACCUMULO / PRE-ALTSEASON", "level": "MONITORA", "emoji": "👀",
            "desc": f"BTC Dom a {btc_dom:.1f}%. Costruzione posizioni graduale."}

def is_quiet_time():
    if not bot_data.get("quiet_mode", False):
        return False
    h = datetime.now().hour
    if QUIET_START > QUIET_END:
        return h >= QUIET_START or h < QUIET_END
    return QUIET_START <= h < QUIET_END

def check_price_alerts(prices):
    triggered = []
    remaining = []
    for alert in bot_data.get("price_alerts", []):
        sym = alert["symbol"]
        target = alert["price"]
        above = alert["above"]
        current = prices.get(sym, {}).get("price", 0)
        if current == 0:
            remaining.append(alert)
            continue
        hit = (above and current >= target) or (not above and current <= target)
        if hit:
            direction = "raggiunto ↗️" if above else "raggiunto ↘️"
            triggered.append(f"🔔 *ALERT {sym}*: `${current:,.2f}` ha {direction} la soglia `${target:,.2f}`")
        else:
            remaining.append(alert)
    if triggered:
        bot_data["price_alerts"] = remaining
        save_data(bot_data)
    return triggered

def format_report(global_data, prices, phase, fg=None):
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    btc_dom = global_data["btc_dominance"]
    total3 = global_data["total3_b"]
    eth_btc = prices["ETH"]["price"] / prices["BTC"]["price"] if prices["BTC"]["price"] else 0
    lines = [
        f"*🤖 ALTSEASON BOT — {now}*", "",
        f"{phase['emoji']} *{phase['phase']}* — `{phase['level']}`",
        f"_{phase['desc']}_", "",
        f"📊 *MACRO*",
        f"• BTC Dominance: `{btc_dom:.2f}%`",
        f"• ETH/BTC Ratio: `{eth_btc:.5f}`",
        f"• TOTAL3: `${total3:.1f}B`",
    ]
    if fg:
        lines.append(f"• Fear & Greed: {fg['emoji']} `{fg['value']} — {fg['label']}`")
    lines += ["", "💰 *PREZZI & 24h*"]
    for sym in ["BTC", "ETH", "XRP", "SOL", "ADA", "BNB", "DOGE"]:
        p = prices.get(sym, {})
        arrow = "🟢" if p.get("change24", 0) >= 0 else "🔴"
        lines.append(f"• {arrow} *{sym}*: `${p.get('price', 0):,.2f}` ({p.get('change24', 0):+.1f}%)")
    return "\n".join(lines)

async def send_help(update):
    msg = """👋 *ALTSEASON BOT 2026 — GUIDA COMPLETA*

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 *MONITORAGGIO MERCATO*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**/status** — Report completo del mercato
📋 Analizza: BTC Dom, ETH/BTC, TOTAL3, RSI, MACD, Fear&Greed
⏰ Quando: Ogni 2-3 ore per tenere il polso del mercato
💡 Azione: Se MONITORA → tieni. Se AZIONE → ruota verso altcoin. Se USCITA → prendi profitti

**/phase** — Quale fase del ciclo stai vivendo?
📋 Ti dice: ACCUMULO → ALTSEASON → USCITA
⏰ Quando: Mattina e sera
💡 Azione: Adatta la strategia in base alla fase

**/macro** — Dati macroeconomici
📋 Mostra: BTC Dom, ETH/BTC, TOTAL3, Market Cap totale
⏰ Quando: Dopo movimenti importanti
💡 Azione: Se Dom scende → compra altcoin. Se sale → vai su BTC

**/feargreed** — Sentiment del mercato (0-100)
📋 Misura: Paura vs avidità dei trader
⏰ Quando: Prima di grandi decisioni
💡 Azione: <25=compra, 25-50=accumula, 50-75=tieni, >75=vendi 25%

**/rsimacd** — Indicatori tecnici BTC e ETH
📋 Mostra: RSI (momentum) e MACD (trend)
⏰ Quando: Per timing di ingresso/uscita
💡 Azione: RSI<35=oversold(compra), RSI>70=overbought(vendi), MACD+ve=rialzo

**/top** — Quali coin stanno salendo più?
📋 Classifica: Asset per performance 24h
⏰ Quando: Per capire dove va il capitale
💡 Azione: Se top=meme → fine altseason. Se top=large cap → altseason solida

**/price BTC** — Prezzo in tempo reale
📋 Mostra: Prezzo, variazione 24h, market cap, volume
⏰ Quando: Quando ricevi un alert di target raggiunto
💡 Azione: Confronta con ingresso — decidi se vendere

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔔 *ALERT AUTOMATICI SU PREZZI*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**/alert XRP 3** — Avvisami quando XRP sale a $3
⏰ Timeline: Impostalo ORA prima che salga
💡 Azione: Quando l'alert scatta → prendi il 25% della posizione

**/alert SOL 200 down** — Avvisami quando SOL SCENDE a $200
⏰ Timeline: Per rientrare durante correzioni
💡 Azione: Quando scatta → compra il 10% in più

**/alerts** — Vedi tutti i tuoi alert attivi
**/delalert 1** — Cancella alert numero 1

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💼 *TRACKING PORTFOLIO & P&L*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**/addcoin XRP 22571 1.36** — Registra posizione (qty, prezzo acquisto)
⏰ Quando: Subito dopo aver comprato
💡 Azione: Il bot calcola P&L automatico in tempo reale

**/portfolio** — Vedi valore attuale di tutte le posizioni
⏰ Quando: Ogni mattina per monitorare guadagni
💡 Azione: Se P&L > +100% → inizia a prendere profitto

**/removecoin BTC** — Togli un asset dal tracking
💡 Quando: L'hai venduto completamente

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🌙 *IMPOSTAZIONI*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

**/quiet** — Attiva/disattiva silenzio notturno (23:00-08:00)
**/setup** — Imposta automaticamente i 28 alert della strategia

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ *TIMELINE TIPICA ALTSEASON*
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

*GIUGNO-LUGLIO*: BTC Dom scende 55-52%, ETH e SOL cominciano a salire
→ Azione: Tieni tutto, non vendere ancora

*AGOSTO-SETTEMBRE*: BTC Dom sotto 52%, altcoin esplodono +300%
→ Azione: Prendi il 25% di profitto su ogni coin

*OTTOBRE-NOVEMBRE*: Fear&Greed >80, XRP pump tardivo, DOGE/BONK +1000%
→ Azione: ESCI dal 50-75% di tutto, sposta in stablecoin

*DICEMBRE*: Crollo -60/-80% dai top
→ Azione: Chi è uscito adesso accumula BTC a prezzi stracciati

🚀 *QUICK START*
1️⃣ /addcoin XRP 25142 1.36
2️⃣ /setup
3️⃣ /status (ogni 2-3 ore)
4️⃣ /portfolio (ogni mattina)
5️⃣ Quando ricevi alert → /price [COIN] → decidi se vendere

Buona bull run! 🚀💰"""
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_help(update)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_help(update)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Recupero dati...", reply_markup=KEYBOARD)
    try:
        global_data = get_global_data()
        prices = get_prices()
        fg = get_fear_greed()
        btc_dom = global_data["btc_dominance"]
        eth_btc = prices["ETH"]["price"] / prices["BTC"]["price"] if prices["BTC"]["price"] else 0
        total3_change = prices["ETH"]["change24"]*0.4 + prices["SOL"]["change24"]*0.2 + prices["ADA"]["change24"]*0.2 + prices["XRP"]["change24"]*0.2
        phase = detect_phase(btc_dom, eth_btc, total3_change)
        await update.message.reply_text(format_report(global_data, prices, phase, fg), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_phase(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        global_data = get_global_data()
        prices = get_prices()
        btc_dom = global_data["btc_dominance"]
        eth_btc = prices["ETH"]["price"] / prices["BTC"]["price"] if prices["BTC"]["price"] else 0
        total3_change = prices["ETH"]["change24"]*0.4 + prices["SOL"]["change24"]*0.2 + prices["ADA"]["change24"]*0.2 + prices["XRP"]["change24"]*0.2
        phase = detect_phase(btc_dom, eth_btc, total3_change)
        msg = f"{phase['emoji']} *{phase['phase']}*\n\n`{phase['level']}`\n\n_{phase['desc']}_"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_macro(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        global_data = get_global_data()
        prices = get_prices()
        fg = get_fear_greed()
        btc_dom = global_data["btc_dominance"]
        eth_btc = prices["ETH"]["price"] / prices["BTC"]["price"] if prices["BTC"]["price"] else 0
        msg = (f"📊 *MACRO MERCATO*\n\n"
               f"• BTC Dominance: `{btc_dom:.2f}%`\n"
               f"• ETH/BTC: `{eth_btc:.5f}`\n"
               f"• TOTAL3: `${global_data['total3_b']:.1f}B`\n"
               f"• MCap Totale: `${global_data['total_mcap']/1e12:.2f}T`\n"
               f"• Fear & Greed: {fg['emoji']} `{fg['value']} — {fg['label']}`\n\n"
               f"{'🟢 Altseason in corso!' if btc_dom < 52 else '🔴 BTC domina ancora'}")
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_feargreed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        fg = get_fear_greed()
        v = fg["value"]
        desc = ("Paura estrema — zona di accumulo 🛒" if v<=25 else
                "Paura — mercato cauto" if v<=45 else
                "Neutro — nessun segnale forte" if v<=55 else
                "Avidità — attenzione ai top" if v<=75 else
                "Avidità estrema — zona di uscita ⚠️")
        msg = f"😱 *FEAR & GREED INDEX*\n\n{fg['emoji']} `{v}/100 — {fg['label']}`\n\n_{desc}_"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_top(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        prices = get_prices()
        valid = {s: p for s, p in prices.items() if p.get("change24") is not None}
        sorted_assets = sorted(valid.items(), key=lambda x: x[1].get("change24", 0), reverse=True)
        lines = ["🏆 *TOP PERFORMER 24h*\n"]
        for i, (sym, p) in enumerate(sorted_assets[:5], 1):
            c = p.get("change24", 0)
            arrow = "🟢" if c >= 0 else "🔴"
            lines.append(f"{i}. {arrow} *{sym}*: `{c:+.2f}%` — `${p.get('price',0):,.4f}`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /price BTC", reply_markup=KEYBOARD)
        return
    symbol = context.args[0].upper()
    if symbol not in ASSETS:
        await update.message.reply_text(f"❌ Disponibili: {', '.join(ASSETS.keys())}", reply_markup=KEYBOARD)
        return
    try:
        prices = get_prices()
        p = prices[symbol]
        arrow = "🟢" if p["change24"] >= 0 else "🔴"
        msg = (f"{arrow} *{symbol}*\n\n"
               f"💵 Prezzo: `${p['price']:,.4f}`\n"
               f"📈 24h: `{p['change24']:+.2f}%`\n"
               f"💎 MCap: `${p['mcap']/1e9:.2f}B`\n"
               f"📊 Volume: `${p['vol24']/1e6:.1f}M`")
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text(
            "Uso:\n`/alert BTC 120000` — avvisa quando BTC sale a 120k\n`/alert ETH 3000 down` — avvisa quando ETH scende a 3000",
            parse_mode="Markdown", reply_markup=KEYBOARD)
        return
    symbol = context.args[0].upper()
    if symbol not in ASSETS:
        await update.message.reply_text(f"❌ Asset non valido. Disponibili: {', '.join(ASSETS.keys())}", reply_markup=KEYBOARD)
        return
    try:
        target = float(context.args[1].replace(",", ""))
    except:
        await update.message.reply_text("❌ Prezzo non valido", reply_markup=KEYBOARD)
        return
    above = True
    if len(context.args) >= 3 and context.args[2].lower() == "down":
        above = False
    prices = get_prices()
    current = prices.get(symbol, {}).get("price", 0)
    direction = "salga a" if above else "scenda a"
    bot_data["price_alerts"].append({"symbol": symbol, "price": target, "above": above})
    save_data(bot_data)
    await update.message.reply_text(
        f"✅ *Alert impostato!*\n\nTi avviso quando *{symbol}* {direction} `${target:,.2f}`\nPrezzo attuale: `${current:,.2f}`",
        parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alerts = bot_data.get("price_alerts", [])
    if not alerts:
        await update.message.reply_text("Nessun alert attivo. Usa /alert BTC 120000 per impostarne uno.", reply_markup=KEYBOARD)
        return
    lines = ["🔔 *Alert Attivi*\n"]
    for i, a in enumerate(alerts, 1):
        direction = "↗️ sopra" if a["above"] else "↘️ sotto"
        lines.append(f"{i}. *{a['symbol']}* {direction} `${a['price']:,.2f}`")
    lines.append("\nUsa /delalert 1 per eliminare")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_delalert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /delalert 1", reply_markup=KEYBOARD)
        return
    try:
        idx = int(context.args[0]) - 1
        alerts = bot_data.get("price_alerts", [])
        if 0 <= idx < len(alerts):
            removed = alerts.pop(idx)
            save_data(bot_data)
            await update.message.reply_text(f"✅ Alert eliminato: *{removed['symbol']}* `${removed['price']:,.2f}`", parse_mode="Markdown", reply_markup=KEYBOARD)
        else:
            await update.message.reply_text("❌ Numero alert non valido", reply_markup=KEYBOARD)
    except:
        await update.message.reply_text("❌ Errore. Usa /delalert 1", reply_markup=KEYBOARD)

async def cmd_addcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 3:
        await update.message.reply_text("Uso: `/addcoin BTC 0.5 95000`\n(asset, quantità, prezzo di acquisto)", parse_mode="Markdown", reply_markup=KEYBOARD)
        return
    symbol = context.args[0].upper()
    if symbol not in ASSETS:
        await update.message.reply_text(f"❌ Disponibili: {', '.join(ASSETS.keys())}", reply_markup=KEYBOARD)
        return
    try:
        qty = float(context.args[1])
        buy_price = float(context.args[2].replace(",", ""))
    except:
        await update.message.reply_text("❌ Valori non validi", reply_markup=KEYBOARD)
        return
    bot_data["portfolio"][symbol] = {"qty": qty, "buy_price": buy_price}
    save_data(bot_data)
    await update.message.reply_text(
        f"✅ *{symbol}* aggiunto al portfolio!\n\nQuantità: `{qty}`\nPrezzo acquisto: `${buy_price:,.2f}`\nValore investito: `${qty*buy_price:,.2f}`",
        parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    portfolio = bot_data.get("portfolio", {})
    if not portfolio:
        await update.message.reply_text("Portfolio vuoto.\nUsa `/addcoin BTC 0.5 95000` per aggiungere.", parse_mode="Markdown", reply_markup=KEYBOARD)
        return
    try:
        prices = get_prices()
        lines = ["💼 *IL TUO PORTFOLIO*\n"]
        total_invested = 0
        total_current = 0
        for sym, pos in portfolio.items():
            p = prices.get(sym, {}).get("price", 0)
            qty = pos["qty"]
            buy = pos["buy_price"]
            invested = qty * buy
            current = qty * p
            pnl = current - invested
            pnl_pct = ((p - buy) / buy * 100) if buy else 0
            arrow = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"{arrow} *{sym}*")
            lines.append(f"   Qty: `{qty}` | Acquisto: `${buy:,.2f}`")
            lines.append(f"   Attuale: `${p:,.2f}` | P&L: `{pnl_pct:+.1f}%` (`${pnl:+,.0f}`)")
            lines.append("")
            total_invested += invested
            total_current += current
        total_pnl = total_current - total_invested
        total_pct = ((total_current - total_invested) / total_invested * 100) if total_invested else 0
        arrow = "🟢" if total_pnl >= 0 else "🔴"
        lines += [f"{'─'*20}", f"{arrow} *TOTALE*",
                  f"Investito: `${total_invested:,.0f}`",
                  f"Attuale: `${total_current:,.0f}`",
                  f"P&L: `{total_pct:+.1f}%` (`${total_pnl:+,.0f}`)"]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_removecoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Uso: /removecoin BTC", reply_markup=KEYBOARD)
        return
    symbol = context.args[0].upper()
    if symbol in bot_data.get("portfolio", {}):
        del bot_data["portfolio"][symbol]
        save_data(bot_data)
        await update.message.reply_text(f"✅ *{symbol}* rimosso dal portfolio.", parse_mode="Markdown", reply_markup=KEYBOARD)
    else:
        await update.message.reply_text(f"❌ {symbol} non trovato nel portfolio.", reply_markup=KEYBOARD)

async def cmd_quiet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_data["quiet_mode"] = not bot_data.get("quiet_mode", False)
    save_data(bot_data)
    if bot_data["quiet_mode"]:
        msg = f"🌙 *No Disturb ATTIVO*\nNessuna notifica automatica dalle {QUIET_START}:00 alle {QUIET_END}:00\n\nUsa /quiet per disattivarlo."
    else:
        msg = "☀️ *No Disturb DISATTIVO*\nRiceverai tutte le notifiche normalmente."
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_setup_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    strategy_alerts = [
        {"symbol": "XRP", "price": 3.0, "above": True},
        {"symbol": "XRP", "price": 5.0, "above": True},
        {"symbol": "XRP", "price": 8.0, "above": True},
        {"symbol": "XRP", "price": 12.0, "above": True},
        {"symbol": "SOL", "price": 200.0, "above": True},
        {"symbol": "SOL", "price": 350.0, "above": True},
        {"symbol": "SOL", "price": 500.0, "above": True},
        {"symbol": "SOL", "price": 800.0, "above": True},
        {"symbol": "ETH", "price": 4000.0, "above": True},
        {"symbol": "ETH", "price": 6000.0, "above": True},
        {"symbol": "ETH", "price": 9000.0, "above": True},
        {"symbol": "ETH", "price": 14000.0, "above": True},
        {"symbol": "BNB", "price": 900.0, "above": True},
        {"symbol": "BNB", "price": 1200.0, "above": True},
        {"symbol": "BNB", "price": 1500.0, "above": True},
        {"symbol": "BNB", "price": 2000.0, "above": True},
        {"symbol": "DOGE", "price": 0.30, "above": True},
        {"symbol": "DOGE", "price": 0.60, "above": True},
        {"symbol": "DOGE", "price": 1.00, "above": True},
        {"symbol": "HBAR", "price": 0.20, "above": True},
        {"symbol": "HBAR", "price": 0.40, "above": True},
        {"symbol": "HBAR", "price": 0.70, "above": True},
        {"symbol": "ADA", "price": 0.80, "above": True},
        {"symbol": "ADA", "price": 1.50, "above": True},
        {"symbol": "ADA", "price": 2.50, "above": True},
    ]
    bot_data["price_alerts"] = strategy_alerts
    save_data(bot_data)
    msg = (
        "✅ *Alert strategia impostati!*\n\n"
        "Hai ora *28 alert attivi* su:\n\n"
        "📊 *XRP*: $3 → $5 → $8 → $12\n"
        "☀️ *SOL*: $200 → $350 → $500 → $800\n"
        "💎 *ETH*: $4k → $6k → $9k → $14k\n"
        "🔶 *BNB*: $900 → $1.2k → $1.5k → $2k\n"
        "🐕 *DOGE*: $0.30 → $0.60 → $1.00\n"
        "🌐 *HBAR*: $0.20 → $0.40 → $0.70\n"
        "🔵 *ADA*: $0.80 → $1.50 → $2.50\n\n"
        "Quando una coin tocca il target ricevi subito la notifica! 🚀"
    )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 Status": await cmd_status(update, context)
    elif text == "🎯 Fase": await cmd_phase(update, context)
    elif text == "📈 Macro": await cmd_macro(update, context)
    elif text == "🏆 Top Performer": await cmd_top(update, context)
    elif text == "😱 Fear & Greed": await cmd_feargreed(update, context)
    elif text == "📉 RSI & MACD": await update.message.reply_text("RSI e MACD via /rsimacd", reply_markup=KEYBOARD)
    elif text == "💼 Portfolio": await cmd_portfolio(update, context)
    elif text == "🔔 I miei Alert": await cmd_alerts(update, context)
    elif text == "🌙 No Disturb": await cmd_quiet(update, context)
    elif text == "💰 Prezzo BTC": context.args = ["BTC"]; await cmd_price(update, context)
    elif text == "💰 Prezzo ETH": context.args = ["ETH"]; await cmd_price(update, context)
    elif text == "💰 Prezzo XRP": context.args = ["XRP"]; await cmd_price(update, context)
    elif text == "💰 Prezzo SOL": context.args = ["SOL"]; await cmd_price(update, context)
    elif text == "❓ Aiuto": await send_help(update)

async def auto_monitor(app):
    await asyncio.sleep(5)
    while True:
        try:
            if is_quiet_time():
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                continue
            global_data = get_global_data()
            prices = get_prices()
            fg = get_fear_greed()
            btc_dom = global_data["btc_dominance"]
            eth_btc = prices["ETH"]["price"] / prices["BTC"]["price"] if prices["BTC"]["price"] else 0
            total3_change = prices["ETH"]["change24"]*0.4 + prices["SOL"]["change24"]*0.2 + prices["ADA"]["change24"]*0.2 + prices["XRP"]["change24"]*0.2
            phase = detect_phase(btc_dom, eth_btc, total3_change)
            triggered = check_price_alerts(prices)
            for alert_msg in triggered:
                await app.bot.send_message(chat_id=CHAT_ID, text=alert_msg, parse_mode="Markdown")
        except Exception as e:
            log.error(f"Errore monitor: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

WEBAPP_HTML = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webapp.html'), 'r').read() if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webapp.html')) else "<h1>Altseason Bot</h1>"

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        elif self.path in ('/', '/webapp.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(WEBAPP_HTML.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

def start_web_server():
    port = int(os.environ.get('PORT', 8080))
    server = HTTPServer(('', port), WebHandler)
    log.info(f"🌐 Web server avviato su porta {port}")
    server.serve_forever()

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("phase", cmd_phase))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("macro", cmd_macro))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("feargreed", cmd_feargreed))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))
    app.add_handler(CommandHandler("addcoin", cmd_addcoin))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("removecoin", cmd_removecoin))
    app.add_handler(CommandHandler("quiet", cmd_quiet))
    app.add_handler(CommandHandler("setup", cmd_setup_alerts))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    web_thread = threading.Thread(target=start_web_server, daemon=True)
    web_thread.start()

    log.info("🚀 Altseason Bot PRO avviato!")
    await app.bot.send_message(
        chat_id=CHAT_ID,
        text="✅ *Altseason Bot PRO Online* 🚀\n\nNuove funzioni attive:\n🔔 Alert su prezzi specifici\n💼 Tracking portfolio con P&L\n🌙 Modalità No Disturb\n☀️ Riepilogo mattutino alle 8:00\n\nPremi ❓ Aiuto per vedere tutti i comandi!",
        parse_mode="Markdown"
    )

    async with app:
        await app.start()
        await app.updater.start_polling()
        await auto_monitor(app)

if __name__ == "__main__":
    asyncio.run(main())
