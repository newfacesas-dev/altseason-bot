import asyncio
import logging
import requests
import anthropic
import pandas as pd
import time
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler, CallbackQueryHandler

TELEGRAM_TOKEN = "8940955681:AAGbto8_W43gSe21rA3LlN776tMQfD2auIo"
CHAT_ID = "670903243"

CHECK_INTERVAL_SECONDS = 1800
BTC_DOM_THRESHOLD = 52.0
BTC_DOM_WARNING = 48.0
ETH_BTC_BREAKOUT = 0.060
RSI_OVERSOLD = 35
RSI_OVERBOUGHT = 70
VOLUME_SPIKE_MULTIPLIER = 2.0
QUIET_START = 23
QUIET_END = 8

ASSETS = {
    "BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "SOL": "solana",
    "ADA": "cardano", "DOGE": "dogecoin", "BNB": "binancecoin",
    "HBAR": "hedera-hashgraph", "BONK": "bonk", "ALGO": "algorand",
    "XLM": "stellar", "POL": "matic-network", "TRX": "tron",
    "GRT": "the-graph", "NEAR": "near", "FET": "fetch-ai",
    "SEI": "sei-network", "LUNA": "terra-luna-2", "MANA": "decentraland",
    "PEPE": "pepe", "SHIB": "shiba-inu",
    "AGIX": "singularitynet", "RENDER": "render-token", "INJ": "injective-protocol", "TIA": "celestia",
}

PORTFOLIO_QTY = {
    "XRP": 25142, "SOL": 201, "ETH": 10.52, "DOGE": 31128,
    "BNB": 5.05, "HBAR": 14686, "BONK": 150804881,
    "SEI": 13723, "FET": 3223, "LUNA": 9057,
}

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users")
os.makedirs(DATA_DIR, exist_ok=True)
AI_LIMITS = {"free": 5, "basic": 50, "pro": 999}


ADMIN_ID = "670903243"

ADMIN_KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("👥 I miei Utenti"), KeyboardButton("📊 Stats Admin")],
    [KeyboardButton("💰 Ricavi"), KeyboardButton("🔙 Torna al Bot")],
], resize_keyboard=True)

def get_user_file(chat_id):
    return os.path.join(DATA_DIR, f"user_{chat_id}.json")

def load_user(chat_id):
    try:
        f = get_user_file(str(chat_id))
        if os.path.exists(f):
            with open(f, "r") as fp:
                return json.load(fp)
    except: pass
    return {"portfolio": {}, "alerts": [], "quiet_mode": False, "plan": "free", "ai_msgs": 0}

def save_user(chat_id, data):
    try:
        with open(get_user_file(str(chat_id)), "w") as fp:
            json.dump(data, fp, indent=2)
    except Exception as e:
        log.error(f"Save error: {e}")

def get_uid(update):
    return str(update.message.chat_id)
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)
_cache = {}
CACHE_TTL = 180

KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("📊 Status"), KeyboardButton("🎯 Fase")],
    [KeyboardButton("📈 Macro"), KeyboardButton("🏆 Top Performer")],
    [KeyboardButton("😱 Fear & Greed"), KeyboardButton("📉 RSI & MACD")],
    [KeyboardButton("💼 Portfolio"), KeyboardButton("💹 Aggiungi Coin")],
    [KeyboardButton("🔔 I miei Alert"), KeyboardButton("📊 Il mio piano")],
    [KeyboardButton("💰 Prezzo BTC"), KeyboardButton("💰 Prezzo ETH")],
    [KeyboardButton("💰 Prezzo XRP"), KeyboardButton("💰 Prezzo SOL")],
    [KeyboardButton("📅 Timeline"), KeyboardButton("🔄 Reset Portfolio")],
    [KeyboardButton("📤 Piano Uscita"), KeyboardButton("🚨 Check Uscita")],
    [KeyboardButton("💱 Forex & Indici"), KeyboardButton("💳 Abbonati")],
    [KeyboardButton("📊 Il mio piano"), KeyboardButton("❓ Aiuto")],
], resize_keyboard=True)

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
    except: pass
    return {"portfolio": {}, "alerts": [], "quiet_mode": False}

def save_data(d):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(d, f, indent=2)
    except Exception as e:
        log.error(f"Save error: {e}")

DATA = load_data()

def init_portfolio():
    try:
        prices = get_prices()
        DATA["portfolio"] = {}
        for sym, qty in PORTFOLIO_QTY.items():
            p = prices.get(sym, {}).get("price", 0)
            if p > 0:
                DATA["portfolio"][sym] = {"qty": qty, "buy": p}
        save_data(DATA)
        log.info(f"Portfolio inizializzato: {len(DATA['portfolio'])} asset")
        return True
    except Exception as e:
        log.error(f"Init portfolio error: {e}")
        return False

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
        result = {
            "dom": d["market_cap_percentage"]["btc"],
            "mcap": tot / 1e12,
            "total3": (tot - btcm - ethm) / 1e9,
        }
        _cache['g'] = {'d': result, 't': time.time()}
        return result
    except:
        return {"dom": 58, "mcap": 2.5, "total3": 850}

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
            result[sym] = {
                "price": d.get("usd", 0),
                "ch": d.get("usd_24h_change", 0),
                "mcap": d.get("usd_market_cap", 0),
                "vol": d.get("usd_24h_vol", 0),
            }
        _cache['p'] = {'d': result, 't': time.time()}
        return result
    except:
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
        closes = [float(x[4]) for x in data]
        vols = [float(x[5]) for x in data]
        return closes, vols
    except:
        return [], []

