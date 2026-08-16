"""
XRPL RLUSD Pair Collector — Milestone M8, Gap 2B
====================================================

Scopo (e SOLO questo): accumulare nel tempo il volume reale della coppia
XRP/RLUSD, ascoltando lo stream WebSocket ufficiale `book_changes` di
XRPL (un messaggio 'bookChanges' per ogni ledger validato — non polling
HTTP ledger-by-ledger). Alimenta esclusivamente xrp_rlusd_pair_growth in
xrpl_feature_engine.py. xrp_dependency_ratio resta MISSING, non toccato.

Architettura (approvata):
- PRIMARY: connessione WebSocket persistente, subscribe(streams=["book_changes"]).
  Ogni messaggio 'bookChanges' contiene gia' un riepilogo per-ledger di
  TUTTI i book che hanno avuto attivita' in quel ledger (stessa struttura
  gia' verificata per la chiamata REST book_changes, confermata
  ufficialmente identica anche per lo stream: "This message contains a
  summary of all changes to order books... that occurred in that ledger").
- Filtro: isola SOLO il book con currency_a=="XRP_drops" e currency_b che
  corrisponde all'issuer RLUSD gia' noto nel progetto (raw._RLUSD_ISSUER),
  con la currency in forma hex (raw._RLUSD_CURRENCY_HEX) o "RLUSD" —
  gestite entrambe le rappresentazioni per sicurezza, senza assumerne una.
- BACKFILL: alla connessione (prima volta o dopo una riconnessione), se
  esiste un last_processed_ledger_index persistito piu' vecchio del
  ledger corrente, i SOLI ledger mancanti vengono recuperati via la
  chiamata REST book_changes gia' esistente in M1 (raw._xrpl_rpc_call),
  non un poller continuo — solo per colmare il gap.
- Persistenza: stesso principio JSONL/JSON gia' usato ovunque nel
  progetto, su file dedicati, mai gli stessi di M1/M4/Gap1A.

Nessuna chiamata a API a pagamento. Nessun proxy: il book XRP/RLUSD e'
identificato esattamente, non stimato.

Isolamento totale: qualunque errore (rete, parsing, IO) viene loggato e
gestito con backoff — mai propagato al chiamante, mai un crash del
processo che ospita anche il polling Telegram.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timezone

import xrpl_raw_data_layer as raw

log = logging.getLogger("xrpl_rlusd_pair_collector")

_XRPL_WS_PRIMARY = os.environ.get("XRPL_WS_URL", "wss://xrplcluster.com/")
_XRPL_WS_FALLBACK = os.environ.get("XRPL_WS_FALLBACK_URL", "wss://s1.ripple.com/")

_COLLECTOR_STATE_PATH = os.environ.get("XRPL_RLUSD_PAIR_STATE_PATH", "/data/xrpl_rlusd_pair_collector_state.json")
_VOLUME_HISTORY_PATH = os.environ.get("XRPL_RLUSD_PAIR_HISTORY_PATH", "/data/xrpl_rlusd_pair_volume_history.jsonl")

_PERIOD_HOURS = 24.0  # stessa cadenza giornaliera gia' usata altrove nel progetto
_RECONNECT_BACKOFF_BASE = 2.0
_RECONNECT_BACKOFF_MAX = 60.0
_BACKFILL_MAX_LEDGERS = 2000  # tetto di sicurezza: oltre questo, il gap e' troppo ampio per un backfill puntuale

_DROPS_PER_XRP = 1_000_000.0


# ============================================================
# IDENTIFICAZIONE DEL BOOK XRP/RLUSD (nessuna soglia, match esatto)
# ============================================================

def _currency_b_matches_rlusd(currency_b):
    """currency_b ha forma 'issuer/currency'. Verifica issuer + currency
    contro l'RLUSD gia' noto nel progetto (raw._RLUSD_ISSUER /
    raw._RLUSD_CURRENCY_HEX), accettando sia la forma hex sia 'RLUSD'
    letterale (non verificabile con certezza quale rippled usi nello
    stream senza una chiamata live dedicata: gestite entrambe)."""
    if not isinstance(currency_b, str) or "/" not in currency_b:
        return False
    issuer, _, currency = currency_b.partition("/")
    if issuer != raw._RLUSD_ISSUER:
        return False
    return currency == raw._RLUSD_CURRENCY_HEX or currency.upper() == "RLUSD"


def _extract_xrp_rlusd_change(changes):
    """Cerca nell'array 'changes' di un messaggio/risposta book_changes
    l'unico book XRP/RLUSD. Ritorna il dict del change o None se assente
    in quel ledger (normale: non ogni ledger ha attivita' su quel book)."""
    if not isinstance(changes, list):
        return None
    for change in changes:
        if not isinstance(change, dict):
            continue
        if change.get("currency_a") == "XRP_drops" and _currency_b_matches_rlusd(change.get("currency_b")):
            return change
    return None


def _parse_volumes(change):
    """volume_a (drops XRP) e volume_b (unita' RLUSD) come float. None se
    mancanti o non numerici — mai un valore inventato."""
    try:
        vol_xrp_drops = float(change.get("volume_a"))
        vol_rlusd = float(change.get("volume_b"))
    except (TypeError, ValueError):
        return None, None
    if vol_xrp_drops < 0 or vol_rlusd < 0:
        return None, None
    return vol_xrp_drops, vol_rlusd


# ============================================================
# PERSISTENZA STATO (dedup, resume) — file JSON singolo, scrittura atomica
# ============================================================

def _default_state():
    now = datetime.now(timezone.utc).isoformat()
    return {
        "last_processed_ledger_index": None,
        "period_start_utc": now,
        "accumulated_volume_xrp": 0.0,
        "accumulated_volume_rlusd": 0.0,
        "period_has_gap": False,
        "updated_at_utc": now,
    }


def read_state(path=None):
    path = path or _COLLECTOR_STATE_PATH
    try:
        if not os.path.exists(path):
            return _default_state()
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or "last_processed_ledger_index" not in state:
            return _default_state()
        return state
    except Exception as e:
        log.warning(f"[xrpl_rlusd_pair_collector] lettura stato fallita, riparto da zero: {e}")
        return _default_state()


def _write_state(state, path=None):
    """Scrittura quasi-atomica (file temporaneo + rename) per non
    corrompere lo stato se il processo si interrompe a meta' scrittura."""
    path = path or _COLLECTOR_STATE_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp_path = f"{path}.tmp"
        state = dict(state)
        state["updated_at_utc"] = datetime.now(timezone.utc).isoformat()
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp_path, path)
    except Exception as e:
        log.warning(f"[xrpl_rlusd_pair_collector] scrittura stato fallita (non bloccante): {e}")


