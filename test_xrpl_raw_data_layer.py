"""
Test M1 — XRPL Raw Data Layer.
Usa mock delle risposte HTTP: nessuna rete reale necessaria (l'ambiente
di sviluppo sandboxed non ha accesso a XRPL/DeFiLlama/RWA.xyz).
Un test finale di integrazione con rete reale va eseguito da Enrico
sul suo terminale, come da metodo di lavoro consolidato in questo progetto.
"""
import os
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import xrpl_raw_data_layer as layer


def _fake_response(status_code=200, json_data=None, raise_json_error=False):
    resp = MagicMock()
    resp.status_code = status_code
    if raise_json_error:
        resp.json.side_effect = ValueError("invalid json")
    else:
        resp.json.return_value = json_data
    return resp


class TestEnvelope(unittest.TestCase):
    def test_available_envelope_shape(self):
        env = layer._available("test.source", {"foo": "bar"})
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertEqual(env["source"], "test.source")
        self.assertIsNone(env["error"])
        self.assertIn("fetched_at_utc", env)
        self.assertEqual(env["data"], {"foo": "bar"})

    def test_unavailable_envelope_shape(self):
        env = layer._unavailable("test.source", "qualche motivo")
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIsNone(env["data"])
        self.assertEqual(env["error"], "qualche motivo")


class TestCache(unittest.TestCase):
    def setUp(self):
        layer._raw_cache.clear()

    def test_cache_set_get_roundtrip(self):
        layer._cache_set("k1", {"x": 1})
        self.assertEqual(layer._cache_get("k1"), {"x": 1})

    def test_cache_miss_returns_none(self):
        self.assertIsNone(layer._cache_get("does-not-exist"))

    def test_cache_expiry(self):
        layer._cache_set("k2", {"x": 2})
        # forzo scadenza manuale
        layer._raw_cache["k2"] = (0, {"x": 2})
        self.assertIsNone(layer._cache_get("k2"))


class TestHttpGetJson(unittest.TestCase):
    @patch("xrpl_raw_data_layer.requests.get")
    def test_success(self, mock_get):
        mock_get.return_value = _fake_response(200, {"ok": True})
        data, err = layer._http_get_json("https://example.test", source="unit")
        self.assertIsNone(err)
        self.assertEqual(data, {"ok": True})

    @patch("xrpl_raw_data_layer.requests.get")
    @patch("xrpl_raw_data_layer.time.sleep", return_value=None)
    def test_retry_then_success(self, mock_sleep, mock_get):
        mock_get.side_effect = [_fake_response(503), _fake_response(200, {"ok": True})]
        data, err = layer._http_get_json("https://example.test", max_retries=2, source="unit")
        self.assertIsNone(err)
        self.assertEqual(data, {"ok": True})
        self.assertEqual(mock_get.call_count, 2)

    @patch("xrpl_raw_data_layer.requests.get")
    @patch("xrpl_raw_data_layer.time.sleep", return_value=None)
    def test_all_retries_exhausted(self, mock_sleep, mock_get):
        mock_get.return_value = _fake_response(503)
        data, err = layer._http_get_json("https://example.test", max_retries=2, source="unit")
        self.assertIsNone(data)
        self.assertIn("503", err)
        self.assertEqual(mock_get.call_count, 3)  # 1 iniziale + 2 retry

    @patch("xrpl_raw_data_layer.requests.get")
    def test_non_retryable_status_no_retry(self, mock_get):
        mock_get.return_value = _fake_response(404)
        data, err = layer._http_get_json("https://example.test", max_retries=2, source="unit")
        self.assertIsNone(data)
        self.assertIn("404", err)
        self.assertEqual(mock_get.call_count, 1)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_invalid_json_response(self, mock_get):
        mock_get.return_value = _fake_response(200, raise_json_error=True)
        data, err = layer._http_get_json("https://example.test", source="unit")
        self.assertIsNone(data)
        self.assertIn("non-JSON", err)