def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return None
    s = pd.Series(closes)
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return round((100 - (100 / (1 + rs))).iloc[-1], 1)

def calc_macd(closes):
    if len(closes) < 26:
        return None, None, None
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
            if avg > 0 and vols[-1] > avg * VOLUME_SPIKE_MULTIPLIER:
                vol_spike = round(vols[-1] / avg, 1)
        result[sym] = {"rsi": rsi, "macd": macd, "signal": signal, "hist": hist, "vol_spike": vol_spike}
    return result


def get_claude_response(user_msg, market_context):
    try:
        api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not api_key:
            return 'API key non configurata.'
        client = anthropic.Anthropic(api_key=api_key)
        pf_str = str(DATA.get('portfolio', {}))
        system = ('Sei un esperto trader crypto per Altseason 2026.\n'
            'DATI MERCATO:\n' + market_context + '\n'
            'PORTFOLIO: ' + pf_str + '\n'
            'Rispondi in italiano, max 200 parole, usa emoji, sii pratico.')
        msg = client.messages.create(
            model='claude-sonnet-4-5',
            max_tokens=1000,
            system=system,
            messages=[{'role': 'user', 'content': user_msg}]
        )
        return msg.content[0].text
    except Exception as e:
        return f'Errore AI: {e}'


def get_forex():
    """Fetch forex and indices prices from Yahoo Finance API"""
    if 'forex' in _cache and time.time() - _cache['forex']['t'] < 300:
        return _cache['forex']['d']
    try:
        symbols = {
            "EUR/USD": "EURUSD=X",
            "GBP/USD": "GBPUSD=X", 
            "USD/JPY": "JPY=X",
            "USD/CHF": "CHF=X",
            "AUD/USD": "AUDUSD=X",
            "XAU/USD": "GC=F",
            "XAG/USD": "SI=F",
            "S&P500": "^GSPC",
            "NASDAQ": "^IXIC",
            "DXY": "DX-Y.NYB",
        }
        result = {}
        for name, sym in symbols.items():
            try:
                r = requests.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&range=2d",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=5
                )
                data = r.json()["chart"]["result"][0]
                closes = data["indicators"]["quote"][0]["close"]
                closes = [c for c in closes if c is not None]
                if len(closes) >= 2:
                    price = closes[-1]
                    prev = closes[-2]
                    ch = ((price - prev) / prev) * 100
                    result[name] = {"price": price, "ch": ch}
            except:
                pass
        _cache['forex'] = {'d': result, 't': time.time()}
        return result
    except Exception as e:
        log.error(f"Forex error: {e}")
        return {}

def phase(dom):
    if dom < BTC_DOM_WARNING:
        return "🚨 USCITA", "TOP CICLO! Prendi profitto subito", "USCITA"
    if dom < BTC_DOM_THRESHOLD:
        return "⚡ ALTSEASON ATTIVA", "BTC Dom sotto 52% — ruota verso altcoin", "AZIONE"
    return "👀 ACCUMULO", f"BTC Dom {dom:.1f}% — tieni le posizioni", "MONITORA"

def is_quiet():
    if not DATA.get("quiet_mode", False):
        return False
    h = datetime.now().hour
    if QUIET_START > QUIET_END:
        return h >= QUIET_START or h < QUIET_END
    return QUIET_START <= h < QUIET_END

def check_alerts(prices):
    triggered = []
    remaining = []
    for a in DATA.get("alerts", []):
        sym = a["sym"]
        target = a["price"]
        above = a["above"]
        cur = prices.get(sym, {}).get("price", 0)
        if cur == 0:
            remaining.append(a)
            continue
        hit = (above and cur >= target) or (not above and cur <= target)
        if hit:
            d = "↗️" if above else "↘️"
            triggered.append(f"🔔 *{sym}* {d} Target `${target:,.2f}` — ora `${cur:,.2f}`")
        else:
            remaining.append(a)
    if triggered:
        DATA["alerts"] = remaining
        save_data(DATA)
    return triggered

async def cmd_help(u, c):
    msg = """👋 *ALTSEASON BOT 2026 — GUIDA COMPLETA*

📊 *MONITORAGGIO*
/status — Report completo
/phase — Fase del ciclo
/macro — BTC Dom, ETH/BTC, TOTAL3
/feargreed — Sentiment 0-100
/rsimacd — RSI e MACD indicatori
/top — Top performer 24h
/price BTC — Prezzo asset

💼 *PORTFOLIO & P&L*
/portfolio — P&L in tempo reale
/reset — Reset con prezzi attuali
/addcoin XRP 1000 1.36 — Aggiungi
/removecoin BTC — Rimuovi

🔔 *ALERT PREZZI*
/alert XRP 3 — Avvisami sale a $3
/alert SOL 200 down — Avvisami scende
/alerts — Lista alert attivi
/delalert 1 — Cancella alert #1
/setup — 28 alert strategia automatici

📅 /timeline — Roadmap altseason 2026

🌙 /quiet — Silenzio notturno 23:00-08:00

⏰ *TIMELINE RAPIDA*
GIU-LUG: TIENI tutto
AGO-SET: Vendi 25% ogni coin
OTT-NOV: ESCI 50-75%
DIC: Accumula BTC

🚀 Buona bull run! 💰"""
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_start(u, c): await cmd_help(u, c)

