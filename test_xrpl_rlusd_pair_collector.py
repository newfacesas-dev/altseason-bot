"""
Test M8 Gap 2B — XRPL RLUSD Pair Collector.
Nessuna rete reale: WebSocket e chiamate REST sono simulate. Messaggi
'bookChanges' costruiti nella struttura REALE verificata nell'audit
(xrpl.org: currency_a/currency_b/volume_a/volume_b).
"""
import os
import json
import asyncio
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, AsyncMock

import xrpl_raw_data_layer as raw
import xrpl_rlusd_pair_collector as collector


def _change(currency_a, currency_b, volume_a, volume_b):
    return {
        "currency_a": currency_a, "currency_b": currency_b,
        "volume_a": str(volume_a), "volume_b": str(volume_b),
        "high": "1", "low": "1", "open": "1", "close": "1",
    }


def _rlusd_change(volume_xrp_drops, volume_rlusd, hex_form=True):
    currency = raw._RLUSD_CURRENCY_HEX if hex_form else "RLUSD"
    return _change("XRP_drops", f"{raw._RLUSD_ISSUER}/{currency}", volume_xrp_drops, volume_rlusd)


def _other_change():
    return _change("XRP_drops", "rSomeOtherIssuer1234567890/USD", 999, 888)


class TestBookIdentification(unittest.TestCase):
    def test_recognizes_rlusd_book_hex_form(self):
        change = _rlusd_change(1_000_000, 1.0, hex_form=True)
        self.assertTrue(collector._currency_b_matches_rlusd(change["currency_b"]))

    def test_recognizes_rlusd_book_literal_form(self):
        change = _rlusd_change(1_000_000, 1.0, hex_form=False)
        self.assertTrue(collector._currency_b_matches_rlusd(change["currency_b"]))

    def test_rejects_other_issuer_same_currency_code(self):
        fake = f"rNotTheRealIssuer0000000000000/{raw._RLUSD_CURRENCY_HEX}"
        self.assertFalse(collector._currency_b_matches_rlusd(fake))

    def test_rejects_other_currency_same_issuer(self):
        fake = f"{raw._RLUSD_ISSUER}/USD"
        self.assertFalse(collector._currency_b_matches_rlusd(fake))

    def test_rejects_malformed_currency_b(self):
        self.assertFalse(collector._currency_b_matches_rlusd("not-a-valid-format"))
        self.assertFalse(collector._currency_b_matches_rlusd(None))
        self.assertFalse(collector._currency_b_matches_rlusd(123))

    def test_extract_finds_rlusd_among_many_changes(self):
        changes = [_other_change(), _rlusd_change(500, 0.5), _other_change()]
        found = collector._extract_xrp_rlusd_change(changes)
        self.assertIsNotNone(found)
        self.assertEqual(found["volume_a"], "500")

    def test_extract_returns_none_when_absent(self):
        changes = [_other_change(), _other_change()]
        self.assertIsNone(collector._extract_xrp_rlusd_change(changes))

    def test_extract_handles_empty_or_malformed_changes(self):
        self.assertIsNone(collector._extract_xrp_rlusd_change([]))
        self.assertIsNone(collector._extract_xrp_rlusd_change(None))
        self.assertIsNone(collector._extract_xrp_rlusd_change("not-a-list"))
        self.assertIsNone(collector._extract_xrp_rlusd_change(["not-a-dict", 123]))


class TestVolumeParsing(unittest.TestCase):
    def test_parses_valid_volumes(self):
        change = _rlusd_change(1000000, 1.5)
        vol_xrp, vol_rlusd = collector._parse_volumes(change)
        self.assertAlmostEqual(vol_xrp, 1000000.0)
        self.assertAlmostEqual(vol_rlusd, 1.5)

    def test_rejects_non_numeric(self):
        change = {"volume_a": "abc", "volume_b": "1.0"}
        vol_xrp, vol_rlusd = collector._parse_volumes(change)
        self.assertIsNone(vol_xrp)
        self.assertIsNone(vol_rlusd)

    def test_rejects_negative(self):
        change = {"volume_a": "-100", "volume_b": "1.0"}
        vol_xrp, vol_rlusd = collector._parse_volumes(change)
        self.assertIsNone(vol_xrp)


