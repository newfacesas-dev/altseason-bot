"""
Test M3 — XRPL Score Layer.
Nessuna rete, nessun accesso ai RAW: le feature sono dizionari sintetici
passati direttamente (stesso formato prodotto da xrpl_feature_engine.py),
usando il parametro di test 'features' esposto dalle funzioni pubbliche.
"""
import unittest
from datetime import datetime, timezone

import xrpl_score_layer as sl


def _feat(status, value=None, as_of=None, reason=None):
    return {
        "value": value,
        "status": status,
        "source": "test",
        "as_of": (as_of or datetime.now(timezone.utc)).isoformat(),
        "history_points": 5 if status in (sl.STATUS_ACTIVE, sl.STATUS_PARTIAL) else 0,
        "history_required": 30,
        "reason": reason,
    }


def _all_missing_features():
    keys = set()
    for categories in (sl.SCORE1_CATEGORIES, sl.SCORE2_CATEGORIES):
        for cat in categories.values():
            for m in cat["metrics"]:
                if m["feature_key"]:
                    keys.add(m["feature_key"])
    return {k: _feat(sl.STATUS_MISSING, reason="test: missing di default") for k in keys}


class TestWeightSums(unittest.TestCase):
    def test_score1_category_weights_sum_to_one(self):
        for key, cat in sl.SCORE1_CATEGORIES.items():
            total = sum(m["weight"] for m in cat["metrics"])
            self.assertAlmostEqual(total, 1.0, places=6, msg=f"categoria {key} non somma a 1.0")

    def test_score2_category_weights_sum_to_one(self):
        for key, cat in sl.SCORE2_CATEGORIES.items():
            total = sum(m["weight"] for m in cat["metrics"])
            self.assertAlmostEqual(total, 1.0, places=6, msg=f"categoria {key} non somma a 1.0")

    def test_score1_macro_weights_sum_to_one(self):
        total = sum(c["macro_weight"] for c in sl.SCORE1_CATEGORIES.values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_score2_macro_weights_sum_to_one(self):
        total = sum(c["macro_weight"] for c in sl.SCORE2_CATEGORIES.values())
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_score1_macro_weights_match_approved_values(self):
        self.assertAlmostEqual(sl.SCORE1_CATEGORIES["A"]["macro_weight"], 0.30)
        self.assertAlmostEqual(sl.SCORE1_CATEGORIES["B"]["macro_weight"], 0.25)
        self.assertAlmostEqual(sl.SCORE1_CATEGORIES["C"]["macro_weight"], 0.25)
        self.assertAlmostEqual(sl.SCORE1_CATEGORIES["D"]["macro_weight"], 0.20)

    def test_score2_macro_weights_match_approved_values(self):
        self.assertAlmostEqual(sl.SCORE2_CATEGORIES["F"]["macro_weight"], 0.60)
        self.assertAlmostEqual(sl.SCORE2_CATEGORIES["E"]["macro_weight"], 0.40)


class TestZscoreToPercentile(unittest.TestCase):
    def test_zero_is_fifty(self):
        self.assertAlmostEqual(sl._zscore_to_percentile(0), 50.0, places=4)

    def test_positive_above_fifty(self):
        self.assertGreater(sl._zscore_to_percentile(1), 50.0)

    def test_negative_below_fifty(self):
        self.assertLess(sl._zscore_to_percentile(-1), 50.0)

    def test_none_input(self):
        self.assertIsNone(sl._zscore_to_percentile(None))

    def test_extreme_clipped_to_range(self):
        self.assertLessEqual(sl._zscore_to_percentile(50), 100.0)
        self.assertGreaterEqual(sl._zscore_to_percentile(-50), 0.0)

    def test_non_numeric(self):
        self.assertIsNone(sl._zscore_to_percentile("abc"))

    # --- valori noti: calibrazione MAD grezzo -> z standard -> percentile ---

    def test_known_value_z_raw_one_gives_75_not_84(self):
        # Prima della correzione: Phi(1.0) = 84.13 (SBAGLIATO per un MAD grezzo).
        # Dopo la correzione: z_std = 0.6744897501960816 * 1.0 -> Phi(z_std) = 75.0
        result = sl._zscore_to_percentile(1.0)
        self.assertAlmostEqual(result, 75.0, places=3)
        self.assertNotAlmostEqual(result, 84.1345, places=1)

    def test_known_value_z_raw_minus_one_gives_25(self):
        result = sl._zscore_to_percentile(-1.0)
        self.assertAlmostEqual(result, 25.0, places=3)

    def test_known_value_mad_to_sigma_factor_matches_verified_constant(self):
        # Phi^-1(0.75) verificato numericamente = 0.6744897501960816,
        # non assunto a memoria: ricontrollo qui che il modulo usi
        # esattamente questo valore, non una costante diversa.
        self.assertAlmostEqual(sl._MAD_TO_STANDARD_Z_FACTOR, 0.6744897501960816, places=12)

    def test_known_value_z_raw_at_scaled_factor_gives_fifty_after_double_scaling_sanity(self):
        # z_raw tale che z_std=0 -> deve dare esattamente 50
        self.assertAlmostEqual(sl._zscore_to_percentile(0.0), 50.0, places=6)


class TestTxPaymentActivityNoLongerAliasesBurnRate(unittest.TestCase):
    def test_tx_payment_activity_feature_key_is_none(self):
        metric = next(
            m for m in sl.SCORE1_CATEGORIES["D"]["metrics"] if m["name"] == "tx_payment_activity"
        )
        self.assertIsNone(metric["feature_key"])
        self.assertIsNone(metric["normalization"])

    def test_tx_payment_activity_always_missing_even_if_burn_rate_active(self):
        # anche se burn_rate (usato da F.fee_burn_per_tx) fosse ACTIVE,
        # tx_payment_activity NON deve piu' riusarlo: deve restare MISSING.
        features = _all_missing_features()
        features["burn_rate"] = _feat(sl.STATUS_ACTIVE, value=42.0)
        result = sl.compute_ecosystem_growth_score(features=features)
        self.assertIn("D.tx_payment_activity", result["missing_metrics"])
        self.assertNotIn("D.tx_payment_activity", result["active_metrics"])
        cat_d = result["category_breakdown"]["D"]
        for r in cat_d["reasons"]:
            if "tx_payment_activity" in r:
                self.assertIn("non ancora implementata", r)


class TestNoDataAtAll(unittest.TestCase):
    def test_ecosystem_growth_not_computable_with_empty_features(self):
        result = sl.compute_ecosystem_growth_score(features={})
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], sl.SCORE_STATUS_NOT_COMPUTABLE)
        self.assertEqual(result["confidence"]["confidence_label"], sl.CONFIDENCE_LOW_FORCED)

    def test_capture_dependency_not_computable_with_empty_features(self):
        result = sl.compute_capture_dependency_score(features={})
        self.assertIsNone(result["score"])
        self.assertEqual(result["status"], sl.SCORE_STATUS_NOT_COMPUTABLE)

    def test_all_missing_features_never_produce_zero_score(self):
        result = sl.compute_ecosystem_growth_score(features=_all_missing_features())
        self.assertIsNone(result["score"], "uno score MISSING deve essere None, mai 0")
        for cat in result["category_breakdown"].values():
            self.assertIsNone(cat["score"], f"categoria {cat['category']} deve essere None, mai 0")


