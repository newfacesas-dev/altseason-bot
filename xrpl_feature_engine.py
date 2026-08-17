"""
XRPL Feature Engine — Milestone M2
====================================

Scopo (e SOLO questo):
- Leggere ESCLUSIVAMENTE i dati RAW gia' prodotti da xrpl_raw_data_layer.py (M1).
- Trasformarli in feature normalizzate e riutilizzabili (growth, acceleration,
  velocity, ratio, trend vs media mobile).

Questo modulo NON fa chiamate API (nessun requests.get/post), NON calcola
score, NON calcola confidence, NON produce divergenze, NON prende decisioni.
Non importato ne' agganciato al flusso live di altseason_bot.py.

Riuso esplicito, nessuna duplicazione:
- Lettura storico snapshot: xrpl_raw_data_layer.read_xrpl_raw_snapshots
  (stessa funzione gia' validata in M1, non reimplementata).
- Costante valuta RLUSD: xrpl_raw_data_layer._RLUSD_CURRENCY_HEX
  (stesso valore gia' usato per raccogliere i dati, non riscritto qui).

Nota sul Relative Strength (XRP/BTC, XRP/ETH):
Il Rotation Engine esistente vive dentro altseason_bot.py, lo stesso processo
che gestisce il polling Telegram in produzione. Importare quel file come
modulo eseguirebbe qualunque codice a livello di modulo, col rischio concreto
di avviare un secondo polling Telegram in conflitto con quello live se il
main() non fosse protetto da `if __name__ == "__main__":` (non verificabile
con certezza da qui). Per non correre questo rischio, le feature di relative
strength accettano le funzioni del Rotation Engine (_rot_get_history,
_rot_perf) per dependency injection: se non vengono fornite, la feature
risulta MISSING con motivo esplicito, mai un valore inventato.
"""

import logging
import statistics
from datetime import datetime, timezone, timedelta

import xrpl_raw_data_layer as raw

log = logging.getLogger("xrpl_feature_engine")

# ============================================================
# STATI AMMESSI
# ============================================================

STATUS_ACTIVE = "ACTIVE"
STATUS_PARTIAL = "PARTIAL"
STATUS_NON_MATURE = "NON_MATURE"
STATUS_MISSING = "MISSING"

# ============================================================
# TOOLKIT STATISTICO CONDIVISO
# ============================================================
# Asset-agnostico: non conosce XRP, RWA o RLUSD. Prende solo numeri e serie.
# Ogni funzione ritorna None (mai zero, mai un valore inventato) quando
# l'input non permette un calcolo valido.

def growth_pct(current, base, min_abs_base=1e-9):
    """Variazione percentuale tra 'current' e 'base'.
    None se un valore manca, non e' numerico, o 'base' e' troppo vicino a
    zero (evita percentuali gonfiate da una base minuscola)."""
    if current is None or base is None:
        return None
    try:
        current = float(current)
        base = float(base)
    except (TypeError, ValueError):
        return None
    if abs(base) < min_abs_base:
        return None
    return (current - base) / base * 100.0


def acceleration(growth_now, growth_prev):
    """Differenza tra due tassi di crescita (derivata seconda approssimata).
    None se uno dei due manca."""
    if growth_now is None or growth_prev is None:
        return None
    try:
        return float(growth_now) - float(growth_prev)
    except (TypeError, ValueError):
        return None


def velocity(current, previous, dt_days, min_dt_days=1e-6):
    """Tasso assoluto di variazione per giorno. None se dt_days troppo
    piccolo (evita divisione per un intervallo temporale nullo/invalido)."""
    if current is None or previous is None or dt_days is None:
        return None
    try:
        current = float(current)
        previous = float(previous)
        dt_days = float(dt_days)
    except (TypeError, ValueError):
        return None
    if dt_days <= min_dt_days:
        return None
    return (current - previous) / dt_days


def ratio(numerator, denominator, min_abs_denominator=1e-9):
    """Rapporto percentuale numerator/denominator. None se denominator
    manca o e' troppo vicino a zero."""
    if numerator is None or denominator is None:
        return None
    try:
        numerator = float(numerator)
        denominator = float(denominator)
    except (TypeError, ValueError):
        return None
    if abs(denominator) < min_abs_denominator:
        return None
    return numerator / denominator * 100.0


def trend_vs_ma(current, window_values):
    """Z-score robusto di 'current' rispetto alla mediana/MAD di
    'window_values'. None se meno di 2 valori validi nella finestra.
    Se MAD == 0 (nessuna variabilita' nella finestra): ritorna 0.0 se
    current coincide con la mediana, altrimenti None (un salto rispetto
    a una finestra piatta non ha uno z-score matematicamente definito,
    meglio dichiararlo assente che inventare un numero enorme)."""
    if current is None or not window_values:
        return None
    try:
        current = float(current)
        values = [float(v) for v in window_values if v is not None]
    except (TypeError, ValueError):
        return None
    if len(values) < 2:
        return None
    med = statistics.median(values)
    mad = statistics.median([abs(v - med) for v in values])
    if mad == 0:
        return 0.0 if current == med else None
    return (current - med) / mad


