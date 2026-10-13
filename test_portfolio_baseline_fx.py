"""
Test baseline FISSA in EUR (patch_baseline_fx_fixed.py).

Parte 1: funzioni pure (_fx_valid, _position_view, _apply_baselinefx, ...).
Parte 2: handler async con tutto simulato (rete, Redis, Telegram): nessuna
chiamata reale. Va eseguito accanto ad altseason_bot.py gia' patchato.
Uso: python3 -m unittest test_portfolio_baseline_fx.py -v
"""
import copy
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

import altseason_bot as bot
from altseason_bot import (
    _fx_valid, _position_view, _apply_baselinefx, _fx_source_label,
    _fmt_fx_info, _fetch_ecb_eurusd, _get_eurusd_info,
)


class TestFxValid(unittest.TestCase):
    def test_ok(self):
        self.assertTrue(_fx_valid(1.1664))
        self.assertTrue(_fx_valid("1.1"))

    def test_bad(self):
        for v in (None, 0, -1, "abc", 0.1, 5.0):
            self.assertFalse(_fx_valid(v), v)


class TestPositionView(unittest.TestCase):
    def test_fixed_baseline_does_not_move_with_todays_fx(self):
        a = _position_view(1000, 1.0, 1.1664, 1.2, 1.10)
        b = _position_view(1000, 1.0, 1.1664, 1.2, 1.20)
        self.assertAlmostEqual(a["base_value"], 1000 / 1.1664)
        self.assertAlmostEqual(a["base_value"], b["base_value"])
        self.assertAlmostEqual(a["base_price"], b["base_price"])
        self.assertNotAlmostEqual(a["cur_value"], b["cur_value"])

    def test_eur_pnl(self):
        v = _position_view(1000, 1.0, 1.1664, 1.2, 1.1181)
        self.assertEqual(v["currency"], "EUR")
        self.assertAlmostEqual(v["cur_value"], 1000 * 1.2 / 1.1181)
        self.assertAlmostEqual(v["pnl"], v["cur_value"] - 1000 / 1.1664)
        self.assertAlmostEqual(v["pnl_pct"], v["pnl"] / v["base_value"] * 100)
        self.assertTrue(v["baseline_valid"])
        self.assertFalse(v["missing_fx"])

    def test_same_price_but_fx_moved_gives_fx_effect_only(self):
        v = _position_view(100, 2.0, 1.1664, 2.0, 1.1181)
        self.assertGreater(v["pnl"], 0)

    def test_missing_baseline_fx_is_nd_never_todays_fx(self):
        v = _position_view(1000, 1.0, None, 1.2, 1.1181)
        self.assertFalse(v["baseline_valid"])
        self.assertTrue(v["missing_fx"])
        self.assertIsNone(v["base_value"])
        self.assertIsNone(v["pnl"])
        self.assertAlmostEqual(v["cur_value"], 1000 * 1.2 / 1.1181)

    def test_usd_fallback(self):
        v = _position_view(1000, 1.0, None, 1.2, None)
        self.assertEqual(v["currency"], "USD")
        self.assertTrue(v["baseline_valid"])
        self.assertAlmostEqual(v["pnl"], 200.0)
        self.assertAlmostEqual(v["pnl_pct"], 20.0)

    def test_invalid_buy(self):
        for buy in (None, 0, "x"):
            v = _position_view(10, buy, 1.1664, 1.0, 1.1)
            self.assertFalse(v["baseline_valid"])
            self.assertFalse(v["missing_fx"])
            self.assertIsNone(v["pnl"])


