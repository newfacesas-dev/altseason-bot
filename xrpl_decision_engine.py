"""
XRPL Decision Engine — Milestone M5
=====================================

Scopo (e SOLO questo): interpretare gli output gia' calcolati da
xrpl_score_layer.py (M3), xrpl_confidence_engine.py e
xrpl_divergence_state.py (M4) in uno degli 8 stati qualitativi gia'
congelati. Interprete puro: NON calcola feature, NON ricalcola score,
NON modifica Confidence o Divergence, NON fa chiamate API, NON legge i
RAW, NON tocca Telegram/alert/Market Score/Rotation Engine/Altseason
Score esistenti, NON importa altseason_bot.py.

=== Indicatori esterni del bot (Market Score, Rotation Engine,
    Altseason Score, Fear&Greed, BTC Dominance, ETH/BTC) ===
Non importati da altseason_bot.py (stesso rischio gia' documentato in M2:
eseguire quel file come modulo potrebbe avviare un secondo polling
Telegram in produzione). Sono accettati SOLO via dependency injection,
in un dict opzionale 'external_signals' con chiavi riconosciute:
  - 'rotation_state': stringa gia' calcolata dal Rotation Engine esistente
    (es. 'DISTRIBUTION_WARNING', 'RISK_OFF', altro)
  - 'fear_greed_extreme_euphoria': bool gia' calcolato dal bot esistente
    (la soglia che definisce "euforia estrema" appartiene al bot, non
    viene reinventata qui — passare un numero grezzo e definire una
    soglia nuova qui violerebbe "nessuna soglia nuova arbitraria")
  - 'market_score_status', 'altseason_state', 'btc_dominance_trend',
    'eth_btc_trend': riservati per un collegamento futuro, oggi non
    usati da nessuno degli 8 stati (nessuno degli 8 stati approvati li
    richiede esplicitamente oltre a rotation_state/fear_greed)
Se assenti, il Decision Engine resta pienamente funzionante solo con
Score1, Score2, Confidence e Divergence — come richiesto — semplicemente
gli stati che li userebbero come rifinitura (DISTRIBUTION_RISK) non
potranno mai attivarsi senza quel segnale, invece di essere inventati.

=== Nessuna soglia nuova arbitraria ===
Ogni condizione qui sotto usa ESCLUSIVAMENTE output categorici gia'
calcolati altrove (stato di Divergence, etichetta di Confidence, stato
COMPUTED/NOT_COMPUTABLE dello score, flag 'indispensable' gia' definiti
nei registri di M3). Nessun confronto diretto con un valore numerico di
score (es. 'se score1>60') e' mai stato introdotto: sarebbe una soglia
di business nuova, non approvata.
"""

import os
import json
import logging
from datetime import datetime, timezone

import xrpl_score_layer as sl
import xrpl_confidence_engine as ce
import xrpl_divergence_state as ds

log = logging.getLogger("xrpl_decision_engine")

_DECISION_STATE_PATH = os.environ.get("XRPL_DECISION_STATE_PATH", "/data/xrpl_decision_state_log.jsonl")
_CONFIRM_N = 3  # stesso valore verificato contro GIORNI_CONFERMA=3 in altseason_bot.py (M4)

DECISION_DISTRIBUTION_RISK = "DISTRIBUTION_RISK"
DECISION_SPECULATIVE_RALLY = "SPECULATIVE_RALLY"
DECISION_STRUCTURAL_WEAKNESS = "STRUCTURAL_WEAKNESS"
DECISION_XRP_NOT_CAPTURING_VALUE = "XRP_NOT_CAPTURING_VALUE"
DECISION_STRONG_STRUCTURAL_BULLISH = "STRONG_STRUCTURAL_BULLISH"
DECISION_STRUCTURAL_BULLISH = "STRUCTURAL_BULLISH"
DECISION_EARLY_INSTITUTIONAL_ADOPTION = "EARLY_INSTITUTIONAL_ADOPTION"
DECISION_WAIT = "WAIT"

RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW_MEDIUM = "LOW_MEDIUM"
RISK_LOW = "LOW"
RISK_NA = "N/A"

_CONFIDENCE_MEDIUM_OR_ABOVE = (ce.LABEL_HIGH, ce.LABEL_MEDIUM)

_RECOGNIZED_EXTERNAL_KEYS = (
    "rotation_state", "fear_greed_extreme_euphoria",
    "market_score_status", "altseason_state", "btc_dominance_trend", "eth_btc_trend",
)
_RISK_ROTATION_STATES = ("DISTRIBUTION_WARNING", "RISK_OFF")


# ============================================================
# INDISPENSABILI — riuso diretto dei flag gia' definiti in M3
# ============================================================

def _indispensable_feature_keys(categories_def):
    return [
        m["feature_key"]
        for cat in categories_def.values()
        for m in cat["metrics"]
        if m.get("indispensable") and m.get("feature_key") is not None
    ]