async def cmd_status(u, c):
    await u.message.reply_text("⏳ Recupero dati...", reply_markup=KEYBOARD)
    try:
        g = get_global()
        p = get_prices()
        fg = get_fg()
        ph, desc, level = phase(g["dom"])
        eth_btc = p["ETH"]["price"] / p["BTC"]["price"] if p["BTC"]["price"] else 0
        now = datetime.now().strftime("%d/%m/%Y %H:%M")
        msg = f"*🤖 STATUS — {now}*\n\n{ph} (`{level}`)\n_{desc}_\n\n📊 *MACRO*\n• BTC Dom: `{g['dom']:.2f}%`\n• ETH/BTC: `{eth_btc:.5f}`\n• TOTAL3: `${g['total3']:.1f}B`\n• Fear&Greed: {fg['em']} `{fg['v']} — {fg['lbl']}`\n\n💰 *PREZZI*\n• 🟢/🔴 BTC: `${p['BTC']['price']:,.0f}` ({p['BTC']['ch']:+.1f}%)\n• ETH: `${p['ETH']['price']:,.0f}` ({p['ETH']['ch']:+.1f}%)\n• XRP: `${p['XRP']['price']:,.3f}` ({p['XRP']['ch']:+.1f}%)\n• SOL: `${p['SOL']['price']:,.1f}` ({p['SOL']['ch']:+.1f}%)"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_phase(u, c):
    try:
        g = get_global()
        ph, desc, level = phase(g["dom"])
        actions = {
            "MONITORA": "1️⃣ Tieni tutto\n2️⃣ Aspetta BTC Dom <52%\n3️⃣ Non vendere ancora",
            "AZIONE": "1️⃣ Ruota verso altcoin\n2️⃣ Vendi 25% quando +100%\n3️⃣ Monitora XRP",
            "USCITA": "1️⃣ ESCI progressivamente\n2️⃣ Sposta in USDT\n3️⃣ DOGE e BONK escono primi",
        }
        msg = f"{ph}\n\n_{desc}_\n\nBTC Dom: `{g['dom']:.2f}%`\n\n📋 *Cosa fare ora:*\n{actions[level]}"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_macro(u, c):
    try:
        g = get_global()
        p = get_prices()
        fg = get_fg()
        eth_btc = p["ETH"]["price"] / p["BTC"]["price"] if p["BTC"]["price"] else 0
        msg = f"📊 *MACRO*\n\n• BTC Dom: `{g['dom']:.2f}%` {'🔴 Altseason!' if g['dom'] < 52 else '🟡 BTC domina'}\n• ETH/BTC: `{eth_btc:.5f}` {'🟢 Breakout!' if eth_btc > 0.06 else '⚪ Sotto soglia'}\n• TOTAL3: `${g['total3']:.1f}B`\n• MCap: `${g['mcap']:.2f}T`\n• Fear&Greed: {fg['em']} `{fg['v']} — {fg['lbl']}`"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_feargreed(u, c):
    try:
        fg = get_fg()
        v = fg["v"]
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
            rsi = ind.get("rsi", "N/A")
            hist = ind.get("hist", 0)
            trend = "↗️ Rialzista" if hist and hist > 0 else "↘️ Ribassista"
            rsi_s = "🟢 Oversold — COMPRA" if rsi != "N/A" and rsi < RSI_OVERSOLD else ("🔴 Overbought — ATTENZIONE" if rsi != "N/A" and rsi > RSI_OVERBOUGHT else "⚪ Neutro")
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