# ============================================================
# STORICO VOLUME PER PERIODO (letto da xrpl_feature_engine.py)
# ============================================================

def _append_volume_history(entry, path=None):
    path = path or _VOLUME_HISTORY_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"[xrpl_rlusd_pair_collector] scrittura storico volume fallita (non bloccante): {e}")


def get_volume_period_series(path=None):
    """Serie (datetime, volume_xrp_float) per xrp_rlusd_pair_growth in M2.
    Una entry per periodo completato (giornaliero). Righe corrotte
    saltate, mai un crash. I periodi marcati 'complete': False (gap di
    backfill non recuperato durante quel periodo) vengono ESCLUSI: un
    giorno con dati mancanti non deve mai essere confrontato come se
    fosse un giorno completo."""
    path = path or _VOLUME_HISTORY_PATH
    out = []
    try:
        if not os.path.exists(path):
            return out
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("complete") is False:
                        continue
                    dt = datetime.fromisoformat(entry["period_end_utc"])
                    vol = float(entry["volume_xrp"])
                    out.append((dt, vol))
                except Exception:
                    continue
    except Exception as e:
        log.warning(f"[xrpl_rlusd_pair_collector] lettura storico volume fallita: {e}")
        return []
    out.sort(key=lambda pair: pair[0])
    return out