def _indispensable_qualified_names(categories_def):
    return [
        f"{cat_key}.{m['name']}"
        for cat_key, cat in categories_def.items()
        for m in cat["metrics"]
        if m.get("indispensable")
    ]


def _score_indispensable_ok(score_result, categories_def):
    """True se ALMENO UNA delle metriche indispensabili di questo score
    NON e' NON_MATURE/MISSING (stesso principio di M3, riletto qui senza
    ricalcolarlo: si legge solo l'output gia' prodotto)."""
    if score_result is None:
        return False
    qualified = _indispensable_qualified_names(categories_def)
    unavailable = set(score_result.get("non_mature_metrics", [])) | set(score_result.get("missing_metrics", []))
    return any(q not in unavailable for q in qualified)


# ============================================================
# PERSISTENZA ANTI-FLICKER — stessa tecnica di M4, file separato
# (spazio di stati diverso: 8 decisioni vs 5 pattern+2 di Divergence,
# accoppiarli nello stesso file mischierebbe due enum differenti)
# ============================================================

def _read_last_committed(path=None):
    path = path or _DECISION_STATE_PATH
    try:
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
        if not lines:
            return None
        return json.loads(lines[-1])
    except Exception as e:
        log.warning(f"[xrpl_decision_engine] lettura stato decisione fallita: {e}")
        return None


def _persist_decision_state(entry, path=None):
    path = path or _DECISION_STATE_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        log.warning(f"[xrpl_decision_engine] salvataggio stato decisione fallito (non bloccante): {e}")


def _apply_anti_flicker(raw_decision, confirm_n=_CONFIRM_N, state_path=None, record=True):
    previous = _read_last_committed(state_path) if record else None
    if previous is None:
        candidate = raw_decision
        streak = 1
        committed = raw_decision if confirm_n <= 1 else DECISION_WAIT
    else:
        prev_candidate = previous.get("candidate_decision")
        prev_committed = previous.get("committed_decision", DECISION_WAIT)
        streak = (previous.get("candidate_streak", 1) + 1) if raw_decision == prev_candidate else 1
        candidate = raw_decision
        committed = candidate if streak >= confirm_n else prev_committed

    entry = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "raw_decision": raw_decision,
        "candidate_decision": candidate,
        "candidate_streak": streak,
        "committed_decision": committed,
        "confirm_n": confirm_n,
    }
    if record:
        _persist_decision_state(entry, state_path)
    return entry


# ============================================================
# CLASSIFICAZIONE — 8 stati, priorita' rischio -> bullish -> WAIT
# ============================================================

