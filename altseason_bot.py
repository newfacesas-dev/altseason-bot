import asyncio
import logging
import requests
import time
import json
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

TELEGRAM_TOKEN = "8940955681:AAGbto8_W43gSe21rA3LlN776tMQfD2auIo"
CHAT_ID = "670903243"

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger(__name__)

ASSETS = {"BTC":"bitcoin","ETH":"ethereum","XRP":"ripple","SOL":"solana","ADA":"cardano","DOGE":"dogecoin","BNB":"binancecoin","HBAR":"hedera-hashgraph","BONK":"bonk","ALGO":"algorand","XLM":"stellar","POL":"matic-network","TRX":"tron","GRT":"the-graph","NEAR":"near","FET":"fetch-ai","SEI":"sei-network","LUNA":"terra-luna-2","MANA":"decentraland"}

PORTFOLIO_QTY = {"XRP":25142,"SOL":201,"ETH":10.52,"DOGE":31128,"BNB":5.05,"HBAR":14686,"BONK":150804881,"SEI":13723,"FET":3223,"LUNA":9057}

DATA_FILE = "bot_data.json"
_cache = {}

KEYBOARD = ReplyKeyboardMarkup([
    [KeyboardButton("📊 Status"), KeyboardButton("💼 Portfolio")],
    [KeyboardButton("🎯 Fase"), KeyboardButton("😱 Fear & Greed")],
    [KeyboardButton("🏆 Top"), KeyboardButton("📅 Timeline")],
    [KeyboardButton("⚙️ Setup Alert"), KeyboardButton("🔄 Reset")],
    [KeyboardButton("❓ Aiuto")],
], resize_keyboard=True)

def load_data():
    try:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE,'r') as f: return json.load(f)
    except: pass
    return {"portfolio":{},"alerts":[]}

def save_data(d):
    try:
        with open(DATA_FILE,'w') as f: json.dump(d,f)
    except: pass

DATA = load_data()

def get_global():
    if 'g' in _cache and time.time()-_cache['g']['t']<180: return _cache['g']['d']
    try:
        r = requests.get("https://api.coingecko.com/api/v3/global",timeout=10).json()["data"]
        result = {"dom":r["market_cap_percentage"]["btc"],"mcap":r["total_market_cap"]["usd"]/1e12}
        _cache['g'] = {'d':result,'t':time.time()}
        return result
    except: return {"dom":58,"mcap":2.5}

