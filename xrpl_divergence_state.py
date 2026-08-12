"""
XRPL Divergence State — Milestone M4 (parte 2/2)
====================================================

Scopo (e SOLO questo): classificare la relazione tra il trend di Score1
(XRPL Ecosystem Growth, categorie A-D combinate), del trend della
categoria F (XRP Economic Dependency) e del trend della categoria E
(XRP Value Capture) in uno dei 5 pattern gia' congelati, o
NO_CLEAR_DIVERGENCE se nessuno si applica, o NON_MATURE se lo storico
non basta per classificare in modo affidabile.

Non implementa il Decision Engine (sara' M5). Non tocca M1/M2/M3, non
importa altseason_bot.py, non fa chiamate API.

=== Perche' serve una nuova, piccola persistenza (dichiarato, non nascosto) ===
Classificare "in salita/piatto/in discesa" richiede uno storico dei valori
di Score1/F/E nel tempo. Nessuno strato esistente (M1-M3) persiste una
serie di valori di SCORE (M1 persiste dati grezzi, M2/M3 sono stateless).
Qui si riusa lo STESSO pattern gia' approvato in M1 — file JSONL append-only
sullo stesso Railway Volume — applicato a un nuovo dominio dati (i valori
di score nel tempo), non una nuova architettura.
L'anti-flickering (N conferme consecutive prima di cambiare stato)
richiede allo stesso modo un piccolo stato persistito tra chiamate
successive: stesso principio del meccanismo di conferma multi-giorno gia'
usato altrove nel bot (State Change Alert), qui reimplementato in modo
autonomo — non importato da altseason_bot.py per i motivi di sicurezza
gia' documentati in M2 (rischio di eseguire codice a livello di modulo).

=== Classificazione trend: nessuna soglia assoluta arbitraria ===
Riuso diretto di xrpl_feature_engine.trend_vs_ma (mediana/MAD, stessa
metodologia gia' congelata) per ottenere uno z grezzo, poi CALIBRATO con
la stessa costante MAD->sigma gia' verificata e usata in M3
(xrpl_score_layer._MAD_TO_STANDARD_Z_FACTOR, riusata qui via import, non
un nuovo numero) prima di applicare le bande. Le soglie a 1 e 2 sigma
standard sono una convenzione statistica riconosciuta (grafici di
controllo, regola ~68%/~95% di una normale), non una percentuale di
business inventata. "Forte" (usato solo per E, per distinguere i pattern
3 e 4) usa la banda a 2 sigma, stessa logica, piu' ampia.
"""

import os
import json
import logging
from datetime import datetime, timezone, timedelta

import xrpl_feature_engine as fe
import xrpl_score_layer as sl

log = logging.getLogger("xrpl_divergence_state")

_SCORE_HISTORY_PATH = os.environ.get("XRPL_SCORE_HISTORY_PATH", "/data/xrpl_score_history.jsonl")
_DIVERGENCE_STATE_PATH = os.environ.get("XRPL_DIVERGENCE_STATE_PATH", "/data/xrpl_divergence_state_log.jsonl")

_TREND_WINDOW_DAYS = 30
_NORMAL_BAND_SIGMA = 1.0   # confine flat/direzionale: 1 sigma standard (~68% dei valori entro banda, per una normale)
_STRONG_BAND_SIGMA = 2.0   # confine "forte" per E: 2 sigma standard (~95%), stessa convenzione, banda piu' ampia
_CONFIRM_N = 3             # verificato contro GIORNI_CONFERMA=3 in altseason_bot.py (grep, nessun import): stesso valore, non una coincidenza non controllata

TREND_UP = "UP"
TREND_STRONG_UP = "STRONG_UP"
TREND_DOWN = "DOWN"
TREND_FLAT = "FLAT"
TREND_NON_MATURE = "NON_MATURE"

