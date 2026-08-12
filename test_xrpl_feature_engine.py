"""
Test M2 — XRPL Feature Engine.
Nessuna rete: gli snapshot RAW sono sintetici, scritti su file temporaneo
con lo stesso formato prodotto da M1.
"""
import os
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import xrpl_raw_data_layer as raw
import xrpl_feature_engine as fe


def _iso(dt):
    return dt.isoformat()


def _snap(ts, rlusd_supply=None, amm_lp_value=None, rwa_error="RWA_XYZ_API_KEY non configurata (test)"):
    sources = {
        "xrpl_native": {},
        "defillama": {},
        "rwa_xyz": {
            "assets_xrpl": {
                "status": "SOURCE_UNAVAILABLE",
                "source": "rwa_xyz.assets",
                "data": None,
                "error": rwa_error,
            }
        },
    }
    if rlusd_supply is not None:
        sources["xrpl_native"]["gateway_balances_rlusd"] = {
            "status": "RAW_AVAILABLE",
            "source": "xrpl.gateway_balances",
            "data": {"account": "rTEST", "obligations": {raw._RLUSD_CURRENCY_HEX: str(rlusd_supply)}},
            "error": None,
        }
    else:
        sources["xrpl_native"]["gateway_balances_rlusd"] = {
            "status": "SOURCE_UNAVAILABLE", "source": "xrpl.gateway_balances", "data": None, "error": "test-down",
        }
    if amm_lp_value is not None:
        sources["xrpl_native"]["amm_info_xrp_rlusd"] = {
            "status": "RAW_AVAILABLE",
            "source": "xrpl.amm_info",
            "data": {"amm": {"lp_token": {"value": str(amm_lp_value)}}},
            "error": None,
        }
    else:
        sources["xrpl_native"]["amm_info_xrp_rlusd"] = {
            "status": "SOURCE_UNAVAILABLE", "source": "xrpl.amm_info", "data": None, "error": "test-down",
        }
    return {"timestamp_utc": _iso(ts), "sources": sources}


class TestToolkit(unittest.TestCase):
    def test_growth_pct_basic(self):
        self.assertAlmostEqual(fe.growth_pct(110, 100), 10.0)

    def test_growth_pct_none_current(self):
        self.assertIsNone(fe.growth_pct(None, 100))

    def test_growth_pct_none_base(self):
        self.assertIsNone(fe.growth_pct(100, None))

    def test_growth_pct_zero_base(self):
        self.assertIsNone(fe.growth_pct(100, 0))

    def test_growth_pct_tiny_base(self):
        self.assertIsNone(fe.growth_pct(100, 1e-12))

    def test_growth_pct_non_numeric(self):
        self.assertIsNone(fe.growth_pct("abc", 100))
        self.assertIsNone(fe.growth_pct(100, "abc"))

    def test_growth_pct_negative_base(self):
        self.assertAlmostEqual(fe.growth_pct(-90, -100), -10.0)

    def test_acceleration_basic(self):
        self.assertAlmostEqual(fe.acceleration(10, 4), 6.0)

    def test_acceleration_none(self):
        self.assertIsNone(fe.acceleration(None, 4))
        self.assertIsNone(fe.acceleration(10, None))

    def test_velocity_basic(self):
        self.assertAlmostEqual(fe.velocity(110, 100, 2), 5.0)

    def test_velocity_none_inputs(self):
        self.assertIsNone(fe.velocity(None, 100, 2))
        self.assertIsNone(fe.velocity(110, None, 2))
        self.assertIsNone(fe.velocity(110, 100, None))

    def test_velocity_zero_dt(self):
        self.assertIsNone(fe.velocity(110, 100, 0))

    def test_velocity_negative_dt(self):
        self.assertIsNone(fe.velocity(110, 100, -1))

    def test_ratio_basic(self):
        self.assertAlmostEqual(fe.ratio(25, 50), 50.0)

    def test_ratio_zero_denominator(self):
        self.assertIsNone(fe.ratio(25, 0))

    def test_ratio_none(self):
        self.assertIsNone(fe.ratio(None, 50))
        self.assertIsNone(fe.ratio(25, None))

    def test_trend_vs_ma_basic(self):
        z = fe.trend_vs_ma(8, [4, 5, 6])
        self.assertAlmostEqual(z, 3.0)

    def test_trend_vs_ma_insufficient_window(self):
        self.assertIsNone(fe.trend_vs_ma(8, [5]))
        self.assertIsNone(fe.trend_vs_ma(8, []))

    def test_trend_vs_ma_mad_zero_matching(self):
        self.assertEqual(fe.trend_vs_ma(5, [5, 5, 5]), 0.0)

    def test_trend_vs_ma_mad_zero_mismatch(self):
        self.assertIsNone(fe.trend_vs_ma(9, [5, 5, 5]))

    def test_trend_vs_ma_none_current(self):
        self.assertIsNone(fe.trend_vs_ma(None, [4, 5, 6]))

    def test_trend_vs_ma_filters_none_in_window(self):
        z = fe.trend_vs_ma(8, [4, None, 5, 6, None])
        self.assertAlmostEqual(z, 3.0)


