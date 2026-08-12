"""
Test M5 — XRPL Decision Engine.
Tutti gli input (score1/score2/confidence1/confidence2/divergence) sono
dizionari sintetici costruiti direttamente, per isolare la logica di
classificazione da M3/M4 reali. Nessuna rete, nessun import di
altseason_bot.py.
"""
import os
import copy
import tempfile
import unittest

import xrpl_decision_engine as de
import xrpl_divergence_state as ds
import xrpl_confidence_engine as ce
import xrpl_score_layer as sl


def _score(status=sl.SCORE_STATUS_COMPUTED, non_mature=None, missing=None):
    return {
        "score": 60.0 if status == sl.SCORE_STATUS_COMPUTED else None,
        "status": status,
        "active_metrics": [], "partial_metrics": [],
        "non_mature_metrics": non_mature or [], "missing_metrics": missing or [],
        "category_breakdown": {}, "reasons": [],
    }


def _conf(label):
    return {
        "confidence_score": 80.0 if label == ce.LABEL_HIGH else 50.0,
        "confidence_label": label,
        "coverage": 80.0, "freshness": 80.0, "maturity": 80.0,
        "cross_source_status": ce.CROSS_SOURCE_NOT_AVAILABLE, "reasons": [],
    }


def _div(state, trend_score1="FLAT", trend_f="FLAT", trend_e="FLAT"):
    return {
        "state": state, "raw_pattern": state, "candidate_streak": 3, "confirm_n": 3,
        "trends": {"score1": trend_score1, "F": trend_f, "E": trend_e},
        "history_points": {"score1": 10, "F": 10, "E": 10},
        "reasons": [],
    }


def _score1_indispensable_ok():
    return _score(non_mature=[])


def _score2_indispensable_ok():
    return _score(non_mature=[])


def _decide(div_state, trend_score1="FLAT", trend_f="FLAT", trend_e="FLAT",
            conf1_label=ce.LABEL_HIGH, conf2_label=ce.LABEL_HIGH,
            external_signals=None, state_path=None, confirm_n=1, record=False):
    return de.compute_decision(
        score1_result=_score1_indispensable_ok(),
        score2_result=_score2_indispensable_ok(),
        confidence1=_conf(conf1_label),
        confidence2=_conf(conf2_label),
        divergence_result=_div(div_state, trend_score1, trend_f, trend_e),
        external_signals=external_signals,
        record=record, state_path=state_path, confirm_n=confirm_n,
    )


class TestEightStates(unittest.TestCase):
    def test_1_distribution_risk(self):
        r = _decide(
            ds.STATE_STRUCTURAL_BEARISH_DIVERGENCE, trend_score1="DOWN", trend_e="UP",
            external_signals={"rotation_state": "DISTRIBUTION_WARNING", "fear_greed_extreme_euphoria": True},
        )
        self.assertEqual(r["raw_decision"], de.DECISION_DISTRIBUTION_RISK)
        self.assertEqual(r["risk_level"], de.RISK_HIGH)

    def test_2_speculative_rally(self):
        r = _decide(ds.STATE_UNSUPPORTED_SPECULATIVE_RALLY, trend_e="STRONG_UP", conf2_label=ce.LABEL_MEDIUM)
        self.assertEqual(r["raw_decision"], de.DECISION_SPECULATIVE_RALLY)
        self.assertEqual(r["risk_level"], de.RISK_HIGH)

    def test_3_structural_weakness(self):
        r = _decide(ds.STATE_NO_CLEAR_DIVERGENCE, trend_score1="DOWN")
        self.assertEqual(r["raw_decision"], de.DECISION_STRUCTURAL_WEAKNESS)
        self.assertEqual(r["risk_level"], de.RISK_HIGH)

    def test_4_xrp_not_capturing_value(self):
        r = _decide(ds.STATE_ECOSYSTEM_GROWTH_WITHOUT_XRP_CAPTURE, trend_score1="UP", trend_f="FLAT")
        self.assertEqual(r["raw_decision"], de.DECISION_XRP_NOT_CAPTURING_VALUE)
        self.assertEqual(r["risk_level"], de.RISK_MEDIUM)

    def test_5_strong_structural_bullish(self):
        r = _decide(
            ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, trend_score1="UP", trend_f="UP", trend_e="UP",
            conf1_label=ce.LABEL_HIGH, conf2_label=ce.LABEL_HIGH,
        )
        self.assertEqual(r["raw_decision"], de.DECISION_STRONG_STRUCTURAL_BULLISH)
        self.assertEqual(r["risk_level"], de.RISK_LOW)

    def test_6_structural_bullish(self):
        r = _decide(
            ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, trend_score1="UP", trend_f="UP", trend_e="UP",
            conf1_label=ce.LABEL_MEDIUM, conf2_label=ce.LABEL_MEDIUM,
        )
        self.assertEqual(r["raw_decision"], de.DECISION_STRUCTURAL_BULLISH)
        self.assertEqual(r["risk_level"], de.RISK_LOW_MEDIUM)

    def test_7_early_institutional_adoption(self):
        r = _decide(
            ds.STATE_STRUCTURAL_ADOPTION_NOT_PRICED, trend_score1="UP", trend_f="UP", trend_e="FLAT",
            conf1_label=ce.LABEL_MEDIUM,
        )
        self.assertEqual(r["raw_decision"], de.DECISION_EARLY_INSTITUTIONAL_ADOPTION)
        self.assertEqual(r["risk_level"], de.RISK_MEDIUM)

    def test_8_wait_default(self):
        r = _decide(ds.STATE_NO_CLEAR_DIVERGENCE)
        self.assertEqual(r["raw_decision"], de.DECISION_WAIT)
        self.assertEqual(r["risk_level"], de.RISK_NA)


