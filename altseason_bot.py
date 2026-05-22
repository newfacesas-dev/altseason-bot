import asyncio
import logging
import requests
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

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

ASSETS = {
    "BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "SOL": "solana",
    "ADA": "cardano", "DOGE": "dogecoin", "BNB": "binancecoin",
    "HBAR": "hedera-hashgraph", "BONK": "bonk", "ALGO": "algorand",
    "XLM": "stellar", "POL": "matic-network", "TRX": "tron",
    "GRT": "the-graph", "NEAR": "near", "FET": "fetch-ai",
    "PEOPLE": "constitutiondao", "MANA": "decentraland", "SEI": "sei-network",
}

DATA_FILE = "bot_data.json"
_cache = {}

KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("📊 Status"), KeyboardButton("💼 Portfolio")],
    [KeyboardButton("🎯 Fase"), KeyboardButton("😱 Fear & Greed")],
    [KeyboardButton("🏆 Top"), KeyboardButton("🔔 Alert")],
    [KeyboardButton("⚙️ Setup Alert"), KeyboardButton("❓ Aiuto")],
], resize_keyboard=True)

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
    except:
        pass
    return {"portfolio": {}, "alerts": []}

def save_data(d):
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(d, f, indent=2)
    except:
        pass

DATA = load_data()

if not DATA.get("portfolio"):
    DATA["portfolio"] = {
        "XRP": {"qty": 25142, "buy": 1.36},
        "SOL": {"qty": 201, "buy": 86.96},
        "ETH": {"qty": 10.52, "buy": 2100},
        "DOGE": {"qty": 31128, "buy": 0.11},
        "BONK": {"qty": 150804881, "buy": 0.000022},
        "HBAR": {"qty": 14686, "buy": 0.077},
        "BNB": {"qty": 5.05, "buy": 655},
        "ADA": {"qty": 4996, "buy": 0.25},
        "ALGO": {"qty": 14606, "buy": 0.22},
        "XLM": {"qty": 13136, "buy": 0.29},
        "POL": {"qty": 24281, "buy": 0.22},
        "TRX": {"qty": 5437, "buy": 0.26},
        "GRT": {"qty": 43036, "buy": 0.12},
        "FET": {"qty": 3223, "buy": 0.55},
        "PEOPLE": {"qty": 7951, "buy": 0.006},
        "NEAR": {"qty": 379, "buy": 2.8},
        "MANA": {"qty": 1186, "buy": 0.32},
        "SEI": {"qty": 13723, "buy": 0.27},
    }
    save_data(DATA)

def get_global():
    if 'g' in _cache and time.time() - _cache['g']['t'] < 180:
        return _cache['g']['d']
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global", timeout=10)
        d = r.json()["data"]
        result = {
            "dom": d["market_cap_percentage"]["btc"],
            "mcap": d["total_market_cap"]["usd"] / 1e12,
        }
        _cache['g'] = {'d': result, 't': time.time()}
        return result
    except:
        return {"dom": 55, "mcap": 2.5}

def get_prices():
    if 'p' in _cache and time.time() - _cache['p']['t'] < 180:
        return _cache['p']['d']
    try:
        ids = ",".join(ASSETS.values())
        r = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true", timeout=10)
        raw = r.json()
        result = {}
        for sym, cid in ASSETS.items():
            d = raw.get(cid, {})
            result[sym] = {"price": d.get("usd", 0), "ch": d.get("usd_24h_change", 0)}
        _cache['p'] = {'d': result, 't': time.time()}
        return result
    except:
        return {s: {"price": 0, "ch": 0} for s in ASSETS}

def get_fg():
    if 'fg' in _cache and time.time() - _cache['fg']['t'] < 300:
        return _cache['fg']['d']
    try:
        r = requests.get("https://api.alternative.me/fng/?limit=1", timeout=10)
        d = r.json()["data"][0]
        v = int(d["value"])
        result = {"v": v, "lbl": d["value_classification"]}
        _cache['fg'] = {'d': result, 't': time.time()}
        return result
    except:
        return {"v": 50, "lbl": "Neutral"}

def phase(dom):
    if dom < 48:
        return "🚨 USCITA", "Top ciclo vicino!"
    if dom < 52:
        return "⚡ AZIONE", "Altseason attiva — ruota verso altcoin"
    return "👀 MONITORA", "Fase accumulo — tieni le posizioni"