async def cmd_price(u, c):
    if not c.args:
        await u.message.reply_text("Uso: /price BTC", reply_markup=KEYBOARD)
        return
    s = c.args[0].upper()
    if s not in ASSETS:
        await u.message.reply_text(f"❌ Disponibili: {', '.join(list(ASSETS.keys())[:10])}", reply_markup=KEYBOARD)
        return
    try:
        p = get_prices()[s]
        a = "🟢" if p["ch"] >= 0 else "🔴"
        msg = f"{a} *{s}*\n\n💵 `${p['price']:,.4f}`\n📈 24h: `{p['ch']:+.2f}%`\n💎 MCap: `${p['mcap']/1e9:.1f}B`\n📊 Vol: `${p['vol']/1e6:.1f}M`"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_portfolio(u, c):
    pf = DATA.get("portfolio", {})
    if not pf:
        await u.message.reply_text("Portfolio vuoto. Usa /reset", reply_markup=KEYBOARD)
        return
    try:
        prices = get_prices()
        lines = ["💼 *PORTFOLIO*\n"]
        ti = 0
        tc = 0
        for sym, pos in sorted(pf.items()):
            pr = prices.get(sym, {}).get("price", 0)
            if pr == 0: continue
            qty = pos["qty"]
            buy = pos["buy"]
            inv = qty * buy
            cur = qty * pr
            pnl = cur - inv
            pct = ((pr - buy) / buy * 100) if buy else 0
            a = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"{a} *{sym}*: `{pct:+.1f}%` (`${pnl:+,.0f}`)")
            ti += inv
            tc += cur
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
    if init_portfolio():
        await u.message.reply_text(f"✅ Portfolio resettato con prezzi attuali!\n{len(DATA['portfolio'])} asset. P&L parte da 0%.", reply_markup=KEYBOARD)
    else:
        await u.message.reply_text("❌ Errore reset", reply_markup=KEYBOARD)

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
        DATA["portfolio"][s] = {"qty": qty, "buy": buy}
        save_data(DATA)
        await u.message.reply_text(f"✅ *{s}*: `{qty}` @ `${buy:,.4f}`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except:
        await u.message.reply_text("❌ Valori non validi", reply_markup=KEYBOARD)

async def cmd_removecoin(u, c):
    if not c.args:
        await u.message.reply_text("Uso: /removecoin BTC", reply_markup=KEYBOARD)
        return
    s = c.args[0].upper()
    if s in DATA.get("portfolio", {}):
        del DATA["portfolio"][s]
        save_data(DATA)
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
        above = True
        if len(c.args) >= 3 and c.args[2].lower() == "down":
            above = False
        DATA["alerts"].append({"sym": s, "price": t, "above": above})
        save_data(DATA)
        d = "sale a" if above else "scende a"
        await u.message.reply_text(f"✅ Alert: *{s}* {d} `${t:,.2f}`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except:
        await u.message.reply_text("❌ Errore", reply_markup=KEYBOARD)

async def cmd_alerts(u, c):
    al = DATA.get("alerts", [])
    if not al:
        await u.message.reply_text("Nessun alert. Usa /alert XRP 3", reply_markup=KEYBOARD)
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
        al = DATA.get("alerts", [])
        if 0 <= i < len(al):
            r = al.pop(i)
            save_data(DATA)
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
        "DOGE": [0.30, 0.60, 1.00], "HBAR": [0.20, 0.40, 0.70],
        "SEI": [0.80, 1.50, 3.00],
    }
    for sym, prices in targets.items():
        for p in prices:
            alerts.append({"sym": sym, "price": p, "above": True})
    DATA["alerts"] = alerts
    save_data(DATA)
    await u.message.reply_text(f"✅ *{len(alerts)} alert impostati!*\n\nXRP: $3→$5→$8→$12\nSOL: $200→$350→$500→$800\nETH: $4k→$6k→$9k→$14k\nBNB: $900→$1.2k→$1.5k→$2k\nDOGE: $0.30→$0.60→$1.00\nHBAR: $0.20→$0.40→$0.70\nSEI: $0.80→$1.50→$3.00", parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_timeline(u, c):
    msg = """📅 *TIMELINE ALTSEASON 2026*

🌱 *GIUGNO-LUGLIO — ACCUMULO*
BTC Dom: 55-52% — Fear&Greed <40
→ TIENI tutto, non vendere nulla
→ ETH e SOL iniziano a salire
→ Imposta gli alert sui target T1

⚡ *AGOSTO-SETTEMBRE — ROTAZIONE*
BTC Dom <52% — Altcoin +300%
→ Vendi 25% di ogni coin al T1
→ XRP, ADA, BNB esplodono
→ Target: XRP $3, SOL $200, ETH $4k

🚀 *OTTOBRE-NOVEMBRE — EUFORIA*
Fear&Greed >80 — XRP pump tardivo
→ ESCI dal 50-75% di tutto
→ DOGE e BONK escono PRIMI
→ Sposta in USDT/USDC

📉 *DICEMBRE 2026 — TOP CICLO*
BTC Dom risale — Crollo -60/-80%
→ Chi è uscito accumula BTC
→ Bear market inizia

🎯 *TARGET FINALI*
XRP: $3→$5→$8→$12
SOL: $200→$350→$500→$800
ETH: $4k→$6k→$9k→$14k
BNB: $900→$1.2k→$1.5k→$2k
DOGE: $0.30→$0.60→$1.00
HBAR: $0.20→$0.40→$0.70

🚨 *SEGNALI DI TOP*
• XRP pump +15% tardivo → ESCI 50%
• Fear&Greed >85 × 3 giorni → ESCI
• Meme mania DOGE/BONK → ESCI meme
• BTC Dom <48% → ESCI tutto"""
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)


async def cmd_exit_plan(u, c):
    msg = (
        "📤 *PIANO DI USCITA GRADUALE*\n\n"
        "━━━━━━━━━\n"
        "🟡 *BLOCCO 1 - Inizio Euforia*\n"
        "━━━━━━━━━\n"
        "Trigger: Fear&Greed >75 per 2 giorni\n"
        "Azione: Vendi 10-15% di tutto\n"
        "Timing: 3-7 giorni graduali\n"
        "Priority: Meme coin prima (DOGE, BONK)\n\n"
        "━━━━━━━━━\n"
        "🟠 *BLOCCO 2 - Mercato Accelerato*\n"
        "━━━━━━━━━\n"
        "Trigger: BTC Dom <50% + F&G >80\n"
        "Azione: Vendi 20-30% aggiuntivo\n"
        "Timing: 5-14 giorni graduali\n"
        "Priority: AI speculative, meme, small cap\n\n"
        "━━━━━━━━━\n"
        "🔴 *BLOCCO 3 - Blow-off Top*\n"
        "━━━━━━━━━\n"
        "Trigger: XRP pump + meme isterici + retail impazzito\n"
        "Azione: Vendi 30-40% aggiuntivo\n"
        "Timing: 48h-7 giorni VELOCI\n"
        "Priority: Tutto tranne BTC e ETH\n\n"
        "━━━━━━━━━\n"
        "🚨 *STOP LOSS EMERGENZA*\n"
        "━━━━━━━━━\n"
        "Trigger: Mercato crolla -30% in 7 giorni\n"
        "Azione: Esci dal 50% IMMEDIATAMENTE\n\n"
        "💡 *REGOLE D'ORO*\n"
        "- MAI vendere tutto in un giorno\n"
        "- MAI rientrare per FOMO\n"
        "- Preleva 30% profitti in fiat\n"
        "- Bear market: accumula BTC gradualmente\n"
        "- Portfolio futuro: 70% BTC, 20% alt, 10% operativo"
    )
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)