STATE_STRUCTURAL_ADOPTION_NOT_PRICED = "STRUCTURAL_ADOPTION_NOT_PRICED"
STATE_ECOSYSTEM_GROWTH_WITHOUT_XRP_CAPTURE = "ECOSYSTEM_GROWTH_WITHOUT_XRP_CAPTURE"
STATE_UNSUPPORTED_SPECULATIVE_RALLY = "UNSUPPORTED_SPECULATIVE_RALLY"
STATE_ADOPTION_CONFIRMED_AND_PRICED = "ADOPTION_CONFIRMED_AND_PRICED"
STATE_STRUCTURAL_BEARISH_DIVERGENCE = "STRUCTURAL_BEARISH_DIVERGENCE"
STATE_NO_CLEAR_DIVERGENCE = "NO_CLEAR_DIVERGENCE"
STATE_NON_MATURE = "NON_MATURE"


def record_score_observation(score1_result, score2_result, path=None):
    path = path or _SCORE_HISTORY_PATH
    score1_value = score1_result.get("score") if score1_result else None
    f_value = None
    e_value = None
    if score2_result:
        cb = score2_result.get("category_breakdown", {})
        f_value = cb.get("F", {}).get("score")
        e_value = cb.get("E", {}).get("score")

    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "score1": score1_value,
        "f_score": f_value,
        "e_score": e_value,
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"[xrpl_divergence_state] salvataggio storico score fallito (non bloccante): {e}")
    return entry


def _read_score_history(path=None, n=1_000_000):
    path = path or _SCORE_HISTORY_PATH
    try:
        if not os.path.exists(path):
            return []
        righe = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    righe.append(line)
        ultime = righe[-n:] if len(righe) >= n else righe
        out = []
        for r in ultime:
            try:
                out.append(json.loads(r))
            except Exception:
                continue
        return out
    except Exception as e:
        log.warning(f"[xrpl_divergence_state] lettura storico score fallita: {e}")
        return []


def _series_for_key(history, key):
    out = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        val = entry.get(key)
        if val is None:
            continue
        dt = fe._parse_ts(entry.get("timestamp_utc"))
        if dt is None:
            continue
        out.append((dt, val))
    out.sort(key=lambda pair: pair[0])
    return out


def _classify_trend(series, window_days=_TREND_WINDOW_DAYS):
    """UP/STRONG_UP/DOWN/FLAT/NON_MATURE.

    trend_vs_ma() di M2 ritorna (current-mediana)/MAD GREZZO, non uno z-score
    standard (stessa scoperta gia' fatta e corretta in M3 per la
    normalizzazione degli score). Per bande statisticamente coerenti con
    quella correzione, qui si applica la STESSA costante di calibrazione
    MAD->sigma gia' definita in xrpl_score_layer.py (riusata via import,
    non un nuovo numero) prima di confrontare con le soglie a 1/2 sigma."""
    if len(series) < 2:
        return TREND_NON_MATURE
    latest_dt, latest_val = series[-1]
    cutoff = latest_dt - timedelta(days=window_days)
    window_values = [v for dt, v in series if cutoff <= dt < latest_dt]
    if len(window_values) < 2:
        return TREND_NON_MATURE
    z_raw = fe.trend_vs_ma(latest_val, window_values)
    if z_raw is None:
        return TREND_NON_MATURE
    z_std = sl._MAD_TO_STANDARD_Z_FACTOR * z_raw
    if z_std >= _STRONG_BAND_SIGMA:
        return TREND_STRONG_UP
    if z_std >= _NORMAL_BAND_SIGMA:
        return TREND_UP
    if z_std <= -_NORMAL_BAND_SIGMA:
        return TREND_DOWN
    return TREND_FLAT


