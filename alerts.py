# -*- coding: utf-8 -*-
"""
alerts.py — Sistema di ALERT AUTOMATICI per Altseason Oracle Bot.

Modulo AUTONOMO e ISOLATO: non modifica nulla del bot esistente.
- Recupera i dati di mercato da solo (CoinGecko + Alternative.me, API gratuite, no key).
- Valuta 7 regole di alert.
- Anti-spam con stato su file JSON (atomico) + cooldown per ogni tipo di alert.
- Genera il testo dell'alert con OpenAI (client.responses.create, modello da OPENAI_MODEL),
  con fallback a un testo deterministico se OpenAI non risponde.
- alert_loop(application): gira in background ogni 5 minuti, NON blocca run_polling().

Integrazione nel bot: vedi start_alert_system() in fondo al file.
"""

import os
import json
import asyncio
import logging
import tempfile
from datetime import datetime, timezone

import httpx  # già dipendenza di python-telegram-bot v20+

logger = logging.getLogger("alerts")

# ---------------------------------------------------------------------------
# CONFIGURAZIONE (tutto da variabili d'ambiente, con default sensati)
# ---------------------------------------------------------------------------

# Interruttore generale: ALERT_ENABLED=false per spegnere tutto senza toccare il codice
ALERT_ENABLED = os.getenv("ALERT_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")

# Chat ID di fallback (il tuo) se ALERT_CHAT_IDS non è impostata
DEFAULT_ADMIN_CHAT_ID = 670903243


def _parse_chat_ids(raw: str):
    """Accetta ID separati da virgola/spazio/righe. Ritorna lista di int senza duplicati."""
    if not raw:
        return []
    out = []
    for piece in raw.replace("\n", ",").replace(" ", ",").split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            out.append(int(piece))
        except ValueError:
            logger.warning("ALERT_CHAT_IDS: valore non valido ignorato: %r", piece)
    # dedup mantenendo l'ordine
    seen, uniq = set(), []
    for cid in out:
        if cid not in seen:
            seen.add(cid)
            uniq.append(cid)
    return uniq


ALERT_CHAT_IDS = _parse_chat_ids(os.getenv("ALERT_CHAT_IDS", "")) or [DEFAULT_ADMIN_CHAT_ID]

# Intervallo del loop e cooldown anti-ripetizione (secondi)
ALERT_INTERVAL_SECONDS = int(os.getenv("ALERT_INTERVAL_SECONDS", "300"))      # 5 minuti
ALERT_COOLDOWN_SECONDS = int(os.getenv("ALERT_COOLDOWN_SECONDS", "10800"))    # 3 ore

# Soglie regole (tutte sovrascrivibili da env)
ALERT_BTC_FLOOR = float(os.getenv("ALERT_BTC_FLOOR", "0"))                    # 0 = regola disattivata finché non imposti il tuo livello
ALERT_BTC_DOM_DROP = float(os.getenv("ALERT_BTC_DOM_DROP", "0.5"))           # punti percentuali di calo
ALERT_BTC_DOM_LOOKBACK_MIN = int(os.getenv("ALERT_BTC_DOM_LOOKBACK_MIN", "60"))
ALERT_FNG_FEAR = int(os.getenv("ALERT_FNG_FEAR", "20"))                       # paura estrema sotto questo valore
ALERT_FNG_GREED = int(os.getenv("ALERT_FNG_GREED", "80"))                     # avidità estrema sopra questo valore (regola rischio)
ALERT_ETHBTC_24H = float(os.getenv("ALERT_ETHBTC_24H", "5.0"))              # % 24h per breakout/recupero ETH/BTC
ALERT_ALT_24H = float(os.getenv("ALERT_ALT_24H", "10.0"))                   # % 24h per considerare un'altcoin "in accelerazione"
ALERT_ALT_COUNT = int(os.getenv("ALERT_ALT_COUNT", "3"))                     # quante alt in accelerazione per far scattare

