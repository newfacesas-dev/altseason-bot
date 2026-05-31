#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_binance.py - PROBE usa-e-getta per verificare se Binance Futures e'
raggiungibile dall'IP di Railway (US West).
Prova funding rate e open interest per BTC/ETH/SOL/XRP.
NON tocca il bot. Stampa un report leggibile nei log. Da rimuovere dopo l'uso.
"""
import sys
import requests

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]

def line(s=""):
    print(s, flush=True)

def test_funding():
    line("=" * 50)
    line("TEST 1: FUNDING RATE (fapi.binance.com/fapi/v1/premiumIndex)")
    line("=" * 50)
    ok = 0
    for sym in SYMBOLS:
        try:
            url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={sym}"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            d = r.json()
            fr = float(d.get("lastFundingRate", 0)) * 100
            line(f"  OK  {sym}: funding rate = {fr:+.4f}%")
            ok += 1
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            line(f"  FAIL {sym}: HTTP {code} ({e})")
        except Exception as e:
            line(f"  FAIL {sym}: {type(e).__name__}: {e}")
    return ok

def test_oi():
    line("=" * 50)
    line("TEST 2: OPEN INTEREST (fapi.binance.com/fapi/v1/openInterest)")
    line("=" * 50)
    ok = 0
    for sym in SYMBOLS:
        try:
            url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={sym}"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            d = r.json()
            oi = float(d.get("openInterest", 0))
            line(f"  OK  {sym}: open interest = {oi:,.0f} contratti")
            ok += 1
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else "?"
            line(f"  FAIL {sym}: HTTP {code} ({e})")
        except Exception as e:
            line(f"  FAIL {sym}: {type(e).__name__}: {e}")
    return ok

def main():
    line("")
    line("#" * 50)
    line("# PROBE BINANCE FUTURES - test raggiungibilita da Railway")
    line("#" * 50)
    # mostro l'IP pubblico di uscita, utile per capire la regione
    try:
        ip = requests.get("https://api.ipify.org", timeout=10).text
        line(f"IP pubblico di uscita: {ip}")
    except Exception as e:
        line(f"IP non determinabile: {e}")

    f_ok = test_funding()
    o_ok = test_oi()

    line("")
    line("=" * 50)
    line("VERDETTO:")
    if f_ok == len(SYMBOLS) and o_ok == len(SYMBOLS):
        line("  ✅ BINANCE RAGGIUNGIBILE - possiamo integrare Funding + OI")
    elif f_ok == 0 and o_ok == 0:
        line("  ❌ BINANCE BLOCCATO da questo IP - serve fonte alternativa (Bybit/altro)")
    else:
        line(f"  ⚠️ PARZIALE - funding {f_ok}/{len(SYMBOLS)}, OI {o_ok}/{len(SYMBOLS)} - da valutare")
    line("=" * 50)
    line("")
    line("Probe terminato. Il bot NON e' partito (questo e' solo il test).")
    line("Ricordati di rimettere lo Start Command a: python altseason_bot.py")

if __name__ == "__main__":
    main()