class TestParseTs(unittest.TestCase):
    def test_valid(self):
        dt = fe._parse_ts("2026-08-11T06:17:24.491639+00:00")
        self.assertIsNotNone(dt)

    def test_invalid_string(self):
        self.assertIsNone(fe._parse_ts("not-a-date"))

    def test_none_input(self):
        self.assertIsNone(fe._parse_ts(None))

    def test_non_string_input(self):
        self.assertIsNone(fe._parse_ts(12345))

    def test_empty_string(self):
        self.assertIsNone(fe._parse_ts(""))


class TestExtractors(unittest.TestCase):
    def test_extract_rlusd_supply_available(self):
        snap = _snap(datetime.now(timezone.utc), rlusd_supply=829107126.2)
        self.assertAlmostEqual(fe._extract_rlusd_supply(snap), 829107126.2)

    def test_extract_rlusd_supply_unavailable(self):
        snap = _snap(datetime.now(timezone.utc), rlusd_supply=None)
        self.assertIsNone(fe._extract_rlusd_supply(snap))

    def test_extract_rlusd_supply_malformed(self):
        self.assertIsNone(fe._extract_rlusd_supply({}))
        self.assertIsNone(fe._extract_rlusd_supply({"sources": {}}))

    def test_extract_amm_pool_value_available(self):
        snap = _snap(datetime.now(timezone.utc), amm_lp_value=1234.5)
        self.assertAlmostEqual(fe._extract_amm_pool_value(snap), 1234.5)

    def test_extract_amm_pool_value_unavailable(self):
        snap = _snap(datetime.now(timezone.utc), amm_lp_value=None)
        self.assertIsNone(fe._extract_amm_pool_value(snap))