async def cmd_stoploss(u, c):
    try:
        p = get_prices()
        g = get_global()
        fg = get_fg()
        warnings = []
        if fg["v"] > 80:
            warnings.append(f"🔴 *BLOCCO 2 ATTIVO*\nFear&Greed `{fg['v']}` — Vendi 20-30% progressivamente")
        elif fg["v"] > 75:
            warnings.append(f"🟡 *BLOCCO 1 ATTIVO*\nFear&Greed `{fg['v']}` — Inizia a vendere 10-15%")
        if g["dom"] < 48:
            warnings.append(f"🔴 *BTC DOM CRITICA* `{g['dom']:.1f}%`\nZona storica top ciclo — accelera uscite!")
        memes = [(s, p[s]["ch"]) for s in ["DOGE","BONK","PEPE"] if p.get(s, {}).get("ch", 0) > 15]
        if memes:
            meme_str = ", ".join([f"{s} +{c:.0f}%" for s,c in memes])
            warnings.append(f"🎰 *MEME MANIA AVANZATA*\n{meme_str}\nSegnale top ciclo — ESCI dai meme!")
        if p.get("XRP", {}).get("ch", 0) > 15 and g["dom"] < 52:
            warnings.append(f"⚠️ *XRP PUMP TARDIVO* +{p['XRP']['ch']:.1f}%\nStoricamente indica TOP CICLO — Esci dal 50%!")
        if warnings:
            msg = "🚨 *ALERT PIANO DI USCITA*\n\n" + "\n\n".join(warnings)
        else:
            msg = f"✅ *Nessun segnale di uscita urgente*\n\nFear&Greed: `{fg['v']}` sotto soglia\nBTC Dom: `{g['dom']:.1f}%` nella norma\nNessuna meme mania in corso"
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"Errore: {e}", reply_markup=KEYBOARD)



async def cmd_myplan(u, c):
    uid = get_uid(u)
    ud = load_user(uid)
    plan = ud.get("plan", "free")
    used = ud.get("ai_msgs", 0)
    limit = AI_LIMITS.get(plan, 5)
    remaining = max(0, limit - used)
    
    plan_emoji = {"free": "🆓", "basic": "💙", "pro": "👑"}.get(plan, "🆓")
    plan_name = {"free": "Free", "basic": "Basic", "pro": "Pro"}.get(plan, "Free")
    
    msg = (
        f"👤 *IL TUO PIANO*\n\n"
        f"{plan_emoji} Piano: *{plan_name}*\n"
        f"🤖 Messaggi AI usati: `{used}/{limit}`\n"
        f"✅ Messaggi rimasti: `{remaining}`\n\n"
    )
    
    if plan == "free":
        msg += (
            "⬆️ *Vuoi più messaggi AI?*\n\n"
            "💙 *Basic* €9.99/mese → 50 msg/giorno\n"
            "👑 *Pro* €19.99/mese → Illimitati\n\n"
            "Scrivi /upgrade per info"
        )
    elif plan == "basic":
        msg += "👑 Upgrada a *Pro* per messaggi illimitati!\n/upgrade"
    else:
        msg += "🎉 Sei al piano massimo!"
    
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)


async def cmd_resetai(u, c):
    """Admin command: reset AI counter for a user"""
    uid = get_uid(u)
    if uid != "670903243":
        await u.message.reply_text("❌ Comando riservato all'admin", reply_markup=KEYBOARD)
        return
    if not c.args:
        await u.message.reply_text("Uso: /resetai CHAT_ID", reply_markup=KEYBOARD)
        return
    target = c.args[0]
    ud = load_user(target)
    ud["ai_msgs"] = 0
    save_user(target, ud)
    await u.message.reply_text(f"✅ Counter AI resettato per {target}", reply_markup=KEYBOARD)


async def cmd_setplan(u, c):
    """Admin command: set plan for a user"""
    uid = get_uid(u)
    if uid != "670903243":
        await u.message.reply_text("❌ Comando riservato all'admin", reply_markup=KEYBOARD)
        return
    if len(c.args) < 2:
        await u.message.reply_text("Uso: /setplan CHAT_ID free|basic|pro", reply_markup=KEYBOARD)
        return
    target = c.args[0]
    plan = c.args[1].lower()
    if plan not in ["free", "basic", "pro"]:
        await u.message.reply_text("❌ Piano non valido", reply_markup=KEYBOARD)
        return
    ud = load_user(target)
    ud["plan"] = plan
    ud["ai_msgs"] = 0
    save_user(target, ud)
    await u.message.reply_text(f"✅ Piano {plan} impostato per {target}", reply_markup=KEYBOARD)


async def cmd_users(u, c):
    """Admin command: list all users"""
    uid = get_uid(u)
    if uid != "670903243":
        await u.message.reply_text("❌ Comando riservato all'admin", reply_markup=KEYBOARD)
        return
    try:
        files = [f for f in os.listdir(DATA_DIR) if f.startswith("user_")]
        lines = [f"👥 *UTENTI TOTALI: {len(files)}*\n"]
        for f in files[:20]:
            chat_id = f.replace("user_", "").replace(".json", "")
            ud = load_user(chat_id)
            plan = ud.get("plan", "free")
            used = ud.get("ai_msgs", 0)
            emoji = {"free": "🆓", "basic": "💙", "pro": "👑"}.get(plan, "🆓")
            lines.append(f"{emoji} `{chat_id}` — {plan} ({used} msg)")
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)



