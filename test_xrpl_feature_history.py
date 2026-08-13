"""
Test M8 (Gap 1, primo passo) — XRPL Feature History Layer.
Nessuna rete: le feature sono dizionari sintetici. File temporanei
dedicati per ogni test, mai il path reale.
"""
import os
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

import xrpl_feature_history as fh
import xrpl_feature_engine as fe


def _features(rlusd_value=100.0, rlusd_status=fe.STATUS_ACTIVE, amm_value=50.0):
    return {
        "rlusd_growth": {
            "value": rlusd_value, "status": rlusd_status, "source": "test",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "history_points": 5, "history_required": 30, "reason": None,
        },
        "amm_growth": {
            "value": amm_value, "status": fe.STATUS_ACTIVE, "source": "test",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "history_points": 5, "history_required": 30, "reason": None,
        },
        "rwa_value_trend": {
            "value": None, "status": fe.STATUS_MISSING, "source": "test",
            "as_of": datetime.now(timezone.utc).isoformat(),
            "history_points": 0, "history_required": 30, "reason": "RWA disabilitato",
        },
    }


class TestCompactAndHash(unittest.TestCase):
    def test_compact_features_keeps_only_value_and_status(self):
        compact = fh._compact_features(_features())
        self.assertEqual(set(compact["rlusd_growth"].keys()), {"value", "status"})
        self.assertNotIn("reason", compact["rlusd_growth"])
        self.assertNotIn("as_of", compact["rlusd_growth"])

    def test_content_hash_deterministic_regardless_of_key_order(self):
        f1 = {"a": {"value": 1, "status": "ACTIVE"}, "b": {"value": 2, "status": "ACTIVE"}}
        f2 = {"b": {"value": 2, "status": "ACTIVE"}, "a": {"value": 1, "status": "ACTIVE"}}
        self.assertEqual(fh._content_hash(f1), fh._content_hash(f2))

    def test_content_hash_differs_when_value_changes(self):
        f1 = fh._compact_features(_features(rlusd_value=100.0))
        f2 = fh._compact_features(_features(rlusd_value=101.0))
        self.assertNotEqual(fh._content_hash(f1), fh._content_hash(f2))


class TestRecordAndDedup(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "history.jsonl")

    def _line_count(self):
        if not os.path.exists(self.path):
            return 0
        with open(self.path) as f:
            return len([ln for ln in f if ln.strip()])

    def test_first_write_always_succeeds(self):
        result = fh.record_feature_snapshot(features=_features(), path=self.path)
        self.assertTrue(result["written"])
        self.assertEqual(self._line_count(), 1)

    def test_identical_content_same_day_is_skipped(self):
        fh.record_feature_snapshot(features=_features(rlusd_value=100.0), path=self.path)
        result = fh.record_feature_snapshot(features=_features(rlusd_value=100.0), path=self.path)
        self.assertFalse(result["written"])
        self.assertEqual(self._line_count(), 1)  # nessun duplicato aggiunto

    def test_different_content_same_day_is_preserved(self):
        # STESSO giorno, valori DIVERSI: deve essere preservato, non scartato
        # solo perche' e' la stessa data (correzione esplicita richiesta).
        fh.record_feature_snapshot(features=_features(rlusd_value=100.0), path=self.path)
        result = fh.record_feature_snapshot(features=_features(rlusd_value=105.0), path=self.path)
        self.assertTrue(result["written"])
        self.assertEqual(self._line_count(), 2)

    def test_three_calls_two_identical_one_different(self):
        fh.record_feature_snapshot(features=_features(rlusd_value=100.0), path=self.path)
        fh.record_feature_snapshot(features=_features(rlusd_value=100.0), path=self.path)  # dup, skip
        fh.record_feature_snapshot(features=_features(rlusd_value=100.0), path=self.path)  # dup, skip
        fh.record_feature_snapshot(features=_features(rlusd_value=110.0), path=self.path)  # nuovo
        self.assertEqual(self._line_count(), 2)

    def test_entry_format_has_required_fields(self):
        fh.record_feature_snapshot(features=_features(), path=self.path)
        last = fh.get_latest_snapshot(path=self.path)
        self.assertIn("timestamp_utc", last)
        self.assertIn("content_hash", last)
        self.assertIn("features", last)
        self.assertIn("rlusd_growth", last["features"])
        self.assertEqual(set(last["features"]["rlusd_growth"].keys()), {"value", "status"})

    def test_missing_status_feature_recorded_with_null_value(self):
        fh.record_feature_snapshot(features=_features(), path=self.path)
        last = fh.get_latest_snapshot(path=self.path)
        self.assertIsNone(last["features"]["rwa_value_trend"]["value"])
        self.assertEqual(last["features"]["rwa_value_trend"]["status"], fe.STATUS_MISSING)

    def test_write_failure_isolated_never_raises(self):
        # path con un COMPONENTE che e' un file esistente (non una directory):
        # os.makedirs fallisce sempre qui, indipendentemente dai privilegi
        # dell'utente (a differenza di un path 'semplicemente inesistente',
        # che root potrebbe comunque creare).
        blocking_file = os.path.join(self.tmpdir, "blocking_file")
        with open(blocking_file, "w") as f:
            f.write("sono un file, non una directory")
        bad_path = os.path.join(blocking_file, "sub", "history.jsonl")
        try:
            result = fh.record_feature_snapshot(features=_features(), path=bad_path)
        except Exception as e:
            self.fail(f"record_feature_snapshot ha sollevato un'eccezione: {e}")
        self.assertFalse(result["written"])