class TestFeatureEngineWithFixtures(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tmp_path = os.path.join(self.tmpdir, "snap.jsonl")
        self._patcher = patch.object(raw, "_RAW_SNAPSHOT_PATH", self.tmp_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _write_snapshots(self, snapshots):
        with open(self.tmp_path, "w", encoding="utf-8") as f:
            for s in snapshots:
                f.write(json.dumps(s) + "\n")

    def test_no_snapshots_at_all_gives_missing(self):
        result = fe.rlusd_supply_trend()
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertEqual(result["history_points"], 0)

    def test_single_snapshot_rlusd_growth_non_mature(self):
        now = datetime.now(timezone.utc)
        self._write_snapshots([_snap(now, rlusd_supply=800_000_000)])
        result = fe.rlusd_growth(window_days=30)
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertEqual(result["history_points"], 1)
        self.assertIn("storico insufficiente", result["reason"])

    def test_two_snapshots_far_apart_rlusd_growth_active(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=35)
        self._write_snapshots([
            _snap(old, rlusd_supply=800_000_000),
            _snap(now, rlusd_supply=880_000_000),
        ])
        result = fe.rlusd_growth(window_days=30)
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 10.0, places=4)
        self.assertEqual(result["history_points"], 2)

    def test_two_snapshots_partial_window_gives_non_mature(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=10)
        self._write_snapshots([
            _snap(old, rlusd_supply=800_000_000),
            _snap(now, rlusd_supply=880_000_000),
        ])
        result = fe.rlusd_growth(window_days=30)
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)

    def test_rlusd_velocity_two_close_points_partial(self):
        # intervallo brevissimo (minuti) << 7gg richiesti: valore calcolabile,
        # ma stato deve restare PARTIAL, mai ACTIVE solo per avere 2 punti
        now = datetime.now(timezone.utc)
        prev = now - timedelta(minutes=5)
        self._write_snapshots([
            _snap(prev, rlusd_supply=800_000_000),
            _snap(now, rlusd_supply=800_000_100),
        ])
        result = fe.rlusd_velocity()
        self.assertEqual(result["status"], fe.STATUS_PARTIAL)
        self.assertIsNotNone(result["value"])
        self.assertEqual(result["history_required"], 7)

    def test_rlusd_velocity_two_points_below_seven_days_still_partial(self):
        # 3 giorni di distanza: sotto la soglia dei 7gg approvati -> PARTIAL, non ACTIVE
        now = datetime.now(timezone.utc)
        prev = now - timedelta(days=3)
        self._write_snapshots([
            _snap(prev, rlusd_supply=800_000_000),
            _snap(now, rlusd_supply=810_000_000),
        ])
        result = fe.rlusd_velocity()
        self.assertEqual(result["status"], fe.STATUS_PARTIAL)
        self.assertIsNotNone(result["value"])

    def test_rlusd_velocity_two_points_at_least_seven_days_active(self):
        # 7+ giorni di distanza: raggiunta la finestra minima approvata -> ACTIVE
        now = datetime.now(timezone.utc)
        prev = now - timedelta(days=8)
        self._write_snapshots([
            _snap(prev, rlusd_supply=800_000_000),
            _snap(now, rlusd_supply=840_000_000),
        ])
        result = fe.rlusd_velocity()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertIsNotNone(result["value"])
        self.assertIsNone(result["reason"])

    def test_rlusd_velocity_single_point_non_mature(self):
        now = datetime.now(timezone.utc)
        self._write_snapshots([_snap(now, rlusd_supply=800_000_000)])
        result = fe.rlusd_velocity()
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)

    def test_rlusd_velocity_zero_points_missing(self):
        self._write_snapshots([])
        result = fe.rlusd_velocity()
        self.assertEqual(result["status"], fe.STATUS_MISSING)

    def test_amm_growth_missing_when_no_amm_data(self):
        now = datetime.now(timezone.utc)
        self._write_snapshots([_snap(now, amm_lp_value=None)])
        result = fe.amm_growth()
        self.assertEqual(result["status"], fe.STATUS_MISSING)

    def test_amm_growth_active_with_enough_history(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=31)
        self._write_snapshots([
            _snap(old, amm_lp_value=1000.0),
            _snap(now, amm_lp_value=1100.0),
        ])
        result = fe.amm_growth(window_days=30)
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 10.0, places=4)

    def test_xrp_rlusd_pair_growth_always_missing_even_with_amm_history(self):
        # anche con storico AMM ampio e maturo, xrp_rlusd_pair_growth NON deve
        # riusare quel dato: misura attivita'/volume, non liquidita' del pool.
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=91)
        self._write_snapshots([
            _snap(old, amm_lp_value=500.0),
            _snap(now, amm_lp_value=600.0),
        ])
        result = fe.xrp_rlusd_pair_growth(window_days=90)
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIsNone(result["value"])
        self.assertIn("amm_growth", result["reason"])
        self.assertIn("book_changes", result["reason"])

    def test_xrp_rlusd_pair_growth_missing_with_no_data_too(self):
        result = fe.xrp_rlusd_pair_growth()
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIsNone(result["value"])

    def test_rwa_features_always_missing_with_reason(self):
        now = datetime.now(timezone.utc)
        self._write_snapshots([_snap(now, rwa_error="RWA_XYZ_API_KEY non configurata (test)")])
        for fn in (fe.rwa_value_trend, fe.rwa_growth_30d, fe.rwa_growth_90d, fe.rwa_acceleration):
            result = fn()
            self.assertEqual(result["status"], fe.STATUS_MISSING)
            self.assertIn("RWA_XYZ_API_KEY", result["reason"])

    def test_dex_volume_features_always_missing_with_m5_reason(self):
        for fn in (fe.dex_volume_trend, fe.dex_volume_growth, fe.dex_volume_acceleration):
            result = fn()
            self.assertEqual(result["status"], fe.STATUS_MISSING)
            self.assertIn("M5", result["reason"])

    def test_trustline_features_always_missing_with_pagination_reason(self):
        for fn in (fe.trustline_growth, fe.trustline_acceleration):
            result = fn()
            self.assertEqual(result["status"], fe.STATUS_MISSING)
            self.assertIn("paginato", result["reason"])

    def test_fee_burn_features_always_missing_with_issuer_only_reason(self):
        for fn in (fe.fee_per_tx, fe.burn_rate):
            result = fn()
            self.assertEqual(result["status"], fe.STATUS_MISSING)
            self.assertIn("issuer RLUSD", result["reason"])

    def test_xrp_dependency_ratio_and_pool_share_structurally_missing(self):
        for fn in (fe.xrp_dependency_ratio, fe.xrp_pool_share):
            result = fn()
            self.assertEqual(result["status"], fe.STATUS_MISSING)
            self.assertIsNotNone(result["reason"])

    def test_compute_all_features_never_raises_and_covers_all_keys(self):
        now = datetime.now(timezone.utc)
        self._write_snapshots([_snap(now, rlusd_supply=800_000_000, amm_lp_value=1000.0)])
        try:
            result = fe.compute_all_features()
        except Exception as e:
            self.fail(f"compute_all_features ha sollevato un'eccezione: {e}")
        expected_keys = {
            "rwa_value_trend", "rwa_growth_30d", "rwa_growth_90d", "rwa_acceleration",
            "rlusd_supply_trend", "rlusd_growth", "rlusd_velocity",
            "dex_volume_trend", "dex_volume_growth", "dex_volume_acceleration", "amm_growth",
            "trustline_growth", "trustline_acceleration", "fee_per_tx", "burn_rate",
            "xrp_dependency_ratio", "xrp_pool_share", "xrp_rlusd_pair_growth",
            "xrp_btc_relative_strength", "xrp_eth_relative_strength",
        }
        self.assertEqual(set(result.keys()), expected_keys)
        for name, feat in result.items():
            for required_key in ("value", "status", "source", "as_of", "history_points", "history_required", "reason"):
                self.assertIn(required_key, feat, f"{name} manca del campo {required_key}")
            self.assertIn(feat["status"], (fe.STATUS_ACTIVE, fe.STATUS_PARTIAL, fe.STATUS_NON_MATURE, fe.STATUS_MISSING))
            if feat["status"] == fe.STATUS_MISSING:
                self.assertIsNone(feat["value"], f"{name} e' MISSING ma ha un valore non-None")


class TestRelativeStrengthInjection(unittest.TestCase):
    def test_missing_when_not_injected(self):
        result = fe.xrp_btc_relative_strength()
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIn("altseason_bot.py", result["reason"])

    def test_active_when_injected_with_valid_functions(self):
        def fake_get_history(cg_id):
            return [1.0] * 10

        def fake_perf(closes, giorni):
            return 5.0 if closes else None

        result = fe.xrp_btc_relative_strength(fake_get_history, fake_perf, giorni=7)
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 0.0)

    def test_non_mature_when_injected_but_no_data(self):
        def fake_get_history(cg_id):
            return None

        def fake_perf(closes, giorni):
            return None

        result = fe.xrp_eth_relative_strength(fake_get_history, fake_perf)
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)

    def test_missing_when_injected_functions_raise(self):
        def raising_get_history(cg_id):
            raise RuntimeError("boom")

        result = fe.xrp_btc_relative_strength(raising_get_history, lambda c, g: 1.0)
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIn("errore durante il riuso", result["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
