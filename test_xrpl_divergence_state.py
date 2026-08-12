"""
Test M4 — XRPL Divergence State.
Storico iniettato via 'history_override' (mai file reali), anti-flickering
testato con path temporanei dedicati per non toccare lo stato reale.
"""
import os
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

import xrpl_divergence_state as ds


def _mkhistory(points):
    """points: lista di (giorni_fa, score1, f_score, e_score)."""
    now = datetime.now(timezone.utc)
    out = []
    for days_ago, s1, f, e in points:
        out.append({
            "timestamp_utc": (now - timedelta(days=days_ago)).isoformat(),
            "score1": s1, "f_score": f, "e_score": e,
        })
    return out


class TestClassifyTrend(unittest.TestCase):
    def test_insufficient_points_non_mature(self):
        self.assertEqual(ds._classify_trend([]), ds.TREND_NON_MATURE)
        self.assertEqual(ds._classify_trend([(datetime.now(timezone.utc), 50.0)]), ds.TREND_NON_MATURE)

    def test_flat_within_one_mad(self):
        history = _mkhistory([(20, 50, None, None), (15, 51, None, None), (10, 49, None, None), (0, 50, None, None)])
        series = ds._series_for_key(history, "score1")
        self.assertEqual(ds._classify_trend(series), ds.TREND_FLAT)

    def test_up_beyond_one_mad(self):
        history = _mkhistory([(20, 40, None, None), (15, 41, None, None), (10, 39, None, None), (0, 90, None, None)])
        series = ds._series_for_key(history, "score1")
        self.assertEqual(ds._classify_trend(series), ds.TREND_STRONG_UP)

    def test_down_beyond_one_mad(self):
        history = _mkhistory([(20, 60, None, None), (15, 61, None, None), (10, 59, None, None), (0, 10, None, None)])
        series = ds._series_for_key(history, "score1")
        self.assertIn(ds._classify_trend(series), (ds.TREND_DOWN,))


class TestFivePatterns(unittest.TestCase):
    """Ognuno dei 5 pattern congelati, costruito forzando i trend attesi
    tramite storico sintetico. record=False, history_override esplicito."""

    def _run(self, points_score1, points_f, points_e, state_path):
        history = []
        now = datetime.now(timezone.utc)
        for i, (d, v) in enumerate(points_score1):
            history.append({"timestamp_utc": (now - timedelta(days=d)).isoformat(), "score1": v, "f_score": None, "e_score": None})
        for i, (d, v) in enumerate(points_f):
            history.append({"timestamp_utc": (now - timedelta(days=d)).isoformat(), "score1": None, "f_score": v, "e_score": None})
        for i, (d, v) in enumerate(points_e):
            history.append({"timestamp_utc": (now - timedelta(days=d)).isoformat(), "score1": None, "f_score": None, "e_score": v})
        return ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history, state_path=state_path, confirm_n=1,
        )

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "state.jsonl")

    def _flat_up_up(self):
        # A-D UP forte, F UP forte, E FLAT
        s1 = [(20, 40), (15, 41), (10, 39), (0, 90)]
        f = [(20, 40), (15, 41), (10, 39), (0, 90)]
        e = [(20, 50), (15, 51), (10, 49), (0, 50)]
        return self._run(s1, f, e, self.state_path)

    def test_pattern_1_structural_adoption_not_priced(self):
        result = self._flat_up_up()
        self.assertEqual(result["state"], ds.STATE_STRUCTURAL_ADOPTION_NOT_PRICED)

    def test_pattern_2_ecosystem_growth_without_xrp_capture(self):
        s1 = [(20, 40), (15, 41), (10, 39), (0, 90)]   # UP forte
        f = [(20, 50), (15, 51), (10, 49), (0, 50)]    # FLAT
        e = [(20, 50), (15, 51), (10, 49), (0, 50)]    # FLAT (irrilevante per pattern 2)
        result = self._run(s1, f, e, os.path.join(self.tmpdir, "s2.jsonl"))
        self.assertEqual(result["state"], ds.STATE_ECOSYSTEM_GROWTH_WITHOUT_XRP_CAPTURE)

    def test_pattern_3_unsupported_speculative_rally(self):
        s1 = [(20, 50), (15, 51), (10, 49), (0, 50)]   # FLAT (A-D non conferma)
        f = [(20, 50), (15, 51), (10, 49), (0, 50)]    # FLAT (F non conferma)
        e = [(20, 40), (15, 41), (10, 39), (0, 90)]    # STRONG_UP
        result = self._run(s1, f, e, os.path.join(self.tmpdir, "s3.jsonl"))
        self.assertEqual(result["state"], ds.STATE_UNSUPPORTED_SPECULATIVE_RALLY)

    def test_pattern_4_adoption_confirmed_and_priced(self):
        s1 = [(20, 40), (15, 41), (10, 39), (0, 90)]   # UP
        f = [(20, 40), (15, 41), (10, 39), (0, 90)]    # UP
        e = [(20, 40), (15, 41), (10, 39), (0, 90)]    # UP
        result = self._run(s1, f, e, os.path.join(self.tmpdir, "s4.jsonl"))
        self.assertEqual(result["state"], ds.STATE_ADOPTION_CONFIRMED_AND_PRICED)

    def test_pattern_5_structural_bearish_divergence(self):
        s1 = [(20, 60), (15, 61), (10, 59), (0, 10)]   # DOWN
        f = [(20, 50), (15, 51), (10, 49), (0, 50)]    # FLAT (irrilevante per pattern 5)
        e = [(20, 40), (15, 41), (10, 39), (0, 90)]    # STRONG_UP
        result = self._run(s1, f, e, os.path.join(self.tmpdir, "s5.jsonl"))
        self.assertEqual(result["state"], ds.STATE_STRUCTURAL_BEARISH_DIVERGENCE)

    def test_no_clear_divergence(self):
        # A-D DOWN, F UP, E FLAT: nessuno dei 5 pattern corrisponde
        s1 = [(20, 60), (15, 61), (10, 59), (0, 10)]
        f = [(20, 40), (15, 41), (10, 39), (0, 90)]
        e = [(20, 50), (15, 51), (10, 49), (0, 50)]
        result = self._run(s1, f, e, os.path.join(self.tmpdir, "s6.jsonl"))
        self.assertEqual(result["state"], ds.STATE_NO_CLEAR_DIVERGENCE)