# ============================================================
# UTILITY DI SUPPORTO (timestamp, caricamento serie, risultato)
# ============================================================

def _parse_ts(ts_str):
    """Parsa un timestamp ISO 8601. None se assente o non valido
    (mai un'eccezione che risale al chiamante)."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        return datetime.fromisoformat(ts_str)
    except (ValueError, TypeError):
        return None


def _feature_result(value, status, source, as_of, history_points, history_required, reason):
    return {
        "value": value,
        "status": status,
        "source": source,
        "as_of": as_of.isoformat() if isinstance(as_of, datetime) else as_of,
        "history_points": history_points,
        "history_required": history_required,
        "reason": reason,
    }


def _load_all_snapshots():
    """Legge tutti gli snapshot RAW disponibili (riuso diretto di M1,
    nessuna reimplementazione). n molto grande = 'tutti quelli che ci sono'."""
    try:
        return raw.read_xrpl_raw_snapshots(n=1_000_000)
    except Exception as e:
        log.warning(f"[xrpl_feature_engine] impossibile leggere snapshot RAW: {e}")
        return []


def _load_series(extractor):
    """Costruisce una serie temporale (datetime, valore) applicando
    'extractor' a ogni snapshot RAW. Salta silenziosamente gli snapshot
    con timestamp invalido o dato non estraibile (mai un crash)."""
    series = []
    for snap in _load_all_snapshots():
        if not isinstance(snap, dict):
            continue
        dt = _parse_ts(snap.get("timestamp_utc"))
        if dt is None:
            continue
        try:
            val = extractor(snap)
        except Exception:
            val = None
        if val is not None:
            series.append((dt, val))
    series.sort(key=lambda pair: pair[0])
    return series


def _latest_known_timestamp():
    """as_of di fallback quando una feature non ha nemmeno un punto valido:
    usa il timestamp dell'ultimo snapshot RAW esistente, se c'e'; altrimenti
    l'istante corrente."""
    snaps = _load_all_snapshots()
    if snaps:
        dt = _parse_ts(snaps[-1].get("timestamp_utc"))
        if dt is not None:
            return dt
    return datetime.now(timezone.utc)


def _find_base_point(series, latest_dt, window_days):
    """Cerca il punto della serie piu' recente che sia comunque a
    'window_days' o piu' di distanza da latest_dt (base per un calcolo di
    crescita). Ritorna (valore, giorni_reali_di_distanza) o (None, None)
    se lo storico non arriva ancora a coprire quella finestra."""
    target = latest_dt - timedelta(days=window_days)
    candidates = [(dt, v) for dt, v in series if dt <= target]
    if not candidates:
        return None, None
    candidates.sort(key=lambda pair: pair[0])
    dt, v = candidates[-1]
    actual_gap_days = (latest_dt - dt).total_seconds() / 86400.0
    return v, actual_gap_days


# ============================================================
# ESTRATTORI — leggono un singolo valore da un singolo snapshot RAW
# ============================================================
# Ognuno ritorna None se il dato non e' disponibile in quello snapshot
# (fonte SOURCE_UNAVAILABLE, campo mancante, valore non numerico).

def _extract_rlusd_supply(snapshot):
    try:
        env = snapshot["sources"]["xrpl_native"]["gateway_balances_rlusd"]
    except (KeyError, TypeError):
        return None
    if env.get("status") != raw.STATUS_RAW_AVAILABLE:
        return None
    try:
        obligations = env["data"]["obligations"]
        val = obligations.get(raw._RLUSD_CURRENCY_HEX)
        return float(val) if val is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def _extract_amm_pool_value(snapshot):
    """Usa il valore dell'LP token come proxy della dimensione del pool
    XRP/RLUSD (metrica singola, evita di dover convertire due valute
    diverse — XRP e RLUSD — in un'unica unita' di misura)."""
    try:
        env = snapshot["sources"]["xrpl_native"]["amm_info_xrp_rlusd"]
    except (KeyError, TypeError):
        return None
    if env.get("status") != raw.STATUS_RAW_AVAILABLE:
        return None
    try:
        val = env["data"]["amm"]["lp_token"]["value"]
        return float(val)
    except (KeyError, TypeError, ValueError):
        return None


def _extract_rwa_reason(snapshot):
    """Ritorna il motivo dichiarato da M1 per cui RWA.xyz non e' disponibile
    (se presente), per dare un motivo specifico invece che generico."""
    try:
        env = snapshot["sources"]["rwa_xyz"]["assets_xrpl"]
        return env.get("error")
    except (KeyError, TypeError):
        return None


