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


def _snap(ts, rlusd_supply=None, amm_lp_value=None, dex_volume=None, trustline_count=None,
          trustline_complete=True, rwa_error="RWA_XYZ_API_KEY non configurata (test)"):
    sources = {
        "xrpl_native": {},
        "defillama": {},
        "xrpl_to": {},
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
    if dex_volume is not None:
        sources["xrpl_to"]["dex_volume"] = {
            "status": "RAW_AVAILABLE",
            "source": "xrpl_to.dex_volume",
            "data": {"gDexVolume": dex_volume},
            "error": None,
        }
    else:
        sources["xrpl_to"]["dex_volume"] = {
            "status": "SOURCE_UNAVAILABLE", "source": "xrpl_to.dex_volume", "data": None, "error": "test-down",
        }
    if trustline_count is not None:
        sources["xrpl_native"]["account_lines_rlusd_issuer_paginated"] = {
            "status": "RAW_AVAILABLE" if trustline_complete else "SOURCE_UNAVAILABLE",
            "source": "xrpl.account_lines_paginated",
            "data": {"total_trustlines": trustline_count, "pages_fetched": 3, "complete": trustline_complete},
            "error": None if trustline_complete else "tetto di sicurezza raggiunto (test)",
        }
    else:
        sources["xrpl_native"]["account_lines_rlusd_issuer_paginated"] = {
            "status": "SOURCE_UNAVAILABLE", "source": "xrpl.account_lines_paginated", "data": None, "error": "test-down",
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

    def test_xrp_rlusd_pair_growth_missing_when_amm_history_present_but_collector_absent(self):
        # xrp_rlusd_pair_growth legge dal collector WebSocket dedicato
        # (M8 Gap 2B), MAI dai RAW di M1: uno storico AMM ricco negli
        # snapshot di M1 non ha alcun effetto su questa feature.
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=91)
        self._write_snapshots([
            _snap(old, amm_lp_value=500.0),
            _snap(now, amm_lp_value=600.0),
        ])
        result = fe.xrp_rlusd_pair_growth()
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIsNone(result["value"])

    def _write_rlusd_pair_history(self, hist_path, entries):
        with open(hist_path, "w") as f:
            for days_ago, vol, complete in entries:
                now = datetime.now(timezone.utc)
                f.write(json.dumps({
                    "period_end_utc": (now - timedelta(days=days_ago)).isoformat(),
                    "volume_xrp": vol, "complete": complete,
                }) + "\n")

    def test_xrp_rlusd_pair_growth_default_call_uses_approved_window(self):
        # M8 Gap 2B, chiusura definitiva: la finestra (84gg/28oss) e'
        # ora approvata — la chiamata di produzione (senza window_days
        # esplicito, come fa compute_all_features()) deve funzionare.
        import xrpl_rlusd_pair_collector as collector_mod
        tmpdir = tempfile.mkdtemp()
        hist_path = os.path.join(tmpdir, "hist.jsonl")
        # 30 periodi completi, distanziati di 3gg l'uno dall'altro (0..87gg fa)
        entries = [(i * 3, 1000.0 + i * 10, True) for i in range(30)]
        self._write_rlusd_pair_history(hist_path, entries)
        with patch.object(collector_mod, "_VOLUME_HISTORY_PATH", hist_path):
            result = fe.xrp_rlusd_pair_growth()  # nessun window_days esplicito
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertIsNotNone(result["value"])

    def test_xrp_rlusd_pair_growth_active_with_sufficient_history(self):
        import xrpl_rlusd_pair_collector as collector_mod
        tmpdir = tempfile.mkdtemp()
        hist_path = os.path.join(tmpdir, "hist.jsonl")
        entries = [(84, 1000.0, True), (0, 1500.0, True)] + [(i, 1000.0, True) for i in range(1, 27)]
        self._write_rlusd_pair_history(hist_path, entries)
        with patch.object(collector_mod, "_VOLUME_HISTORY_PATH", hist_path):
            result = fe.xrp_rlusd_pair_growth(window_days=84)
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 50.0, places=4)

    def test_xrp_rlusd_pair_growth_non_mature_below_min_observations(self):
        # Meno di 28 periodi completi: NON_MATURE per soglia di maturita',
        # anche se il punto base a 84gg esiste.
        import xrpl_rlusd_pair_collector as collector_mod
        tmpdir = tempfile.mkdtemp()
        hist_path = os.path.join(tmpdir, "hist.jsonl")
        entries = [(84, 1000.0, True), (0, 1500.0, True)]  # solo 2 periodi
        self._write_rlusd_pair_history(hist_path, entries)
        with patch.object(collector_mod, "_VOLUME_HISTORY_PATH", hist_path):
            result = fe.xrp_rlusd_pair_growth(window_days=84)
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertIsNone(result["value"])
        self.assertIn("minimo approvato", result["reason"])

    def test_xrp_rlusd_pair_growth_non_mature_when_no_base_point_at_84_days(self):
        # 28+ periodi completi ma tutti troppo recenti (nessuno a 84gg+ di distanza).
        import xrpl_rlusd_pair_collector as collector_mod
        tmpdir = tempfile.mkdtemp()
        hist_path = os.path.join(tmpdir, "hist.jsonl")
        entries = [(i, 1000.0, True) for i in range(30)]  # 0..29gg fa, mai 84gg
        self._write_rlusd_pair_history(hist_path, entries)
        with patch.object(collector_mod, "_VOLUME_HISTORY_PATH", hist_path):
            result = fe.xrp_rlusd_pair_growth(window_days=84)
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertIsNone(result["value"])

    def test_xrp_rlusd_pair_growth_incomplete_period_excluded_from_series(self):
        # Un periodo marcato 'complete': False (gap di backfill non
        # recuperato) NON deve mai essere usato come osservazione valida,
        # ne' contare per il minimo di 28 osservazioni.
        import xrpl_rlusd_pair_collector as collector_mod
        tmpdir = tempfile.mkdtemp()
        hist_path = os.path.join(tmpdir, "hist.jsonl")
        entries = [(84, 1000.0, True), (0, 1500.0, True)]
        entries += [(i, 1000.0, True) for i in range(1, 27)]  # 26 -> totale 28 complete
        entries += [(40, 99999.0, False)]  # incompleto, DEVE essere ignorato
        self._write_rlusd_pair_history(hist_path, entries)
        with patch.object(collector_mod, "_VOLUME_HISTORY_PATH", hist_path):
            result = fe.xrp_rlusd_pair_growth(window_days=84)
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 50.0, places=4)  # come se il periodo incompleto non esistesse

    def test_xrp_rlusd_pair_growth_now_in_approved_history_windows(self):
        # M8 Gap 2B, chiusura definitiva: approvata esplicitamente.
        import xrpl_score_layer as sl
        self.assertIn("xrp_rlusd_pair_growth", sl._APPROVED_HISTORY_WINDOWS)
        spec = sl._APPROVED_HISTORY_WINDOWS["xrp_rlusd_pair_growth"]
        self.assertEqual(spec["window_days"], 84)
        self.assertEqual(spec["min_observations"], 28)

    def test_rwa_features_always_missing_with_reason(self):
        now = datetime.now(timezone.utc)
        self._write_snapshots([_snap(now, rwa_error="RWA_XYZ_API_KEY non configurata (test)")])
        for fn in (fe.rwa_value_trend, fe.rwa_growth_30d, fe.rwa_growth_90d, fe.rwa_acceleration):
            result = fn()
            self.assertEqual(result["status"], fe.STATUS_MISSING)
            self.assertIn("RWA_XYZ_API_KEY", result["reason"])

    def test_dex_volume_missing_without_any_raw_snapshot(self):
        # M8 Gap 2A: senza storico raccolto, restano MISSING (non piu'
        # incondizionatamente come prima — ora dipende dai dati reali).
        for fn in (fe.dex_volume_trend, fe.dex_volume_growth):
            result = fn()
            self.assertEqual(result["status"], fe.STATUS_MISSING)

    def test_dex_volume_trend_active_with_sufficient_history(self):
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=20), dex_volume=100000.0),
            _snap(datetime.now(timezone.utc) - timedelta(days=10), dex_volume=110000.0),
            _snap(datetime.now(timezone.utc), dex_volume=120000.0),
        ])
        result = fe.dex_volume_trend()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertIsNotNone(result["value"])

    def test_dex_volume_growth_non_mature_with_short_history(self):
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=5), dex_volume=100000.0),
            _snap(datetime.now(timezone.utc), dex_volume=110000.0),
        ])
        result = fe.dex_volume_growth()
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)

    def test_dex_volume_acceleration_missing_without_any_snapshot(self):
        result = fe.dex_volume_acceleration()
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIsNone(result["value"])

    def test_dex_volume_acceleration_non_mature_below_30_days(self):
        # solo una finestra di 30gg disponibile, manca la seconda (60gg totali)
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=20), dex_volume=100000.0),
            _snap(datetime.now(timezone.utc), dex_volume=110000.0),
        ])
        result = fe.dex_volume_acceleration()
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertIsNone(result["value"])

    def test_dex_volume_acceleration_non_mature_below_60_days(self):
        # ~40gg di storico: sotto i ~60gg richiesti per due finestre consecutive
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=35), dex_volume=100000.0),
            _snap(datetime.now(timezone.utc), dex_volume=120000.0),
        ])
        result = fe.dex_volume_acceleration()
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertIsNone(result["value"])

    def test_dex_volume_acceleration_correct_formula_with_known_values(self):
        # 60gg fa=100000 (+10%->30gg fa=110000), 30gg fa=110000 (+20%->oggi=132000)
        # growth_prev = (110000-100000)/100000*100 = 10.0
        # growth_now  = (132000-110000)/110000*100 = 20.0
        # acceleration = growth_now - growth_prev = 10.0
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=63), dex_volume=100000.0),
            _snap(datetime.now(timezone.utc) - timedelta(days=33), dex_volume=110000.0),
            _snap(datetime.now(timezone.utc) - timedelta(days=3), dex_volume=132000.0),
            _snap(datetime.now(timezone.utc), dex_volume=132000.0),
        ])
        result = fe.dex_volume_acceleration()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 10.0, places=4)

    def test_dex_volume_acceleration_growth_now_component_isolated(self):
        # verifica growth_now da solo: se growth_prev=0 (nessuna variazione
        # nel periodo precedente), acceleration deve coincidere con growth_now
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=63), dex_volume=100000.0),
            _snap(datetime.now(timezone.utc) - timedelta(days=33), dex_volume=100000.0),  # 0% nel periodo precedente
            _snap(datetime.now(timezone.utc), dex_volume=150000.0),  # +50% nel periodo recente
        ])
        result = fe.dex_volume_acceleration()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 50.0, places=4)  # growth_prev=0, quindi accel=growth_now

    def test_dex_volume_acceleration_negative_when_slowing_down(self):
        # crescita che rallenta: growth_prev > growth_now -> accelerazione negativa
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=63), dex_volume=100000.0),
            _snap(datetime.now(timezone.utc) - timedelta(days=33), dex_volume=150000.0),  # +50%
            _snap(datetime.now(timezone.utc), dex_volume=165000.0),  # +10% (rallentamento)
        ])
        result = fe.dex_volume_acceleration()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertLess(result["value"], 0)

    def test_dex_volume_acceleration_zero_values_handled(self):
        # gDexVolume=0 e' un valore valido (verificato in Gap 2A): la
        # metodologia esistente (growth_pct con soglia min_abs_base) deve
        # gestirlo senza inventare nulla, non dare un errore.
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=63), dex_volume=0.0),
            _snap(datetime.now(timezone.utc) - timedelta(days=33), dex_volume=0.0),
            _snap(datetime.now(timezone.utc), dex_volume=0.0),
        ])
        result = fe.dex_volume_acceleration()
        # base troppo vicina a zero -> growth_pct ritorna None -> NON_MATURE,
        # mai un valore inventato (stesso comportamento gia' congelato di growth_pct)
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertIsNone(result["value"])

    def test_dex_volume_acceleration_missing_m2_status_propagates(self):
        # snapshot con dex_volume esplicitamente SOURCE_UNAVAILABLE (non
        # None): l'extractor deve saltarlo, non trattarlo come uno zero.
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=63), dex_volume=None),
            _snap(datetime.now(timezone.utc) - timedelta(days=33), dex_volume=None),
            _snap(datetime.now(timezone.utc), dex_volume=None),
        ])
        result = fe.dex_volume_acceleration()
        self.assertEqual(result["status"], fe.STATUS_MISSING)

    def test_dex_volume_acceleration_not_in_score1_registry(self):
        # Requisito esplicito: NON deve essere registrata in M3.
        import xrpl_score_layer as sl
        all_feature_keys = {
            m["feature_key"]
            for cats in (sl.SCORE1_CATEGORIES, sl.SCORE2_CATEGORIES)
            for cat in cats.values()
            for m in cat["metrics"]
        }
        self.assertNotIn("dex_volume_acceleration", all_feature_keys)

    def test_trustline_growth_default_call_uses_approved_window(self):
        # M8 Gap 3, chiusura definitiva: window_days=30 ora approvato —
        # la chiamata di produzione (senza window_days esplicito) deve
        # funzionare, non piu' NON_MATURE per assenza di approvazione.
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=35), trustline_count=30000),
            _snap(datetime.now(timezone.utc), trustline_count=31500),
        ])
        result = fe.trustline_growth()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 5.0, places=4)  # (31500-30000)/30000*100

    def test_trustline_growth_active_with_explicit_window(self):
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=35), trustline_count=30000),
            _snap(datetime.now(timezone.utc), trustline_count=31500),
        ])
        result = fe.trustline_growth(window_days=30)
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 5.0, places=4)

    def test_trustline_growth_incomplete_snapshot_excluded(self):
        # Un conteggio non 'complete' (tetto raggiunto o pagina fallita)
        # non deve mai essere usato come punto valido della serie.
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=35), trustline_count=30000, trustline_complete=True),
            _snap(datetime.now(timezone.utc) - timedelta(days=15), trustline_count=999999, trustline_complete=False),
            _snap(datetime.now(timezone.utc), trustline_count=31500, trustline_complete=True),
        ])
        result = fe.trustline_growth()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], 5.0, places=4)  # come se il punto incompleto non esistesse

    def test_trustline_growth_missing_with_no_data(self):
        result = fe.trustline_growth()
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIsNone(result["value"])

    def test_trustline_growth_non_mature_short_history(self):
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=5), trustline_count=30000),
            _snap(datetime.now(timezone.utc), trustline_count=31500),
        ])
        result = fe.trustline_growth()
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertIsNone(result["value"])

    def test_trustline_acceleration_correct_formula_with_known_values(self):
        # 60gg fa=28000, 30gg fa=30000 (+7.142857%), oggi=31500 (+5.0%)
        # growth_prev = (30000-28000)/28000*100 = 7.142857...
        # growth_now  = (31500-30000)/30000*100 = 5.0
        # acceleration = growth_now - growth_prev = -2.142857...
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=63), trustline_count=28000),
            _snap(datetime.now(timezone.utc) - timedelta(days=33), trustline_count=30000),
            _snap(datetime.now(timezone.utc) - timedelta(days=3), trustline_count=31500),
            _snap(datetime.now(timezone.utc), trustline_count=31500),
        ])
        result = fe.trustline_acceleration()
        self.assertEqual(result["status"], fe.STATUS_ACTIVE)
        self.assertAlmostEqual(result["value"], -2.142857, places=4)

    def test_trustline_acceleration_non_mature_below_60_days(self):
        self._write_snapshots([
            _snap(datetime.now(timezone.utc) - timedelta(days=35), trustline_count=30000),
            _snap(datetime.now(timezone.utc), trustline_count=31500),
        ])
        result = fe.trustline_acceleration()
        self.assertEqual(result["status"], fe.STATUS_NON_MATURE)
        self.assertIsNone(result["value"])

    def test_trustline_acceleration_missing_with_no_data(self):
        result = fe.trustline_acceleration()
        self.assertEqual(result["status"], fe.STATUS_MISSING)
        self.assertIsNone(result["value"])

    def test_trustline_growth_now_in_approved_history_windows(self):
        # M8 Gap 3, chiusura definitiva: approvato esplicitamente.
        import xrpl_score_layer as sl
        self.assertIn("trustline_growth", sl._APPROVED_HISTORY_WINDOWS)
        spec = sl._APPROVED_HISTORY_WINDOWS["trustline_growth"]
        self.assertEqual(spec["window_days"], 90)
        self.assertEqual(spec["min_observations"], 30)

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
