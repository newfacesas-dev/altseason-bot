"""
XRPL Feature History Layer — Gap 1 (primo passo), Milestone M8
==================================================================

Scopo (e SOLO questo): persistere nel tempo gli output di
xrpl_feature_engine.compute_all_features(), cosi' che in futuro (passo
separato, da autorizzare esplicitamente) M3 possa leggere uno storico dei
valori GIA' DERIVATI per calcolare percentili/normalizzazioni oggi
impossibili (Gap 1 dell'audit M7bis).

Questo modulo NON modifica M1/M2/M3. NON cambia score, pesi o soglie.
NON e' ancora usato da M3 — e' solo lo strato di persistenza + lettura.
Chiudere davvero il Gap 1 richiedera' un passo successivo, distinto e da
approvare separatamente, che estenda la logica di normalizzazione di M3.

=== Formato ===
Una riga JSONL = uno snapshot completo di tutte le feature in quel
momento (stesso principio di M1: uno snapshot compatto per chiamata, non
una riga per singola feature).

=== Dedup per contenuto, non per data ===
La pipeline M6 produce normalmente uno snapshot al giorno, ma il layer
non deve scartare automaticamente una seconda osservazione reale dello
stesso giorno. Il controllo e' quindi sul CONTENUTO (hash SHA-256 dei
valori+status di tutte le feature), non sulla data: se i valori sono
identici all'ultimo snapshot registrato, e' una vera duplicazione (nessuna
informazione nuova) e viene saltata; se anche una sola feature e'
cambiata, la nuova osservazione viene preservata, anche nello stesso giorno.
"""

import os
import json
import hashlib
import logging
from datetime import datetime, timezone, timedelta

import xrpl_feature_engine as fe

log = logging.getLogger("xrpl_feature_history")

_FEATURE_HISTORY_PATH = os.environ.get("XRPL_FEATURE_HISTORY_PATH", "/data/xrpl_feature_history.jsonl")


def _compact_features(features):
    """Riduce l'output completo di compute_all_features() a solo
    value+status per feature, come richiesto ('salva timestamp + valore
    + status'). Scarta reason/source/as_of/history_points: quei dettagli
    restano disponibili chiamando M2 dal vivo quando servono; qui serve
    solo cio' che alimenta un futuro storico numerico."""
    out = {}
    for name, feat in features.items():
        if not isinstance(feat, dict):
            continue
        out[name] = {"value": feat.get("value"), "status": feat.get("status")}
    return out


def _content_hash(compact_features):
    """Hash deterministico del contenuto (serializzazione con chiavi
    ordinate, cosi' lo stesso insieme di valori produce sempre lo stesso
    hash indipendentemente dall'ordine con cui e' stato costruito)."""
    serialized = json.dumps(compact_features, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _read_last_entry(path=None):
    path = path or _FEATURE_HISTORY_PATH
    try:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception as e:
        log.warning(f"[xrpl_feature_history] lettura ultimo snapshot fallita: {e}")
        return None


def _read_all_entries(path=None, n=1_000_000):
    path = path or _FEATURE_HISTORY_PATH
    try:
        if not os.path.exists(path):
            return []
        with open(path, encoding="utf-8") as fh:
            righe = [ln.strip() for ln in fh if ln.strip()]
        ultime = righe[-n:] if len(righe) >= n else righe
        out = []
        for r in ultime:
            try:
                out.append(json.loads(r))
            except Exception:
                continue
        return out
    except Exception as e:
        log.warning(f"[xrpl_feature_history] lettura storico fallita: {e}")
        return []


def record_feature_snapshot(features=None, path=None):
    """Registra un nuovo snapshot delle feature, SOLO se il contenuto
    differisce dall'ultimo gia' presente (dedup per contenuto reale, non
    per data). 'features': se assente, chiama
    xrpl_feature_engine.compute_all_features() (comportamento reale).

    Ritorna sempre un dict: {'written': bool, 'reason': str, 'entry': dict|None}.
    Non solleva mai un'eccezione verso il chiamante."""
    path = path or _FEATURE_HISTORY_PATH
    if features is None:
        try:
            features = fe.compute_all_features()
        except Exception as e:
            log.warning(f"[xrpl_feature_history] compute_all_features() fallita: {e}")
            return {"written": False, "reason": f"errore nel calcolo delle feature: {e}", "entry": None}

    compact = _compact_features(features)
    new_hash = _content_hash(compact)

    last = _read_last_entry(path)
    if last is not None and last.get("content_hash") == new_hash:
        return {
            "written": False,
            "reason": "contenuto identico all'ultimo snapshot registrato: nessuna nuova informazione",
            "entry": None,
        }

    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "content_hash": new_hash,
        "features": compact,
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        log.warning(f"[xrpl_feature_history] scrittura snapshot fallita (non bloccante): {e}")
        return {"written": False, "reason": f"scrittura su disco fallita: {e}", "entry": None}

    return {"written": True, "reason": "nuovo contenuto, snapshot registrato", "entry": entry}


def get_feature_series(feature_key, window_days=None, path=None):
    """Ritorna la serie storica (datetime, valore) per una singola feature,
    letta ESCLUSIVAMENTE da questo storico (mai dai RAW di M1). Salta
    snapshot con timestamp invalido, feature assente, o valore None
    (status MISSING/NON_MATURE) — mai un valore inventato.

    'window_days': se fornito, limita ai punti entro N giorni dall'ultimo
    punto disponibile nella serie (non da 'adesso')."""
    entries = _read_all_entries(path)
    series = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        dt = fe._parse_ts(entry.get("timestamp_utc"))
        if dt is None:
            continue
        feat = entry.get("features", {}).get(feature_key)
        if not isinstance(feat, dict):
            continue
        value = feat.get("value")
        if value is None:
            continue
        series.append((dt, value))
    series.sort(key=lambda pair: pair[0])

    if window_days is not None and series:
        latest_dt = series[-1][0]
        cutoff = latest_dt - timedelta(days=window_days)
        series = [(dt, v) for dt, v in series if dt >= cutoff]

    return series


def get_latest_snapshot(path=None):
    """Ritorna l'ultimo snapshot completo registrato (utile per ispezione/
    test), o None se lo storico e' vuoto."""
    return _read_last_entry(path)