def _extract_xrpl_to_dex_volume(snapshot):
    """Volume DEX aggregato di rete da XRPL.to (M8 Gap 2A). Fonte esterna,
    non protocollo XRPL nativo — per questo vive in un gruppo 'xrpl_to'
    separato da 'xrpl_native' nel dizionario sources di M1."""
    try:
        env = snapshot["sources"]["xrpl_to"]["dex_volume"]
    except (KeyError, TypeError):
        return None
    if env.get("status") != raw.STATUS_RAW_AVAILABLE:
        return None
    try:
        val = env["data"]["gDexVolume"]
        return float(val)
    except (KeyError, TypeError, ValueError):
        return None


# ============================================================
# COSTRUTTORI DI FEATURE GENERICI (growth/acceleration/velocity/trend)
# ============================================================

def _build_growth_feature(extractor, window_days, source_name, feature_name):
    as_of_fallback = _latest_known_timestamp()
    series = _load_series(extractor)
    if not series:
        return _feature_result(
            None, STATUS_MISSING, source_name, as_of_fallback, 0, window_days,
            f"nessun dato raccolto per {feature_name}",
        )
    latest_dt, latest_val = series[-1]
    base_val, gap_days = _find_base_point(series, latest_dt, window_days)
    if base_val is None:
        return _feature_result(
            None, STATUS_NON_MATURE, source_name, latest_dt, len(series), window_days,
            f"storico insufficiente: servono {window_days} giorni, disponibili al momento "
            f"{(latest_dt - series[0][0]).total_seconds() / 86400.0:.2f} giorni "
            f"({len(series)} punti raccolti)",
        )
    value = growth_pct(latest_val, base_val)
    if value is None:
        return _feature_result(
            None, STATUS_NON_MATURE, source_name, latest_dt, len(series), window_days,
            "base troppo vicina a zero per calcolare una crescita percentuale affidabile",
        )
    status = STATUS_ACTIVE if gap_days >= window_days * 0.8 else STATUS_PARTIAL
    reason = None if status == STATUS_ACTIVE else (
        f"finestra reale ({gap_days:.1f}gg) piu' corta della richiesta ({window_days}gg)"
    )
    return _feature_result(value, status, source_name, latest_dt, len(series), window_days, reason)


def _build_trend_feature(extractor, window_days, source_name, feature_name):
    as_of_fallback = _latest_known_timestamp()
    series = _load_series(extractor)
    if not series:
        return _feature_result(
            None, STATUS_MISSING, source_name, as_of_fallback, 0, window_days,
            f"nessun dato raccolto per {feature_name}",
        )
    latest_dt, latest_val = series[-1]
    cutoff = latest_dt - timedelta(days=window_days)
    window_values = [v for dt, v in series if dt >= cutoff]
    if len(window_values) < 2:
        return _feature_result(
            None, STATUS_NON_MATURE, source_name, latest_dt, len(series), window_days,
            f"servono almeno 2 punti nella finestra di {window_days} giorni, "
            f"disponibili {len(window_values)}",
        )
    value = trend_vs_ma(latest_val, window_values)
    if value is None:
        return _feature_result(
            None, STATUS_NON_MATURE, source_name, latest_dt, len(series), window_days,
            "finestra senza variabilita' (MAD=0) e valore corrente diverso dalla mediana: "
            "z-score non definito in modo affidabile",
        )
    return _feature_result(value, STATUS_ACTIVE, source_name, latest_dt, len(series), window_days, None)


def _build_velocity_feature(extractor, source_name, feature_name, required_days=7):
    """Storico minimo richiesto: 7gg, come da design congelato (velocity
    e' tecnicamente calcolabile con soli 2 punti, ma NON e' considerata
    matura/ACTIVE finche' l'intervallo reale tra i due punti non raggiunge
    la finestra minima approvata). Sotto quella soglia il valore viene
    comunque calcolato (e' matematicamente valido), ma lo stato resta
    PARTIAL — mai ACTIVE solo perche' sono tecnicamente disponibili 2 punti."""
    as_of_fallback = _latest_known_timestamp()
    series = _load_series(extractor)
    if len(series) == 0:
        return _feature_result(
            None, STATUS_MISSING, source_name, as_of_fallback, 0, required_days,
            f"nessun dato raccolto per {feature_name}",
        )
    if len(series) < 2:
        return _feature_result(
            None, STATUS_NON_MATURE, source_name, series[-1][0], len(series), required_days,
            f"solo {len(series)} punto disponibile: servono almeno 2 punti per calcolare "
            f"una velocity, oltre alla finestra minima di {required_days}gg per considerarla matura",
        )
    (dt_prev, v_prev), (dt_now, v_now) = series[-2], series[-1]
    dt_days = (dt_now - dt_prev).total_seconds() / 86400.0
    value = velocity(v_now, v_prev, dt_days)
    if value is None:
        return _feature_result(
            None, STATUS_NON_MATURE, source_name, dt_now, len(series), required_days,
            "intervallo temporale tra gli ultimi due punti troppo piccolo per un calcolo affidabile",
        )
    if dt_days >= required_days:
        return _feature_result(value, STATUS_ACTIVE, source_name, dt_now, len(series), required_days, None)
    return _feature_result(
        value, STATUS_PARTIAL, source_name, dt_now, len(series), required_days,
        f"valore calcolabile ma intervallo reale tra i due punti ({dt_days:.3f}gg) sotto la "
        f"finestra minima approvata di {required_days}gg: stato non ancora maturo",
    )