# Stato anti-spam
ALERT_STATE_FILE = os.getenv("ALERT_STATE_FILE", "alert_state.json")

# OpenAI
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Endpoint dati (gratuiti, senza API key)
CG_BASE = "https://api.coingecko.com/api/v3"
FNG_URL = "https://api.alternative.me/fng/?limit=1"
HTTP_TIMEOUT = float(os.getenv("ALERT_HTTP_TIMEOUT", "20"))
HTTP_HEADERS = {"User-Agent": "AltseasonOracleBot/1.0 (+alerts)"}

# Da escludere dal conteggio "altcoin in accelerazione" (stablecoin / wrapped / BTC / ETH)
EXCLUDE_IDS = {
    "bitcoin", "ethereum",
    "tether", "usd-coin", "dai", "first-digital-usd", "ethena-usde", "usds",
    "binance-usd", "true-usd", "paxos-standard", "frax", "usdd",
    "wrapped-bitcoin", "weth", "staked-ether", "wrapped-steth", "coinbase-wrapped-btc",
}


# ---------------------------------------------------------------------------
# STATO (JSON atomico): cooldown + storico per i delta (dominance)
# ---------------------------------------------------------------------------

def _default_state():
    return {"last_sent": {}, "history": {"btc_dom": []}}


def _load_state():
    try:
        with open(ALERT_STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # garantisce le chiavi minime
        data.setdefault("last_sent", {})
        data.setdefault("history", {}).setdefault("btc_dom", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _default_state()


def _save_state(state):
    """Scrittura atomica: scrive su file temporaneo e poi rinomina (evita file corrotti)."""
    try:
        d = os.path.dirname(os.path.abspath(ALERT_STATE_FILE)) or "."
        fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ALERT_STATE_FILE)
    except OSError as e:
        logger.warning("Impossibile salvare lo stato alert: %s", e)


def _on_cooldown(state, key, now_ts):
    last = state.get("last_sent", {}).get(key)
    if last is None:
        return False
    return (now_ts - float(last)) < ALERT_COOLDOWN_SECONDS


def _mark_sent(state, key, now_ts):
    state.setdefault("last_sent", {})[key] = now_ts


def _push_history(state, name, value, now_ts, keep_seconds=3 * 3600):
    """Aggiunge un punto allo storico e pota i dati più vecchi di keep_seconds."""
    hist = state.setdefault("history", {}).setdefault(name, [])
    hist.append([now_ts, value])
    cutoff = now_ts - keep_seconds
    state["history"][name] = [p for p in hist if p[0] >= cutoff]


def _value_ago(state, name, lookback_seconds, now_ts):
    """Ritorna il valore più recente che sia comunque più vecchio di lookback_seconds (o None)."""
    hist = state.get("history", {}).get(name, [])
    cutoff = now_ts - lookback_seconds
    older = [v for (t, v) in hist if t <= cutoff]
    return older[-1] if older else None


# ---------------------------------------------------------------------------
# RECUPERO DATI DI MERCATO (asincrono, resiliente: un endpoint che fallisce
# non blocca gli altri; i campi mancanti restano None e le regole li ignorano)
# ---------------------------------------------------------------------------

async def fetch_market_data():
    data = {
        "btc_usd": None, "btc_24h": None,
        "eth_usd": None, "eth_24h": None,
        "ethbtc": None, "ethbtc_24h": None,
        "btc_dom": None,
        "fng": None, "fng_label": None,
        "alts_accel": None, "alts_accel_names": [],
    }

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, headers=HTTP_HEADERS) as client:
        # 1) Prezzi BTC/ETH + variazione 24h
        try:
            r = await client.get(
                f"{CG_BASE}/simple/price",
                params={"ids": "bitcoin,ethereum", "vs_currencies": "usd", "include_24hr_change": "true"},
            )
            r.raise_for_status()
            j = r.json()
            data["btc_usd"] = j.get("bitcoin", {}).get("usd")
            data["btc_24h"] = j.get("bitcoin", {}).get("usd_24h_change")
            data["eth_usd"] = j.get("ethereum", {}).get("usd")
            data["eth_24h"] = j.get("ethereum", {}).get("usd_24h_change")
            if data["btc_usd"] and data["eth_usd"]:
                data["ethbtc"] = data["eth_usd"] / data["btc_usd"]
                # variazione ETH/BTC stimata dalle due variazioni 24h
                if data["btc_24h"] is not None and data["eth_24h"] is not None:
                    be = 1 + (data["btc_24h"] / 100.0)
                    ee = 1 + (data["eth_24h"] / 100.0)
                    if be != 0:
                        data["ethbtc_24h"] = (ee / be - 1) * 100.0
        except Exception as e:
            logger.warning("Fetch prezzi fallito: %s", e)

        # 2) BTC Dominance
        try:
            r = await client.get(f"{CG_BASE}/global")
            r.raise_for_status()
            data["btc_dom"] = r.json().get("data", {}).get("market_cap_percentage", {}).get("btc")
        except Exception as e:
            logger.warning("Fetch dominance fallito: %s", e)

        # 3) Fear & Greed Index
        try:
            r = await client.get(FNG_URL)
            r.raise_for_status()
            item = (r.json().get("data") or [{}])[0]
            data["fng"] = int(item.get("value")) if item.get("value") is not None else None
            data["fng_label"] = item.get("value_classification")
        except Exception as e:
            logger.warning("Fetch Fear&Greed fallito: %s", e)

        # 4) Altcoin principali in accelerazione (top 20 per market cap, escluse stable/wrapped)
        try:
            r = await client.get(
                f"{CG_BASE}/coins/markets",
                params={
                    "vs_currency": "usd", "order": "market_cap_desc",
                    "per_page": "20", "page": "1", "price_change_percentage": "24h",
                },
            )
            r.raise_for_status()
            names = []
            for coin in r.json():
                cid = (coin.get("id") or "").lower()
                sym = (coin.get("symbol") or "").lower()
                if cid in EXCLUDE_IDS or "usd" in sym:
                    continue
                chg = coin.get("price_change_percentage_24h")
                if chg is not None and chg >= ALERT_ALT_24H:
                    names.append(f"{(coin.get('symbol') or '').upper()} (+{chg:.1f}%)")
            data["alts_accel_names"] = names
            data["alts_accel"] = len(names)
        except Exception as e:
            logger.warning("Fetch altcoin fallito: %s", e)

    return data