def _classify(score1, score2, conf1, conf2, divergence, external_signals):
    reasons = []

    score1_ok = _score_indispensable_ok(score1, sl.SCORE1_CATEGORIES)
    score2_ok = _score_indispensable_ok(score2, sl.SCORE2_CATEGORIES)
    if not score1_ok and not score2_ok:
        reasons.append(
            "componenti indispensabili non mature/mancanti su entrambi gli score "
            "(Ecosystem Growth e Capture & Dependency): nessuna lettura affidabile possibile"
        )
        return DECISION_WAIT, RISK_NA, reasons

    div_state = divergence.get("state")
    rotation_state = external_signals.get("rotation_state")
    fear_greed_euphoria = external_signals.get("fear_greed_extreme_euphoria")

    # --- 1. DISTRIBUTION_RISK ---
    if (
        div_state == ds.STATE_STRUCTURAL_BEARISH_DIVERGENCE
        and rotation_state in _RISK_ROTATION_STATES
        and fear_greed_euphoria is True
    ):
        reasons.append(
            "Divergenza ribassista strutturale (A-D in calo, E in salita) confermata da "
            "Rotation Engine in stato di rischio e Fear&Greed in euforia estrema"
        )
        return DECISION_DISTRIBUTION_RISK, RISK_HIGH, reasons

    # --- 2. SPECULATIVE_RALLY ---
    if div_state == ds.STATE_UNSUPPORTED_SPECULATIVE_RALLY and conf2.get("confidence_label") in _CONFIDENCE_MEDIUM_OR_ABOVE:
        reasons.append(
            "Relative strength XRP in forte salita ma non confermata da adozione "
            "dell'ecosistema (A-D) ne' da dipendenza economica (F): rally non supportato dai fondamentali"
        )
        return DECISION_SPECULATIVE_RALLY, RISK_HIGH, reasons

    # --- 3. STRUCTURAL_WEAKNESS ---
    if divergence.get("trends", {}).get("score1") == ds.TREND_DOWN:
        reasons.append(
            "XRPL Ecosystem Growth Score in trend discendente, indipendentemente "
            "dall'andamento del prezzo di XRP"
        )
        return DECISION_STRUCTURAL_WEAKNESS, RISK_HIGH, reasons

    # --- 4. XRP_NOT_CAPTURING_VALUE ---
    if div_state == ds.STATE_ECOSYSTEM_GROWTH_WITHOUT_XRP_CAPTURE and conf1.get("confidence_label") in _CONFIDENCE_MEDIUM_OR_ABOVE:
        reasons.append("XRPL cresce ma XRP non sta catturando valore economico da quella crescita")
        return DECISION_XRP_NOT_CAPTURING_VALUE, RISK_MEDIUM, reasons

    # --- 5. STRONG_STRUCTURAL_BULLISH ---
    rotation_not_risk = rotation_state not in _RISK_ROTATION_STATES if rotation_state is not None else True
    if (
        div_state == ds.STATE_ADOPTION_CONFIRMED_AND_PRICED
        and conf1.get("confidence_label") == ce.LABEL_HIGH
        and conf2.get("confidence_label") == ce.LABEL_HIGH
        and rotation_not_risk
    ):
        reasons.append(
            "Crescita dell'ecosistema, dipendenza economica di XRP e prezzo di mercato "
            "tutti confermati insieme, con alta confidence su entrambi gli score"
        )
        return DECISION_STRONG_STRUCTURAL_BULLISH, RISK_LOW, reasons

    # --- 6. STRUCTURAL_BULLISH ---
    if (
        div_state == ds.STATE_ADOPTION_CONFIRMED_AND_PRICED
        and conf1.get("confidence_label") in _CONFIDENCE_MEDIUM_OR_ABOVE
        and conf2.get("confidence_label") in _CONFIDENCE_MEDIUM_OR_ABOVE
    ):
        reasons.append(
            "Segnali di adozione, dipendenza economica e prezzo allineati positivamente, "
            "ma non ancora confermati con la massima affidabilita' dei dati"
        )
        return DECISION_STRUCTURAL_BULLISH, RISK_LOW_MEDIUM, reasons

    # --- 7. EARLY_INSTITUTIONAL_ADOPTION ---
    if (
        div_state == ds.STATE_STRUCTURAL_ADOPTION_NOT_PRICED
        and conf1.get("confidence_label") in _CONFIDENCE_MEDIUM_OR_ABOVE
        and score1_ok
    ):
        reasons.append("Adozione strutturale crescente e confermata dai dati, il mercato non l'ha ancora prezzata")
        return DECISION_EARLY_INSTITUTIONAL_ADOPTION, RISK_MEDIUM, reasons

    # --- 8. WAIT (default) ---
    reasons.append("Dati ancora insufficienti o nessun pattern chiaramente identificabile per una lettura affidabile")
    return DECISION_WAIT, RISK_NA, reasons


# ============================================================
# ORCHESTRAZIONE
# ============================================================

def compute_decision(
    score1_result=None,
    score2_result=None,
    confidence1=None,
    confidence2=None,
    divergence_result=None,
    external_signals=None,
    record=True,
    state_path=None,
    confirm_n=_CONFIRM_N,
):
    """Calcola la decisione corrente. Interprete puro: nessuno degli
    input passati viene mai modificato (letti soltanto)."""
    external_signals = external_signals or {}

    score1 = score1_result if score1_result is not None else sl.compute_ecosystem_growth_score()
    score2 = score2_result if score2_result is not None else sl.compute_capture_dependency_score()
    conf1 = confidence1 if confidence1 is not None else ce.compute_confidence(score1)
    conf2 = confidence2 if confidence2 is not None else ce.compute_confidence(score2)
    divergence = (
        divergence_result
        if divergence_result is not None
        else ds.compute_divergence_state(score1_result=score1, score2_result=score2, record=record)
    )

    raw_decision, risk_level, reasons = _classify(score1, score2, conf1, conf2, divergence, external_signals)
    flicker_entry = _apply_anti_flicker(raw_decision, confirm_n, state_path, record)

    inputs_used = ["score1", "score2", "confidence1", "confidence2", "divergence"]
    inputs_used += [k for k in _RECOGNIZED_EXTERNAL_KEYS if external_signals.get(k) is not None]
    inputs_missing = [k for k in _RECOGNIZED_EXTERNAL_KEYS if external_signals.get(k) is None]

    return {
        "decision": flicker_entry["committed_decision"],
        "raw_decision": raw_decision,
        "risk_level": risk_level,
        "confidence": {"ecosystem_growth": conf1, "capture_dependency": conf2},
        "reason": reasons,
        "inputs_used": inputs_used,
        "inputs_missing": inputs_missing,
        "confirmed": flicker_entry["candidate_streak"] >= confirm_n,
        "confirmation_streak": flicker_entry["candidate_streak"],
    }


if __name__ == "__main__":
    print(json.dumps(compute_decision(), indent=2, ensure_ascii=False, default=str))