# ============================================================
# FEATURE — RWA
# ============================================================
# RWA.xyz e' disabled-by-default in M1 (nessuna API key configurata).
# Nessun fallback: tutte MISSING finche' la fonte non e' abilitata.

def rwa_value_trend():
    reason = _extract_rwa_reason_latest()
    return _feature_result(None, STATUS_MISSING, "rwa_xyz.assets", _latest_known_timestamp(), 0, 30, reason)


def rwa_growth_30d():
    reason = _extract_rwa_reason_latest()
    return _feature_result(None, STATUS_MISSING, "rwa_xyz.assets", _latest_known_timestamp(), 0, 30, reason)


def rwa_growth_90d():
    reason = _extract_rwa_reason_latest()
    return _feature_result(None, STATUS_MISSING, "rwa_xyz.assets", _latest_known_timestamp(), 0, 90, reason)


def rwa_acceleration():
    reason = _extract_rwa_reason_latest()
    return _feature_result(None, STATUS_MISSING, "rwa_xyz.assets", _latest_known_timestamp(), 0, 60, reason)


def _extract_rwa_reason_latest():
    snaps = _load_all_snapshots()
    if not snaps:
        return "nessuno snapshot RAW disponibile"
    reason = _extract_rwa_reason(snaps[-1])
    return reason or "RWA.xyz non disponibile (nessun dato nello snapshot piu' recente)"


# ============================================================
# FEATURE — RLUSD
# ============================================================

def rlusd_supply_trend(window_days=30):
    return _build_trend_feature(_extract_rlusd_supply, window_days, "xrpl.gateway_balances", "rlusd_supply_trend")


def rlusd_growth(window_days=30):
    return _build_growth_feature(_extract_rlusd_supply, window_days, "xrpl.gateway_balances", "rlusd_growth")


def rlusd_velocity():
    return _build_velocity_feature(_extract_rlusd_supply, "xrpl.gateway_balances", "rlusd_velocity")


# ============================================================
# FEATURE — DEX/AMM
# ============================================================
# dex_volume_*: la raccolta storica di book_changes (ledger-by-ledger) e'
# esplicitamente rimandata alla M5 (vedi deliverable M1). Qui non si tenta
# nessuna sostituzione di fonte non concordata: MISSING dichiarato, non
# un fallback inventato.

def dex_volume_trend(window_days=30):
    """M8 Gap 2A: usa il volume DEX aggregato da XRPL.to (PRIMARY source),
    stessa identica logica gia' congelata di rlusd_supply_trend (z-score
    robusto via trend_vs_ma su una finestra di livelli grezzi) — nessuna
    formula nuova, solo una fonte diversa per l'extractor."""
    return _build_trend_feature(_extract_xrpl_to_dex_volume, window_days, "xrpl_to.dex_volume", "dex_volume_trend")


def dex_volume_growth(window_days=30):
    """M8 Gap 2A: stessa identica logica gia' congelata di rlusd_growth
    (growth_pct su una finestra), nessuna formula nuova."""
    return _build_growth_feature(_extract_xrpl_to_dex_volume, window_days, "xrpl_to.dex_volume", "dex_volume_growth")