# ---------------------------------------------------------------------------
# VALUTAZIONE REGOLE → lista di segnali {key, titolo, descrizione}
# ---------------------------------------------------------------------------

def evaluate_rules(d, state, now_ts):
    signals = []

    # Aggiorna lo storico della dominance per i calcoli di delta
    if d.get("btc_dom") is not None:
        _push_history(state, "btc_dom", d["btc_dom"], now_ts)

    # 1) BTC sotto livello critico (attiva solo se ALERT_BTC_FLOOR > 0)
    if ALERT_BTC_FLOOR > 0 and d.get("btc_usd") is not None and d["btc_usd"] < ALERT_BTC_FLOOR:
        signals.append({
            "key": "btc_floor",
            "titolo": "BTC sotto livello critico",
            "descrizione": f"Prezzo BTC ${d['btc_usd']:,.0f}, sotto la soglia critica di ${ALERT_BTC_FLOOR:,.0f}.",
        })

    # 2) BTC Dominance in calo rilevante (delta su finestra di lookback)
    if d.get("btc_dom") is not None:
        ref = _value_ago(state, "btc_dom", ALERT_BTC_DOM_LOOKBACK_MIN * 60, now_ts)
        if ref is not None and (ref - d["btc_dom"]) >= ALERT_BTC_DOM_DROP:
            signals.append({
                "key": "btc_dom_drop",
                "titolo": "BTC Dominance in calo",
                "descrizione": (
                    f"Dominance BTC scesa da {ref:.2f}% a {d['btc_dom']:.2f}% "
                    f"(-{ref - d['btc_dom']:.2f} pp in ~{ALERT_BTC_DOM_LOOKBACK_MIN} min). "
                    f"Possibile rotazione di capitali verso le altcoin."
                ),
            })

    # 3) Fear & Greed in paura estrema
    if d.get("fng") is not None and d["fng"] < ALERT_FNG_FEAR:
        signals.append({
            "key": "fng_extreme_fear",
            "titolo": "Fear & Greed in paura estrema",
            "descrizione": f"Indice Fear & Greed a {d['fng']} ({d.get('fng_label') or 'Extreme Fear'}), zona di paura estrema.",
        })

    # 4) ETH/BTC in breakout o forte recupero
    if d.get("ethbtc_24h") is not None and d["ethbtc_24h"] >= ALERT_ETHBTC_24H:
        ratio = f" (ratio {d['ethbtc']:.5f})" if d.get("ethbtc") else ""
        signals.append({
            "key": "ethbtc_breakout",
            "titolo": "ETH/BTC in forza",
            "descrizione": f"ETH/BTC +{d['ethbtc_24h']:.1f}% nelle ultime 24h{ratio}: forza relativa di ETH su BTC.",
        })

    # 5) Altcoin principali in accelerazione
    if d.get("alts_accel") is not None and d["alts_accel"] >= ALERT_ALT_COUNT:
        elenco = ", ".join(d.get("alts_accel_names", [])[:8])
        signals.append({
            "key": "alts_acceleration",
            "titolo": "Altcoin in accelerazione",
            "descrizione": f"{d['alts_accel']} altcoin della top 20 sopra +{ALERT_ALT_24H:.0f}% in 24h: {elenco}.",
        })

    # 6) Segnali compatibili con inizio altseason (condizione composita)
    dom_ref = _value_ago(state, "btc_dom", ALERT_BTC_DOM_LOOKBACK_MIN * 60, now_ts)
    dom_falling = (
        d.get("btc_dom") is not None and dom_ref is not None and (dom_ref - d["btc_dom"]) >= 0.2
    )
    ethbtc_up = d.get("ethbtc_24h") is not None and d["ethbtc_24h"] >= ALERT_ETHBTC_24H
    alts_hot = d.get("alts_accel") is not None and d["alts_accel"] >= ALERT_ALT_COUNT
    if dom_falling and ethbtc_up and alts_hot:
        signals.append({
            "key": "altseason_start",
            "titolo": "Possibile inizio altseason",
            "descrizione": (
                "Confluenza rialzista alt: dominance BTC in calo, ETH/BTC in forza e più altcoin in accelerazione "
                "simultaneamente. Pattern compatibile con una fase iniziale di altseason."
            ),
        })

    # 7) Segnali di rischio (riduzione esposizione)
    risk = False
    motivi = []
    if d.get("fng") is not None and d["fng"] >= ALERT_FNG_GREED and d.get("btc_24h") is not None and d["btc_24h"] <= -3:
        risk = True
        motivi.append(f"avidità estrema (F&G {d['fng']}) con BTC {d['btc_24h']:.1f}% in 24h")
    if d.get("btc_24h") is not None and d["btc_24h"] <= -7:
        risk = True
        motivi.append(f"forte calo di BTC ({d['btc_24h']:.1f}% in 24h)")
    if risk:
        signals.append({
            "key": "risk_reduction",
            "titolo": "Segnale di rischio",
            "descrizione": "Condizioni di rischio: " + "; ".join(motivi) + ". Valutare riduzione esposizione/stop.",
        })

    return signals