class TestAllActive(unittest.TestCase):
    def test_ecosystem_growth_computed_with_zscore_metrics_active(self):
        features = _all_missing_features()
        features["rwa_value_trend"] = _feat(sl.STATUS_ACTIVE, value=1.0)
        features["rlusd_supply_trend"] = _feat(sl.STATUS_ACTIVE, value=-1.0)
        result = sl.compute_ecosystem_growth_score(features=features)
        self.assertEqual(result["status"], sl.SCORE_STATUS_COMPUTED)
        self.assertIsNotNone(result["score"])
        self.assertIn("A.rwa_distributed", result["active_metrics"])
        self.assertIn("B.rlusd_circulating_supply", result["active_metrics"])
        cat_a = result["category_breakdown"]["A"]
        self.assertAlmostEqual(cat_a["coverage_ratio"], 0.55, places=4)
        cat_b = result["category_breakdown"]["B"]
        self.assertAlmostEqual(cat_b["coverage_ratio"], 1.0, places=4)
        self.assertAlmostEqual(cat_b["score"], sl._zscore_to_percentile(-1.0), places=4)

    def test_unavailable_normalization_metrics_stay_non_mature_even_if_m2_active(self):
        features = _all_missing_features()
        features["dex_volume_growth"] = _feat(sl.STATUS_ACTIVE, value=12.5)
        result = sl.compute_ecosystem_growth_score(features=features)
        self.assertIn("C.dex_volume", result["non_mature_metrics"])
        self.assertNotIn("C.dex_volume", result["active_metrics"])