# Wizard stati
WIZARD_COIN, WIZARD_QTY, WIZARD_PRICE = range(3)

# Coin popolari per selezione rapida
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
    await u.message.reply_text(
        "💼 *AGGIUNGI AL PORTFOLIO*\n\nSeleziona la coin o scrivila:",
        parse_mode="Markdown",
        reply_markup=make_coin_keyboard()
    )
    return WIZARD_COIN

async def wizard_coin_button(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data.replace("coin_", "")
    
    if data == "MANUAL":
        await query.edit_message_text("✍️ Scrivi il simbolo della coin (es. BTC, ETH, XRP):")
        return WIZARD_COIN
    
    context.user_data["wizard_coin"] = data
    await query.edit_message_text(
        f"✅ Coin selezionata: *{data}*\n\nQuante ne hai?",
        parse_mode="Markdown"
    )
    return WIZARD_QTY

async def wizard_coin_text(update, context):
    coin = update.message.text.upper().strip()
    if coin not in ASSETS:
        await update.message.reply_text(
            f"❌ *{coin}* non trovata.\nCoin disponibili: {', '.join(list(ASSETS.keys())[:10])}...",
            parse_mode="Markdown"
        )
        return WIZARD_COIN
    context.user_data["wizard_coin"] = coin
    await update.message.reply_text(f"✅ *{coin}* selezionata!\n\nQuante ne hai?", parse_mode="Markdown")
    return WIZARD_QTY

async def wizard_qty(update, context):
    try:
        qty = float(update.message.text.replace(",", "."))
        context.user_data["wizard_qty"] = qty
        coin = context.user_data["wizard_coin"]
        
        # Mostra prezzo attuale come riferimento
        try:
            prices = get_prices()
            current = prices.get(coin, {}).get("price", 0)
            price_hint = f"\n\n💡 Prezzo attuale: `${current:,.4f}`" if current else ""
        except:
            price_hint = ""
        
        await update.message.reply_text(
            f"✅ Quantità: *{qty}*{price_hint}\n\nA quanto hai comprato in media ($)?\n(Scrivi 0 per usare il prezzo attuale)",
            parse_mode="Markdown"
        )
        return WIZARD_PRICE
    except:
        await update.message.reply_text("❌ Scrivi un numero valido (es. 1000 o 0.5)")
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
        
        uid = get_uid(update)
        ud = load_user(uid)
        ud["portfolio"][coin] = {"qty": qty, "buy": buy_price}
        save_user(uid, ud)
        
        invested = qty * buy_price
        await update.message.reply_text(
            f"✅ *{coin} aggiunto al portfolio!*\n\n"
            f"• Quantità: `{qty}`\n"
            f"• Prezzo acquisto: `${buy_price:,.4f}`\n"
            f"• Valore investito: `${invested:,.2f}`\n\n"
            f"Premi /portfolio per vedere il tuo P&L",
            parse_mode="Markdown",
            reply_markup=KEYBOARD
        )
        return ConversationHandler.END
    except:
        await update.message.reply_text("❌ Scrivi un numero valido (es. 1.36)")
        return WIZARD_PRICE

async def wizard_cancel(update, context):
    await update.message.reply_text("❌ Operazione annullata", reply_markup=KEYBOARD)
    return ConversationHandler.END


async def cmd_pay(u, c):
    msg = (
        "💳 *ABBONATI AL BOT*\n\n"
        "Scegli il tuo piano:\n\n"
        "💙 *Basic* — €9.99/mese\n"
        "• 50 messaggi AI al giorno\n"
        "• Portfolio completo\n"
        "• 20 alert prezzi\n\n"
        "👑 *Pro* — €19.99/mese\n"
        "• Messaggi AI illimitati\n"
        "• Alert illimitati\n"
        "• Tutte le funzioni\n\n"
        "━━━━━━━━━━━━━━━\n"
        "💰 *Come pagare:*\n\n"
        "Invia il pagamento a uno di questi wallet:\n\n"
        "🔷 *USDT (TRC20):*\n`[IN ARRIVO]`\n\n"
        "🔶 *BTC:*\n`[IN ARRIVO]`\n\n"
        "🟣 *ETH/USDC:*\n`[IN ARRIVO]`\n\n"
        "━━━━━━━━━━━━━━━\n"
        "📩 Dopo il pagamento invia lo screenshot a @enricoluciano\n"
        "Il tuo piano verrà attivato entro 24h!"
    )
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_admin(u, c):
    uid = get_uid(u)
    if uid != ADMIN_ID:
        await u.message.reply_text("Accesso negato", reply_markup=KEYBOARD)
        return
    try:
        files = [f for f in os.listdir(DATA_DIR) if f.startswith("user_")]
        total = len(files)
        free = basic = pro = 0
        for f in files:
            cid = f.replace("user_","").replace(".json","")
            plan = load_user(cid).get("plan","free")
            if plan == "free": free += 1
            elif plan == "basic": basic += 1
            else: pro += 1
        ricavi = basic * 9.99 + pro * 19.99
        msg = (
            f"\U0001f451 *PANNELLO ADMIN*\n\n"
            f"\U0001f465 Utenti: `{total}` (Free: {free} | Basic: {basic} | Pro: {pro})\n"
            f"\U0001f4b0 Ricavi: `\u20ac{ricavi:.2f}/mese`\n\n"
            f"Comandi:\n"
            f"`/setplan CHATID pro` \u2014 upgrade\n"
            f"`/resetai CHATID` \u2014 reset AI\n"
            f"`/users` \u2014 lista utenti"
        )
        await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=ADMIN_KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"Errore: {e}", reply_markup=KEYBOARD)