def dex_volume_acceleration():
    """M8 Gap 2A (Decisione 2, approvata): confronta la crescita
    dell'ultimo periodo di 30gg con quella del periodo di 30gg precedente.
    Riusa ESCLUSIVAMENTE growth_pct(), acceleration(), _find_base_point()
    gia' esistenti e congelate — nessuna formula nuova, nessun fallback,
    nessun valore artificiale.

    growth_now  = growth_pct(volume_oggi, volume_30gg_fa)   [crescita 30gg-fa -> oggi]
    growth_prev = growth_pct(volume_30gg_fa, volume_60gg_fa) [crescita 60gg-fa -> 30gg-fa]
    dex_volume_acceleration = acceleration(growth_now, growth_prev)

    Nota sull'ordine degli argomenti: growth_pct(current, base) e' la
    convenzione gia' congelata e usata ovunque nel progetto (es.
    _build_growth_feature: growth_pct(latest_val, base_val)) — qui
    applicata due volte in sequenza, non invertita, per non introdurre un
    segno errato rispetto a come growth_pct e' gia' usata altrove.

    NON registrata in M3: resta una feature M2 disponibile per usi
    futuri, come richiesto esplicitamente."""
    as_of_fallback = _latest_known_timestamp()
    series = _load_series(_extract_xrpl_to_dex_volume)
    if not series:
        return _feature_result(
            None, STATUS_MISSING, "xrpl_to.dex_volume", as_of_fallback, 0, 60,
            "nessun dato raccolto per dex_volume_acceleration",
        )

    latest_dt, latest_val = series[-1]

    base_30, _gap_30 = _find_base_point(series, latest_dt, 30)
    if base_30 is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl_to.dex_volume", latest_dt, len(series), 60,
            f"storico insufficiente per la finestra dei 30gg piu' recenti: disponibili "
            f"{(latest_dt - series[0][0]).total_seconds() / 86400.0:.2f}gg in totale",
        )

    base_60, _gap_60 = _find_base_point(series, latest_dt, 60)
    if base_60 is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl_to.dex_volume", latest_dt, len(series), 60,
            f"storico insufficiente per la seconda finestra dei 30gg (60gg totali "
            f"richiesti per confrontare due periodi consecutivi): disponibili "
            f"{(latest_dt - series[0][0]).total_seconds() / 86400.0:.2f}gg in totale",
        )

    growth_now = growth_pct(latest_val, base_30)
    growth_prev = growth_pct(base_30, base_60)
    if growth_now is None or growth_prev is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl_to.dex_volume", latest_dt, len(series), 60,
            "una delle due basi di calcolo e' troppo vicina a zero per un growth_pct affidabile",
        )

    value = acceleration(growth_now, growth_prev)
    if value is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl_to.dex_volume", latest_dt, len(series), 60,
            "acceleration() non calcolabile nonostante growth_now/growth_prev disponibili",
        )

    return _feature_result(value, STATUS_ACTIVE, "xrpl_to.dex_volume", latest_dt, len(series), 60, None)


def amm_growth(window_days=30):
    return _build_growth_feature(_extract_amm_pool_value, window_days, "xrpl.amm_info", "amm_growth")


# ============================================================
# FEATURE — NETWORK
# ============================================================

def _extract_trustline_count(snapshot):
    """M8 Gap 3: conteggio trust line paginato completo (issuer RLUSD).
    Usa SOLO snapshot con complete=True nei dati grezzi — un conteggio
    parziale (tetto raggiunto, pagina fallita, marker ripetuto) non deve
    mai essere trattato come un punto valido della serie."""
    try:
        env = snapshot["sources"]["xrpl_native"]["account_lines_rlusd_issuer_paginated"]
    except (KeyError, TypeError):
        return None
    if env.get("status") != raw.STATUS_RAW_AVAILABLE:
        return None
    try:
        data = env["data"]
        if not data.get("complete"):
            return None
        return float(data["total_trustlines"])
    except (KeyError, TypeError, ValueError):
        return None


# M8 Gap 3: window_days=30 esplicitamente approvato per trustline_growth.
# Motivazione (non per analogia): il conteggio trust line e' uno STOCK
# (adozione), non un flusso di trading — non serve controllare la
# stagionalita' settimanale (motivo dei 84gg per XRP/RLUSD). 30gg e' il
# ciclo mensile gia' usato per metriche della stessa classe concettuale
# (adozione istituzionale, es. RWA growth), non un numero preso da una
# metrica di volume.
_TRUSTLINE_GROWTH_APPROVED_WINDOW_DAYS = 30


def trustline_growth(window_days=None):
    """M8 Gap 3: crescita del conteggio trust line RLUSD, raccolto con
    paginazione completa (xrpl_account_lines_paginated in M1). Riuso
    diretto di _build_growth_feature() gia' congelato (stessa identica
    logica di amm_growth/dex_volume_growth) — nessuna formula nuova.

    'window_days': se non passato esplicitamente, usa la finestra
    approvata (30gg)."""
    if window_days is None:
        window_days = _TRUSTLINE_GROWTH_APPROVED_WINDOW_DAYS
    return _build_growth_feature(_extract_trustline_count, window_days, "xrpl.account_lines_paginated", "trustline_growth")