class TestMixActivePartial(unittest.TestCase):
    def test_partial_counts_half_weight(self):
        features = _all_missing_features()
        features["rlusd_supply_trend"] = _feat(sl.STATUS_PARTIAL, value=0.0)
        result = sl.compute_ecosystem_growth_score(features=features)
        cat_b = result["category_breakdown"]["B"]
        self.assertIn("B.rlusd_circulating_supply", cat_b["partial_metrics"])
        self.assertAlmostEqual(cat_b["available_weight"], 0.5, places=4)
        self.assertAlmostEqual(cat_b["partial_weight"], 0.5, places=4)
        self.assertAlmostEqual(cat_b["score"], 50.0, places=2)

    def test_mix_active_and_partial_across_categories(self):
        features = _all_missing_features()
        features["rwa_value_trend"] = _feat(sl.STATUS_ACTIVE, value=2.0)
        features["rlusd_supply_trend"] = _feat(sl.STATUS_PARTIAL, value=0.5)
        result = sl.compute_ecosystem_growth_score(features=features)
        self.assertIn("A.rwa_distributed", result["active_metrics"])
        self.assertIn("B.rlusd_circulating_supply", result["partial_metrics"])
        self.assertEqual(result["status"], sl.SCORE_STATUS_COMPUTED)
        self.assertGreater(result["partial_weight"], 0.0)
        self.assertGreater(result["available_weight"], 0.0)


class TestNonMature(unittest.TestCase):
    def test_non_mature_excluded_from_numerator_and_denominator(self):
        features = _all_missing_features()
        features["rlusd_supply_trend"] = _feat(sl.STATUS_NON_MATURE, value=None, reason="storico insufficiente")
        result = sl.compute_ecosystem_growth_score(features=features)
        cat_b = result["category_breakdown"]["B"]
        self.assertEqual(cat_b["available_weight"], 0.0)
        self.assertIn("B.rlusd_circulating_supply", cat_b["non_mature_metrics"])
        self.assertEqual(cat_b["status"], sl.SCORE_STATUS_NOT_COMPUTABLE)


class TestMissing(unittest.TestCase):
    def test_missing_excluded_and_never_zero(self):
        features = _all_missing_features()
        result = sl.compute_capture_dependency_score(features=features)
        self.assertIsNone(result["score"])
        for name in result["missing_metrics"]:
            self.assertNotIn(name, result["active_metrics"])
            self.assertNotIn(name, result["partial_metrics"])


class TestWholeCategoryAbsent(unittest.TestCase):
    def test_category_with_zero_data_excluded_from_macro_aggregation(self):
        features = _all_missing_features()
        features["rlusd_supply_trend"] = _feat(sl.STATUS_ACTIVE, value=0.0)
        result = sl.compute_ecosystem_growth_score(features=features)
        self.assertEqual(result["status"], sl.SCORE_STATUS_COMPUTED)
        self.assertAlmostEqual(result["score"], 50.0, places=2)
        self.assertEqual(result["category_breakdown"]["A"]["status"], sl.SCORE_STATUS_NOT_COMPUTABLE)
        self.assertEqual(result["category_breakdown"]["C"]["status"], sl.SCORE_STATUS_NOT_COMPUTABLE)
        self.assertEqual(result["category_breakdown"]["D"]["status"], sl.SCORE_STATUS_NOT_COMPUTABLE)


class TestVeryLowCoverage(unittest.TestCase):
    def test_low_coverage_score_computed_but_low_confidence(self):
        features = _all_missing_features()
        features["rlusd_supply_trend"] = _feat(sl.STATUS_ACTIVE, value=0.0)
        result = sl.compute_ecosystem_growth_score(features=features)
        self.assertEqual(result["status"], sl.SCORE_STATUS_COMPUTED)
        self.assertIsNotNone(result["score"])
        self.assertLess(result["confidence"]["confidence_score"], 50.0)
        self.assertIn(
            result["confidence"]["confidence_label"],
            (sl.CONFIDENCE_LOW, sl.CONFIDENCE_LOW_FORCED),
        )

    def test_category_low_internal_coverage_reflected_in_coverage_ratio(self):
        features = _all_missing_features()
        features["rwa_value_trend"] = _feat(sl.STATUS_ACTIVE, value=0.0)
        result = sl.compute_ecosystem_growth_score(features=features)
        cat_a = result["category_breakdown"]["A"]
        self.assertLess(cat_a["coverage_ratio"], 1.0)
        self.assertAlmostEqual(cat_a["coverage_ratio"], 0.55, places=4)


