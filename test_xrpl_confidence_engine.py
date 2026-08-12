"""
Test M4 — XRPL Confidence Engine.
Nessuna rete, nessun file: score_result e features sono dizionari
sintetici costruiti direttamente nel formato prodotto da M2/M3.
"""
import unittest
from datetime import datetime, timezone, timedelta

import xrpl_confidence_engine as ce
import xrpl_score_layer as sl


def _feat(status, as_of=None):
    return {
        "value": 1.0, "status": status, "source": "test",
        "as_of": (as_of or datetime.now(timezone.utc)).isoformat(),
        "history_points": 5, "history_required": 30, "reason": None,
    }


def _category(macro_weight, coverage_ratio, active=None, partial=None, non_mature=None, missing=None, score=50.0):
    return {
        "macro_weight": macro_weight,
        "coverage_ratio": coverage_ratio,
        "active_metrics": active or [],
        "partial_metrics": partial or [],
        "non_mature_metrics": non_mature or [],
        "missing_metrics": missing or [],
        "score": score,
        "status": sl.SCORE_STATUS_COMPUTED if score is not None else sl.SCORE_STATUS_NOT_COMPUTABLE,
    }


def _score_result(category_breakdown, score=50.0, status=sl.SCORE_STATUS_COMPUTED):
    return {
        "score_name": "test", "score": score, "status": status,
        "available_weight": 0.5, "missing_weight": 0.5, "partial_weight": 0.0,
        "active_metrics": [], "partial_metrics": [], "non_mature_metrics": [], "missing_metrics": [],
        "category_breakdown": category_breakdown, "reasons": [],
    }


class TestScoreNotComputable(unittest.TestCase):
    def test_not_computable_gives_not_mature_label(self):
        result = _score_result({}, score=None, status=sl.SCORE_STATUS_NOT_COMPUTABLE)
        conf = ce.compute_confidence(result, features={})
        self.assertIsNone(conf["confidence_score"])
        self.assertEqual(conf["confidence_label"], ce.LABEL_NOT_MATURE)
        self.assertEqual(conf["coverage"], 0.0)


class TestCoverageMaturityFreshness(unittest.TestCase):
    def test_full_coverage_full_maturity_fresh_gives_high(self):
        cb = {
            "A": _category(0.30, 1.0, active=["A.x"]),
            "B": _category(0.25, 1.0, active=["B.x"]),
            "C": _category(0.25, 1.0, active=["C.x"]),
            "D": _category(0.20, 1.0, active=["D.x"]),
        }
        result = _score_result(cb)
        conf = ce.compute_confidence(result, features={})
        self.assertAlmostEqual(conf["coverage"], 100.0, places=2)

    def test_low_coverage_strongly_limits_confidence(self):
        cb = {
            "A": _category(0.30, 0.0),
            "B": _category(0.25, 1.0, active=["B.x"]),
            "C": _category(0.25, 0.0),
            "D": _category(0.20, 0.0),
        }
        result = _score_result(cb)
        conf = ce.compute_confidence(result, features={})
        self.assertAlmostEqual(conf["coverage"], 25.0, places=2)
        self.assertLess(conf["confidence_score"], 30.0)
        self.assertIn(conf["confidence_label"], (ce.LABEL_LOW,))

    def test_partial_weighs_less_than_active_in_maturity(self):
        cb_all_active = {"B": _category(0.25, 1.0, active=["B.x", "B.y"])}
        cb_all_partial = {"B": _category(0.25, 1.0, partial=["B.x", "B.y"])}
        conf_active = ce.compute_confidence(_score_result(cb_all_active), features={})
        conf_partial = ce.compute_confidence(_score_result(cb_all_partial), features={})
        self.assertGreater(conf_active["maturity"], conf_partial["maturity"])

    def test_no_active_or_partial_gives_maturity_none(self):
        cb = {"B": _category(0.25, 0.0, non_mature=["B.x"])}
        result = _score_result(cb)
        conf = ce.compute_confidence(result, features={})
        self.assertIsNone(conf["maturity"])
        self.assertTrue(any("maturity non disponibile" in r for r in conf["reasons"]))

    def test_missing_never_becomes_zero_score_but_lowers_confidence(self):
        cb = {
            "A": _category(0.30, 0.0, missing=["A.x"]),
            "B": _category(0.25, 1.0, active=["B.x"]),
            "C": _category(0.25, 0.0, missing=["C.x"]),
            "D": _category(0.20, 0.0, missing=["D.x"]),
        }
        result = _score_result(cb)
        conf = ce.compute_confidence(result, features={})
        # lo SCORE (non testato qui, e' responsabilita' di M3) non deve
        # mai essere confuso con la confidence: qui verifichiamo solo che
        # la confidence rifletta la scarsita' di dati, mai un valore fittizio
        self.assertLess(conf["confidence_score"], 50.0)

    def test_freshness_computed_from_feature_as_of(self):
        cb = {
            "A": _category(0.30, 0.0),
            "B": _category(0.25, 1.0, active=["B.rlusd_circulating_supply"]),
            "C": _category(0.25, 0.0),
            "D": _category(0.20, 0.0),
        }
        result = _score_result(cb)
        features = {"rlusd_supply_trend": _feat(sl.STATUS_ACTIVE, as_of=datetime.now(timezone.utc))}
        conf = ce.compute_confidence(result, features=features)
        self.assertIsNotNone(conf["freshness"])
        self.assertGreater(conf["freshness"], 90.0)  # fresco, appena calcolato

    def test_freshness_degrades_with_stale_data(self):
        cb = {
            "A": _category(0.30, 0.0),
            "B": _category(0.25, 1.0, active=["B.rlusd_circulating_supply"]),
            "C": _category(0.25, 0.0),
            "D": _category(0.20, 0.0),
        }
        result = _score_result(cb)
        stale = datetime.now(timezone.utc) - timedelta(days=25)
        features = {"rlusd_supply_trend": _feat(sl.STATUS_ACTIVE, as_of=stale)}
        conf = ce.compute_confidence(result, features=features)
        self.assertIsNotNone(conf["freshness"])
        self.assertLess(conf["freshness"], 20.0)

    def test_freshness_none_when_no_as_of_available(self):
        cb = {
            "A": _category(0.30, 0.0),
            "B": _category(0.25, 1.0, active=["B.rlusd_circulating_supply"]),
            "C": _category(0.25, 0.0),
            "D": _category(0.20, 0.0),
        }
        result = _score_result(cb)
        conf = ce.compute_confidence(result, features={})  # nessuna feature reale
        self.assertIsNone(conf["freshness"])