class TestGetFeatureSeries(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "history.jsonl")

    def _write_raw_entries(self, entries):
        with open(self.path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_empty_history_gives_empty_series(self):
        series = fh.get_feature_series("rlusd_growth", path=self.path)
        self.assertEqual(series, [])

    def test_series_extracted_correctly_and_sorted(self):
        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp_utc": (now - timedelta(days=2)).isoformat(), "content_hash": "a",
             "features": {"rlusd_growth": {"value": 10.0, "status": fe.STATUS_ACTIVE}}},
            {"timestamp_utc": (now - timedelta(days=1)).isoformat(), "content_hash": "b",
             "features": {"rlusd_growth": {"value": 20.0, "status": fe.STATUS_ACTIVE}}},
            {"timestamp_utc": now.isoformat(), "content_hash": "c",
             "features": {"rlusd_growth": {"value": 30.0, "status": fe.STATUS_ACTIVE}}},
        ]
        self._write_raw_entries(entries)
        series = fh.get_feature_series("rlusd_growth", path=self.path)
        self.assertEqual([v for _, v in series], [10.0, 20.0, 30.0])

    def test_null_value_entries_are_skipped(self):
        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp_utc": now.isoformat(), "content_hash": "a",
             "features": {"rwa_value_trend": {"value": None, "status": fe.STATUS_MISSING}}},
        ]
        self._write_raw_entries(entries)
        series = fh.get_feature_series("rwa_value_trend", path=self.path)
        self.assertEqual(series, [])

    def test_feature_absent_from_some_entries_is_skipped_not_crashed(self):
        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp_utc": now.isoformat(), "content_hash": "a", "features": {}},
            {"timestamp_utc": now.isoformat(), "content_hash": "b",
             "features": {"rlusd_growth": {"value": 5.0, "status": fe.STATUS_ACTIVE}}},
        ]
        self._write_raw_entries(entries)
        series = fh.get_feature_series("rlusd_growth", path=self.path)
        self.assertEqual(len(series), 1)

    def test_invalid_timestamp_skipped(self):
        entries = [
            {"timestamp_utc": "not-a-date", "content_hash": "a",
             "features": {"rlusd_growth": {"value": 5.0, "status": fe.STATUS_ACTIVE}}},
        ]
        self._write_raw_entries(entries)
        series = fh.get_feature_series("rlusd_growth", path=self.path)
        self.assertEqual(series, [])

    def test_malformed_line_does_not_crash_reading(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("questo non e' json valido\n")
            f.write(json.dumps({
                "timestamp_utc": datetime.now(timezone.utc).isoformat(), "content_hash": "a",
                "features": {"rlusd_growth": {"value": 5.0, "status": fe.STATUS_ACTIVE}},
            }) + "\n")
        series = fh.get_feature_series("rlusd_growth", path=self.path)
        self.assertEqual(len(series), 1)

    def test_window_days_filters_correctly(self):
        now = datetime.now(timezone.utc)
        entries = [
            {"timestamp_utc": (now - timedelta(days=40)).isoformat(), "content_hash": "old",
             "features": {"rlusd_growth": {"value": 1.0, "status": fe.STATUS_ACTIVE}}},
            {"timestamp_utc": now.isoformat(), "content_hash": "new",
             "features": {"rlusd_growth": {"value": 2.0, "status": fe.STATUS_ACTIVE}}},
        ]
        self._write_raw_entries(entries)
        series_all = fh.get_feature_series("rlusd_growth", path=self.path)
        series_windowed = fh.get_feature_series("rlusd_growth", window_days=30, path=self.path)
        self.assertEqual(len(series_all), 2)
        self.assertEqual(len(series_windowed), 1)
        self.assertEqual(series_windowed[0][1], 2.0)


class TestNeverReadsRawFile(unittest.TestCase):
    def test_module_does_not_reference_raw_snapshot_path(self):
        with open(fh.__file__, encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("xrpl_raw_snapshots", src)
        self.assertNotIn("import xrpl_raw_data_layer", src)


class TestRealIntegration(unittest.TestCase):
    def test_record_with_real_feature_engine_never_raises(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "history.jsonl")
        try:
            result = fh.record_feature_snapshot(path=path)
        except Exception as e:
            self.fail(f"integrazione reale ha sollevato un'eccezione: {e}")
        self.assertIn("written", result)
        self.assertTrue(result["written"])  # primo snapshot, nessuno storico precedente


if __name__ == "__main__":
    unittest.main(verbosity=2)
