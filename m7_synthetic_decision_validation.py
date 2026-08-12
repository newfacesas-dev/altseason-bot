"""
M7 — Validazione SINTETICA del Decision Engine
=================================================

ATTENZIONE: questo script NON e' un backtest storico. Usa sequenze
COSTRUITE per esercitare la logica del Decision Engine (M5) — codice
reale e congelato, mai modificato — su scenari controllati. Serve a
verificare ritardo dei segnali, immunita' al rumore (falsi positivi da
flip-flop), e comportamento durante l'immaturita' dei dati.

Nessun dato storico reale e' usato qui. Per il backtest reale (unico
componente genuinamente backtestabile: il segnale grezzo di relative
strength XRP/BTC e XRP/ETH su prezzi storici reali) vedi
m7_backtest_relative_strength.py.

Non modifica M1-M6. Non tocca Telegram. Non fa chiamate API.
"""
import copy
import tempfile
import os

import xrpl_decision_engine as de
import xrpl_divergence_state as ds
import xrpl_confidence_engine as ce
import xrpl_score_layer as sl


def _score(non_mature=None):
    return {
        "score": 60.0, "status": sl.SCORE_STATUS_COMPUTED,
        "active_metrics": [], "partial_metrics": [],
        "non_mature_metrics": non_mature or [], "missing_metrics": [],
        "category_breakdown": {}, "reasons": [],
    }


def _conf(label):
    return {
        "confidence_score": 80.0 if label == ce.LABEL_HIGH else 50.0,
        "confidence_label": label, "coverage": 80.0, "freshness": 80.0,
        "maturity": 80.0, "cross_source_status": ce.CROSS_SOURCE_NOT_AVAILABLE, "reasons": [],
    }


def _div(state, t1="FLAT", tf="FLAT", te="FLAT"):
    return {
        "state": state, "raw_pattern": state, "candidate_streak": 3, "confirm_n": 3,
        "trends": {"score1": t1, "F": tf, "E": te},
        "history_points": {"score1": 10, "F": 10, "E": 10}, "reasons": [],
    }


def run_sequence(name, steps, confirm_n=3):
    """steps: lista di dict con chiavi div_state,t1,tf,te,conf1,conf2.
    Esegue la sequenza attraverso il VERO Decision Engine, un passo alla
    volta, con anti-flicker persistito su file temporaneo dedicato."""
    tmpdir = tempfile.mkdtemp()
    state_path = os.path.join(tmpdir, "decision.jsonl")
    print(f"\n{'='*70}\nSCENARIO: {name}\n{'='*70}")
    results = []
    for day, step in enumerate(steps, start=1):
        score1 = _score(non_mature=step.get("score1_non_mature", []))
        score2 = _score(non_mature=step.get("score2_non_mature", []))
        conf1 = _conf(step.get("conf1", ce.LABEL_HIGH))
        conf2 = _conf(step.get("conf2", ce.LABEL_HIGH))
        divergence = _div(step["div_state"], step.get("t1", "FLAT"), step.get("tf", "FLAT"), step.get("te", "FLAT"))

        score1_before = copy.deepcopy(score1)
        r = de.compute_decision(
            score1_result=score1, score2_result=score2,
            confidence1=conf1, confidence2=conf2, divergence_result=divergence,
            record=True, state_path=state_path, confirm_n=confirm_n,
        )
        assert score1 == score1_before, "VIOLAZIONE: input mutato dal Decision Engine!"

        results.append(r)
        print(f"  giorno {day:2d}: raw={r['raw_decision']:32s} committed={r['decision']:32s} "
              f"streak={r['confirmation_streak']} confirmed={r['confirmed']}")
    return results