class TestApplyBaselineFx(unittest.TestCase):
    def test_cases(self):
        pf = {
            "A": {"qty": 1, "buy": 1.0, "baseline_at": "2026-08-24T13:21:00+02:00"},
            "B": {"qty": 1, "buy": 1.0, "baseline_at": "x", "baseline_fx": 1.12},
            "C": {"qty": 1, "buy": 1.0},
            "D": {"qty": 1, "buy": None, "baseline_at": "x"},
        }
        before = copy.deepcopy(pf)
        filled, already, nob = _apply_baselinefx(pf, 1.1664)
        self.assertEqual(filled, ["A"])
        self.assertEqual(already, ["B"])
        self.assertEqual(nob, ["C", "D"])
        self.assertEqual(pf["A"]["baseline_fx"], 1.1664)
        self.assertEqual(pf["B"]["baseline_fx"], 1.12)
        self.assertNotIn("baseline_fx", pf["C"])
        for k in pf:
            self.assertEqual(pf[k]["qty"], before[k]["qty"])
            self.assertEqual(pf[k]["buy"], before[k]["buy"])


class TestLabels(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(_fx_source_label("ecb", "2026-10-12"), "BCE 12/10/2026")
        self.assertEqual(_fx_source_label("yahoo", None), "Yahoo")
        self.assertIn("1.1181", _fmt_fx_info({"rate": 1.1181, "source": "yahoo"}))


class _Resp:
    def __init__(self, data, ok=True):
        self._d, self._ok = data, ok

    def raise_for_status(self):
        if not self._ok:
            raise RuntimeError("http")

    def json(self):
        return self._d


class TestEcb(unittest.TestCase):
    def setUp(self):
        bot._ECB_FX_CACHE["ts"] = 0.0
        bot._ECB_FX_CACHE["val"] = None

    def test_ok(self):
        with patch.object(bot.requests, "get", return_value=_Resp({"date": "2026-10-12", "rates": {"USD": 1.1181}})):
            r = _fetch_ecb_eurusd()
        self.assertEqual(r, {"rate": 1.1181, "source": "ecb", "date": "2026-10-12"})

    def test_bad_rate(self):
        with patch.object(bot.requests, "get", return_value=_Resp({"rates": {"USD": 0}})):
            self.assertIsNone(_fetch_ecb_eurusd())

    def test_exception(self):
        with patch.object(bot.requests, "get", side_effect=RuntimeError("down")):
            self.assertIsNone(_fetch_ecb_eurusd())

    def test_http_error(self):
        with patch.object(bot.requests, "get", return_value=_Resp({}, ok=False)):
            self.assertIsNone(_fetch_ecb_eurusd())


class TestGetInfo(unittest.IsolatedAsyncioTestCase):
    async def test_yahoo_first(self):
        with patch.object(bot, "_fetch_ecb_eurusd") as e:
            r = await _get_eurusd_info({"EUR/USD": {"price": 1.12}})
        self.assertEqual(r["source"], "yahoo")
        e.assert_not_called()

    async def test_ecb_fallback(self):
        ecb = {"rate": 1.1181, "source": "ecb", "date": "2026-10-12"}
        with patch.object(bot, "_fetch_ecb_eurusd", return_value=ecb):
            self.assertEqual(await _get_eurusd_info({}), ecb)

    async def test_both_fail(self):
        with patch.object(bot, "_fetch_ecb_eurusd", return_value=None):
            self.assertIsNone(await _get_eurusd_info({}))


# ---------- handler ----------
def _upd(text_args=None):
    u = MagicMock()
    u.uid = "1"
    u.message.reply_text = AsyncMock()
    c = MagicMock()
    c.args = text_args
    c.user_data = {}
    return u, c


def _sent(u):
    return "\n".join(str(call.args[0]) for call in u.message.reply_text.await_args_list)


class _H(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = {"1": {"portfolio": {
            "AAA": {"qty": 1000, "buy": 1.0, "baseline_at": "2026-08-24T13:21:00+02:00", "baseline_fx": 1.1664},
            "BBB": {"qty": 10, "buy": 100.0, "baseline_at": "2026-08-24T13:21:00+02:00"},
        }}}
        self.saved = []
        self.prices = {"AAA": {"price": 1.2}, "BBB": {"price": 110.0}}
        self.forex = {"EUR/USD": {"price": 1.1181}}
        self.n_prices = 0
        self.n_forex = 0
        outer = self

        def gp():
            outer.n_prices += 1
            return outer.prices

        def gf():
            outer.n_forex += 1
            return outer.forex

        ps = [
            patch.object(bot, "get_uid", lambda u: u.uid),
            patch.object(bot, "ADMIN_ID", "1"),
            patch.object(bot, "load_user", lambda uid: self.db.setdefault(uid, {})),
            patch.object(bot, "save_user", lambda uid, ud: (self.saved.append(uid), self.db.__setitem__(uid, ud))),
            patch.object(bot, "get_prices", gp),
            patch.object(bot, "get_forex", gf),
        ]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)


class TestPortfolio(_H):
    async def test_eur_fixed_and_missing_fx_excluded(self):
        u, c = _upd()
        await bot.cmd_portfolio(u, c)
        out = _sent(u)
        self.assertEqual(self.n_prices, 1)
        self.assertEqual(self.n_forex, 1)
        self.assertIn("€", out)
        self.assertIn("N/D (cambio storico mancante)", out)
        self.assertIn("1 posizioni senza cambio storico", out)
        self.assertIn("P&L calcolato su 1/2", out)
        base = 1000 / 1.1664
        self.assertIn("{:,.2f}".format(base), out)  # valore baseline totale = solo AAA
        cur_all = 1000 * 1.2 / 1.1181 + 10 * 110.0 / 1.1181
        self.assertIn("{:,.2f}".format(cur_all), out)

    async def test_baseline_value_independent_of_fx_today(self):
        outs = []
        for fx in (1.10, 1.25):
            self.forex = {"EUR/USD": {"price": fx}}
            u, c = _upd()
            await bot.cmd_portfolio(u, c)
            outs.append(_sent(u))
        b = "{:,.2f}".format(1000 / 1.1664)
        self.assertIn(b, outs[0])
        self.assertIn(b, outs[1])

    async def test_no_fx_anywhere_falls_back_to_usd(self):
        self.forex = {}
        with patch.object(bot, "_fetch_ecb_eurusd", return_value=None):
            u, c = _upd()
            await bot.cmd_portfolio(u, c)
        out = _sent(u)
        self.assertIn("non disponibile", out)
        self.assertIn("$", out)
        self.assertNotIn("€", out)

    async def test_ecb_fallback_shown(self):
        self.forex = {}
        ecb = {"rate": 1.1181, "source": "ecb", "date": "2026-10-12"}
        with patch.object(bot, "_fetch_ecb_eurusd", return_value=ecb):
            u, c = _upd()
            await bot.cmd_portfolio(u, c)
        out = _sent(u)
        self.assertIn("BCE 12/10/2026", out)
        self.assertIn("€", out)

    async def test_does_not_write(self):
        u, c = _upd()
        await bot.cmd_portfolio(u, c)
        self.assertEqual(self.saved, [])


class TestResetBaseline(_H):
    async def test_refused_without_fx(self):
        self.forex = {}
        with patch.object(bot, "_fetch_ecb_eurusd", return_value=None):
            u, c = _upd()
            await bot.cmd_resetbaseline(u, c)
        self.assertIn("Reset annullato", _sent(u))
        self.assertNotIn("pending_resetbaseline", c.user_data)
        self.assertEqual(self.saved, [])

    async def test_preview_and_pending_have_fx(self):
        u, c = _upd()
        await bot.cmd_resetbaseline(u, c)
        p = c.user_data["pending_resetbaseline"]
        self.assertEqual(p["fx"], 1.1181)
        self.assertEqual(p["fx_source"], "yahoo")
        self.assertEqual(p["prices"], {"AAA": 1.2, "BBB": 110.0})
        out = _sent(u)
        self.assertIn("€", out)
        self.assertIn("Baseline precedente: `N/D`", out)  # BBB senza cambio
        self.assertEqual(self.n_prices, 1)
        self.assertEqual(self.n_forex, 1)
        self.assertEqual(self.saved, [])

    async def _confirm(self, c, data="resetbaseline_confirm"):
        upd = MagicMock()
        q = upd.callback_query
        q.answer = AsyncMock()
        q.edit_message_text = AsyncMock()
        q.message.chat_id = 1
        q.data = data
        await bot.resetbaseline_callback(upd, c)
        return q

    async def test_confirm_saves_fx_and_keeps_qty(self):
        u, c = _upd()
        await bot.cmd_resetbaseline(u, c)
        q = await self._confirm(c)
        pf = self.db["1"]["portfolio"]
        for s in ("AAA", "BBB"):
            self.assertEqual(pf[s]["baseline_fx"], 1.1181)
            self.assertEqual(pf[s]["baseline_fx_source"], "yahoo")
        self.assertEqual(pf["AAA"]["buy"], 1.2)
        self.assertEqual(pf["AAA"]["qty"], 1000)
        self.assertEqual(pf["BBB"]["qty"], 10)
        self.assertIn("1.1181", q.edit_message_text.await_args.args[0])
        self.assertEqual(self.n_prices, 1)  # nessuna seconda get_prices alla conferma
        self.assertEqual(self.n_forex, 1)

    async def test_confirm_without_fx_in_pending_refused(self):
        c = MagicMock()
        c.user_data = {"pending_resetbaseline": {"prices": {"AAA": 9.0}, "baseline_at": "2026-10-13T08:00:00+02:00"}}
        before = copy.deepcopy(self.db)
        await self._confirm(c)
        self.assertEqual(self.db, before)
        self.assertEqual(self.saved, [])

    async def test_cancel(self):
        u, c = _upd()
        await bot.cmd_resetbaseline(u, c)
        await self._confirm(c, "resetbaseline_cancel")
        self.assertNotIn("pending_resetbaseline", c.user_data)
        self.assertEqual(self.saved, [])

    async def test_fixed_after_reset(self):
        u, c = _upd()
        await bot.cmd_resetbaseline(u, c)
        await self._confirm(c)
        outs = []
        for fx in (1.10, 1.30):
            self.forex = {"EUR/USD": {"price": fx}}
            u2, c2 = _upd()
            await bot.cmd_portfolio(u2, c2)
            outs.append(_sent(u2))
        b = "{:,.2f}".format(1000 * 1.2 / 1.1181 + 10 * 110.0 / 1.1181)
        self.assertIn(b, outs[0])
        self.assertIn(b, outs[1])


class TestBaselineFxCmd(_H):
    async def test_non_admin(self):
        u, c = _upd(["1.1664"])
        u.uid = "2"
        await bot.cmd_baselinefx(u, c)
        self.assertIn("riservato", _sent(u))
        self.assertEqual(self.saved, [])

    async def test_bad_args(self):
        for args in (None, [], ["a"], ["1", "2"], ["9.9"], ["0"]):
            u, c = _upd(args)
            await bot.cmd_baselinefx(u, c)
            self.assertEqual(self.saved, [], args)

    async def test_fills_only_missing_and_is_idempotent(self):
        u, c = _upd(["1,1664"])
        await bot.cmd_baselinefx(u, c)
        pf = self.db["1"]["portfolio"]
        self.assertEqual(pf["BBB"]["baseline_fx"], 1.1664)
        self.assertEqual(pf["BBB"]["baseline_fx_source"], "manual")
        self.assertEqual(pf["AAA"]["baseline_fx"], 1.1664)
        self.assertEqual(pf["BBB"]["buy"], 100.0)
        self.assertEqual(pf["BBB"]["qty"], 10)
        n = len(self.saved)
        u2, c2 = _upd(["1.5"])
        await bot.cmd_baselinefx(u2, c2)
        self.assertEqual(len(self.saved), n)
        self.assertEqual(pf["BBB"]["baseline_fx"], 1.1664)


if __name__ == "__main__":
    unittest.main()