# ---------------------------------------------------------------------------
# SNAPSHOT LEGGIBILE (usato sia per il prompt OpenAI sia per il fallback)
# ---------------------------------------------------------------------------

def _now_str():
    now = datetime.now(timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        now = now.astimezone(ZoneInfo("Europe/Rome"))
        return now.strftime("%d/%m/%Y %H:%M %Z")
    except Exception:
        return now.strftime("%d/%m/%Y %H:%M UTC")


def _build_snapshot(d):
    righe = []
    if d.get("btc_usd") is not None:
        chg = f" (24h: {d['btc_24h']:+.1f}%)" if d.get("btc_24h") is not None else ""
        righe.append(f"- BTC: ${d['btc_usd']:,.0f}{chg}")
    if d.get("eth_usd") is not None:
        chg = f" (24h: {d['eth_24h']:+.1f}%)" if d.get("eth_24h") is not None else ""
        righe.append(f"- ETH: ${d['eth_usd']:,.0f}{chg}")
    if d.get("ethbtc") is not None:
        chg = f" (24h: {d['ethbtc_24h']:+.1f}%)" if d.get("ethbtc_24h") is not None else ""
        righe.append(f"- ETH/BTC: {d['ethbtc']:.5f}{chg}")
    if d.get("btc_dom") is not None:
        righe.append(f"- BTC Dominance: {d['btc_dom']:.2f}%")
    if d.get("fng") is not None:
        righe.append(f"- Fear & Greed: {d['fng']} ({d.get('fng_label') or '-'})")
    if d.get("alts_accel") is not None:
        righe.append(f"- Altcoin top in accelerazione (>+{ALERT_ALT_24H:.0f}% 24h): {d['alts_accel']}")
    return "\n".join(righe) if righe else "- (dati di mercato non disponibili)"


# ---------------------------------------------------------------------------
# GENERAZIONE TESTO ALERT via OpenAI (sync wrapped in thread → non blocca il loop)
# ---------------------------------------------------------------------------

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        from openai import OpenAI
        _openai_client = OpenAI()  # legge OPENAI_API_KEY dall'ambiente
    return _openai_client


def _openai_generate_sync(prompt: str) -> str:
    client = _get_openai_client()
    resp = client.responses.create(model=OPENAI_MODEL, input=prompt)
    text = getattr(resp, "output_text", None)
    if not text:
        # fallback di parsing per versioni che non espongono output_text
        parts = []
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
        text = "\n".join(parts)
    return (text or "").strip()


def _fallback_text(signal, when, snapshot):
    """Testo deterministico se OpenAI non è disponibile: stessa struttura richiesta."""
    return (
        "⚡ ALERT OPERATIVO\n"
        f"🕒 Data e ora: {when}\n"
        f"📍 Segnale rilevato: {signal['titolo']}\n"
        f"🧠 Interpretazione: {signal['descrizione']}\n"
        "⚖️ Rischio/opportunità: valutare nel contesto del proprio portafoglio e orizzonte temporale.\n"
        "🎯 Azione consigliata: verificare il setup prima di operare; gestire il rischio con size e stop adeguati.\n"
        "📊 Livelli da monitorare:\n"
        f"{snapshot}"
    )


async def generate_alert_text(signal, market_data):
    when = _now_str()
    snapshot = _build_snapshot(market_data)
    prompt = (
        "Sei un analista senior di un hedge fund crypto. Scrivi un alert operativo in ITALIANO, "
        "conciso, professionale e diretto. NON usare Markdown, NON usare asterischi, NON aggiungere "
        "premesse o disclaimer.\n\n"
        "Usa ESATTAMENTE questa struttura, una voce per riga con queste etichette ed emoji:\n"
        "⚡ ALERT OPERATIVO\n"
        f"🕒 Data e ora: {when}\n"
        "📍 Segnale rilevato: ...\n"
        "🧠 Interpretazione: ...\n"
        "⚖️ Rischio/opportunità: ...\n"
        "🎯 Azione consigliata: ...\n"
        "📊 Livelli da monitorare: ...\n\n"
        f"Dati di mercato attuali:\n{snapshot}\n\n"
        f"Segnale tecnico che ha fatto scattare l'alert:\n- {signal['titolo']}: {signal['descrizione']}\n"
    )
    try:
        text = await asyncio.to_thread(_openai_generate_sync, prompt)
        if text:
            return text
        logger.warning("OpenAI ha restituito testo vuoto, uso il fallback.")
    except Exception as e:
        logger.warning("Generazione OpenAI fallita (%s), uso il fallback.", e)
    return _fallback_text(signal, when, snapshot)


# ---------------------------------------------------------------------------
# INVIO (broadcast a tutti gli ALERT_CHAT_IDS; un errore su un chat non blocca gli altri)
# ---------------------------------------------------------------------------

async def _broadcast(application, text):
    for cid in ALERT_CHAT_IDS:
        try:
            await application.bot.send_message(chat_id=cid, text=text)
        except Exception as e:
            logger.warning("Invio alert a %s fallito: %s", cid, e)


# ---------------------------------------------------------------------------
# LOOP PRINCIPALE — gira in background, non blocca run_polling()
# ---------------------------------------------------------------------------

async def alert_loop(application):
    logger.info(
        "alert_loop avviato | intervallo=%ss | cooldown=%ss | destinatari=%s",
        ALERT_INTERVAL_SECONDS, ALERT_COOLDOWN_SECONDS, ALERT_CHAT_IDS,
    )
    await asyncio.sleep(10)  # piccola attesa per lasciare partire il bot

    while True:
        try:
            state = _load_state()
            now_ts = datetime.now(timezone.utc).timestamp()

            data = await fetch_market_data()
            signals = evaluate_rules(data, state, now_ts)

            for sig in signals:
                if _on_cooldown(state, sig["key"], now_ts):
                    continue
                text = await generate_alert_text(sig, data)
                await _broadcast(application, text)
                _mark_sent(state, sig["key"], now_ts)
                logger.info("Alert inviato: %s", sig["key"])

            _save_state(state)  # salva storico + cooldown anche se nessun alert è scattato

        except asyncio.CancelledError:
            logger.info("alert_loop interrotto (shutdown).")
            raise
        except Exception as e:
            logger.exception("Errore nel ciclo alert (continuo comunque): %s", e)

        await asyncio.sleep(ALERT_INTERVAL_SECONDS)


# ---------------------------------------------------------------------------
# AVVIO — da agganciare al post_init del bot (vedi README in fondo)
# ---------------------------------------------------------------------------

async def start_alert_system(application):
    """
    Avvia alert_loop come task in background, senza bloccare run_polling().
    Da usare come post_init dell'Application, oppure da richiamare dentro
    un post_init già esistente.
    """
    if not ALERT_ENABLED:
        logger.info("Sistema alert DISATTIVATO (ALERT_ENABLED=false).")
        return
    application.create_task(alert_loop(application))
    logger.info("Sistema alert agganciato all'Application.")


# ---------------------------------------------------------------------------
# SELF-TEST manuale (non invia nulla su Telegram, non serve il bot):
#   python3 alerts.py
# Mostra lo snapshot di mercato e quali alert scatterebbero adesso.
# ---------------------------------------------------------------------------

async def _selftest():
    logging.basicConfig(level=logging.INFO)
    state = _load_state()
    now_ts = datetime.now(timezone.utc).timestamp()
    data = await fetch_market_data()
    print("\n=== SNAPSHOT MERCATO ===")
    print(_build_snapshot(data))
    signals = evaluate_rules(data, state, now_ts)
    print("\n=== SEGNALI ATTIVI ADESSO ===")
    if not signals:
        print("(nessun segnale)")
    for s in signals:
        print(f"- [{s['key']}] {s['titolo']}: {s['descrizione']}")
    print(f"\nDestinatari configurati: {ALERT_CHAT_IDS}")


if __name__ == "__main__":
    asyncio.run(_selftest())