def scenario_1_gradual_genuine_bullish():
    """Segnale bullish genuino che si stabilizza dal giorno 3 in poi.
    Domanda: quanti giorni servono prima che il Decision Engine lo
    dichiari CONFERMATO?"""
    steps = (
        [{"div_state": ds.STATE_NO_CLEAR_DIVERGENCE, "conf1": ce.LABEL_LOW}] * 2 +
        [{"div_state": ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "t1": "UP", "tf": "UP", "te": "UP",
          "conf1": ce.LABEL_HIGH, "conf2": ce.LABEL_HIGH}] * 6
    )
    results = run_sequence("Segnale bullish genuino, graduale (10 giorni)", steps)
    first_confirmed_day = next((i + 1 for i, r in enumerate(results) if r["confirmed"]), None)
    print(f"  -> Primo giorno con decisione CONFERMATA: {first_confirmed_day}")
    print(f"  -> Segnale genuino stabile dal giorno 3: ritardo di conferma = "
          f"{(first_confirmed_day - 3) if first_confirmed_day else 'MAI'} giorni oltre l'inizio del pattern")
    return results


def scenario_2_noisy_flip_flop():
    """Segnale che alterna ogni giorno tra due letture diverse. Domanda:
    il Decision Engine si lascia ingannare (falso positivo da rumore)?"""
    pattern_a = {"div_state": ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "t1": "UP", "tf": "UP", "te": "UP"}
    pattern_b = {"div_state": ds.STATE_NO_CLEAR_DIVERGENCE}
    steps = [pattern_a if i % 2 == 0 else pattern_b for i in range(10)]
    results = run_sequence("Segnale rumoroso, alterna ogni giorno (10 giorni)", steps)
    ever_confirmed = any(r["confirmed"] for r in results)
    print(f"  -> Il rumore ha mai prodotto una decisione CONFERMATA? {ever_confirmed} "
          f"(atteso: False — l'anti-flicker deve sopprimere il rumore)")
    return results


def scenario_3_sudden_risk_mid_bullish_streak():
    """Rischio improvviso per un solo giorno, in mezzo a uno streak bullish
    gia' confermato. Domanda: quanto e' 'protetto' (o esposto) il sistema
    a un evento di rischio isolato di un solo giorno?"""
    steps = (
        [{"div_state": ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "t1": "UP", "tf": "UP", "te": "UP"}] * 4 +
        [{"div_state": ds.STATE_STRUCTURAL_BEARISH_DIVERGENCE, "t1": "DOWN", "te": "UP"}] +
        [{"div_state": ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "t1": "UP", "tf": "UP", "te": "UP"}] * 4
    )
    results = run_sequence("Rischio isolato di un giorno dentro uno streak bullish confermato (9 giorni)", steps)
    day5_raw = results[4]["raw_decision"]
    day5_committed = results[4]["decision"]
    print(f"  -> Giorno 5 (rischio isolato): raw_decision={day5_raw} (visibile subito) "
          f"ma committed={day5_committed} (protetto dall'anti-flicker, 1 solo giorno non basta)")
    print("  -> LIMITE REALE da segnalare: un rischio genuino di un solo giorno NON altera "
          "immediatamente la decisione committed, solo il raw_decision (che va comunque monitorato)")
    return results


def scenario_4_cold_start_to_maturity():
    """Simula il percorso realistico dei prossimi giorni del bot live:
    partenza da dati completamente immaturi, maturazione graduale."""
    indispensable_score1 = ["A.rwa_distributed", "B.rlusd_circulating_supply"]
    steps = (
        [{"div_state": ds.STATE_NON_MATURE, "score1_non_mature": indispensable_score1,
          "score2_non_mature": ["E.xrp_btc_relative_strength"],
          "conf1": ce.LABEL_NOT_MATURE, "conf2": ce.LABEL_NOT_MATURE}] * 3 +
        [{"div_state": ds.STATE_NO_CLEAR_DIVERGENCE, "conf1": ce.LABEL_LOW, "conf2": ce.LABEL_LOW}] * 3 +
        [{"div_state": ds.STATE_STRUCTURAL_ADOPTION_NOT_PRICED, "t1": "UP", "tf": "UP",
          "conf1": ce.LABEL_MEDIUM}] * 4
    )
    results = run_sequence("Percorso realistico cold-start -> dati maturi (10 giorni)", steps)
    return results


if __name__ == "__main__":
    scenario_1_gradual_genuine_bullish()
    scenario_2_noisy_flip_flop()
    scenario_3_sudden_risk_mid_bullish_streak()
    scenario_4_cold_start_to_maturity()