def trustline_acceleration():
    """M8 Gap 3: approvato. Stessa identica costruzione di
    dex_volume_acceleration — riuso ESCLUSIVO di growth_pct(),
    acceleration(), _find_base_point() gia' congelati, nessuna formula
    nuova:
        growth_now  = growth_pct(count_oggi, count_30gg_fa)
        growth_prev = growth_pct(count_30gg_fa, count_60gg_fa)
        trustline_acceleration = acceleration(growth_now, growth_prev)
    Storico minimo ~60gg (due finestre consecutive da 30gg). Nessun
    fallback, nessuna interpolazione."""
    as_of_fallback = _latest_known_timestamp()
    series = _load_series(_extract_trustline_count)
    if not series:
        return _feature_result(
            None, STATUS_MISSING, "xrpl.account_lines_paginated", as_of_fallback, 0, 60,
            "nessun dato raccolto per trustline_acceleration",
        )

    latest_dt, latest_val = series[-1]

    base_30, _gap_30 = _find_base_point(series, latest_dt, 30)
    if base_30 is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.account_lines_paginated", latest_dt, len(series), 60,
            f"storico insufficiente per la finestra dei 30gg piu' recenti: disponibili "
            f"{(latest_dt - series[0][0]).total_seconds() / 86400.0:.2f}gg in totale",
        )

    base_60, _gap_60 = _find_base_point(series, latest_dt, 60)
    if base_60 is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.account_lines_paginated", latest_dt, len(series), 60,
            f"storico insufficiente per la seconda finestra dei 30gg (60gg totali "
            f"richiesti per confrontare due periodi consecutivi): disponibili "
            f"{(latest_dt - series[0][0]).total_seconds() / 86400.0:.2f}gg in totale",
        )

    growth_now = growth_pct(latest_val, base_30)
    growth_prev = growth_pct(base_30, base_60)
    if growth_now is None or growth_prev is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.account_lines_paginated", latest_dt, len(series), 60,
            "una delle due basi di calcolo e' troppo vicina a zero per un growth_pct affidabile",
        )

    value = acceleration(growth_now, growth_prev)
    if value is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.account_lines_paginated", latest_dt, len(series), 60,
            "acceleration() non calcolabile nonostante growth_now/growth_prev disponibili",
        )

    return _feature_result(value, STATUS_ACTIVE, "xrpl.account_lines_paginated", latest_dt, len(series), 60, None)


_ISSUER_ONLY_REASON = (
    "account_tx_rlusd_issuer in M1 interroga SOLO l'account issuer RLUSD (parametro "
    "di default), non l'attivita' a livello dell'intera rete XRPL. Usarlo come proxy "
    "di fee/burn network-wide sarebbe fuorviante: verificato esplicitamente come da "
    "istruzione, dato dichiarato MISSING anziche' calcolato su una base sbagliata."
)


def fee_per_tx():
    return _feature_result(None, STATUS_MISSING, "xrpl.account_tx", _latest_known_timestamp(), 0, 30, _ISSUER_ONLY_REASON)


_DROPS_PER_XRP = 1_000_000.0


def _extract_total_coins_drops(snapshot):
    """M8 Gap 4A: total_coins (drops) dal nuovo adapter leggero xrpl.ledger_info."""
    try:
        env = snapshot["sources"]["xrpl_native"]["ledger_info"]
    except (KeyError, TypeError):
        return None
    if env.get("status") != raw.STATUS_RAW_AVAILABLE:
        return None
    try:
        return float(env["data"]["total_coins_drops"])
    except (KeyError, TypeError, ValueError):
        return None


def burn_rate():
    """M8 Gap 4A: implementata con dati XRPL nativi (contatore cumulativo
    total_coins, monotonicamente decrescente per costruzione).

    xrp_burned = (total_coins_precedente - total_coins_corrente) / 1_000_000
    burn_rate  = xrp_burned / giorni_trascorsi

    Usa ESATTAMENTE due snapshot RAW consecutivi con total_coins valido —
    mai un valore inventato. Se total_coins aumenta (dato anomalo: XRP
    non ha nuova emissione), il delta non viene trattato come burn."""
    as_of_fallback = _latest_known_timestamp()
    series = _load_series(_extract_total_coins_drops)

    if len(series) < 2:
        status = STATUS_MISSING if not series else STATUS_NON_MATURE
        as_of = as_of_fallback if not series else series[-1][0]
        return _feature_result(
            None, status, "xrpl.ledger_info", as_of, len(series), None,
            f"servono almeno 2 snapshot con total_coins valido, disponibili {len(series)}",
        )

    (dt_prev, drops_prev), (dt_curr, drops_curr) = series[-2], series[-1]
    dt_days = (dt_curr - dt_prev).total_seconds() / 86400.0
    if dt_days <= 0:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.ledger_info", dt_curr, len(series), None,
            f"intervallo temporale non valido tra gli ultimi due snapshot ({dt_days:.6f}gg)",
        )

    xrp_burned = (drops_prev - drops_curr) / _DROPS_PER_XRP
    if xrp_burned < 0:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.ledger_info", dt_curr, len(series), None,
            f"total_coins e' aumentato tra i due snapshot (delta={xrp_burned:.6f} XRP): dato "
            f"anomalo (XRP non prevede nuova emissione), non trattato come burn valido",
        )

    value = xrp_burned / dt_days
    return _feature_result(value, STATUS_ACTIVE, "xrpl.ledger_info", dt_curr, len(series), None, None)


# ============================================================
# FEATURE — XRP DEPENDENCY
# ============================================================