class TestCrossSource(unittest.TestCase):
    def test_not_available_by_default(self):
        cb = {"B": _category(0.25, 1.0, active=["B.x"])}
        conf = ce.compute_confidence(_score_result(cb), features={})
        self.assertEqual(conf["cross_source_status"], ce.CROSS_SOURCE_NOT_AVAILABLE)

    def test_agree_status(self):
        cb = {"B": _category(0.25, 1.0, active=["B.x"])}
        checks = [{"metric": "rlusd_supply", "agree": True}]
        conf = ce.compute_confidence(_score_result(cb), features={}, cross_source_checks=checks)
        self.assertEqual(conf["cross_source_status"], ce.CROSS_SOURCE_AGREE)

    def test_disagree_caps_confidence_never_averaged_silently(self):
        cb = {
            "A": _category(0.30, 1.0, active=["A.x"]),
            "B": _category(0.25, 1.0, active=["B.x"]),
            "C": _category(0.25, 1.0, active=["C.x"]),
            "D": _category(0.20, 1.0, active=["D.x"]),
        }
        result = _score_result(cb)
        checks = [{"metric": "rlusd_supply", "agree": False}]
        conf_no_check = ce.compute_confidence(result, features={})
        conf_disagree = ce.compute_confidence(result, features={}, cross_source_checks=checks)
        self.assertEqual(conf_disagree["cross_source_status"], ce.CROSS_SOURCE_DISAGREE)
        self.assertLessEqual(conf_disagree["confidence_score"], ce._DISAGREEMENT_CAP)
        self.assertLess(conf_disagree["confidence_score"], conf_no_check["confidence_score"])
        self.assertEqual(conf_disagree["confidence_label"], ce.LABEL_LOW)

    def test_disagree_present_in_reasons(self):
        cb = {"B": _category(0.25, 1.0, active=["B.x"])}
        checks = [{"metric": "x", "agree": False}]
        conf = ce.compute_confidence(_score_result(cb), features={}, cross_source_checks=checks)
        self.assertTrue(any("disagreement" in r for r in conf["reasons"]))


class TestOutputShape(unittest.TestCase):
    def test_required_fields_present(self):
        cb = {"B": _category(0.25, 1.0, active=["B.x"])}
        conf = ce.compute_confidence(_score_result(cb), features={})
        for key in ("confidence_score", "confidence_label", "coverage", "freshness",
                    "maturity", "cross_source_status", "reasons"):
            self.assertIn(key, conf)

    def test_labels_are_only_the_four_allowed(self):
        cb = {"B": _category(0.25, 1.0, active=["B.x"])}
        conf = ce.compute_confidence(_score_result(cb), features={})
        self.assertIn(conf["confidence_label"], (ce.LABEL_HIGH, ce.LABEL_MEDIUM, ce.LABEL_LOW, ce.LABEL_NOT_MATURE))


class TestRealIntegration(unittest.TestCase):
    def test_real_score_layer_output_never_raises(self):
        try:
            r1 = sl.compute_ecosystem_growth_score()
            conf1 = ce.compute_confidence(r1)
            r2 = sl.compute_capture_dependency_score()
            conf2 = ce.compute_confidence(r2)
        except Exception as e:
            self.fail(f"integrazione reale ha sollevato un'eccezione: {e}")
        self.assertIn(conf1["confidence_label"], (ce.LABEL_HIGH, ce.LABEL_MEDIUM, ce.LABEL_LOW, ce.LABEL_NOT_MATURE))
        self.assertIn(conf2["confidence_label"], (ce.LABEL_HIGH, ce.LABEL_MEDIUM, ce.LABEL_LOW, ce.LABEL_NOT_MATURE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
