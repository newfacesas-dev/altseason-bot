#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_bybit.py - PROBE usa-e-getta per verificare se Bybit e' raggiungibile
dall'IP di Railway (US West), come alternativa a Binance (bloccato, HTTP 451).
Testa funding rate e open interest per BTC/ETH/SOL/XRP via API pubblica v5.
NON tocca il bot. Stampa un report leggibile. Da rimuovere dopo l'uso.
"""
import requests

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

def line(s=""):
    print(s, flush=True)

def test_funding_and_ticker():
    """Bybit v5: /v5/market/tickers (category=linear) restituisce in un colpo
    sia fundingRate sia openInterest per il simbolo. Una sola chiamata per simbolo."""
    line("=" * 50)
    line("TEST Bybit v5: /v5/market/tickers (funding + open interest)")
    line("=" * 50)
    fok = 0
    ook = 0
    for sym in SYMBOLS:
        try:
            url = f"https://api.bybit.com/v5/market/tickers?category=linear&symbol={sym}"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            j = r.json()
            lst = j.get("result", {}).get("list", [])
            if not lst:
                line(f"  WARN {sym}: risposta senza dati (retCode={j.get('retCode')})")
                continue
            d = lst[0]
            fr = d.get("fundingRate")
            oi = d.get("openInterest")
            fr_txt = f"{float(fr)*100:+.4f}%" if fr not in (None, "") else "n/d"
            oi_txt = f"{float(oi):,.0f}" if oi not in (None, "") else "n/d"
            if fr not in (None, ""):
                fok += 1
            if oi not in (None, ""):
                ook += 1
            line(f"  OK  {sym}: funding={fr_txt}, open_interest={oi_txt}")
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            line(f"  FAIL {sym}: HTTP {code} ({e})")
        except Exception as e:
            line(f"  FAIL {sym}: {type(e).__name__}: {e}")
    return fok, ook

def main():
    line("")
    line("#" * 50)
    line("# PROBE BYBIT - test raggiungibilita da Railway")
    line("#" * 50)
    try:
        ip = requests.get("https://api.ipify.org", timeout=10).text
        line(f"IP pubblico di uscita: {ip}")
    except Exception as e:
        line(f"IP non determinabile: {e}")

    fok, ook = test_funding_and_ticker()

    line("")
    line("=" * 50)
    line("VERDETTO:")
    if fok == len(SYMBOLS) and ook == len(SYMBOLS):
        line("  BYBIT RAGGIUNGIBILE - possiamo integrare Funding + OI da Bybit")
    elif fok == 0 and ook == 0:
        line("  BYBIT BLOCCATO/VUOTO - serve altra fonte")
    else:
        line(f"  PARZIALE - funding {fok}/{len(SYMBOLS)}, OI {ook}/{len(SYMBOLS)}")
    line("=" * 50)
    line("")
    line("Probe terminato. Il bot NON e' partito (questo e' solo il test).")
    line("Ricordati di rimettere lo Start Command a: python altseason_bot.py")

if __name__ == "__main__":
    main()