async def cmd_upgrade(u, c):
    msg = (
        "💎 *PIANI DISPONIBILI*\n\n"
        "🆓 *Free* — Gratis\n"
        "• 5 messaggi AI al giorno\n"
        "• Status, fase, prezzi\n\n"
        "💙 *Basic* — €9.99/mese\n"
        "• 50 messaggi AI al giorno\n"
        "• Portfolio completo\n"
        "• 20 alert prezzi\n\n"
        "👑 *Pro* — €19.99/mese\n"
        "• Messaggi AI illimitati\n"
        "• Alert illimitati\n"
        "• Tutto incluso\n\n"
        "📩 Per upgradare scrivi a @admin"
    )
    await u.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)



async def cmd_forex(u, c):
    await u.message.reply_text("⏳ Recupero dati forex...", reply_markup=KEYBOARD)
    try:
        data = get_forex()
        if not data:
            await u.message.reply_text("❌ Dati forex non disponibili", reply_markup=KEYBOARD)
            return
        
        lines = ["💱 *FOREX & INDICI*\n"]
        
        lines.append("🌍 *Valute principali*")
        for sym in ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD"]:
            if sym in data:
                d = data[sym]
                a = "🟢" if d["ch"] >= 0 else "🔴"
                lines.append(f"{a} *{sym}*: `{d['price']:.4f}` ({d['ch']:+.2f}%)")
        
        lines.append("\n📈 *Indici & Commodities*")
        for sym in ["S&P500", "NASDAQ", "XAU/USD", "XAG/USD", "DXY"]:
            if sym in data:
                d = data[sym]
                a = "🟢" if d["ch"] >= 0 else "🔴"
                price_fmt = f"{d['price']:,.2f}" if d['price'] > 100 else f"{d['price']:.4f}"
                lines.append(f"{a} *{sym}*: `{price_fmt}` ({d['ch']:+.2f}%)")
        
        lines.append("\n_Vuoi analisi AI su una coppia? Scrivimi tipo: Analizza EUR/USD_")
        
        await u.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await u.message.reply_text(f"❌ Errore: {e}", reply_markup=KEYBOARD)

async def cmd_quiet(u, c):
    DATA["quiet_mode"] = not DATA.get("quiet_mode", False)
    save_data(DATA)
    msg = "🌙 No Disturb ATTIVO — nessuna notifica 23:00-08:00" if DATA["quiet_mode"] else "☀️ No Disturb DISATTIVO"
    await u.message.reply_text(msg, reply_markup=KEYBOARD)

async def handle_text(u, c):
    t = u.message.text
    if t == "📊 Status": await cmd_status(u, c)
    elif t == "🎯 Fase": await cmd_phase(u, c)
    elif t == "📈 Macro": await cmd_macro(u, c)
    elif t == "🏆 Top Performer": await cmd_top(u, c)
    elif t == "😱 Fear & Greed": await cmd_feargreed(u, c)
    elif t == "📉 RSI & MACD": await cmd_rsimacd(u, c)
    elif t == "💼 Portfolio": await cmd_portfolio(u, c)
    elif t == "🔔 I miei Alert": await cmd_alerts(u, c)
    elif t == "📅 Timeline": await cmd_timeline(u, c)
    elif t == "🔄 Reset Portfolio": await cmd_reset(u, c)
    elif t == "💱 Forex & Indici": await cmd_forex(u, c)
    elif t == "🌙 No Disturb": await cmd_quiet(u, c)
    elif t == "💳 Abbonati": await cmd_pay(u, c)
    elif t == "💹 Aggiungi Coin": await cmd_addwizard(u, c)
    elif t == "👥 I miei Utenti": await cmd_users(u, c)
    elif t == "📊 Stats Admin": await cmd_admin(u, c)
    elif t == "💰 Ricavi": await cmd_stats(u, c) if hasattr(cmd_stats, "__call__") else await cmd_admin(u, c)
    elif t == "🔙 Torna al Bot": await u.message.reply_text("✅ Benvenuto nel bot!", reply_markup=KEYBOARD)
    elif t == "📊 Il mio piano": await cmd_myplan(u, c)
    elif t == "📤 Piano Uscita": await cmd_exit_plan(u, c)
    elif t == "🚨 Check Uscita": await cmd_stoploss(u, c)
    elif t == "💰 Prezzo BTC": c.args = ["BTC"]; await cmd_price(u, c)
    elif t == "💰 Prezzo ETH": c.args = ["ETH"]; await cmd_price(u, c)
    elif t == "💰 Prezzo XRP": c.args = ["XRP"]; await cmd_price(u, c)
    elif t == "💰 Prezzo SOL": c.args = ["SOL"]; await cmd_price(u, c)
    elif t == "❓ Aiuto": await cmd_help(u, c)
    else:
        try:
            uid = get_uid(u)
            ud = load_user(uid)
            limit = AI_LIMITS.get(ud.get("plan", "free"), 5)
            used = ud.get("ai_msgs", 0)
            if used >= limit:
                await u.message.reply_text(
                    f"⚠️ Hai usato tutti i {limit} messaggi AI del piano Free.\n\nUpgrada a Basic (50 msg) o Pro (illimitati)!\n\n/upgrade per info",
                    reply_markup=KEYBOARD
                )
                return
            ud["ai_msgs"] = used + 1
            save_user(uid, ud)
            await u.message.reply_text(f"🤖 Sto analizzando... ({used+1}/{limit})", reply_markup=KEYBOARD)
            g = get_global()
            p = get_prices()
            fg = get_fg()
            ph, desc, level = phase(g["dom"])
            ctx = (
                f"Fase: {ph} ({level})\n"
                f"BTC Dom: {g['dom']:.2f}pct\n"
                f"Fear&Greed: {fg['v']} {fg['lbl']}\n"
                f"BTC: ${p['BTC']['price']:,.0f} ({p['BTC']['ch']:+.1f}pct)\n"
                f"ETH: ${p['ETH']['price']:,.0f} ({p['ETH']['ch']:+.1f}pct)\n"
                f"XRP: ${p['XRP']['price']:,.4f} ({p['XRP']['ch']:+.1f}pct)\n"
                f"SOL: ${p['SOL']['price']:,.1f} ({p['SOL']['ch']:+.1f}pct)"
            )
            response = get_claude_response(t, ctx)
            await u.message.reply_text(f"🤖 *AI Analysis*\n\n{response}", parse_mode="Markdown", reply_markup=KEYBOARD)
        except Exception as e:
            await u.message.reply_text(f"Errore: {e}", reply_markup=KEYBOARD)