class TestXrplGatewayBalances(unittest.TestCase):
    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.post")
    def test_available(self, mock_post):
        mock_post.return_value = _fake_response(200, {
            "result": {"account": layer._RLUSD_ISSUER, "obligations": {"RLUSD": "1000.0"}}
        })
        env = layer.xrpl_gateway_balances()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertEqual(env["data"]["obligations"]["RLUSD"], "1000.0")

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.time.sleep", return_value=None)
    def test_primary_fails_fallback_succeeds(self, mock_sleep, mock_post):
        # primario (con retry) fallisce sempre, fallback riesce al primo colpo
        primary_fail = _fake_response(503)
        fallback_ok = _fake_response(200, {"result": {"account": "X", "obligations": {}}})
        mock_post.side_effect = [primary_fail, primary_fail, primary_fail, fallback_ok]
        env = layer.xrpl_gateway_balances(account="X")
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.time.sleep", return_value=None)
    def test_both_nodes_fail_returns_unavailable_not_exception(self, mock_sleep, mock_post):
        mock_post.return_value = _fake_response(503)
        try:
            env = layer.xrpl_gateway_balances(account="X")
        except Exception as e:
            self.fail(f"xrpl_gateway_balances ha sollevato un'eccezione invece di ritornare SOURCE_UNAVAILABLE: {e}")
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.post")
    def test_malformed_response_missing_account_field(self, mock_post):
        mock_post.return_value = _fake_response(200, {"result": {"obligations": {}}})
        env = layer.xrpl_gateway_balances(account="X")
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("account", env["error"])


class TestXrplAmmInfo(unittest.TestCase):
    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.post")
    def test_available(self, mock_post):
        mock_post.return_value = _fake_response(200, {"result": {"amm": {"lp_token": {}}}})
        env = layer.xrpl_amm_info()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)

    @patch("xrpl_raw_data_layer.requests.post")
    def test_pool_not_found(self, mock_post):
        mock_post.return_value = _fake_response(200, {"result": {}})
        env = layer.xrpl_amm_info()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)


class TestXrplBookChangesLatest(unittest.TestCase):
    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.post")
    def test_full_chain_server_info_then_book_changes(self, mock_post):
        server_info_resp = _fake_response(200, {
            "result": {"info": {"validated_ledger": {"seq": 12345}}}
        })
        book_changes_resp = _fake_response(200, {
            "result": {"changes": [{"currency_a": "XRP_drops"}], "ledger_index": 12345}
        })
        mock_post.side_effect = [server_info_resp, book_changes_resp]
        env = layer.xrpl_book_changes_latest()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertEqual(env["data"]["ledger_index"], 12345)

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.time.sleep", return_value=None)
    def test_server_info_unavailable_propagates_gracefully(self, mock_sleep, mock_post):
        mock_post.return_value = _fake_response(503)
        env = layer.xrpl_book_changes_latest()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("validato", env["error"])


class TestDefiLlamaAdapters(unittest.TestCase):
    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.get")
    def test_chain_tvl_history_available(self, mock_get):
        mock_get.return_value = _fake_response(200, [{"date": 1, "tvl": 100}])
        env = layer.defillama_chain_tvl_history()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_chain_tvl_history_wrong_shape(self, mock_get):
        mock_get.return_value = _fake_response(200, {"unexpected": "dict"})
        env = layer.defillama_chain_tvl_history()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_stablecoins_chain_history_available(self, mock_get):
        mock_get.return_value = _fake_response(200, [{"date": 1, "totalCirculating": {}}])
        env = layer.defillama_stablecoins_chain_history()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_dex_overview_available(self, mock_get):
        mock_get.return_value = _fake_response(200, {"total24h": 12345})
        env = layer.defillama_dex_overview()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)