class TestInsufficientHistory(unittest.TestCase):
    def test_empty_history_gives_non_mature(self):
        result = ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=[], confirm_n=1,
        )
        self.assertEqual(result["state"], ds.STATE_NON_MATURE)
        self.assertEqual(result["raw_pattern"], ds.STATE_NON_MATURE)

    def test_partial_history_only_one_series_gives_non_mature(self):
        now = datetime.now(timezone.utc)
        history = [
            {"timestamp_utc": (now - timedelta(days=20)).isoformat(), "score1": 40, "f_score": None, "e_score": None},
            {"timestamp_utc": now.isoformat(), "score1": 90, "f_score": None, "e_score": None},
        ]
        result = ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history, confirm_n=1,
        )
        self.assertEqual(result["state"], ds.STATE_NON_MATURE)
        self.assertEqual(result["trends"]["F"], ds.TREND_NON_MATURE)
        self.assertEqual(result["trends"]["E"], ds.TREND_NON_MATURE)


class TestAntiFlicker(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "flicker.jsonl")

    def _history_for(self, s1, f, e):
        now = datetime.now(timezone.utc)
        pts = [(20, 40), (15, 41), (10, 39)]
        history = []
        for d, base in pts:
            history.append({"timestamp_utc": (now - timedelta(days=d)).isoformat(),
                             "score1": base, "f_score": base, "e_score": 50 + (base - 40) * 0})
        history.append({"timestamp_utc": now.isoformat(), "score1": s1, "f_score": f, "e_score": e})
        return history

    def test_state_not_committed_before_confirm_n_reached(self):
        history = self._history_for(90, 90, 50)  # pattern 1 candidato
        r1 = ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history, state_path=self.state_path, confirm_n=3,
        )
        self.assertEqual(r1["candidate_streak"], 1)
        self.assertEqual(r1["state"], ds.STATE_NON_MATURE)  # non ancora confermato

        r2 = ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history, state_path=self.state_path, confirm_n=3,
        )
        self.assertEqual(r2["candidate_streak"], 2)
        self.assertEqual(r2["state"], ds.STATE_NON_MATURE)  # ancora non confermato

        r3 = ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history, state_path=self.state_path, confirm_n=3,
        )
        self.assertEqual(r3["candidate_streak"], 3)
        self.assertEqual(r3["state"], r3["raw_pattern"])  # confermato al terzo colpo

    def test_streak_resets_on_different_candidate(self):
        history_a = self._history_for(90, 90, 50)  # pattern 1
        history_b = self._history_for(90, 10, 50)  # pattern diverso (F non conferma)

        ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history_a, state_path=self.state_path, confirm_n=3,
        )
        r2 = ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history_b, state_path=self.state_path, confirm_n=3,
        )
        self.assertEqual(r2["candidate_streak"], 1)  # reset perche' il pattern e' cambiato

    def test_committed_state_persists_across_calls_via_file(self):
        history = self._history_for(90, 90, 50)
        for _ in range(3):
            result = ds.compute_divergence_state(
                score1_result={"score": None}, score2_result={"category_breakdown": {}},
                record=False, history_override=history, state_path=self.state_path, confirm_n=3,
            )
        self.assertEqual(result["state"], result["raw_pattern"])
        with open(self.state_path) as fh:
            lines = [ln for ln in fh if ln.strip()]
        self.assertEqual(len(lines), 3)
        last = json.loads(lines[-1])
        self.assertEqual(last["committed_pattern"], result["state"])


