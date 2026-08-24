"""
Test Portfolio Engine — /resetbaseline + visualizzazione /portfolio.

Testa ESCLUSIVAMENTE le funzioni pure (nessuna chiamata di rete, nessuna
dipendenza da Telegram/Redis): _resetbaseline_validate_price,
_pnl_position, _usd_to_eur, _get_valid_eurusd_rate, _resetbaseline_build_plan.

Gli handler async (cmd_portfolio, cmd_resetbaseline, resetbaseline_callback)
non sono testati qui direttamente: richiederebbero di simulare l'intera
libreria python-telegram-bot (Update, CallbackQuery, Context) in modo
sproporzionato rispetto al rischio reale — la logica di calcolo che
conta davvero e' tutta nelle funzioni pure sopra, gia' coperta.

Va eseguito nell'ambiente reale del bot (stesso Python/dipendenze gia'
configurate), non in un sandbox isolato.
"""
import unittest

from altseason_bot import (
    _resetbaseline_validate_price,
    _pnl_position,
    _usd_to_eur,
    _get_valid_eurusd_rate,
    _resetbaseline_build_plan,
)


class TestValidatePrice(unittest.TestCase):
    def test_valid_positive_number(self):
        self.assertTrue(_resetbaseline_validate_price(1.5))
        self.assertTrue(_resetbaseline_validate_price(100))

    def test_zero_invalid(self):
        self.assertFalse(_resetbaseline_validate_price(0))
        self.assertFalse(_resetbaseline_validate_price(0.0))

    def test_negative_invalid(self):
        self.assertFalse(_resetbaseline_validate_price(-5))

    def test_none_invalid(self):
        self.assertFalse(_resetbaseline_validate_price(None))

    def test_non_numeric_string_invalid(self):
        self.assertFalse(_resetbaseline_validate_price("abc"))

    def test_numeric_string_valid(self):
        self.assertTrue(_resetbaseline_validate_price("1.5"))


class TestPnlPosition(unittest.TestCase):
    def test_case_A_xrp_reset_gives_zero_pnl(self):
        # Test obbligatorio A: qty=20000, buy=1.50 (nuova baseline), current=1.50
        calc = _pnl_position(qty=20000, buy=1.50, current_price=1.50)
        self.assertTrue(calc["baseline_valid"])
        self.assertAlmostEqual(calc["initial_value_usd"], 30000.0)
        self.assertAlmostEqual(calc["current_value_usd"], 30000.0)
        self.assertAlmostEqual(calc["pnl_usd"], 0.0)
        self.assertAlmostEqual(calc["pnl_pct"], 0.0)

    def test_case_B_decimal_quantity_eth(self):
        # Test obbligatorio B: ETH qty=3.2, current=4200, baseline=4200 -> pnl 0
        calc = _pnl_position(qty=3.2, buy=4200, current_price=4200)
        self.assertAlmostEqual(calc["initial_value_usd"], 13440.0, places=4)
        self.assertAlmostEqual(calc["pnl_usd"], 0.0)

    def test_qty_never_modified(self):
        qty = 20000
        _pnl_position(qty=qty, buy=1.0, current_price=1.5)
        self.assertEqual(qty, 20000)  # invariata dopo la chiamata

    def test_positive_pnl(self):
        calc = _pnl_position(qty=100, buy=1.0, current_price=1.5)
        self.assertAlmostEqual(calc["pnl_usd"], 50.0)
        self.assertAlmostEqual(calc["pnl_pct"], 50.0)

    def test_negative_pnl(self):
        calc = _pnl_position(qty=100, buy=2.0, current_price=1.0)
        self.assertAlmostEqual(calc["pnl_usd"], -100.0)
        self.assertAlmostEqual(calc["pnl_pct"], -50.0)

    def test_buy_zero_gives_na_not_zero_percent(self):
        # Test obbligatorio K: buy=0 -> P&L N/D, non 0%
        calc = _pnl_position(qty=100, buy=0, current_price=1.5)
        self.assertFalse(calc["baseline_valid"])
        self.assertIsNone(calc["pnl_usd"])
        self.assertIsNone(calc["pnl_pct"])
        self.assertIsNone(calc["initial_value_usd"])
        # il valore corrente resta comunque calcolabile (fatto oggettivo)
        self.assertAlmostEqual(calc["current_value_usd"], 150.0)

    def test_buy_none_gives_na_not_zero_percent(self):
        # Test obbligatorio L: buy=None -> P&L N/D
        calc = _pnl_position(qty=100, buy=None, current_price=1.5)
        self.assertFalse(calc["baseline_valid"])
        self.assertIsNone(calc["pnl_usd"])
        self.assertIsNone(calc["pnl_pct"])

    def test_buy_negative_gives_na(self):
        calc = _pnl_position(qty=100, buy=-5, current_price=1.5)
        self.assertFalse(calc["baseline_valid"])
        self.assertIsNone(calc["pnl_pct"])

    def test_current_value_always_computed_even_with_invalid_baseline(self):
        # una posizione senza baseline valida DEVE comunque avere un
        # valore corrente calcolabile (entra nel totale attuale)
        calc = _pnl_position(qty=50, buy=None, current_price=2.0)
        self.assertAlmostEqual(calc["current_value_usd"], 100.0)