# ============================================================
# ACCUMULO — elaborazione di un singolo messaggio/ledger
# ============================================================

def _maybe_flush_period(state):
    """Se il periodo corrente (24h) e' scaduto, salva il totale accumulato
    nello storico e apre un nuovo periodo. Nessun dato perso silenziosamente:
    se l'accumulo e' zero (nessuna attivita' XRP/RLUSD in quel periodo), si
    salva comunque un'entry con volume 0.0 — non si salta l'entry. Se pero'
    durante il periodo si e' verificato un gap di backfill troppo ampio per
    essere recuperato (period_has_gap=True), l'entry viene marcata
    esplicitamente 'complete': False — un giorno con un buco di dati NON
    deve mai essere trattato come un'osservazione valida al pari di un
    giorno completo (falserebbe il confronto growth_pct)."""
    try:
        period_start = datetime.fromisoformat(state["period_start_utc"])
    except Exception:
        period_start = datetime.now(timezone.utc)
        state["period_start_utc"] = period_start.isoformat()

    now = datetime.now(timezone.utc)
    if (now - period_start).total_seconds() < _PERIOD_HOURS * 3600.0:
        return state

    entry = {
        "timestamp_utc": now.isoformat(),
        "period_start_utc": state["period_start_utc"],
        "period_end_utc": now.isoformat(),
        "volume_xrp": state["accumulated_volume_xrp"] / _DROPS_PER_XRP,
        "volume_rlusd": state["accumulated_volume_rlusd"],
        "ledger_index_end": state.get("last_processed_ledger_index"),
        "complete": not state.get("period_has_gap", False),
    }
    _append_volume_history(entry)
    if entry["complete"]:
        log.info(f"[xrpl_rlusd_pair_collector] periodo chiuso: {entry['volume_xrp']:.2f} XRP scambiati con RLUSD")
    else:
        log.warning(
            f"[xrpl_rlusd_pair_collector] periodo chiuso ma INCOMPLETO (gap di backfill non recuperato "
            f"durante questo periodo): {entry['volume_xrp']:.2f} XRP registrati, marcato 'complete': False, "
            f"escluso dalla serie usata per xrp_rlusd_pair_growth"
        )

    state["period_start_utc"] = now.isoformat()
    state["accumulated_volume_xrp"] = 0.0
    state["accumulated_volume_rlusd"] = 0.0
    state["period_has_gap"] = False
    return state


def _process_ledger_changes(ledger_index, changes, state):
    """Elabora i 'changes' di UN ledger: dedup, estrazione XRP/RLUSD,
    accumulo, avanzamento del watermark. Ritorna lo stato aggiornato."""
    last = state.get("last_processed_ledger_index")
    if last is not None and ledger_index <= last:
        return state  # dedup rigoroso: ledger gia' processato, ignorato

    change = _extract_xrp_rlusd_change(changes)
    if change is not None:
        vol_xrp_drops, vol_rlusd = _parse_volumes(change)
        if vol_xrp_drops is not None:
            state["accumulated_volume_xrp"] += vol_xrp_drops
            state["accumulated_volume_rlusd"] += vol_rlusd

    state["last_processed_ledger_index"] = ledger_index
    state = _maybe_flush_period(state)
    _write_state(state)
    return state


# ============================================================
# BACKFILL — SOLO per i ledger mancanti dopo una disconnessione
# ============================================================