def xrp_dependency_ratio():
    reason = (
        "richiede la quota di volume DEX che coinvolge XRP sul volume DEX totale per "
        "coppia; M1 non raccoglie volume per singola coppia (solo book_changes non "
        "accumulato e un aggregato chain-wide da DeFiLlama, non scomponibile per coppia). "
        "Gap strutturale, non risolvibile aspettando piu' storico."
    )
    return _feature_result(None, STATUS_MISSING, "derived", _latest_known_timestamp(), 0, None, reason)


def xrp_pool_share():
    reason = (
        "richiede liquidita' nei pool con XRP / liquidita' totale su tutti i pool XRPL; "
        "M1 traccia un solo pool (XRP/RLUSD) e non un aggregato di 'tutti i pool XRPL' "
        "da usare come denominatore. Gap strutturale, non risolvibile aspettando piu' storico."
    )
    return _feature_result(None, STATUS_MISSING, "derived", _latest_known_timestamp(), 0, None, reason)


def _load_rlusd_pair_volume_series():
    """Serie storica del volume XRP/RLUSD accumulato dal collector
    WebSocket dedicato (xrpl_rlusd_pair_collector.py, M8 Gap 2B) — fonte
    diversa dal RAW di M1: qui il dato nasce dall'accumulo in streaming
    di book_changes, non da un singolo snapshot puntuale."""
    try:
        import xrpl_rlusd_pair_collector as collector
    except Exception as e:
        log.warning(f"[xrpl_feature_engine] xrpl_rlusd_pair_collector non disponibile: {e}")
        return []
    try:
        return collector.get_volume_period_series()
    except Exception as e:
        log.warning(f"[xrpl_feature_engine] lettura serie volume XRP/RLUSD fallita: {e}")
        return []


# M8 Gap 2B — metodologia approvata esplicitamente (non per analogia):
# 84gg = 12 settimane esatte (multiplo di 7), per ridurre distorsioni da
# stagionalita' settimanale del volume della coppia; min_observations=28
# = 4 cicli settimanali completi, come soglia minima di maturita' prima
# di fidarsi di un qualunque confronto growth_pct su questa serie.
_XRP_RLUSD_PAIR_GROWTH_APPROVED_WINDOW_DAYS = 84
_XRP_RLUSD_PAIR_GROWTH_APPROVED_MIN_OBSERVATIONS = 28


def xrp_rlusd_pair_growth(window_days=None):
    """M8 Gap 2B: crescita del volume REALE (AMM + order book, tramite
    le offerte sintetiche AMM gia' incluse in book_changes, verificato
    nell'audit) della coppia XRP/RLUSD. Riuso diretto di growth_pct() e
    _find_base_point() gia' congelati — nessuna formula nuova. Fonte:
    xrpl_rlusd_pair_collector.py (stream book_changes), mai i RAW di M1
    per questa specifica feature. Usa SOLO periodi marcati 'complete':
    True (gia' garantito da get_volume_period_series(), che esclude i
    periodi con gap di backfill non recuperato) — nessun periodo
    parziale, nessuna interpolazione, nessun fallback.

    'window_days': se non passato esplicitamente, usa la finestra
    approvata (84gg). Richiede inoltre almeno
    _XRP_RLUSD_PAIR_GROWTH_APPROVED_MIN_OBSERVATIONS (28) periodi
    completi totali prima di fidarsi di un qualunque confronto —
    soglia di maturita' distinta dal singolo punto base cercato a 84gg."""
    as_of_fallback = _latest_known_timestamp()

    if window_days is None:
        window_days = _XRP_RLUSD_PAIR_GROWTH_APPROVED_WINDOW_DAYS

    series = _load_rlusd_pair_volume_series()
    if not series:
        return _feature_result(
            None, STATUS_MISSING, "xrpl.book_changes.rlusd_pair_collector", as_of_fallback, 0, window_days,
            "nessun dato ancora accumulato dal collector XRP/RLUSD (mai avviato, oppure "
            "nessun periodo di raccolta ancora completato)",
        )

    if len(series) < _XRP_RLUSD_PAIR_GROWTH_APPROVED_MIN_OBSERVATIONS:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.book_changes.rlusd_pair_collector", series[-1][0], len(series), window_days,
            f"solo {len(series)} periodi completi disponibili, sotto il minimo approvato di "
            f"{_XRP_RLUSD_PAIR_GROWTH_APPROVED_MIN_OBSERVATIONS} (4 cicli settimanali)",
        )

    latest_dt, latest_val = series[-1]
    base_val, gap_days = _find_base_point(series, latest_dt, window_days)
    if base_val is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.book_changes.rlusd_pair_collector", latest_dt, len(series), window_days,
            f"nessun periodo completo trovato a {window_days}gg o piu' di distanza: "
            f"storico disponibile {(latest_dt - series[0][0]).total_seconds() / 86400.0:.2f} giorni "
            f"({len(series)} periodi completi)",
        )

    value = growth_pct(latest_val, base_val)
    if value is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "xrpl.book_changes.rlusd_pair_collector", latest_dt, len(series), window_days,
            "base troppo vicina a zero per calcolare una crescita percentuale affidabile",
        )

    status = STATUS_ACTIVE if gap_days >= window_days * 0.8 else STATUS_PARTIAL
    reason = None if status == STATUS_ACTIVE else (
        f"finestra reale ({gap_days:.1f}gg) piu' corta della richiesta ({window_days}gg)"
    )
    return _feature_result(value, status, "xrpl.book_changes.rlusd_pair_collector", latest_dt, len(series), window_days, reason)