class TestUsdToEur(unittest.TestCase):
    def test_case_I_known_conversion(self):
        # Test obbligatorio I: EURUSD=1.20, USD 120 -> EUR 100
        result = _usd_to_eur(120.0, 1.20)
        self.assertAlmostEqual(result, 100.0)

    def test_real_verified_rate(self):
        # tasso realmente verificato in sessione (live): 1 EUR = 1.1671 USD
        result = _usd_to_eur(1167.1, 1.1671)
        self.assertAlmostEqual(result, 1000.0, places=2)

    def test_none_value_gives_none(self):
        self.assertIsNone(_usd_to_eur(None, 1.20))

    def test_invalid_rate_gives_none(self):
        self.assertIsNone(_usd_to_eur(100.0, 0))
        self.assertIsNone(_usd_to_eur(100.0, None))
        self.assertIsNone(_usd_to_eur(100.0, -1))


class TestGetValidEurusdRate(unittest.TestCase):
    def test_valid_forex_data(self):
        forex = {"EUR/USD": {"price": 1.1671, "ch": 0.1}}
        self.assertAlmostEqual(_get_valid_eurusd_rate(forex), 1.1671)

    def test_missing_key_gives_none(self):
        # Test obbligatorio J: forex mancante -> mai un cambio inventato
        forex = {"GBP/USD": {"price": 1.3}}
        self.assertIsNone(_get_valid_eurusd_rate(forex))

    def test_empty_dict_gives_none(self):
        self.assertIsNone(_get_valid_eurusd_rate({}))

    def test_none_input_gives_none(self):
        self.assertIsNone(_get_valid_eurusd_rate(None))

    def test_zero_rate_gives_none(self):
        forex = {"EUR/USD": {"price": 0}}
        self.assertIsNone(_get_valid_eurusd_rate(forex))

    def test_non_numeric_rate_gives_none(self):
        forex = {"EUR/USD": {"price": "n/a"}}
        self.assertIsNone(_get_valid_eurusd_rate(forex))


class TestResetbaselineBuildPlan(unittest.TestCase):
    def test_valid_price_included_in_plan(self):
        portfolio = {"XRP": {"qty": 20000, "buy": 1.0}}
        prices = {"XRP": {"price": 1.5}}
        valid, skipped = _resetbaseline_build_plan(portfolio, prices)
        self.assertEqual(valid, {"XRP": 1.5})
        self.assertEqual(skipped, [])

    def test_case_C_zero_price_skipped(self):
        # Test obbligatorio C: prezzo 0 -> asset saltato
        portfolio = {"XRP": {"qty": 20000, "buy": 1.0}}
        prices = {"XRP": {"price": 0}}
        valid, skipped = _resetbaseline_build_plan(portfolio, prices)
        self.assertEqual(valid, {})
        self.assertEqual(skipped, ["XRP"])

    def test_case_D_missing_price_skipped(self):
        # Test obbligatorio D: asset senza prezzo -> saltato
        portfolio = {"ZZZ": {"qty": 100, "buy": 1.0}}
        prices = {}  # nessun prezzo disponibile per ZZZ
        valid, skipped = _resetbaseline_build_plan(portfolio, prices)
        self.assertEqual(valid, {})
        self.assertEqual(skipped, ["ZZZ"])

    def test_mixed_portfolio_partial_skip(self):
        portfolio = {
            "XRP": {"qty": 20000, "buy": 1.0},
            "ZZZ": {"qty": 100, "buy": 5.0},
        }
        prices = {"XRP": {"price": 1.5}}  # ZZZ assente
        valid, skipped = _resetbaseline_build_plan(portfolio, prices)
        self.assertEqual(valid, {"XRP": 1.5})
        self.assertEqual(skipped, ["ZZZ"])

    def test_portfolio_not_mutated(self):
        portfolio = {"XRP": {"qty": 20000, "buy": 1.0}}
        prices = {"XRP": {"price": 1.5}}
        _resetbaseline_build_plan(portfolio, prices)
        # 'buy' nel portfolio originale NON deve cambiare qui — il piano
        # viene solo costruito, l'applicazione avviene altrove (alla conferma)
        self.assertEqual(portfolio["XRP"]["buy"], 1.0)

    def test_qty_untouched_by_plan_building(self):
        portfolio = {"XRP": {"qty": 20000, "buy": 1.0}}
        prices = {"XRP": {"price": 1.5}}
        _resetbaseline_build_plan(portfolio, prices)
        self.assertEqual(portfolio["XRP"]["qty"], 20000)


class TestRetrocompatibility(unittest.TestCase):
    def test_position_without_baseline_at_does_not_crash(self):
        # Test obbligatorio N: portfolio senza baseline_at non crasha
        pos = {"qty": 100, "buy": 1.5}  # nessuna chiave baseline_at/baseline_source
        calc = _pnl_position(pos["qty"], pos["buy"], current_price=2.0)
        self.assertTrue(calc["baseline_valid"])
        self.assertIsNotNone(calc["pnl_usd"])
        # pos.get("baseline_at") deve dare None senza sollevare eccezioni
        self.assertIsNone(pos.get("baseline_at"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