class TestLowConfidenceBlocksBullish(unittest.TestCase):
    def test_low_confidence_blocks_strong_bullish(self):
        r = _decide(
            ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, trend_score1="UP", trend_f="UP", trend_e="UP",
            conf1_label=ce.LABEL_LOW, conf2_label=ce.LABEL_LOW,
        )
        self.assertNotEqual(r["raw_decision"], de.DECISION_STRONG_STRUCTURAL_BULLISH)
        self.assertNotEqual(r["raw_decision"], de.DECISION_STRUCTURAL_BULLISH)
        self.assertEqual(r["raw_decision"], de.DECISION_WAIT)

    def test_not_mature_confidence_blocks_early_adoption(self):
        r = _decide(
            ds.STATE_STRUCTURAL_ADOPTION_NOT_PRICED, trend_score1="UP", trend_f="UP", trend_e="FLAT",
            conf1_label=ce.LABEL_NOT_MATURE,
        )
        self.assertNotEqual(r["raw_decision"], de.DECISION_EARLY_INSTITUTIONAL_ADOPTION)
        self.assertEqual(r["raw_decision"], de.DECISION_WAIT)

    def test_speculative_rally_requires_medium_or_above(self):
        r = _decide(ds.STATE_UNSUPPORTED_SPECULATIVE_RALLY, trend_e="STRONG_UP", conf2_label=ce.LABEL_LOW)
        self.assertNotEqual(r["raw_decision"], de.DECISION_SPECULATIVE_RALLY)


class TestIndispensableMissingForcesWait(unittest.TestCase):
    def test_both_scores_missing_indispensable_forces_wait(self):
        indispensable_score1 = [f"{k}.{m['name']}" for k, cat in sl.SCORE1_CATEGORIES.items() for m in cat["metrics"] if m.get("indispensable")]
        indispensable_score2 = [f"{k}.{m['name']}" for k, cat in sl.SCORE2_CATEGORIES.items() for m in cat["metrics"] if m.get("indispensable")]
        r = de.compute_decision(
            score1_result=_score(non_mature=indispensable_score1),
            score2_result=_score(non_mature=indispensable_score2),
            confidence1=_conf(ce.LABEL_HIGH), confidence2=_conf(ce.LABEL_HIGH),
            divergence_result=_div(ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "UP", "UP", "UP"),
            record=False, confirm_n=1,
        )
        self.assertEqual(r["raw_decision"], de.DECISION_WAIT)
        self.assertTrue(any("indispensabili" in reason for reason in r["reason"]))

    def test_only_one_score_missing_indispensable_does_not_force_wait(self):
        indispensable_score1 = [f"{k}.{m['name']}" for k, cat in sl.SCORE1_CATEGORIES.items() for m in cat["metrics"] if m.get("indispensable")]
        r = de.compute_decision(
            score1_result=_score(non_mature=indispensable_score1),
            score2_result=_score2_indispensable_ok(),
            confidence1=_conf(ce.LABEL_HIGH), confidence2=_conf(ce.LABEL_HIGH),
            divergence_result=_div(ds.STATE_UNSUPPORTED_SPECULATIVE_RALLY, trend_e="STRONG_UP"),
            record=False, confirm_n=1,
        )
        self.assertEqual(r["raw_decision"], de.DECISION_SPECULATIVE_RALLY)


