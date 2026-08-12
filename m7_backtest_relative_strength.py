"""
M7 — Backtest REALE del segnale di relative strength (XRP/BTC, XRP/ETH)
===========================================================================

Questo e' l'UNICO componente della pipeline XRPL con storico realmente
profondo e verificabile: i prezzi di XRP/BTC/ETH via CoinGecko, disponibili
da anni. Walk-forward: per ogni giorno simulato, la classificazione usa
SOLO prezzi fino a quel giorno (nessun look-ahead), esattamente come
accadrebbe in produzione.

ATTENZIONE — cosa NON valida questo script (dichiarato esplicitamente):
- NON valida Score2: il gate NORM_UNAVAILABLE di M3 impedisce a questo
  segnale di contribuire numericamente a un punteggio, per QUALUNQUE data,
  passata o futura. Questo resta vero indipendentemente da questo backtest.
- NON valida la pipeline integrata (Score1+Score2+Confidence+Divergence+
  Decision) — solo la classificazione di trend isolata (UP/DOWN/FLAT/
  STRONG_UP), la stessa logica usata oggi in produzione da M4.
- E' un backtest REALE (dati reali, walk-forward, no look-ahead, nessuna
  interpolazione) ma di un componente isolato, non del sistema.

Riuso diretto, nessuna reimplementazione:
- xrpl_feature_engine.trend_vs_ma (mediana/MAD) — stessa funzione usata
  in produzione da M2/M3/M4.
- xrpl_score_layer._MAD_TO_STANDARD_Z_FACTOR — stessa calibrazione
  MAD->sigma verificata e congelata in M3.
- xrpl_divergence_state._NORMAL_BAND_SIGMA / _STRONG_BAND_SIGMA — stesse
  soglie (1/2 sigma) gia' congelate in M4.

Nessun dato inventato, nessuna interpolazione: se una data manca in
CoinGecko per un asset, quel giorno viene semplicemente escluso
dall'allineamento, non riempito.

Richiede rete verso api.coingecko.com — va eseguito sulla tua macchina
(rete ristretta nell'ambiente sandbox usato per scrivere questo script).
"""
import json
from datetime import datetime, timezone

import requests

import xrpl_feature_engine as fe
import xrpl_score_layer as sl
import xrpl_divergence_state as ds

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
WINDOW_DAYS = 30  # stessa finestra gia' usata altrove nel progetto (RLUSD growth, ecc.)


def fetch_historical_daily_closes(coin_id, from_ts, to_ts):
    """Prezzi storici REALI giornalieri da CoinGecko, range esplicito.
    Nessuna interpolazione: un punto mancante in CoinGecko resta mancante."""
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart/range"
    params = {"vs_currency": "usd", "from": from_ts, "to": to_ts}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    prices = data.get("prices", [])
    out = []
    seen_dates = set()
    for ms, price in prices:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).date()
        if dt in seen_dates:
            continue
        seen_dates.add(dt)
        out.append((dt, price))
    out.sort(key=lambda pair: pair[0])
    return out


def align_and_compute_relative_strength(xrp_prices, base_prices):
    """Allinea per data (solo date presenti in ENTRAMBE le serie — mai
    interpolato) e calcola il rapporto XRP/base giornaliero."""
    base_by_date = dict(base_prices)
    out = []
    for d, xrp_p in xrp_prices:
        base_p = base_by_date.get(d)
        if base_p is not None and base_p > 0:
            out.append((d, xrp_p / base_p))
    return out


def walk_forward_classify(ratio_series, window_days=WINDOW_DAYS):
    """Per ogni giorno (a partire dal window_days-esimo), classifica il
    trend usando SOLO dati fino a quel giorno (walk-forward, no
    look-ahead). Stessa metodologia congelata in M4, applicata qui a una
    serie esterna reale invece che allo storico interno di M1 — stesso
    metodo, dato diverso."""
    results = []
    for i in range(window_days, len(ratio_series)):
        window = [v for _, v in ratio_series[i - window_days:i]]
        current_date, current_val = ratio_series[i]
        z_raw = fe.trend_vs_ma(current_val, window)
        if z_raw is None:
            trend = "NON_MATURE"
        else:
            z_std = sl._MAD_TO_STANDARD_Z_FACTOR * z_raw
            if z_std >= ds._STRONG_BAND_SIGMA:
                trend = "STRONG_UP"
            elif z_std >= ds._NORMAL_BAND_SIGMA:
                trend = "UP"
            elif z_std <= -ds._NORMAL_BAND_SIGMA:
                trend = "DOWN"
            else:
                trend = "FLAT"
        results.append((current_date, current_val, z_raw, trend))
    return results


def summarize(name, series):
    counts = {}
    for _, _, _, t in series:
        counts[t] = counts.get(t, 0) + 1
    total = len(series)
    print(f"\n{name}: distribuzione classificazioni su {total} giorni walk-forward:")
    for t in ("STRONG_UP", "UP", "FLAT", "DOWN", "NON_MATURE"):
        c = counts.get(t, 0)
        if total:
            print(f"  {t:12s}: {c:4d} giorni ({c/total*100:5.1f}%)")
    if total:
        changes = sum(1 for j in range(1, len(series)) if series[j][3] != series[j - 1][3])
        print(f"  Cambi di classificazione: {changes} su {total} giorni ({changes/total*100:.1f}%)")


def main():
    from_date = datetime(2024, 12, 17, tzinfo=timezone.utc)
    to_date = datetime.now(timezone.utc)
    from_ts = int(from_date.timestamp())
    to_ts = int(to_date.timestamp())

    print(f"Scarico prezzi storici reali XRP/BTC/ETH dal {from_date.date()} al {to_date.date()}...")
    xrp = fetch_historical_daily_closes("ripple", from_ts, to_ts)
    btc = fetch_historical_daily_closes("bitcoin", from_ts, to_ts)
    eth = fetch_historical_daily_closes("ethereum", from_ts, to_ts)
    print(f"Punti scaricati: XRP={len(xrp)}, BTC={len(btc)}, ETH={len(eth)}")

    xrp_btc = align_and_compute_relative_strength(xrp, btc)
    xrp_eth = align_and_compute_relative_strength(xrp, eth)
    print(f"Serie allineate: XRP/BTC={len(xrp_btc)} punti, XRP/ETH={len(xrp_eth)} punti")

    trend_btc = walk_forward_classify(xrp_btc)
    trend_eth = walk_forward_classify(xrp_eth)

    summarize("XRP/BTC", trend_btc)
    summarize("XRP/ETH", trend_eth)

    out = {
        "xrp_btc": [{"date": str(d), "ratio": v, "z_raw": z, "trend": t} for d, v, z, t in trend_btc],
        "xrp_eth": [{"date": str(d), "ratio": v, "z_raw": z, "trend": t} for d, v, z, t in trend_eth],
    }
    with open("m7_relative_strength_backtest_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("\nRisultato completo salvato in m7_relative_strength_backtest_result.json")


if __name__ == "__main__":
    main()