async def cmd_help(update, ctx):
    msg = """👋 *ALTSEASON BOT 2026*

📊 *MONITORAGGIO*
/status — Status completo
/phase — Fase del ciclo
/feargreed — Sentiment 0-100
/top — Top performer 24h
/price BTC — Prezzo asset

💼 *PORTFOLIO*
/portfolio — P&L in tempo reale
/addcoin XRP 1000 1.36 — Aggiungi
/removecoin BTC — Rimuovi

🔔 *ALERT*
/alert XRP 3 — Avvisami sale a $3
/alert SOL 200 down — Avvisami scende
/alerts — Lista alert
/delalert 1 — Cancella alert
/setup — 25 alert strategia

⏰ *TIMELINE*
GIU-LUG: BTC Dom 55-52% → TIENI
AGO-SET: Dom <52% → Vendi 25%
OTT-NOV: F&G >80 → ESCI 50-75%
DIC: Crollo → Accumula BTC

Buona bull run! 🚀"""
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_start(update, ctx):
    await cmd_help(update, ctx)

async def cmd_status(update, ctx):
    try:
        g = get_global()
        fg = get_fg()
        ph, desc = phase(g["dom"])
        msg = f"📊 *STATUS*\n\n{ph}\n_{desc}_\n\n• BTC Dom: `{g['dom']:.2f}%`\n• MCap: `${g['mcap']:.2f}T`\n• Fear&Greed: `{fg['v']} — {fg['lbl']}`"
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_phase(update, ctx):
    try:
        g = get_global()
        ph, desc = phase(g["dom"])
        await update.message.reply_text(f"{ph}\n\n_{desc}_\n\nBTC Dom: `{g['dom']:.2f}%`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_feargreed(update, ctx):
    try:
        fg = get_fg()
        v = fg["v"]
        d = "Compra 🛒" if v <= 25 else "Accumula" if v <= 45 else "Neutro" if v <= 55 else "Attenzione" if v <= 75 else "Vendi ⚠️"
        await update.message.reply_text(f"😱 *FEAR & GREED*\n\n`{v}/100 — {fg['lbl']}`\n\n_{d}_", parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_top(update, ctx):
    try:
        p = get_prices()
        s = sorted(p.items(), key=lambda x: x[1]["ch"], reverse=True)
        lines = ["🏆 *TOP 24h*\n"]
        for i, (sym, d) in enumerate(s[:5], 1):
            a = "🟢" if d["ch"] >= 0 else "🔴"
            lines.append(f"{i}. {a} *{sym}* `{d['ch']:+.1f}%`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_price(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Uso: /price BTC", reply_markup=KEYBOARD)
        return
    s = ctx.args[0].upper()
    if s not in ASSETS:
        await update.message.reply_text("❌ Asset non disponibile", reply_markup=KEYBOARD)
        return
    try:
        p = get_prices()[s]
        a = "🟢" if p["ch"] >= 0 else "🔴"
        await update.message.reply_text(f"{a} *{s}*\n\n💵 `${p['price']:,.4f}`\n📈 24h: `{p['ch']:+.1f}%`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_portfolio(update, ctx):
    pf = DATA.get("portfolio", {})
    if not pf:
        await update.message.reply_text("Portfolio vuoto", reply_markup=KEYBOARD)
        return
    try:
        prices = get_prices()
        lines = ["💼 *PORTFOLIO*\n"]
        ti = 0
        tc = 0
        for sym, pos in sorted(pf.items()):
            pr = prices.get(sym, {}).get("price", 0)
            if pr == 0:
                continue
            qty = pos["qty"]
            buy = pos["buy"]
            inv = qty * buy
            cur = qty * pr
            pnl = cur - inv
            pct = ((pr - buy) / buy * 100) if buy else 0
            a = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"{a} *{sym}*: `{pct:+.1f}%` `${pnl:+,.0f}`")
            ti += inv
            tc += cur
        tp = tc - ti
        tpct = ((tc - ti) / ti * 100) if ti else 0
        a = "🟢" if tp >= 0 else "🔴"
        lines.append(f"\n{a} *TOT*: `{tpct:+.1f}%` (`${tp:+,.0f}`)")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}", reply_markup=KEYBOARD)

async def cmd_addcoin(update, ctx):
    if len(ctx.args) < 3:
        await update.message.reply_text("Uso: /addcoin BTC 0.5 95000", reply_markup=KEYBOARD)
        return
    s = ctx.args[0].upper()
    if s not in ASSETS:
        await update.message.reply_text("❌ Asset non valido", reply_markup=KEYBOARD)
        return
    try:
        qty = float(ctx.args[1])
        buy = float(ctx.args[2].replace(",", ""))
        DATA["portfolio"][s] = {"qty": qty, "buy": buy}
        save_data(DATA)
        await update.message.reply_text(f"✅ *{s}*: `{qty}` @ `${buy:,.2f}`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except:
        await update.message.reply_text("❌ Valori non validi", reply_markup=KEYBOARD)

async def cmd_removecoin(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Uso: /removecoin BTC", reply_markup=KEYBOARD)
        return
    s = ctx.args[0].upper()
    if s in DATA.get("portfolio", {}):
        del DATA["portfolio"][s]
        save_data(DATA)
        await update.message.reply_text(f"✅ {s} rimosso", reply_markup=KEYBOARD)
    else:
        await update.message.reply_text(f"❌ {s} non trovato", reply_markup=KEYBOARD)

async def cmd_alert(update, ctx):
    if len(ctx.args) < 2:
        await update.message.reply_text("Uso: /alert XRP 3 [down]", reply_markup=KEYBOARD)
        return
    s = ctx.args[0].upper()
    if s not in ASSETS:
        await update.message.reply_text("❌ Asset non valido", reply_markup=KEYBOARD)
        return
    try:
        t = float(ctx.args[1].replace(",", ""))
        above = True
        if len(ctx.args) >= 3 and ctx.args[2].lower() == "down":
            above = False
        DATA["alerts"].append({"sym": s, "price": t, "above": above})
        save_data(DATA)
        d = "sale a" if above else "scenda a"
        await update.message.reply_text(f"✅ Alert: *{s}* {d} `${t:,.2f}`", parse_mode="Markdown", reply_markup=KEYBOARD)
    except:
        await update.message.reply_text("❌ Errore", reply_markup=KEYBOARD)

async def cmd_alerts(update, ctx):
    al = DATA.get("alerts", [])
    if not al:
        await update.message.reply_text("Nessun alert", reply_markup=KEYBOARD)
        return
    lines = ["🔔 *Alert*\n"]
    for i, a in enumerate(al, 1):
        d = "↗️" if a["above"] else "↘️"
        lines.append(f"{i}. *{a['sym']}* {d} `${a['price']:,.2f}`")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=KEYBOARD)

async def cmd_delalert(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Uso: /delalert 1", reply_markup=KEYBOARD)
        return
    try:
        i = int(ctx.args[0]) - 1
        al = DATA.get("alerts", [])
        if 0 <= i < len(al):
            r = al.pop(i)
            save_data(DATA)
            await update.message.reply_text(f"✅ Eliminato: {r['sym']}", reply_markup=KEYBOARD)
        else:
            await update.message.reply_text("❌ Numero non valido", reply_markup=KEYBOARD)
    except:
        await update.message.reply_text("❌ Errore", reply_markup=KEYBOARD)

async def cmd_setup(update, ctx):
    alerts = []
    targets = {
        "XRP": [3, 5, 8, 12],
        "SOL": [200, 350, 500, 800],
        "ETH": [4000, 6000, 9000, 14000],
        "BNB": [900, 1200, 1500, 2000],
        "DOGE": [0.30, 0.60, 1.00],
        "HBAR": [0.20, 0.40, 0.70],
        "ADA": [0.80, 1.50, 2.50],
    }
    for sym, prices in targets.items():
        for p in prices:
            alerts.append({"sym": sym, "price": p, "above": True})
    DATA["alerts"] = alerts
    save_data(DATA)
    await update.message.reply_text(f"✅ *{len(alerts)} alert impostati!*\n\nXRP, SOL, ETH, BNB, DOGE, HBAR, ADA", parse_mode="Markdown", reply_markup=KEYBOARD)

async def handle_text(update, ctx):
    t = update.message.text
    if t == "📊 Status": await cmd_status(update, ctx)
    elif t == "💼 Portfolio": await cmd_portfolio(update, ctx)
    elif t == "🎯 Fase": await cmd_phase(update, ctx)
    elif t == "😱 Fear & Greed": await cmd_feargreed(update, ctx)
    elif t == "🏆 Top": await cmd_top(update, ctx)
    elif t == "🔔 Alert": await cmd_alerts(update, ctx)
    elif t == "⚙️ Setup Alert": await cmd_setup(update, ctx)
    elif t == "❓ Aiuto": await cmd_help(update, ctx)

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
        except:
            pass
        self.wfile.write(b"<h1>Altseason Bot 2026</h1>")
    def log_message(self, *args):
        pass

def start_web():
    port = int(os.environ.get('PORT', 8080))
    HTTPServer(('', port), WebHandler).serve_forever()

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("phase", cmd_phase))
    app.add_handler(CommandHandler("feargreed", cmd_feargreed))
    app.add_handler(CommandHandler("top", cmd_top))
    app.add_handler(CommandHandler("price", cmd_price))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("addcoin", cmd_addcoin))
    app.add_handler(CommandHandler("removecoin", cmd_removecoin))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("delalert", cmd_delalert))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    threading.Thread(target=start_web, daemon=True).start()

    log.info("Bot online")
    try:
        await app.bot.send_message(chat_id=CHAT_ID, text="✅ Bot Online! Premi ❓ Aiuto", reply_markup=KEYBOARD)
    except:
        pass

    async with app:
        await app.start()
        await app.updater.start_polling()
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