class TestMissingExternalInputs(unittest.TestCase):
    def test_distribution_risk_never_fires_without_external_signals(self):
        r = _decide(ds.STATE_STRUCTURAL_BEARISH_DIVERGENCE, trend_score1="DOWN", trend_e="UP")
        self.assertNotEqual(r["raw_decision"], de.DECISION_DISTRIBUTION_RISK)
        self.assertEqual(r["raw_decision"], de.DECISION_STRUCTURAL_WEAKNESS)

    def test_inputs_missing_lists_absent_external_keys(self):
        r = _decide(ds.STATE_NO_CLEAR_DIVERGENCE)
        for key in ("rotation_state", "fear_greed_extreme_euphoria", "market_score_status",
                    "altseason_state", "btc_dominance_trend", "eth_btc_trend"):
            self.assertIn(key, r["inputs_missing"])
        self.assertNotIn("rotation_state", r["inputs_used"])

    def test_inputs_used_includes_provided_external_keys(self):
        r = _decide(
            ds.STATE_STRUCTURAL_BEARISH_DIVERGENCE, trend_score1="DOWN", trend_e="UP",
            external_signals={"rotation_state": "DISTRIBUTION_WARNING", "fear_greed_extreme_euphoria": True},
        )
        self.assertIn("rotation_state", r["inputs_used"])
        self.assertIn("fear_greed_extreme_euphoria", r["inputs_used"])
        self.assertNotIn("rotation_state", r["inputs_missing"])


class TestContradictorySignals(unittest.TestCase):
    def test_contradictory_signals_never_crash_and_produce_valid_state(self):
        r = _decide(ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, trend_score1="DOWN", trend_f="UP", trend_e="STRONG_UP")
        valid = (
            de.DECISION_DISTRIBUTION_RISK, de.DECISION_SPECULATIVE_RALLY, de.DECISION_STRUCTURAL_WEAKNESS,
            de.DECISION_XRP_NOT_CAPTURING_VALUE, de.DECISION_STRONG_STRUCTURAL_BULLISH,
            de.DECISION_STRUCTURAL_BULLISH, de.DECISION_EARLY_INSTITUTIONAL_ADOPTION, de.DECISION_WAIT,
        )
        self.assertIn(r["raw_decision"], valid)


class TestPriorityRiskVsBullish(unittest.TestCase):
    def test_structural_weakness_wins_over_adoption_confirmed_pattern_if_score1_down(self):
        r = _decide(ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, trend_score1="DOWN", trend_f="UP", trend_e="UP")
        self.assertEqual(r["raw_decision"], de.DECISION_STRUCTURAL_WEAKNESS)


class TestAntiFlicker(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "decision.jsonl")

    def test_not_committed_before_confirm_n(self):
        kwargs = dict(
            score1_result=_score1_indispensable_ok(), score2_result=_score2_indispensable_ok(),
            confidence1=_conf(ce.LABEL_HIGH), confidence2=_conf(ce.LABEL_HIGH),
            divergence_result=_div(ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "UP", "UP", "UP"),
            record=True, state_path=self.state_path, confirm_n=3,
        )
        r1 = de.compute_decision(**kwargs)
        self.assertEqual(r1["confirmation_streak"], 1)
        self.assertFalse(r1["confirmed"])
        self.assertEqual(r1["decision"], de.DECISION_WAIT)

        r2 = de.compute_decision(**kwargs)
        self.assertEqual(r2["confirmation_streak"], 2)
        self.assertFalse(r2["confirmed"])

        r3 = de.compute_decision(**kwargs)
        self.assertEqual(r3["confirmation_streak"], 3)
        self.assertTrue(r3["confirmed"])
        self.assertEqual(r3["decision"], r3["raw_decision"])

    def test_streak_resets_on_different_raw_decision(self):
        kwargs_a = dict(
            score1_result=_score1_indispensable_ok(), score2_result=_score2_indispensable_ok(),
            confidence1=_conf(ce.LABEL_HIGH), confidence2=_conf(ce.LABEL_HIGH),
            divergence_result=_div(ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "UP", "UP", "UP"),
            record=True, state_path=self.state_path, confirm_n=3,
        )
        kwargs_b = dict(kwargs_a, divergence_result=_div(ds.STATE_NO_CLEAR_DIVERGENCE))

        de.compute_decision(**kwargs_a)
        r2 = de.compute_decision(**kwargs_b)
        self.assertEqual(r2["confirmation_streak"], 1)