class TestStatePersistence(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "state.json")

    def test_default_state_when_no_file(self):
        state = collector.read_state(path=self.state_path)
        self.assertIsNone(state["last_processed_ledger_index"])
        self.assertEqual(state["accumulated_volume_xrp"], 0.0)

    def test_write_then_read_roundtrip(self):
        state = collector._default_state()
        state["last_processed_ledger_index"] = 12345
        state["accumulated_volume_xrp"] = 999.5
        collector._write_state(state, path=self.state_path)
        reread = collector.read_state(path=self.state_path)
        self.assertEqual(reread["last_processed_ledger_index"], 12345)
        self.assertAlmostEqual(reread["accumulated_volume_xrp"], 999.5)

    def test_corrupted_state_file_falls_back_to_default(self):
        with open(self.state_path, "w") as f:
            f.write("questo non e' json valido")
        state = collector.read_state(path=self.state_path)
        self.assertIsNone(state["last_processed_ledger_index"])

    def test_persistence_survives_simulated_restart(self):
        state = collector._default_state()
        state["last_processed_ledger_index"] = 500
        collector._write_state(state, path=self.state_path)
        # simula un nuovo processo che rilegge da zero
        fresh_state = collector.read_state(path=self.state_path)
        self.assertEqual(fresh_state["last_processed_ledger_index"], 500)


class TestDedupAndAccumulation(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "state.json")
        self.history_path = os.path.join(self.tmpdir, "hist.jsonl")
        self._patch_state = patch.object(collector, "_COLLECTOR_STATE_PATH", self.state_path)
        self._patch_hist = patch.object(collector, "_VOLUME_HISTORY_PATH", self.history_path)
        self._patch_state.start()
        self._patch_hist.start()

    def tearDown(self):
        self._patch_state.stop()
        self._patch_hist.stop()

    def test_ledger_accumulates_volume(self):
        state = collector._default_state()
        state = collector._process_ledger_changes(100, [_rlusd_change(1_000_000, 1.0)], state)
        self.assertEqual(state["last_processed_ledger_index"], 100)
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 1_000_000.0)

    def test_duplicate_ledger_ignored(self):
        state = collector._default_state()
        state = collector._process_ledger_changes(100, [_rlusd_change(1_000_000, 1.0)], state)
        state = collector._process_ledger_changes(100, [_rlusd_change(1_000_000, 1.0)], state)  # stesso ledger
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 1_000_000.0)  # non raddoppiato

    def test_older_ledger_ignored(self):
        state = collector._default_state()
        state = collector._process_ledger_changes(100, [_rlusd_change(1_000_000, 1.0)], state)
        state = collector._process_ledger_changes(50, [_rlusd_change(5_000_000, 5.0)], state)  # ledger precedente
        self.assertEqual(state["last_processed_ledger_index"], 100)  # invariato
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 1_000_000.0)  # invariato

    def test_ledger_without_rlusd_activity_still_advances_watermark(self):
        state = collector._default_state()
        state = collector._process_ledger_changes(100, [_other_change()], state)
        self.assertEqual(state["last_processed_ledger_index"], 100)
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 0.0)

    def test_multiple_changes_same_ledger_only_rlusd_counted(self):
        state = collector._default_state()
        changes = [_other_change(), _rlusd_change(2_000_000, 2.0), _other_change()]
        state = collector._process_ledger_changes(100, changes, state)
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 2_000_000.0)

    def test_no_activity_at_all_across_many_ledgers(self):
        state = collector._default_state()
        for ledger in range(1, 6):
            state = collector._process_ledger_changes(ledger, [_other_change()], state)
        self.assertEqual(state["last_processed_ledger_index"], 5)
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 0.0)