class TestIndispensableAndForcedLowConfidence(unittest.TestCase):
    def test_all_indispensable_missing_forces_low_confidence_even_if_score_computable(self):
        features = _all_missing_features()
        result = sl.compute_ecosystem_growth_score(features=features)
        self.assertTrue(result["confidence"]["forced_low_confidence"])
        self.assertEqual(result["confidence"]["confidence_label"], sl.CONFIDENCE_LOW_FORCED)
        self.assertIn("rwa_value_trend", result["confidence"]["indispensable_missing"])
        self.assertIn("rlusd_supply_trend", result["confidence"]["indispensable_missing"])

    def test_capture_dependency_indispensable_relative_strength(self):
        features = _all_missing_features()
        result = sl.compute_capture_dependency_score(features=features)
        self.assertIn("xrp_btc_relative_strength", result["confidence"]["indispensable_missing"])
        self.assertTrue(result["confidence"]["forced_low_confidence"])


class TestScore2StructurallyNotComputableToday(unittest.TestCase):
    def test_even_active_relative_strength_stays_non_mature_for_scoring(self):
        features = _all_missing_features()
        features["xrp_btc_relative_strength"] = _feat(sl.STATUS_ACTIVE, value=3.2)
        features["xrp_eth_relative_strength"] = _feat(sl.STATUS_ACTIVE, value=-1.1)
        result = sl.compute_capture_dependency_score(features=features)
        self.assertIn("E.xrp_btc_relative_strength", result["non_mature_metrics"])
        self.assertIn("E.xrp_eth_relative_strength", result["non_mature_metrics"])
        self.assertEqual(result["status"], sl.SCORE_STATUS_NOT_COMPUTABLE)
        self.assertIsNone(result["score"])


class TestReasonsAndOutputShape(unittest.TestCase):
    def test_required_top_level_fields_present(self):
        result = sl.compute_ecosystem_growth_score(features=_all_missing_features())
        required = (
            "score", "status", "confidence", "available_weight", "missing_weight",
            "partial_weight", "active_metrics", "partial_metrics", "non_mature_metrics",
            "missing_metrics", "category_breakdown", "reasons",
        )
        for key in required:
            self.assertIn(key, result, f"campo mancante: {key}")

    def test_confidence_is_separate_object_not_merged_into_score(self):
        result = sl.compute_ecosystem_growth_score(features=_all_missing_features())
        self.assertIsInstance(result["confidence"], dict)
        self.assertIn("confidence_score", result["confidence"])
        self.assertIn("confidence_label", result["confidence"])
        self.assertNotIn("confidence_score", result)

    def test_reasons_is_nonempty_list_of_strings(self):
        result = sl.compute_ecosystem_growth_score(features=_all_missing_features())
        self.assertIsInstance(result["reasons"], list)
        self.assertGreater(len(result["reasons"]), 0)
        for r in result["reasons"]:
            self.assertIsInstance(r, str)

    def test_category_breakdown_has_all_categories(self):
        result = sl.compute_ecosystem_growth_score(features=_all_missing_features())
        self.assertEqual(set(result["category_breakdown"].keys()), {"A", "B", "C", "D"})
        result2 = sl.compute_capture_dependency_score(features=_all_missing_features())
        self.assertEqual(set(result2["category_breakdown"].keys()), {"F", "E"})


class TestRealFeatureEngineIntegration(unittest.TestCase):
    def test_compute_ecosystem_growth_score_with_real_feature_engine_never_raises(self):
        try:
            result = sl.compute_ecosystem_growth_score()
        except Exception as e:
            self.fail(f"compute_ecosystem_growth_score con feature engine reale ha sollevato: {e}")
        self.assertIn(result["status"], (sl.SCORE_STATUS_COMPUTED, sl.SCORE_STATUS_NOT_COMPUTABLE))

    def test_compute_capture_dependency_score_with_real_feature_engine_never_raises(self):
        try:
            result = sl.compute_capture_dependency_score()
        except Exception as e:
            self.fail(f"compute_capture_dependency_score con feature engine reale ha sollevato: {e}")
        self.assertIn(result["status"], (sl.SCORE_STATUS_COMPUTED, sl.SCORE_STATUS_NOT_COMPUTABLE))


if __name__ == "__main__":
    unittest.main(verbosity=2)