class TestNoInputMutation(unittest.TestCase):
    def test_inputs_not_mutated(self):
        score1 = _score1_indispensable_ok()
        score2 = _score2_indispensable_ok()
        conf1 = _conf(ce.LABEL_HIGH)
        conf2 = _conf(ce.LABEL_HIGH)
        divergence = _div(ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, "UP", "UP", "UP")

        score1_copy = copy.deepcopy(score1)
        score2_copy = copy.deepcopy(score2)
        conf1_copy = copy.deepcopy(conf1)
        conf2_copy = copy.deepcopy(conf2)
        divergence_copy = copy.deepcopy(divergence)

        de.compute_decision(
            score1_result=score1, score2_result=score2,
            confidence1=conf1, confidence2=conf2, divergence_result=divergence,
            record=False, confirm_n=1,
        )

        self.assertEqual(score1, score1_copy)
        self.assertEqual(score2, score2_copy)
        self.assertEqual(conf1, conf1_copy)
        self.assertEqual(conf2, conf2_copy)
        self.assertEqual(divergence, divergence_copy)


class TestNoTelegramOrSideEffects(unittest.TestCase):
    def test_module_does_not_import_altseason_bot(self):
        import sys
        self.assertNotIn("altseason_bot", sys.modules)

    def test_module_imports_are_safe(self):
        import xrpl_decision_engine
        with open(xrpl_decision_engine.__file__, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn("import altseason_bot", src)
        self.assertNotIn("import telegram", src.lower())
        self.assertNotIn("from telegram", src.lower())


class TestOutputShape(unittest.TestCase):
    def test_required_fields_present(self):
        r = _decide(ds.STATE_NO_CLEAR_DIVERGENCE)
        for key in ("decision", "risk_level", "confidence", "reason", "inputs_used",
                    "inputs_missing", "confirmed", "confirmation_streak"):
            self.assertIn(key, r)

    def test_decision_is_one_of_eight_states(self):
        r = _decide(ds.STATE_NO_CLEAR_DIVERGENCE)
        valid = (
            de.DECISION_DISTRIBUTION_RISK, de.DECISION_SPECULATIVE_RALLY, de.DECISION_STRUCTURAL_WEAKNESS,
            de.DECISION_XRP_NOT_CAPTURING_VALUE, de.DECISION_STRONG_STRUCTURAL_BULLISH,
            de.DECISION_STRUCTURAL_BULLISH, de.DECISION_EARLY_INSTITUTIONAL_ADOPTION, de.DECISION_WAIT,
        )
        self.assertIn(r["decision"], valid)

    def test_no_buy_sell_language_in_reasons(self):
        r = _decide(ds.STATE_ADOPTION_CONFIRMED_AND_PRICED, trend_score1="UP", trend_f="UP", trend_e="UP")
        joined = " ".join(r["reason"]).upper()
        self.assertNotIn("BUY", joined)
        self.assertNotIn("SELL", joined)
        self.assertNotIn("COMPRA", joined)
        self.assertNotIn("VENDI", joined)


class TestRealIntegration(unittest.TestCase):
    def test_real_layers_never_raise(self):
        try:
            r = de.compute_decision(record=False)
        except Exception as e:
            self.fail(f"integrazione reale ha sollevato un'eccezione: {e}")
        self.assertIn("decision", r)


if __name__ == "__main__":
    unittest.main(verbosity=2)