def _match_pattern(trend_score1, trend_f, trend_e):
    if TREND_NON_MATURE in (trend_score1, trend_f, trend_e):
        return STATE_NON_MATURE, "storico insufficiente su almeno una delle tre serie (Score1/F/E)"

    ad_up = trend_score1 in (TREND_UP, TREND_STRONG_UP)
    ad_down = trend_score1 == TREND_DOWN
    f_up = trend_f in (TREND_UP, TREND_STRONG_UP)
    f_flat_or_down = trend_f in (TREND_FLAT, TREND_DOWN)
    e_flat = trend_e == TREND_FLAT
    e_up = trend_e in (TREND_UP, TREND_STRONG_UP)
    e_strong_up = trend_e == TREND_STRONG_UP

    if ad_up and f_up and e_flat:
        return STATE_STRUCTURAL_ADOPTION_NOT_PRICED, "A-D in crescita, F in crescita, E piatto"
    if ad_up and f_flat_or_down:
        return STATE_ECOSYSTEM_GROWTH_WITHOUT_XRP_CAPTURE, "A-D in crescita ma F piatto/in calo"
    if ad_down and e_up:
        return STATE_STRUCTURAL_BEARISH_DIVERGENCE, "A-D in calo mentre E continua a salire"
    if e_strong_up and not (ad_up and f_up):
        return STATE_UNSUPPORTED_SPECULATIVE_RALLY, "E in forte salita ma A-D/F non confermano"
    if ad_up and f_up and e_up:
        return STATE_ADOPTION_CONFIRMED_AND_PRICED, "A-D, F ed E tutti in crescita"
    return STATE_NO_CLEAR_DIVERGENCE, "nessuno dei 5 pattern congelati corrisponde alla combinazione osservata"


def _read_last_committed_state(path=None):
    path = path or _DIVERGENCE_STATE_PATH
    try:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception as e:
        log.warning(f"[xrpl_divergence_state] lettura stato divergenza fallita: {e}")
        return None


def _persist_state(entry, path=None):
    path = path or _DIVERGENCE_STATE_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"[xrpl_divergence_state] salvataggio stato divergenza fallito (non bloccante): {e}")


def _apply_anti_flicker(raw_pattern, confirm_n=_CONFIRM_N, state_path=None):
    previous = _read_last_committed_state(state_path)
    if previous is None:
        candidate_pattern = raw_pattern
        candidate_streak = 1
        committed_pattern = raw_pattern if confirm_n <= 1 else STATE_NON_MATURE
    else:
        prev_candidate = previous.get("candidate_pattern")
        prev_committed = previous.get("committed_pattern", STATE_NON_MATURE)
        if raw_pattern == prev_candidate:
            candidate_streak = previous.get("candidate_streak", 1) + 1
        else:
            candidate_streak = 1
        candidate_pattern = raw_pattern
        if candidate_streak >= confirm_n:
            committed_pattern = candidate_pattern
        else:
            committed_pattern = prev_committed

    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "raw_pattern": raw_pattern,
        "candidate_pattern": candidate_pattern,
        "candidate_streak": candidate_streak,
        "committed_pattern": committed_pattern,
        "confirm_n": confirm_n,
    }
    _persist_state(entry, state_path)
    return entry


def compute_divergence_state(
    score1_result=None,
    score2_result=None,
    record=True,
    history_override=None,
    score_history_path=None,
    state_path=None,
    window_days=_TREND_WINDOW_DAYS,
    confirm_n=_CONFIRM_N,
):
    if score1_result is None:
        score1_result = sl.compute_ecosystem_growth_score()
    if score2_result is None:
        score2_result = sl.compute_capture_dependency_score()

    if record and history_override is None:
        record_score_observation(score1_result, score2_result, path=score_history_path)

    history = history_override if history_override is not None else _read_score_history(score_history_path)

    series_score1 = _series_for_key(history, "score1")
    series_f = _series_for_key(history, "f_score")
    series_e = _series_for_key(history, "e_score")

    trend_score1 = _classify_trend(series_score1, window_days)
    trend_f = _classify_trend(series_f, window_days)
    trend_e = _classify_trend(series_e, window_days)

    raw_pattern, pattern_reason = _match_pattern(trend_score1, trend_f, trend_e)
    flicker_entry = _apply_anti_flicker(raw_pattern, confirm_n, state_path)

    return {
        "state": flicker_entry["committed_pattern"],
        "raw_pattern": raw_pattern,
        "candidate_streak": flicker_entry["candidate_streak"],
        "confirm_n": confirm_n,
        "trends": {"score1": trend_score1, "F": trend_f, "E": trend_e},
        "history_points": {
            "score1": len(series_score1), "F": len(series_f), "E": len(series_e),
        },
        "reasons": [pattern_reason],
    }


if __name__ == "__main__":
    print(json.dumps(compute_divergence_state(), indent=2, ensure_ascii=False, default=str))
