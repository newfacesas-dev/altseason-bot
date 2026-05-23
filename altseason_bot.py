import asyncio
import logging
import requests
import pandas as pd
import time
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

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
}

PORTFOLIO_QTY = {
    "XRP": 25142, "SOL": 201, "ETH": 10.52, "DOGE": 31128,
    "BNB": 5.05, "HBAR": 14686, "BONK": 150804881,
    "SEI": 13723, "FET": 3223, "LUNA": 9057,
}

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_data.json")
logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)
_cache = {}
CACHE_TTL = 180

KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("📊 Status"), KeyboardButton("🎯 Fase")],
    [KeyboardButton("📈 Macro"), KeyboardButton("🏆 Top Performer")],
    [KeyboardButton("😱 Fear & Greed"), KeyboardButton("📉 RSI & MACD")],
    [KeyboardButton("💼 Portfolio"), KeyboardButton("🔔 I miei Alert")],
    [KeyboardButton("💰 Prezzo BTC"), KeyboardButton("💰 Prezzo ETH")],
    [KeyboardButton("💰 Prezzo XRP"), KeyboardButton("💰 Prezzo SOL")],
    [KeyboardButton("📅 Timeline"), KeyboardButton("🔄 Reset Portfolio")],
    [KeyboardButton("🌙 No Disturb"), KeyboardButton("❓ Aiuto")],
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
    elif t == "🌙 No Disturb": await cmd_quiet(u, c)
    elif t == "💰 Prezzo BTC": c.args = ["BTC"]; await cmd_price(u, c)
    elif t == "💰 Prezzo ETH": c.args = ["ETH"]; await cmd_price(u, c)
    elif t == "💰 Prezzo XRP": c.args = ["XRP"]; await cmd_price(u, c)
    elif t == "💰 Prezzo SOL": c.args = ["SOL"]; await cmd_price(u, c)
    elif t == "❓ Aiuto": await cmd_help(u, c)

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
    ]
    for cmd, fn in cmds:
        app.add_handler(CommandHandler(cmd, fn))
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