async def _backfill_gap(from_ledger, to_ledger, state, loop):
    """Recupera SOLO i ledger tra (from_ledger, to_ledger] via la
    chiamata REST book_changes gia' esistente in M1 (raw._xrpl_rpc_call),
    non un poller continuo. Tetto di sicurezza: se il gap e' troppo
    ampio, si segnala e si riparte dal ledger corrente (perdita dichiarata
    di un intervallo troppo vecchio per essere recuperato in modo
    proporzionato, mai una perdita silenziosa)."""
    gap = to_ledger - from_ledger
    if gap <= 0:
        return state
    if gap > _BACKFILL_MAX_LEDGERS:
        log.warning(
            f"[xrpl_rlusd_pair_collector] gap di {gap} ledger troppo ampio per il backfill "
            f"(tetto {_BACKFILL_MAX_LEDGERS}): riparto dal ledger corrente, intervallo "
            f"{from_ledger + 1}-{to_ledger} dichiarato perso"
        )
        state["last_processed_ledger_index"] = to_ledger
        state["period_has_gap"] = True  # il periodo corrente NON deve risultare 'complete'
        _write_state(state)
        return state

    log.info(f"[xrpl_rlusd_pair_collector] backfill di {gap} ledger ({from_ledger + 1}-{to_ledger})")
    for ledger_index in range(from_ledger + 1, to_ledger + 1):
        result, err = await loop.run_in_executor(
            None, raw._xrpl_rpc_call, "book_changes", {"ledger_index": ledger_index}, "xrpl_rlusd_pair_collector.backfill"
        )
        if result is None:
            log.warning(f"[xrpl_rlusd_pair_collector] backfill ledger {ledger_index} fallito: {err}")
            continue
        state = _process_ledger_changes(ledger_index, result.get("changes"), state)
    return state


# ============================================================
# CONNESSIONE WEBSOCKET — subscribe(streams=["book_changes"])
# ============================================================

async def _get_current_validated_ledger(loop):
    info_env = await loop.run_in_executor(None, raw.xrpl_server_info)
    if info_env.get("status") != raw.STATUS_RAW_AVAILABLE:
        return None
    try:
        return info_env["data"]["info"]["validated_ledger"]["seq"]
    except (KeyError, TypeError):
        return None


async def _run_once(ws_url):
    """Una sessione di connessione: connette, fa il backfill se serve,
    poi ascolta live finche' la connessione regge. Solleva eccezioni
    verso il chiamante (run_collector_forever le gestisce con backoff)."""
    import websockets  # import differito: se la libreria manca, isolato qui

    loop = asyncio.get_event_loop()
    state = read_state()

    async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
        await ws.send(json.dumps({"id": "xrpl_rlusd_pair_collector", "command": "subscribe", "streams": ["book_changes"]}))
        ack = json.loads(await ws.recv())
        if ack.get("status") != "success":
            raise RuntimeError(f"subscribe fallita: {ack}")
        log.info(f"[xrpl_rlusd_pair_collector] connesso e sottoscritto a book_changes ({ws_url})")

        current_ledger = await _get_current_validated_ledger(loop)
        last = state.get("last_processed_ledger_index")
        if last is not None and current_ledger is not None and current_ledger > last:
            state = await _backfill_gap(last, current_ledger, state, loop)
        elif last is None:
            log.info("[xrpl_rlusd_pair_collector] primo avvio: nessun backfill (nessuno stato precedente)")

        async for raw_message in ws:
            try:
                message = json.loads(raw_message)
            except (ValueError, TypeError):
                continue
            if message.get("type") != "bookChanges":
                continue
            ledger_index = message.get("ledger_index")
            if not isinstance(ledger_index, int):
                continue
            state = _process_ledger_changes(ledger_index, message.get("changes"), state)


async def run_collector_forever(ws_urls=None):
    """Loop esterno con riconnessione automatica e backoff esponenziale.
    Non solleva MAI un'eccezione verso il chiamante: isolamento totale
    dal resto del processo (bot Telegram compreso)."""
    urls = ws_urls or [_XRPL_WS_PRIMARY, _XRPL_WS_FALLBACK]
    backoff = _RECONNECT_BACKOFF_BASE
    url_index = 0

    while True:
        url = urls[url_index % len(urls)]
        try:
            await _run_once(url)
            backoff = _RECONNECT_BACKOFF_BASE  # sessione riuscita: resetta il backoff
        except ImportError as e:
            log.warning(f"[xrpl_rlusd_pair_collector] libreria 'websockets' non disponibile, collector disattivato: {e}")
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"[xrpl_rlusd_pair_collector] connessione a {url} interrotta ({e}), riconnessione tra {backoff:.0f}s")

        url_index += 1
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, _RECONNECT_BACKOFF_MAX)