# ============================================================
# FEATURE — RELATIVE STRENGTH (Rotation Engine, dependency injection)
# ============================================================

_ROTATION_REUSE_MISSING_REASON = (
    "Riuso del Rotation Engine non collegato in M2 per sicurezza: importare "
    "altseason_bot.py potrebbe eseguire codice a livello modulo con effetti "
    "collaterali (es. avvio di un secondo polling Telegram in conflitto col bot in "
    "produzione, se il suo main() non fosse protetto da if __name__ == '__main__', "
    "cosa non verificabile con certezza in questa milestone). Va collegato in un "
    "passo successivo esplicito, iniettando _rot_get_history/_rot_perf, dopo aver "
    "verificato la struttura del file altseason_bot.py."
)


def _relative_strength_feature(cg_id_a, cg_id_b, rot_get_history_func, rot_perf_func, giorni, feature_name):
    as_of = datetime.now(timezone.utc)
    if rot_get_history_func is None or rot_perf_func is None:
        return _feature_result(
            None, STATUS_MISSING, "rotation_engine.reuse", as_of, 0, giorni,
            _ROTATION_REUSE_MISSING_REASON,
        )
    try:
        closes_a = rot_get_history_func(cg_id_a)
        closes_b = rot_get_history_func(cg_id_b)
        perf_a = rot_perf_func(closes_a, giorni) if closes_a else None
        perf_b = rot_perf_func(closes_b, giorni) if closes_b else None
    except Exception as e:
        return _feature_result(
            None, STATUS_MISSING, "rotation_engine.reuse", as_of, 0, giorni,
            f"errore durante il riuso del Rotation Engine: {e}",
        )
    if perf_a is None or perf_b is None:
        return _feature_result(
            None, STATUS_NON_MATURE, "rotation_engine.reuse", as_of, 0, giorni,
            "dati insufficienti restituiti dal Rotation Engine per il periodo richiesto",
        )
    value = perf_a - perf_b
    return _feature_result(value, STATUS_ACTIVE, "rotation_engine.reuse", as_of, 2, giorni, None)


def xrp_btc_relative_strength(rot_get_history_func=None, rot_perf_func=None, giorni=7):
    return _relative_strength_feature(
        "ripple", "bitcoin", rot_get_history_func, rot_perf_func, giorni, "xrp_btc_relative_strength"
    )


def xrp_eth_relative_strength(rot_get_history_func=None, rot_perf_func=None, giorni=7):
    return _relative_strength_feature(
        "ripple", "ethereum", rot_get_history_func, rot_perf_func, giorni, "xrp_eth_relative_strength"
    )


# ============================================================
# ORCHESTRAZIONE — calcola tutte le feature in un colpo solo
# ============================================================

def compute_all_features(rot_get_history_func=None, rot_perf_func=None):
    """Ritorna un dict con tutte le feature della M2. Nessuna eccezione
    risale al chiamante: ogni feature e' gia' protetta internamente."""
    return {
        "rwa_value_trend": rwa_value_trend(),
        "rwa_growth_30d": rwa_growth_30d(),
        "rwa_growth_90d": rwa_growth_90d(),
        "rwa_acceleration": rwa_acceleration(),
        "rlusd_supply_trend": rlusd_supply_trend(),
        "rlusd_growth": rlusd_growth(),
        "rlusd_velocity": rlusd_velocity(),
        "dex_volume_trend": dex_volume_trend(),
        "dex_volume_growth": dex_volume_growth(),
        "dex_volume_acceleration": dex_volume_acceleration(),
        "amm_growth": amm_growth(),
        "trustline_growth": trustline_growth(),
        "trustline_acceleration": trustline_acceleration(),
        "fee_per_tx": fee_per_tx(),
        "burn_rate": burn_rate(),
        "xrp_dependency_ratio": xrp_dependency_ratio(),
        "xrp_pool_share": xrp_pool_share(),
        "xrp_rlusd_pair_growth": xrp_rlusd_pair_growth(),
        "xrp_btc_relative_strength": xrp_btc_relative_strength(rot_get_history_func, rot_perf_func),
        "xrp_eth_relative_strength": xrp_eth_relative_strength(rot_get_history_func, rot_perf_func),
    }


if __name__ == "__main__":
    import json
    print(json.dumps(compute_all_features(), indent=2, ensure_ascii=False, default=str))