class TestContradictorySignals(unittest.TestCase):
    def test_contradictory_ad_up_f_down_e_up_falls_back_to_no_clear_or_specific_pattern(self):
        now = datetime.now(timezone.utc)
        history = []
        for d, s1, f, e in [(20, 40, 60, 40), (15, 41, 61, 41), (10, 39, 59, 39), (0, 90, 10, 90)]:
            history.append({"timestamp_utc": (now - timedelta(days=d)).isoformat(),
                             "score1": s1, "f_score": f, "e_score": e})
        result = ds.compute_divergence_state(
            score1_result={"score": None}, score2_result={"category_breakdown": {}},
            record=False, history_override=history, confirm_n=1,
        )
        # A-D UP, F DOWN, E STRONG_UP: A-D UP + F flat_or_down -> pattern 2 vince
        # per priorita' (controllato prima di pattern 3/5); verifichiamo solo
        # che produca uno stato valido tra quelli definiti, mai un crash o
        # uno stato inventato fuori dall'enum.
        valid_states = (
            ds.STATE_STRUCTURAL_ADOPTION_NOT_PRICED, ds.STATE_ECOSYSTEM_GROWTH_WITHOUT_XRP_CAPTURE,
            ds.STATE_UNSUPPORTED_SPECULATIVE_RALLY, ds.STATE_ADOPTION_CONFIRMED_AND_PRICED,
            ds.STATE_STRUCTURAL_BEARISH_DIVERGENCE, ds.STATE_NO_CLEAR_DIVERGENCE, ds.STATE_NON_MATURE,
        )
        self.assertIn(result["state"], valid_states)


class TestRecordAndReadRoundtrip(unittest.TestCase):
    def test_record_then_read_roundtrip(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "hist.jsonl")
        score1_result = {"score": 55.5}
        score2_result = {"category_breakdown": {"F": {"score": 30.0}, "E": {"score": 70.0}}}
        entry = ds.record_score_observation(score1_result, score2_result, path=path)
        self.assertAlmostEqual(entry["score1"], 55.5)
        history = ds._read_score_history(path=path)
        self.assertEqual(len(history), 1)
        self.assertAlmostEqual(history[0]["f_score"], 30.0)
        self.assertAlmostEqual(history[0]["e_score"], 70.0)

    def test_record_handles_none_score2_gracefully(self):
        tmpdir = tempfile.mkdtemp()
        path = os.path.join(tmpdir, "hist2.jsonl")
        entry = ds.record_score_observation({"score": None}, None, path=path)
        self.assertIsNone(entry["f_score"])
        self.assertIsNone(entry["e_score"])


class TestRealIntegration(unittest.TestCase):
    def test_real_score_layer_never_raises(self):
        tmpdir = tempfile.mkdtemp()
        try:
            result = ds.compute_divergence_state(
                score_history_path=os.path.join(tmpdir, "h.jsonl"),
                state_path=os.path.join(tmpdir, "s.jsonl"),
            )
        except Exception as e:
            self.fail(f"integrazione reale ha sollevato un'eccezione: {e}")
        self.assertIn("state", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