class TestPeriodFlush(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.history_path = os.path.join(self.tmpdir, "hist.jsonl")
        self._patcher = patch.object(collector, "_VOLUME_HISTORY_PATH", self.history_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_period_not_flushed_before_24h(self):
        state = collector._default_state()
        state["accumulated_volume_xrp"] = 5_000_000.0
        state = collector._maybe_flush_period(state)
        self.assertFalse(os.path.exists(self.history_path))
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 5_000_000.0)  # non azzerato

    def test_period_flushed_after_24h(self):
        state = collector._default_state()
        state["period_start_utc"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        state["accumulated_volume_xrp"] = 3_000_000.0
        state["accumulated_volume_rlusd"] = 3.0
        state = collector._maybe_flush_period(state)
        self.assertTrue(os.path.exists(self.history_path))
        self.assertAlmostEqual(state["accumulated_volume_xrp"], 0.0)  # azzerato per il nuovo periodo
        with open(self.history_path) as f:
            entry = json.loads(f.readline())
        self.assertAlmostEqual(entry["volume_xrp"], 3.0)  # 3_000_000 drops = 3.0 XRP

    def test_zero_activity_period_still_recorded(self):
        state = collector._default_state()
        state["period_start_utc"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        collector._maybe_flush_period(state)
        with open(self.history_path) as f:
            entry = json.loads(f.readline())
        self.assertAlmostEqual(entry["volume_xrp"], 0.0)  # salvato esplicitamente, non saltato

    def test_complete_period_marked_true(self):
        state = collector._default_state()
        state["period_start_utc"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        state["period_has_gap"] = False
        collector._maybe_flush_period(state)
        with open(self.history_path) as f:
            entry = json.loads(f.readline())
        self.assertTrue(entry["complete"])

    def test_incomplete_period_marked_false_after_unrecovered_gap(self):
        state = collector._default_state()
        state["period_start_utc"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        state["accumulated_volume_xrp"] = 1_000_000.0
        state["period_has_gap"] = True  # simulato: backfill ha superato il tetto durante questo periodo
        flushed_state = collector._maybe_flush_period(state)
        with open(self.history_path) as f:
            entry = json.loads(f.readline())
        self.assertFalse(entry["complete"])
        self.assertFalse(flushed_state["period_has_gap"])  # resettato per il nuovo periodo

    def test_backfill_gap_exceeding_cap_marks_period_incomplete(self):
        async def run():
            loop = asyncio.get_event_loop()
            state = collector._default_state()
            state["last_processed_ledger_index"] = 0
            state["period_has_gap"] = False
            result = await collector._backfill_gap(0, collector._BACKFILL_MAX_LEDGERS + 500, state, loop)
            return result

        result_state = asyncio.run(run())
        self.assertTrue(result_state["period_has_gap"])  # marcato esplicitamente, non un successo silenzioso


class TestVolumeSeriesReading(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.history_path = os.path.join(self.tmpdir, "hist.jsonl")

    def test_empty_history_gives_empty_series(self):
        series = collector.get_volume_period_series(path=self.history_path)
        self.assertEqual(series, [])

    def test_series_sorted_and_parsed(self):
        now = datetime.now(timezone.utc)
        entries = [
            {"period_end_utc": (now - timedelta(days=2)).isoformat(), "volume_xrp": 10.0},
            {"period_end_utc": (now - timedelta(days=1)).isoformat(), "volume_xrp": 20.0},
            {"period_end_utc": now.isoformat(), "volume_xrp": 30.0},
        ]
        with open(self.history_path, "w") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
        series = collector.get_volume_period_series(path=self.history_path)
        self.assertEqual([v for _, v in series], [10.0, 20.0, 30.0])

    def test_malformed_lines_skipped(self):
        with open(self.history_path, "w") as f:
            f.write("non e' json\n")
            f.write(json.dumps({"period_end_utc": datetime.now(timezone.utc).isoformat(), "volume_xrp": 5.0}) + "\n")
        series = collector.get_volume_period_series(path=self.history_path)
        self.assertEqual(len(series), 1)


class TestBackfill(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "state.json")
        self.history_path = os.path.join(self.tmpdir, "hist.jsonl")
        self._patch_state = patch.object(collector, "_COLLECTOR_STATE_PATH", self.state_path)
        self._patch_hist = patch.object(collector, "_VOLUME_HISTORY_PATH", self.history_path)
        self._patch_state.start()
        self._patch_hist.start()

    def tearDown(self):
        self._patch_state.stop()
        self._patch_hist.stop()

    def test_backfill_fills_missing_ledgers(self):
        def fake_rpc_call(method, params, source_label):
            return {"changes": [_rlusd_change(100_000, 0.1)]}, None

        async def run():
            loop = asyncio.get_event_loop()
            state = collector._default_state()
            state["last_processed_ledger_index"] = 10
            with patch.object(raw, "_xrpl_rpc_call", side_effect=fake_rpc_call):
                with patch.object(loop, "run_in_executor", new=AsyncMock(side_effect=lambda _, fn, *a: fn(*a))):
                    result_state = await collector._backfill_gap(10, 13, state, loop)
            return result_state

        result_state = asyncio.run(run())
        self.assertEqual(result_state["last_processed_ledger_index"], 13)
        self.assertAlmostEqual(result_state["accumulated_volume_xrp"], 300_000.0)  # 3 ledger x 100k

    def test_no_gap_no_backfill_needed(self):
        async def run():
            loop = asyncio.get_event_loop()
            state = collector._default_state()
            state["last_processed_ledger_index"] = 50
            result = await collector._backfill_gap(50, 50, state, loop)
            return result

        result_state = asyncio.run(run())
        self.assertEqual(result_state["last_processed_ledger_index"], 50)
        self.assertAlmostEqual(result_state["accumulated_volume_xrp"], 0.0)

    def test_gap_too_large_declared_lost_not_silent(self):
        async def run():
            loop = asyncio.get_event_loop()
            state = collector._default_state()
            state["last_processed_ledger_index"] = 0
            result = await collector._backfill_gap(0, collector._BACKFILL_MAX_LEDGERS + 100, state, loop)
            return result

        result_state = asyncio.run(run())
        # il watermark avanza comunque al ledger corrente (non si resta bloccati indietro)
        self.assertEqual(result_state["last_processed_ledger_index"], collector._BACKFILL_MAX_LEDGERS + 100)


class TestNoDoubleTelegramPolling(unittest.TestCase):
    def test_collector_module_never_imports_telegram_or_altseason_bot(self):
        with open(collector.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("import telegram", src.lower())
        self.assertNotIn("import altseason_bot", src)
        self.assertNotIn("Application.builder", src)
        self.assertNotIn("start_polling", src)


class TestFailureIsolation(unittest.TestCase):
    def test_run_collector_forever_never_raises_on_missing_websockets_lib(self):
        async def run():
            with patch.dict("sys.modules", {"websockets": None}):
                # simuliamo l'assenza della libreria facendo fallire l'import
                with patch.object(collector, "_run_once", side_effect=ImportError("no module named websockets")):
                    await collector.run_collector_forever(ws_urls=["wss://fake"])

        try:
            asyncio.run(run())
        except Exception as e:
            self.fail(f"run_collector_forever ha sollevato un'eccezione: {e}")

    def test_run_collector_forever_retries_on_generic_error(self):
        call_count = {"n": 0}

        async def failing_run_once(url):
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise RuntimeError("errore di rete simulato")
            raise asyncio.CancelledError()  # interrompe il test dopo qualche retry

        with patch.object(collector, "_run_once", side_effect=failing_run_once), \
             patch.object(collector.asyncio, "sleep", new=AsyncMock(return_value=None)):
            with self.assertRaises(asyncio.CancelledError):
                asyncio.run(collector.run_collector_forever(ws_urls=["wss://fake"]))
        self.assertGreaterEqual(call_count["n"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