class TestXrplToDexVolume(unittest.TestCase):
    """M8 Gap 2A: adapter XRPL.to per il volume DEX aggregato di rete."""

    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.get")
    def test_valid_payload_real_shape(self, mock_get):
        # Forma realistica verificata con chiamata reale in fase di audit
        mock_get.return_value = _fake_response(200, {
            "global": {"gDexVolume": 2557644.785188, "gXRPdominance": 98.43},
            "tokens": [],
        })
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertAlmostEqual(env["data"]["gDexVolume"], 2557644.785188)
        self.assertEqual(env["source"], "xrpl_to.dex_volume")
        self.assertIn("fetched_at_utc", env)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_gdexvolume_zero_is_valid(self, mock_get):
        mock_get.return_value = _fake_response(200, {"global": {"gDexVolume": 0}})
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertEqual(env["data"]["gDexVolume"], 0.0)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_global_field_missing(self, mock_get):
        mock_get.return_value = _fake_response(200, {"tokens": []})
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("global", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_gdexvolume_field_missing(self, mock_get):
        mock_get.return_value = _fake_response(200, {"global": {"gXRPdominance": 98.0}})
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("gDexVolume", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_gdexvolume_non_numeric(self, mock_get):
        mock_get.return_value = _fake_response(200, {"global": {"gDexVolume": "non-un-numero"}})
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("non numerico", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_gdexvolume_boolean_rejected(self, mock_get):
        # bool e' sottoclasse di int in Python: deve essere esplicitamente escluso
        mock_get.return_value = _fake_response(200, {"global": {"gDexVolume": True}})
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_gdexvolume_negative_rejected(self, mock_get):
        mock_get.return_value = _fake_response(200, {"global": {"gDexVolume": -100.0}})
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("negativo", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_response_not_a_dict(self, mock_get):
        mock_get.return_value = _fake_response(200, ["lista", "inattesa"])
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_malformed_json(self, mock_get):
        mock_get.return_value = _fake_response(200, raise_json_error=True)
        env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_http_error_status(self, mock_get):
        mock_get.return_value = _fake_response(500)
        with patch.object(layer, "_MAX_RETRIES", 0):
            env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("500", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()
        with patch.object(layer, "_MAX_RETRIES", 0):
            env = layer.xrpl_to_dex_volume()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("timeout", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_never_raises_on_connection_error(self, mock_get):
        # Errore di rete realistico (sottoclasse di RequestException, gia'
        # gestita da _http_get_json) — non un'eccezione Python arbitraria,
        # che non rientra nella categoria "errori di rete" dichiarata.
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("connessione rifiutata")
        with patch.object(layer, "_MAX_RETRIES", 0), \
             patch("xrpl_raw_data_layer.time.sleep", return_value=None):
            try:
                env = layer.xrpl_to_dex_volume()
            except Exception as e:
                self.fail(f"xrpl_to_dex_volume ha sollevato un'eccezione: {e}")
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_cache_avoids_duplicate_calls(self, mock_get):
        mock_get.return_value = _fake_response(200, {"global": {"gDexVolume": 1000.0}})
        layer.xrpl_to_dex_volume()
        layer.xrpl_to_dex_volume()
        self.assertEqual(mock_get.call_count, 1)

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.requests.get")
    def test_included_in_collect_xrpl_raw_snapshot(self, mock_get, mock_post):
        mock_get.return_value = _fake_response(200, {"global": {"gDexVolume": 500.0}})
        mock_post.return_value = _fake_response(500)  # adapter nativi: falliscono velocemente, non ci interessano qui
        tmpdir = tempfile.mkdtemp()
        with patch.object(layer, "_RAW_SNAPSHOT_PATH", os.path.join(tmpdir, "s.jsonl")), \
             patch.object(layer, "_MAX_RETRIES", 0), \
             patch("xrpl_raw_data_layer.time.sleep", return_value=None):
            snapshot = layer.collect_xrpl_raw_snapshot()
        self.assertIn("xrpl_to", snapshot["sources"])
        self.assertIn("dex_volume", snapshot["sources"]["xrpl_to"])
        self.assertEqual(snapshot["sources"]["xrpl_to"]["dex_volume"]["status"], layer.STATUS_RAW_AVAILABLE)


class TestXrplFiRwaMetrics(unittest.TestCase):
    """M8 Gap 5A: adapter xrpl.fi per RWA (totalTvl)."""

    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.get")
    def test_valid_payload(self, mock_get):
        mock_get.return_value = _fake_response(200, {"totalTvl": 1234567.89, "tvlSeries": [{"date": "2026-08-01", "tvl": 1000000}]})
        env = layer.xrpl_fi_rwa_metrics()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertAlmostEqual(env["data"]["total_tvl_usd"], 1234567.89)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_total_tvl_field_missing(self, mock_get):
        mock_get.return_value = _fake_response(200, {"tvlSeries": []})
        env = layer.xrpl_fi_rwa_metrics()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("totalTvl", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_total_tvl_non_numeric(self, mock_get):
        mock_get.return_value = _fake_response(200, {"totalTvl": "non-un-numero"})
        env = layer.xrpl_fi_rwa_metrics()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("non numerico", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_total_tvl_negative_rejected(self, mock_get):
        mock_get.return_value = _fake_response(200, {"totalTvl": -100.0})
        env = layer.xrpl_fi_rwa_metrics()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("negativo", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_http_error_isolated(self, mock_get):
        mock_get.return_value = _fake_response(500)
        with patch.object(layer, "_MAX_RETRIES", 0):
            env = layer.xrpl_fi_rwa_metrics()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_never_raises_on_connection_error(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.ConnectionError("connessione rifiutata")
        with patch.object(layer, "_MAX_RETRIES", 0):
            try:
                env = layer.xrpl_fi_rwa_metrics()
            except Exception as e:
                self.fail(f"xrpl_fi_rwa_metrics ha sollevato un'eccezione: {e}")
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.get")
    def test_cache_avoids_duplicate_calls(self, mock_get):
        mock_get.return_value = _fake_response(200, {"totalTvl": 1000.0})
        layer.xrpl_fi_rwa_metrics()
        layer.xrpl_fi_rwa_metrics()
        self.assertEqual(mock_get.call_count, 1)

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.requests.get")
    def test_included_in_collect_xrpl_raw_snapshot(self, mock_get, mock_post):
        mock_get.return_value = _fake_response(200, {"totalTvl": 1000.0})
        mock_post.return_value = _fake_response(500)
        with patch.object(layer, "_MAX_RETRIES", 0), \
             patch("xrpl_raw_data_layer.time.sleep", return_value=None):
            tmpdir = tempfile.mkdtemp()
            with patch.object(layer, "_RAW_SNAPSHOT_PATH", os.path.join(tmpdir, "s.jsonl")):
                snapshot = layer.collect_xrpl_raw_snapshot()
        self.assertIn("xrpl_fi", snapshot["sources"])
        self.assertEqual(snapshot["sources"]["xrpl_fi"]["rwa_metrics"]["status"], layer.STATUS_RAW_AVAILABLE)
        # DeFiLlama e RWA.xyz devono restare presenti e distinti
        self.assertIn("defillama", snapshot["sources"])
        self.assertIn("rwa_xyz", snapshot["sources"])


class TestXrplLedgerInfo(unittest.TestCase):
    """M8 Gap 4A: adapter leggero xrpl_ledger_info per total_coins."""

    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.post")
    def test_valid_ledger_response(self, mock_post):
        mock_post.return_value = _fake_response(200, {
            "result": {"ledger": {"total_coins": "99985738468528946"}, "validated": True}
        })
        env = layer.xrpl_ledger_info()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertAlmostEqual(env["data"]["total_coins_drops"], 99985738468528946.0)

    @patch("xrpl_raw_data_layer.requests.post")
    def test_total_coins_field_missing(self, mock_post):
        mock_post.return_value = _fake_response(200, {"result": {"ledger": {}, "validated": True}})
        env = layer.xrpl_ledger_info()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("total_coins", env["error"])

    @patch("xrpl_raw_data_layer.requests.post")
    def test_total_coins_non_numeric(self, mock_post):
        mock_post.return_value = _fake_response(200, {
            "result": {"ledger": {"total_coins": "non-un-numero"}, "validated": True}
        })
        env = layer.xrpl_ledger_info()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("non numerico", env["error"])

    @patch("xrpl_raw_data_layer.requests.post")
    def test_total_coins_negative_rejected(self, mock_post):
        mock_post.return_value = _fake_response(200, {
            "result": {"ledger": {"total_coins": "-100"}, "validated": True}
        })
        env = layer.xrpl_ledger_info()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("negativo", env["error"])

    @patch("xrpl_raw_data_layer.requests.post")
    def test_ledger_field_missing(self, mock_post):
        mock_post.return_value = _fake_response(200, {"result": {"validated": True}})
        env = layer.xrpl_ledger_info()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertIn("ledger", env["error"])

    @patch("xrpl_raw_data_layer.requests.post")
    def test_http_error_isolated(self, mock_post):
        mock_post.return_value = _fake_response(500)
        with patch.object(layer, "_MAX_RETRIES", 0):
            env = layer.xrpl_ledger_info()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)

    @patch("xrpl_raw_data_layer.requests.post")
    def test_included_in_collect_xrpl_raw_snapshot(self, mock_post):
        mock_post.return_value = _fake_response(200, {
            "result": {"ledger": {"total_coins": "99985738468528946"}, "validated": True}
        })
        with patch.object(layer, "_MAX_RETRIES", 0), \
             patch("xrpl_raw_data_layer.requests.get", return_value=_fake_response(500)), \
             patch("xrpl_raw_data_layer.time.sleep", return_value=None):
            tmpdir = tempfile.mkdtemp()
            with patch.object(layer, "_RAW_SNAPSHOT_PATH", os.path.join(tmpdir, "s.jsonl")):
                snapshot = layer.collect_xrpl_raw_snapshot()
        self.assertIn("ledger_info", snapshot["sources"]["xrpl_native"])


class TestXrplAccountLinesPaginated(unittest.TestCase):
    """M8 Gap 3 + ottimizzazione finale: paginazione completa di
    account_lines, con endpoint fissato una volta e ledger pinnato."""

    def setUp(self):
        layer._raw_cache.clear()

    @staticmethod
    def _make_fixed_endpoint_mock(primary_fails=True, ledger_index=88530953,
                                   account_lines_pages=None, ledger_resolve_fails_everywhere=False):
        """account_lines_pages: lista di (result, err) restituiti in sequenza
        alle chiamate 'account_lines'. call_log registra ogni chiamata reale."""
        call_log = []
        pages_iter = iter(account_lines_pages or [])

        def fake(url, method, params, source_label):
            call_log.append({"url": url, "method": method, "params": dict(params)})
            if primary_fails and url == layer._XRPL_RPC_PRIMARY:
                return None, "HTTP 402"
            if method == "ledger":
                if ledger_resolve_fails_everywhere:
                    return None, "ledger resolve fallito"
                return {"ledger": {"total_coins": "99"}, "ledger_index": ledger_index}, None
            if method == "account_lines":
                try:
                    return next(pages_iter)
                except StopIteration:
                    return None, "nessuna pagina mock rimanente"
            return None, "metodo non gestito nel mock"

        return fake, call_log

    def test_single_page_complete(self):
        pages = [({"lines": [{"account": f"r{i}", "currency": "RLUSD"} for i in range(50)]}, None)]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertEqual(env["data"]["total_trustlines"], 50)
        self.assertEqual(env["data"]["pages_fetched"], 1)
        self.assertTrue(env["data"]["complete"])

    def test_multiple_pages_complete(self):
        pages = [
            ({"lines": [{"account": f"r1_{i}", "currency": "RLUSD"} for i in range(400)], "marker": "MARK1"}, None),
            ({"lines": [{"account": f"r2_{i}", "currency": "RLUSD"} for i in range(400)], "marker": "MARK2"}, None),
            ({"lines": [{"account": f"r3_{i}", "currency": "RLUSD"} for i in range(30)]}, None),
        ]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        self.assertEqual(env["data"]["total_trustlines"], 830)  # 400+400+30
        self.assertEqual(env["data"]["pages_fetched"], 3)
        self.assertTrue(env["data"]["complete"])

    def test_limit_400_used_in_every_page_request(self):
        pages = [({"lines": [{"account": "r1", "currency": "RLUSD"}]}, None)]
        fake, call_log = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            layer.xrpl_account_lines_paginated()
        account_lines_calls = [c for c in call_log if c["method"] == "account_lines"]
        self.assertEqual(len(account_lines_calls), 1)
        self.assertEqual(account_lines_calls[0]["params"]["limit"], 400)

    def test_ledger_resolved_once_and_pinned_on_every_page(self):
        pages = [
            ({"lines": [{"account": f"r1_{i}", "currency": "RLUSD"} for i in range(400)], "marker": "MARK1"}, None),
            ({"lines": [{"account": f"r2_{i}", "currency": "RLUSD"} for i in range(10)]}, None),
        ]
        fake, call_log = self._make_fixed_endpoint_mock(ledger_index=99999999, account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            layer.xrpl_account_lines_paginated()
        ledger_calls = [c for c in call_log if c["method"] == "ledger"]
        account_lines_calls = [c for c in call_log if c["method"] == "account_lines"]
        # risoluzione ledger tentata sul primario (fallisce) + una volta sul fallback = 2 chiamate 'ledger'
        self.assertEqual(len(ledger_calls), 2)
        # OGNI pagina account_lines usa lo STESSO ledger_index pinnato
        used_ledger_indexes = {c["params"]["ledger_index"] for c in account_lines_calls}
        self.assertEqual(used_ledger_indexes, {99999999})

    def test_primary_tried_exactly_once_fallback_reused_for_all_pages(self):
        pages = [
            ({"lines": [{"account": f"r1_{i}", "currency": "RLUSD"} for i in range(400)], "marker": "MARK1"}, None),
            ({"lines": [{"account": f"r2_{i}", "currency": "RLUSD"} for i in range(400)], "marker": "MARK2"}, None),
            ({"lines": [{"account": f"r3_{i}", "currency": "RLUSD"} for i in range(5)]}, None),
        ]
        fake, call_log = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            layer.xrpl_account_lines_paginated()
        primary_calls = [c for c in call_log if c["url"] == layer._XRPL_RPC_PRIMARY]
        fallback_calls = [c for c in call_log if c["url"] == layer._XRPL_RPC_FALLBACK]
        self.assertEqual(len(primary_calls), 1)  # tentato SOLO per la risoluzione iniziale, mai per pagina
        self.assertEqual(len(fallback_calls), 1 + 3)  # 1 resolve + 3 pagine, tutte sul fallback

    def test_final_marker_absent_ends_pagination(self):
        pages = [({"lines": [{"account": "r1", "currency": "RLUSD"}]}, None)]  # nessun campo 'marker'
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertTrue(env["data"]["complete"])
        self.assertEqual(env["data"]["pages_fetched"], 1)

    def test_repeated_marker_stops_safely(self):
        pages = [({"lines": [{"account": "r1", "currency": "RLUSD"}], "marker": "SAME_MARKER"}, None)] * 10
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated(max_pages=10)
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertFalse(env["data"]["complete"])
        self.assertIn("ripetuto", env["error"])
        self.assertLessEqual(env["data"]["pages_fetched"], 3)

    def test_intermediate_page_failure(self):
        pages = [
            ({"lines": [{"account": "r1", "currency": "RLUSD"}], "marker": "MARK1"}, None),
            (None, "errore di rete simulato"),
        ]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertFalse(env["data"]["complete"])
        self.assertIn("fallita", env["error"])
        self.assertEqual(env["data"]["total_trustlines"], 1)  # la prima pagina resta visibile per debug

    def test_pinned_ledger_unavailable_mid_pagination_gives_incomplete(self):
        # simula: il ledger pinnato non e' piu' disponibile su una pagina
        # successiva (es. nodo con storico limitato) -> stesso percorso di
        # 'pagina fallita', complete=False, mai un dato parziale valido.
        pages = [
            ({"lines": [{"account": "r1", "currency": "RLUSD"}], "marker": "MARK1"}, None),
            (None, "ledgerNotFound"),
        ]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertFalse(env["data"]["complete"])
        self.assertIn("ledgerNotFound", env["error"])

    def test_ledger_resolution_fails_on_both_endpoints(self):
        fake, _ = self._make_fixed_endpoint_mock(ledger_resolve_fails_everywhere=True)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertFalse(env["data"]["complete"])
        self.assertEqual(env["data"]["pages_fetched"], 0)

    def test_safety_cap_reached(self):
        pages = [({"lines": [{"account": "r1", "currency": "RLUSD"}], "marker": f"MARK_{i}"}, None) for i in range(10)]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated(max_pages=5)
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertFalse(env["data"]["complete"])
        self.assertEqual(env["data"]["pages_fetched"], 5)
        self.assertIn("tetto di sicurezza", env["error"])

    def test_dedup_of_duplicate_lines(self):
        pages = [({"lines": [
            {"account": "rDUP", "currency": "RLUSD"},
            {"account": "rDUP", "currency": "RLUSD"},
            {"account": "rUnique", "currency": "RLUSD"},
        ]}, None)]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["data"]["total_trustlines"], 2)  # non 3

    def test_missing_lines_field(self):
        pages = [({"no_lines_here": True}, None)]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertFalse(env["data"]["complete"])

    def test_pages_fetched_zero_on_immediate_failure(self):
        pages = [(None, "connessione rifiutata")]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake):
            env = layer.xrpl_account_lines_paginated()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        self.assertEqual(env["data"]["pages_fetched"], 0)
        self.assertEqual(env["data"]["total_trustlines"], 0)

    def test_cache_avoids_duplicate_calls(self):
        pages = [({"lines": [{"account": "r1", "currency": "RLUSD"}]}, None)]
        fake, _ = self._make_fixed_endpoint_mock(account_lines_pages=pages)
        with patch.object(layer, "_call_xrpl_rpc_fixed_endpoint", side_effect=fake) as mock_call:
            layer.xrpl_account_lines_paginated()
            layer.xrpl_account_lines_paginated()
        # prima esecuzione: 2 chiamate di resolve (primario fallito + fallback) + 1 pagina = 3;
        # seconda esecuzione: 0 (risultato gia' in cache)
        self.assertEqual(mock_call.call_count, 3)

    def test_global_xrpl_rpc_call_untouched_for_other_adapters(self):
        # Requisito esplicito: _xrpl_rpc_call() NON deve essere toccata —
        # verifichiamo che esista ancora identica nella firma, usata da
        # tutti gli altri adapter.
        import inspect
        sig = inspect.signature(layer._xrpl_rpc_call)
        self.assertEqual(list(sig.parameters.keys()), ["method", "params", "source_label"])


class TestRwaXyzDisabledByDefault(unittest.TestCase):
    def setUp(self):
        layer._raw_cache.clear()

    @patch("xrpl_raw_data_layer.requests.get")
    def test_no_network_call_when_disabled(self, mock_get):
        # Con env var assenti (stato di default in questo ambiente di test),
        # l'adapter NON deve fare alcuna chiamata di rete.
        env = layer.rwa_xyz_assets_xrpl()
        self.assertEqual(env["status"], layer.STATUS_SOURCE_UNAVAILABLE)
        mock_get.assert_not_called()
        self.assertIn("credenziali", env["error"])

    @patch("xrpl_raw_data_layer.requests.get")
    def test_enabled_with_key_makes_call(self, mock_get):
        mock_get.return_value = _fake_response(200, {"data": []})
        with patch.object(layer, "_RWA_XYZ_ENABLED", True), \
             patch.object(layer, "_RWA_XYZ_API_KEY", "fake-key-for-test"):
            env = layer.rwa_xyz_assets_xrpl()
        self.assertEqual(env["status"], layer.STATUS_RAW_AVAILABLE)
        mock_get.assert_called_once()


class TestCollectionRunPersistence(unittest.TestCase):
    def setUp(self):
        layer._raw_cache.clear()
        self.tmpdir = tempfile.mkdtemp()
        self.tmp_path = os.path.join(self.tmpdir, "sub", "xrpl_raw_snapshots.jsonl")
        self._sleep_patcher = patch("xrpl_raw_data_layer.time.sleep", return_value=None)
        self._sleep_patcher.start()

    def tearDown(self):
        self._sleep_patcher.stop()

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.requests.get")
    def test_collection_never_raises_even_if_all_sources_fail(self, mock_get, mock_post):
        mock_post.return_value = _fake_response(500)
        mock_get.return_value = _fake_response(500)
        with patch.object(layer, "_RAW_SNAPSHOT_PATH", self.tmp_path), \
             patch.object(layer, "_MAX_RETRIES", 0):
            try:
                snap = layer.collect_xrpl_raw_snapshot()
            except Exception as e:
                self.fail(f"collect_xrpl_raw_snapshot ha sollevato un'eccezione: {e}")
        self.assertIn("sources", snap)
        # tutte le fonti xrpl_native devono essere SOURCE_UNAVAILABLE, mai crash
        for name, env in snap["sources"]["xrpl_native"].items():
            self.assertIn(env["status"], (layer.STATUS_RAW_AVAILABLE, layer.STATUS_SOURCE_UNAVAILABLE))

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.requests.get")
    def test_collection_creates_directory_and_appends(self, mock_get, mock_post):
        mock_post.return_value = _fake_response(500)
        mock_get.return_value = _fake_response(500)
        with patch.object(layer, "_RAW_SNAPSHOT_PATH", self.tmp_path), \
             patch.object(layer, "_MAX_RETRIES", 0):
            layer.collect_xrpl_raw_snapshot()
            layer._raw_cache.clear()
            layer.collect_xrpl_raw_snapshot()
        self.assertTrue(os.path.exists(self.tmp_path))
        with open(self.tmp_path) as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 2)
        # ogni riga deve essere JSON valido
        for l in lines:
            json.loads(l)

    def test_read_raw_snapshots_missing_file_returns_empty_list(self):
        with patch.object(layer, "_RAW_SNAPSHOT_PATH", "/nonexistent/path/x.jsonl"):
            out = layer.read_xrpl_raw_snapshots(3)
        self.assertEqual(out, [])

    @patch("xrpl_raw_data_layer.requests.post")
    @patch("xrpl_raw_data_layer.requests.get")
    def test_read_raw_snapshots_returns_last_n(self, mock_get, mock_post):
        mock_post.return_value = _fake_response(500)
        mock_get.return_value = _fake_response(500)
        with patch.object(layer, "_RAW_SNAPSHOT_PATH", self.tmp_path), \
             patch.object(layer, "_MAX_RETRIES", 0):
            for _ in range(5):
                layer._raw_cache.clear()
                layer.collect_xrpl_raw_snapshot()
            out = layer.read_xrpl_raw_snapshots(2)
        self.assertEqual(len(out), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