def get_prices():
    if 'p' in _cache and time.time()-_cache['p']['t']<180: return _cache['p']['d']
    try:
        ids = ",".join(ASSETS.values())
        raw = requests.get(f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies=usd&include_24hr_change=true",timeout=10).json()
        result = {s:{"price":raw.get(c,{}).get("usd",0),"ch":raw.get(c,{}).get("usd_24h_change",0)} for s,c in ASSETS.items()}
        _cache['p'] = {'d':result,'t':time.time()}
        return result
    except: return {s:{"price":0,"ch":0} for s in ASSETS}

def get_fg():
    if 'fg' in _cache and time.time()-_cache['fg']['t']<300: return _cache['fg']['d']
    try:
        d = requests.get("https://api.alternative.me/fng/?limit=1",timeout=10).json()["data"][0]
        result = {"v":int(d["value"]),"lbl":d["value_classification"]}
        _cache['fg'] = {'d':result,'t':time.time()}
        return result
    except: return {"v":50,"lbl":"Neutral"}

def init_portfolio():
    try:
        prices = get_prices()
        DATA["portfolio"] = {}
        for sym,qty in PORTFOLIO_QTY.items():
            p = prices.get(sym,{}).get("price",0)
            if p>0: DATA["portfolio"][sym] = {"qty":qty,"buy":p}
        save_data(DATA)
        return True
    except: return False

if not DATA.get("portfolio"): init_portfolio()

def phase(dom):
    if dom<48: return "🚨 USCITA","TOP CICLO! Prendi profitto"
    if dom<52: return "⚡ AZIONE","Altseason attiva — ruota altcoin"
    return "👀 MONITORA","Fase accumulo — tieni posizioni"

async def cmd_help(u,c):
    msg = "👋 *ALTSEASON BOT 2026*\n\n/status — Status mercato\n/portfolio — P&L tempo reale\n/timeline — Roadmap altseason\n/setup — 21 alert strategia\n/reset — Reset con prezzi attuali\n/alert XRP 3 — Avviso prezzo\n/feargreed — Sentiment\n/top — Top 24h\n/price BTC — Prezzo singolo"
    await u.message.reply_text(msg,parse_mode="Markdown",reply_markup=KEYBOARD)

async def cmd_start(u,c): await cmd_help(u,c)

async def cmd_timeline(u,c):
    msg = "📅 *TIMELINE ALTSEASON 2026*\n\n🌱 *GIU-LUG*: BTC Dom 55-52%\n→ TIENI tutto\n\n⚡ *AGO-SET*: BTC Dom <52%\n→ Vendi 25% ogni coin\n\n🚀 *OTT-NOV*: F&G >80\n→ ESCI 50-75%\n\n📉 *DIC*: Crollo -60/-80%\n→ Accumula BTC\n\n🎯 *TARGET*\nXRP: $3→$5→$8→$12\nSOL: $200→$350→$500→$800\nETH: $4k→$6k→$9k→$14k\nBNB: $900→$1.2k→$1.5k→$2k\nDOGE: $0.30→$0.60→$1.00\nHBAR: $0.20→$0.40→$0.70\nSEI: $0.80→$1.50→$3.00"
    await u.message.reply_text(msg,parse_mode="Markdown",reply_markup=KEYBOARD)

async def cmd_status(u,c):
    try:
        g = get_global(); fg = get_fg(); ph,desc = phase(g["dom"])
        await u.message.reply_text(f"📊 *STATUS*\n\n{ph}\n_{desc}_\n\n• BTC Dom: `{g['dom']:.2f}%`\n• MCap: `${g['mcap']:.2f}T`\n• F&G: `{fg['v']} — {fg['lbl']}`",parse_mode="Markdown",reply_markup=KEYBOARD)
    except Exception as e: await u.message.reply_text(f"❌ {e}",reply_markup=KEYBOARD)

async def cmd_phase(u,c):
    try:
        g = get_global(); ph,desc = phase(g["dom"])
        await u.message.reply_text(f"{ph}\n\n_{desc}_\n\nBTC Dom: `{g['dom']:.2f}%`",parse_mode="Markdown",reply_markup=KEYBOARD)
    except Exception as e: await u.message.reply_text(f"❌ {e}",reply_markup=KEYBOARD)

async def cmd_feargreed(u,c):
    try:
        fg = get_fg(); v = fg["v"]
        d = "Compra 🛒" if v<=25 else "Accumula" if v<=45 else "Neutro" if v<=55 else "Attenzione" if v<=75 else "Vendi ⚠️"
        await u.message.reply_text(f"😱 *FEAR & GREED*\n\n`{v}/100 — {fg['lbl']}`\n\n_{d}_",parse_mode="Markdown",reply_markup=KEYBOARD)
    except Exception as e: await u.message.reply_text(f"❌ {e}",reply_markup=KEYBOARD)

async def cmd_top(u,c):
    try:
        p = get_prices(); s = sorted(p.items(),key=lambda x:x[1]["ch"],reverse=True)
        lines = ["🏆 *TOP 24h*\n"]
        for i,(sym,d) in enumerate(s[:5],1):
            a = "🟢" if d["ch"]>=0 else "🔴"
            lines.append(f"{i}. {a} *{sym}* `{d['ch']:+.1f}%`")
        await u.message.reply_text("\n".join(lines),parse_mode="Markdown",reply_markup=KEYBOARD)
    except Exception as e: await u.message.reply_text(f"❌ {e}",reply_markup=KEYBOARD)

async def cmd_price(u,c):
    if not c.args: await u.message.reply_text("Uso: /price BTC",reply_markup=KEYBOARD); return
    s = c.args[0].upper()
    if s not in ASSETS: await u.message.reply_text("❌ Non disponibile",reply_markup=KEYBOARD); return
    try:
        p = get_prices()[s]; a = "🟢" if p["ch"]>=0 else "🔴"
        await u.message.reply_text(f"{a} *{s}*\n💵 `${p['price']:,.4f}`\n📈 24h: `{p['ch']:+.1f}%`",parse_mode="Markdown",reply_markup=KEYBOARD)
    except Exception as e: await u.message.reply_text(f"❌ {e}",reply_markup=KEYBOARD)

async def cmd_portfolio(u,c):
    pf = DATA.get("portfolio",{})
    if not pf: await u.message.reply_text("Vuoto. /reset",reply_markup=KEYBOARD); return
    try:
        prices = get_prices(); lines = ["💼 *PORTFOLIO*\n"]; ti=0; tc=0
        for sym,pos in sorted(pf.items()):
            pr = prices.get(sym,{}).get("price",0)
            if pr==0: continue
            qty=pos["qty"]; buy=pos["buy"]; inv=qty*buy; cur=qty*pr; pnl=cur-inv
            pct = ((pr-buy)/buy*100) if buy else 0
            a = "🟢" if pnl>=0 else "🔴"
            lines.append(f"{a} *{sym}*: `{pct:+.1f}%` (`${pnl:+,.0f}`)")
            ti+=inv; tc+=cur
        tp=tc-ti; tpct = ((tc-ti)/ti*100) if ti else 0
        a = "🟢" if tp>=0 else "🔴"
        lines.append(f"\n💰 Investito: `${ti:,.0f}`")
        lines.append(f"💎 Attuale: `${tc:,.0f}`")
        lines.append(f"{a} *P&L*: `{tpct:+.1f}%` (`${tp:+,.0f}`)")
        await u.message.reply_text("\n".join(lines),parse_mode="Markdown",reply_markup=KEYBOARD)
    except Exception as e: await u.message.reply_text(f"❌ {e}",reply_markup=KEYBOARD)

async def cmd_reset(u,c):
    if init_portfolio():
        await u.message.reply_text(f"✅ Portfolio resettato: {len(DATA['portfolio'])} asset. P&L da 0%.",reply_markup=KEYBOARD)
    else: await u.message.reply_text("❌ Errore",reply_markup=KEYBOARD)

async def cmd_setup(u,c):
    alerts = []
    targets = {"XRP":[3,5,8,12],"SOL":[200,350,500,800],"ETH":[4000,6000,9000,14000],"BNB":[900,1200,1500,2000],"DOGE":[0.30,0.60,1.00],"HBAR":[0.20,0.40,0.70],"SEI":[0.80,1.50,3.00]}
    for sym,prices in targets.items():
        for p in prices: alerts.append({"sym":sym,"price":p,"above":True})
    DATA["alerts"] = alerts; save_data(DATA)
    await u.message.reply_text(f"✅ {len(alerts)} alert impostati!",reply_markup=KEYBOARD)

async def cmd_alert(u,c):
    if len(c.args)<2: await u.message.reply_text("Uso: /alert XRP 3",reply_markup=KEYBOARD); return
    s = c.args[0].upper()
    try:
        t = float(c.args[1].replace(",",""))
        above = not (len(c.args)>=3 and c.args[2].lower()=="down")
        DATA["alerts"].append({"sym":s,"price":t,"above":above}); save_data(DATA)
        await u.message.reply_text(f"✅ Alert *{s}* `${t:,.2f}`",parse_mode="Markdown",reply_markup=KEYBOARD)
    except: await u.message.reply_text("❌ Errore",reply_markup=KEYBOARD)

async def handle_text(u,c):
    t = u.message.text
    if t=="📊 Status": await cmd_status(u,c)
    elif t=="💼 Portfolio": await cmd_portfolio(u,c)
    elif t=="🎯 Fase": await cmd_phase(u,c)
    elif t=="😱 Fear & Greed": await cmd_feargreed(u,c)
    elif t=="🏆 Top": await cmd_top(u,c)
    elif t=="📅 Timeline": await cmd_timeline(u,c)
    elif t=="⚙️ Setup Alert": await cmd_setup(u,c)
    elif t=="🔄 Reset": await cmd_reset(u,c)
    elif t=="❓ Aiuto": await cmd_help(u,c)

class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type','text/html'); self.end_headers()
        self.wfile.write(b"<h1>Altseason Bot 2026</h1>")
    def log_message(self,*a): pass

def start_web():
    HTTPServer(('',int(os.environ.get('PORT',8080))),WebHandler).serve_forever()

async def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    for cmd,fn in [("start",cmd_start),("help",cmd_help),("status",cmd_status),("phase",cmd_phase),("feargreed",cmd_feargreed),("top",cmd_top),("price",cmd_price),("portfolio",cmd_portfolio),("reset",cmd_reset),("alert",cmd_alert),("setup",cmd_setup),("timeline",cmd_timeline)]:
        app.add_handler(CommandHandler(cmd,fn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,handle_text))
    threading.Thread(target=start_web,daemon=True).start()
    log.info("Bot online")
    try: await app.bot.send_message(chat_id=CHAT_ID,text="✅ *Bot Online Finale*\n\n/portfolio /timeline /setup /help",parse_mode="Markdown")
    except: pass
    async with app:
        await app.start(); await app.updater.start_polling()
        while True: await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main()