async def auto_monitor(app):
    await asyncio.sleep(10)
    last_phase = None
    loop = 0
    while True:
        try:
            if is_quiet():
                await asyncio.sleep(CHECK_INTERVAL_SECONDS)
                continue
            g = get_global()
            p = get_prices()
            fg = get_fg()
            ph, desc, level = phase(g["dom"])
            triggered = check_alerts(p)
            for msg in triggered:
                await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
            if level != last_phase:
                eth_btc = p["ETH"]["price"] / p["BTC"]["price"] if p["BTC"]["price"] else 0
                msg = f"🚨 *CAMBIO FASE!*\n\n{ph} (`{level}`)\n_{desc}_\n\nBTC Dom: `{g['dom']:.2f}%` | ETH/BTC: `{eth_btc:.5f}`\nFear&Greed: {fg['em']} `{fg['v']}`"
                await app.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown")
                last_phase = level
            memes = [s for s in ["DOGE", "BONK", "PEPE", "SHIB"] if p.get(s, {}).get("ch", 0) > 8]
            if len(memes) >= 2:
                await app.bot.send_message(chat_id=CHAT_ID, text=f"🎰 *MEME MANIA!* {', '.join(memes)} tutti su >8%\n⚠️ Segnale di euforia — considera uscita!", parse_mode="Markdown")
            loop += 1
        except Exception as e:
            log.error(f"Monitor error: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        try:
            wp = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'webapp.html')
            if os.path.exists(wp):
                with open(wp, 'r') as f:
                    self.wfile.write(f.read().encode())
                    return
        except: pass
        self.wfile.write(b"<h1>Altseason Bot 2026</h1>")
    def log_message(self, *a): pass

def start_web():
    port = int(os.environ.get('PORT', 8080))
    HTTPServer(('', port), WebHandler).serve_forever()

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    cmds = [
        ("start", cmd_start), ("help", cmd_help), ("status", cmd_status),
        ("phase", cmd_phase), ("macro", cmd_macro), ("feargreed", cmd_feargreed),
        ("rsimacd", cmd_rsimacd), ("top", cmd_top), ("price", cmd_price),
        ("portfolio", cmd_portfolio), ("reset", cmd_reset), ("addcoin", cmd_addcoin),
        ("removecoin", cmd_removecoin), ("alert", cmd_alert), ("alerts", cmd_alerts),
        ("delalert", cmd_delalert), ("setup", cmd_setup), ("timeline", cmd_timeline),
        ("quiet", cmd_quiet),
        ("forex", cmd_forex),
        ("upgrade", cmd_upgrade),
        ("admin", cmd_admin),
        ("pay", cmd_pay),
        ("add", cmd_addwizard),
        ("myplan", cmd_myplan),
        ("resetai", cmd_resetai),
        ("setplan", cmd_setplan),
        ("users", cmd_users),
        ("exitplan", cmd_exit_plan),
        ("stoploss", cmd_stoploss),
    ]
    for cmd, fn in cmds:
        app.add_handler(CommandHandler(cmd, fn))
    # Wizard aggiungi coin
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("add", cmd_addwizard)],
        states={
            WIZARD_COIN: [
                CallbackQueryHandler(wizard_coin_button, pattern="^coin_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_coin_text),
            ],
            WIZARD_QTY: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_qty)],
            WIZARD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, wizard_price)],
        },
        fallbacks=[CommandHandler("cancel", wizard_cancel)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(wizard_coin_button, pattern="^coin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    threading.Thread(target=start_web, daemon=True).start()

    if not DATA.get("portfolio"):
        init_portfolio()

    log.info("🚀 Altseason Bot COMPLETO online!")
    try:
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text="✅ *Altseason Bot COMPLETO Online!* 🚀\n\n📅 /timeline — Roadmap\n💼 /portfolio — P&L\n⚙️ /setup — 28 alert\n📉 /rsimacd — Indicatori\n❓ /help — Guida completa",
            parse_mode="Markdown"
        )
    except: pass

    async with app:
        await app.start()
        await app.updater.start_polling()
        asyncio.create_task(auto_monitor(app))
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
