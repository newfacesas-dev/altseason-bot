"""
XRPL Raw Data Layer — Milestone M1
====================================

Scopo (e SOLO questo):
- Recuperare dati grezzi da fonti XRPL native, DeFiLlama, RWA.xyz.
- Validare la forma della risposta.
- Salvarli in modo append-only, crash-safe.
- Renderli disponibili in lettura al futuro Feature Engine (M2+).

Questo modulo NON calcola feature, NON normalizza, NON calcola score,
NON prende decisioni. Ogni funzione di raccolta ritorna un "envelope"
con status RAW_AVAILABLE o SOURCE_UNAVAILABLE — mai un'eccezione che
risale al chiamante, mai un errore bloccante.

Non importato né agganciato al flusso live di altseason_bot.py.
Modulo satellite, stesso pattern di performance_tracker.py e
reliability_engine.py: standalone, letto/eseguito separatamente,
zero rischio per il bot in produzione.

Persistenza: nuovo file dedicato append-only sullo stesso Railway
Volume gia' in uso da altseason_bot.py (/data), stesso schema
concettuale di /data/snapshots.jsonl ma isolato in un file proprio
per non toccare il pipeline esistente ne' i suoi consumer.
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, timezone

# ============================================================
# LOGGING
# ============================================================
# Logger standard, nessuna nuova infrastruttura di logging.
# Propaga al root logger: il filtro _TokenMaskFilter gia' installato
# su altseason_bot.py (mascheramento token nei log) si applica anche
# qui automaticamente, perche' e' agganciato al root logger, non a un
# logger specifico. Nessuna duplicazione necessaria.
log = logging.getLogger("xrpl_raw_data_layer")

# ============================================================
# CONFIGURAZIONE (tutta via env var, nessun default pericoloso)
# ============================================================

_XRPL_RPC_PRIMARY = os.environ.get("XRPL_JSON_RPC_URL", "https://xrplcluster.com")
_XRPL_RPC_FALLBACK = os.environ.get("XRPL_JSON_RPC_FALLBACK_URL", "https://s1.ripple.com:51234/")
_XRPL_HTTP_TIMEOUT = float(os.environ.get("XRPL_HTTP_TIMEOUT", "12"))

_RLUSD_ISSUER = os.environ.get("RLUSD_ISSUER_ADDRESS", "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De")
_RLUSD_CURRENCY_HEX = os.environ.get(
    "RLUSD_CURRENCY_HEX", "524C555344000000000000000000000000000000"
)  # "RLUSD" codificato come valuta a 160 bit, come richiesto dal protocollo XRPL

_DEFILLAMA_CHAIN_SLUG = os.environ.get("DEFILLAMA_XRPL_CHAIN_SLUG", "XRPL")
_DEFILLAMA_HTTP_TIMEOUT = float(os.environ.get("DEFILLAMA_HTTP_TIMEOUT", "12"))

_RWA_XYZ_API_KEY = os.environ.get("RWA_XYZ_API_KEY", "").strip()
_RWA_XYZ_ENABLED = bool(_RWA_XYZ_API_KEY) and os.environ.get("RWA_XYZ_ENABLED", "false").lower() == "true"
_RWA_XYZ_BASE_URL = os.environ.get("RWA_XYZ_BASE_URL", "https://api.rwa.xyz")
_RWA_XYZ_HTTP_TIMEOUT = float(os.environ.get("RWA_XYZ_HTTP_TIMEOUT", "12"))

_XRPL_TO_BASE_URL = os.environ.get("XRPL_TO_BASE_URL", "https://api.xrpl.to/v1")
_XRPL_TO_HTTP_TIMEOUT = float(os.environ.get("XRPL_TO_HTTP_TIMEOUT", "12"))

_RAW_SNAPSHOT_PATH = os.environ.get("XRPL_RAW_SNAPSHOT_PATH", "/data/xrpl_raw_snapshots.jsonl")

_CACHE_TTL_SECONDS = float(os.environ.get("XRPL_RAW_CACHE_TTL_SECONDS", "300"))  # 5 min
_MAX_RETRIES = int(os.environ.get("XRPL_RAW_MAX_RETRIES", "2"))
_BACKOFF_BASE_SECONDS = float(os.environ.get("XRPL_RAW_BACKOFF_BASE_SECONDS", "1.5"))

# Stati possibili per ogni singolo dato raccolto
STATUS_RAW_AVAILABLE = "RAW_AVAILABLE"
STATUS_SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"

# ============================================================
# CACHE — stesso pattern gia' in uso nel bot (dict con TTL, es.
# _rot_cache in altseason_bot.py), replicato qui in modo isolato
# per non accoppiare questo modulo satellite a variabili globali
# del file principale.
# ============================================================

_raw_cache = {}  # key -> (timestamp, envelope)


def _cache_get(key):
    entry = _raw_cache.get(key)
    if entry and (time.time() - entry[0]) < _CACHE_TTL_SECONDS:
        return entry[1]
    return None


def _cache_set(key, value):
    _raw_cache[key] = (time.time(), value)


# ============================================================
# ENVELOPE — formato uniforme di ritorno per ogni adapter
# ============================================================

def _envelope(status, source, data=None, error=None):
    return {
        "status": status,
        "source": source,
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
        "data": data,
        "error": error,
    }


def _unavailable(source, reason):
    log.warning(f"[xrpl_raw_data_layer] {source}: SOURCE_UNAVAILABLE ({reason})")
    return _envelope(STATUS_SOURCE_UNAVAILABLE, source, data=None, error=reason)


def _available(source, data):
    return _envelope(STATUS_RAW_AVAILABLE, source, data=data, error=None)


# ============================================================
# HTTP CLIENT CONDIVISO — timeout + retry + backoff.
# Nessuna libreria di retry generica esisteva nel progetto (solo
# try/except puntuali per singola chiamata, es. get_derivatives_coingecko,
# _rot_get_history): questa e' quindi una piccola utility NUOVA ma
# isolata in questo modulo, non una duplicazione di qualcosa di
# gia' esistente altrove nel bot.
# ============================================================

_RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def _http_get_json(url, params=None, timeout=12, max_retries=None, source="http_get"):
    if max_retries is None:
        max_retries = _MAX_RETRIES
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                try:
                    return r.json(), None
                except ValueError as e:
                    last_error = f"risposta non-JSON: {e}"
                    break
            if r.status_code in _RETRYABLE_STATUS and attempt < max_retries:
                sleep_s = _BACKOFF_BASE_SECONDS * (2 ** attempt)
                log.warning(f"[{source}] HTTP {r.status_code}, retry tra {sleep_s:.1f}s (tentativo {attempt+1}/{max_retries})")
                time.sleep(sleep_s)
                continue
            last_error = f"HTTP {r.status_code}"
            break
        except requests.exceptions.Timeout:
            last_error = "timeout"
        except requests.exceptions.RequestException as e:
            last_error = f"errore rete: {e}"
        if attempt < max_retries:
            sleep_s = _BACKOFF_BASE_SECONDS * (2 ** attempt)
            time.sleep(sleep_s)
    return None, last_error


def _http_post_json(url, payload, timeout=12, max_retries=None, source="http_post"):
    if max_retries is None:
        max_retries = _MAX_RETRIES
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            r = requests.post(url, json=payload, timeout=timeout)
            if r.status_code == 200:
                try:
                    return r.json(), None
                except ValueError as e:
                    last_error = f"risposta non-JSON: {e}"
                    break
            if r.status_code in _RETRYABLE_STATUS and attempt < max_retries:
                sleep_s = _BACKOFF_BASE_SECONDS * (2 ** attempt)
                log.warning(f"[{source}] HTTP {r.status_code}, retry tra {sleep_s:.1f}s (tentativo {attempt+1}/{max_retries})")
                time.sleep(sleep_s)
                continue
            last_error = f"HTTP {r.status_code}"
            break
        except requests.exceptions.Timeout:
            last_error = "timeout"
        except requests.exceptions.RequestException as e:
            last_error = f"errore rete: {e}"
        if attempt < max_retries:
            sleep_s = _BACKOFF_BASE_SECONDS * (2 ** attempt)
            time.sleep(sleep_s)
    return None, last_error


def _xrpl_rpc_call(method, params, source_label):
    """Chiamata JSON-RPC a un nodo XRPL pubblico, con fallback automatico
    dal nodo primario (xrplcluster.com) al secondario (s1.ripple.com)
    se il primo fallisce dopo i retry."""
    payload = {"method": method, "params": [params] if params is not None else [{}]}

    body, err = _http_post_json(_XRPL_RPC_PRIMARY, payload, timeout=_XRPL_HTTP_TIMEOUT, source=f"{source_label}/primary")
    if body is None:
        log.warning(f"[{source_label}] nodo primario fallito ({err}), provo il fallback")
        body, err2 = _http_post_json(_XRPL_RPC_FALLBACK, payload, timeout=_XRPL_HTTP_TIMEOUT, source=f"{source_label}/fallback")
        if body is None:
            return None, f"primario: {err}; fallback: {err2}"

    result = body.get("result") if isinstance(body, dict) else None
    if result is None:
        return None, "risposta priva del campo 'result'"
    if isinstance(result, dict) and result.get("status") == "error":
        return None, f"errore XRPL: {result.get('error', 'sconosciuto')}"
    return result, None


# ============================================================
# ADAPTER — XRPL NATIVE
# ============================================================

def xrpl_gateway_balances(account=None, hotwallet=None):
    """RLUSD circulating/outstanding supply (obligations) + balances issuer.
    Nota: alcuni nodi pubblici disabilitano questo metodo per costo
    computazionale — il fallback al secondo nodo copre parzialmente
    questo rischio, ma resta un limite noto e dichiarato."""
    source = "xrpl.gateway_balances"
    cache_key = f"{source}:{account}:{hotwallet}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    account = account or _RLUSD_ISSUER
    params = {"account": account, "strict": True, "ledger_index": "validated"}
    if hotwallet:
        params["hotwallet"] = hotwallet

    result, err = _xrpl_rpc_call("gateway_balances", params, source)
    if result is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    # Validazione minima di forma: deve avere almeno 'account'
    if "account" not in result:
        env = _unavailable(source, "risposta priva del campo 'account' atteso")
        _cache_set(cache_key, env)
        return env

    env = _available(source, result)
    _cache_set(cache_key, env)
    return env


def xrpl_amm_info(asset=None, asset2=None):
    """Dati AMM/pool. Default: pool XRP / RLUSD, la coppia piu' rilevante
    per la Categoria F (XRP Economic Dependency) definita in fase di
    progettazione. Altre coppie sono raggiungibili passando asset/asset2
    espliciti (nessuna modifica al codice necessaria)."""
    source = "xrpl.amm_info"
    asset = asset or {"currency": "XRP"}
    asset2 = asset2 or {
        "currency": _RLUSD_CURRENCY_HEX,
        "issuer": _RLUSD_ISSUER,
    }
    cache_key = f"{source}:{json.dumps(asset, sort_keys=True)}:{json.dumps(asset2, sort_keys=True)}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    params = {"asset": asset, "asset2": asset2, "ledger_index": "validated"}
    result, err = _xrpl_rpc_call("amm_info", params, source)
    if result is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if "amm" not in result:
        env = _unavailable(source, "pool non trovato o risposta priva del campo 'amm'")
        _cache_set(cache_key, env)
        return env

    env = _available(source, result)
    _cache_set(cache_key, env)
    return env


def xrpl_account_tx(account=None, limit=50):
    """Transazioni recenti di un account. Default: issuer RLUSD, come proxy
    di attivita' legata a RLUSD. TODO M2: valutare se servono altri
    account monitorati (vedi deliverable)."""
    source = "xrpl.account_tx"
    account = account or _RLUSD_ISSUER
    cache_key = f"{source}:{account}:{limit}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    params = {"account": account, "limit": limit, "ledger_index_min": -1, "ledger_index_max": -1}
    result, err = _xrpl_rpc_call("account_tx", params, source)
    if result is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if "transactions" not in result:
        env = _unavailable(source, "risposta priva del campo 'transactions'")
        _cache_set(cache_key, env)
        return env

    env = _available(source, result)
    _cache_set(cache_key, env)
    return env


def xrpl_account_lines(account=None):
    """Trust line viste dalla prospettiva dell'account fornito.
    ATTENZIONE (limite noto, da NON forzare): account_lines(issuer) ritorna
    le trust line che l'ISSUER ha verso altri, non l'elenco degli holder
    del token emesso. Per il conteggio holder/trust-line-growth servirebbe
    un'altra strategia (ledger_data paginato, o un indicizzatore terzo tipo
    XRPScAN). Qui l'adapter e' corretto rispetto all'API cosi' com'e';
    la metrica 'trustline_growth' del modello resta un TODO per M2."""
    source = "xrpl.account_lines"
    account = account or _RLUSD_ISSUER
    cache_key = f"{source}:{account}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    params = {"account": account, "ledger_index": "validated"}
    result, err = _xrpl_rpc_call("account_lines", params, source)
    if result is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if "lines" not in result:
        env = _unavailable(source, "risposta priva del campo 'lines'")
        _cache_set(cache_key, env)
        return env

    env = _available(source, result)
    _cache_set(cache_key, env)
    return env


def xrpl_feature():
    """Stato degli amendment del protocollo XRPL."""
    source = "xrpl.feature"
    cache_key = source
    cached = _cache_get(cache_key)
    if cached:
        return cached

    result, err = _xrpl_rpc_call("feature", {}, source)
    if result is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    env = _available(source, result)
    _cache_set(cache_key, env)
    return env


def xrpl_server_info():
    """Stato del server/nodo interrogato (usato anche internamente per
    ricavare l'indice del ledger validato piu' recente)."""
    source = "xrpl.server_info"
    cache_key = source
    cached = _cache_get(cache_key)
    if cached:
        return cached

    result, err = _xrpl_rpc_call("server_info", {}, source)
    if result is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if "info" not in result:
        env = _unavailable(source, "risposta priva del campo 'info'")
        _cache_set(cache_key, env)
        return env

    env = _available(source, result)
    _cache_set(cache_key, env)
    return env


def xrpl_book_changes_latest():
    """Un singolo snapshot di book_changes per il ledger validato piu'
    recente. NON accumula storico (quello e' compito della M5, dove si
    decidera' la cadenza di raccolta ledger-by-ledger). Qui raccogliamo
    solo il dato grezzo disponibile ora, un ledger alla volta, per
    iniziare la raccolta senza costruire ancora l'accumulo completo."""
    source = "xrpl.book_changes"
    cache_key = source
    cached = _cache_get(cache_key)
    if cached:
        return cached

    info_env = xrpl_server_info()
    if info_env["status"] != STATUS_RAW_AVAILABLE:
        env = _unavailable(source, f"impossibile determinare il ledger validato: {info_env['error']}")
        _cache_set(cache_key, env)
        return env

    try:
        ledger_index = info_env["data"]["info"]["validated_ledger"]["seq"]
    except (KeyError, TypeError):
        env = _unavailable(source, "impossibile leggere validated_ledger.seq da server_info")
        _cache_set(cache_key, env)
        return env

    # book_changes NON supporta lo shortcut "validated": richiede l'indice
    # numerico esplicito (limite noto e documentato, vedi deliverable).
    result, err = _xrpl_rpc_call("book_changes", {"ledger_index": ledger_index}, source)
    if result is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if "changes" not in result:
        env = _unavailable(source, "risposta priva del campo 'changes'")
        _cache_set(cache_key, env)
        return env

    env = _available(source, result)
    _cache_set(cache_key, env)
    return env


# ============================================================
# ADAPTER — DEFILLAMA
# ============================================================

def defillama_chain_tvl_history(chain=None):
    source = "defillama.chain_tvl_history"
    chain = chain or _DEFILLAMA_CHAIN_SLUG
    cache_key = f"{source}:{chain}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    url = f"https://api.llama.fi/v2/historicalChainTvl/{chain}"
    data, err = _http_get_json(url, timeout=_DEFILLAMA_HTTP_TIMEOUT, source=source)
    if data is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if not isinstance(data, list):
        env = _unavailable(source, "risposta non nel formato lista attesa")
        _cache_set(cache_key, env)
        return env

    env = _available(source, data)
    _cache_set(cache_key, env)
    return env


def defillama_stablecoins_chain_history(chain=None):
    source = "defillama.stablecoins_chain_history"
    chain = chain or _DEFILLAMA_CHAIN_SLUG
    cache_key = f"{source}:{chain}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    url = f"https://stablecoins.llama.fi/stablecoincharts/{chain}"
    data, err = _http_get_json(url, timeout=_DEFILLAMA_HTTP_TIMEOUT, source=source)
    if data is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if not isinstance(data, list):
        env = _unavailable(source, "risposta non nel formato lista attesa")
        _cache_set(cache_key, env)
        return env

    env = _available(source, data)
    _cache_set(cache_key, env)
    return env


def defillama_dex_overview(chain=None):
    source = "defillama.dex_overview"
    chain = chain or _DEFILLAMA_CHAIN_SLUG
    cache_key = f"{source}:{chain}"
    cached = _cache_get(cache_key)
    if cached:
        return cached

    url = f"https://api.llama.fi/overview/dexs/{chain}"
    data, err = _http_get_json(url, timeout=_DEFILLAMA_HTTP_TIMEOUT, source=source)
    if data is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if not isinstance(data, dict):
        env = _unavailable(source, "risposta non nel formato dict atteso")
        _cache_set(cache_key, env)
        return env

    env = _available(source, data)
    _cache_set(cache_key, env)
    return env


# ============================================================
# ADAPTER — XRPL.TO (esterno, PRIMARY per DEX volume aggregato — M8 Gap 2A)
# ============================================================
# Fonte esterna (non protocollo XRPL nativo), verificata con chiamata reale
# in fase di audit (nessuna API key richiesta, risposta JSON valida, campo
# 'global.gDexVolume' presente e numerico). Usata SOLO per il volume DEX
# aggregato di rete — non sostituisce nessun adapter nativo esistente.
# book_changes nativo resta FALLBACK architetturale (non costruito ora).

def xrpl_to_dex_volume():
    source = "xrpl_to.dex_volume"
    cache_key = source
    cached = _cache_get(cache_key)
    if cached:
        return cached

    url = f"{_XRPL_TO_BASE_URL}/tokens"
    # limit=1: il blocco 'global' (che ci interessa) e' presente comunque,
    # indipendentemente dal numero di token restituiti nella lista — non
    # serve scaricare l'elenco completo per il solo aggregato di rete.
    data, err = _http_get_json(url, params={"limit": 1}, timeout=_XRPL_TO_HTTP_TIMEOUT, source=source)
    if data is None:
        env = _unavailable(source, err)
        _cache_set(cache_key, env)
        return env

    if not isinstance(data, dict):
        env = _unavailable(source, "risposta non nel formato dict atteso")
        _cache_set(cache_key, env)
        return env

    global_block = data.get("global")
    if not isinstance(global_block, dict):
        env = _unavailable(source, "campo 'global' assente o non nel formato dict atteso")
        _cache_set(cache_key, env)
        return env

    raw_value = global_block.get("gDexVolume")
    if raw_value is None:
        env = _unavailable(source, "campo 'global.gDexVolume' assente nella risposta")
        _cache_set(cache_key, env)
        return env

    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        env = _unavailable(source, f"'global.gDexVolume' non numerico (tipo: {type(raw_value).__name__})")
        _cache_set(cache_key, env)
        return env

    if raw_value < 0:
        env = _unavailable(source, f"'global.gDexVolume' negativo ({raw_value}): valore non valido")
        _cache_set(cache_key, env)
        return env

    env = _available(source, {"gDexVolume": float(raw_value)})
    _cache_set(cache_key, env)
    return env


# ============================================================
# ADAPTER — RWA.XYZ (disabled-by-default)
# ============================================================
# Nessuna chiamata di rete se la API key non e' configurata ED
# esplicitamente abilitata via RWA_XYZ_ENABLED=true. Pronto per essere
# attivato inserendo la key e il flag, senza modifiche al codice.

def rwa_xyz_assets_xrpl():
    source = "rwa_xyz.assets"
    if not _RWA_XYZ_ENABLED:
        reason = (
            "RWA_XYZ_API_KEY non configurata o RWA_XYZ_ENABLED non impostato a 'true' — "
            "sorgente disabilitata per mancanza di credenziali (comportamento atteso, nessun errore)"
        )
        return _unavailable(source, reason)

    cache_key = source
    cached = _cache_get(cache_key)
    if cached:
        return cached

    url = f"{_RWA_XYZ_BASE_URL}/v4/assets"
    query = json.dumps({"filter": {"operator": "equals", "field": "network_slug", "value": "xrpl"}})
    headers = {"Authorization": f"Bearer {_RWA_XYZ_API_KEY}"}
    try:
        r = requests.get(url, params={"query": query}, headers=headers, timeout=_RWA_XYZ_HTTP_TIMEOUT)
        if r.status_code != 200:
            env = _unavailable(source, f"HTTP {r.status_code}")
            _cache_set(cache_key, env)
            return env
        data = r.json()
    except requests.exceptions.RequestException as e:
        env = _unavailable(source, f"errore rete: {e}")
        _cache_set(cache_key, env)
        return env
    except ValueError as e:
        env = _unavailable(source, f"risposta non-JSON: {e}")
        _cache_set(cache_key, env)
        return env

    env = _available(source, data)
    _cache_set(cache_key, env)
    return env


# ============================================================
# COLLECTION RUN — orchestrazione + persistenza
# ============================================================

def collect_xrpl_raw_snapshot():
    """Esegue una raccolta completa da tutte le fonti approvate,
    salva il risultato in modo append-only e lo ritorna.
    Mai un'eccezione che risale al chiamante: ogni adapter e' gia'
    protetto internamente, e questa funzione non aggiunge logica che
    possa fallire in modo bloccante."""
    snapshot = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "xrpl_native": {
                "gateway_balances_rlusd": xrpl_gateway_balances(),
                "amm_info_xrp_rlusd": xrpl_amm_info(),
                "account_tx_rlusd_issuer": xrpl_account_tx(),
                "account_lines_rlusd_issuer": xrpl_account_lines(),
                "feature": xrpl_feature(),
                "server_info": xrpl_server_info(),
                "book_changes_latest": xrpl_book_changes_latest(),
            },
            "defillama": {
                "chain_tvl_history": defillama_chain_tvl_history(),
                "stablecoins_chain_history": defillama_stablecoins_chain_history(),
                "dex_overview": defillama_dex_overview(),
            },
            "xrpl_to": {
                "dex_volume": xrpl_to_dex_volume(),
            },
            "rwa_xyz": {
                "assets_xrpl": rwa_xyz_assets_xrpl(),
            },
        },
    }

    try:
        os.makedirs(os.path.dirname(_RAW_SNAPSHOT_PATH), exist_ok=True)
        with open(_RAW_SNAPSHOT_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except Exception as e:
        # Crash-safe: la raccolta e' comunque valida e ritornata al chiamante,
        # anche se il salvataggio su disco fallisce (stesso principio gia'
        # usato in salva_snapshot_auto: mai bloccare per un errore di I/O).
        log.warning(f"[xrpl_raw_data_layer] salvataggio snapshot fallito (non bloccante): {e}")

    return snapshot


def read_xrpl_raw_snapshots(n=3):
    """Legge gli ultimi n snapshot grezzi. Read-only, crash-safe.
    Stesso pattern semplice di _leggi_ultimi_snapshot in altseason_bot.py,
    replicato qui in modo isolato (nessun import incrociato tra i due
    moduli, per non creare un accoppiamento non necessario)."""
    try:
        if not os.path.exists(_RAW_SNAPSHOT_PATH):
            return []
        righe = []
        with open(_RAW_SNAPSHOT_PATH, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    righe.append(line)
        ultimi = righe[-n:] if len(righe) >= n else righe
        out = []
        for r in ultimi:
            try:
                out.append(json.loads(r))
            except Exception:
                continue
        return out
    except Exception as e:
        log.warning(f"[xrpl_raw_data_layer] read_xrpl_raw_snapshots error: {e}")
        return []


if __name__ == "__main__":
    # Esecuzione manuale diretta: utile per un primo test live dal terminale
    # (rete reale necessaria, non disponibile nell'ambiente di sviluppo
    # sandboxed usato per scrivere questo modulo).
    snap = collect_xrpl_raw_snapshot()
    print(json.dumps(snap, indent=2, ensure_ascii=False))
