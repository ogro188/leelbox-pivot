#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test de fidelidad: replay con ventana movil vs senales de produccion.

No escribe en produccion. Compara IDs de senales del ultimo tramo.
"""
import argparse
import os
import sqlite3
import sys
import tempfile
import time

import pandas as pd

sys.path.insert(0, ".")

from core.motor_v8 import PivotRadarEngine  # noqa: E402
from kernel.feeds.csv_resample import resamplear_ohlc  # noqa: E402

DATA = "data"


def cargar(symbol):
    m15 = pd.read_csv(
        os.path.join(DATA, f"{symbol.lower()}_M15.csv"),
        parse_dates=["datetime"],
        index_col="datetime",
    )
    m15.index = pd.to_datetime(m15.index, utc=True)
    m15 = m15[["open", "high", "low", "close", "volume"]].astype(float)
    h1 = resamplear_ohlc(m15, "H1")
    h4 = resamplear_ohlc(m15, "H4")
    d1 = pd.read_csv(
        os.path.join(DATA, f"{symbol.lower()}_D1.csv"),
        parse_dates=["datetime"],
        index_col="datetime",
    )
    d1.index = pd.to_datetime(d1.index, utc=True)
    d1 = d1[["open", "high", "low", "close", "volume"]].astype(float)
    return m15, h1, h4, d1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--dias", type=int, default=36, help="dias hacia atras a comparar")
    args = ap.parse_args()
    symbol = args.symbol.upper()

    m15, h1, h4, d1 = cargar(symbol)
    bars = args.dias * 96
    start = max(0, len(m15) - bars - 500)
    print(
        f"{symbol}: M15={len(m15)} replay desde {m15.index[start]} "
        f"({len(m15) - start} velas)",
        flush=True,
    )

    tmp = tempfile.mkdtemp(prefix="pivot-fidelity-")
    point = 1e-05 if symbol == "EURUSD" else 0.01
    eng = PivotRadarEngine(
        symbol=symbol,
        ntfy_topic="",
        ntfy_server="http://127.0.0.1:9",
        modo_test=False,
        point=point,
        data_dir=tmp,
    )
    ids = []
    original = eng.route_signal

    def route(sig):
        original(sig)
        if getattr(eng, "_emitir", False):
            ids.append(
                (
                    str(sig.id),
                    sig.detector,
                    pd.Timestamp(sig.entry_time).isoformat(),
                    int(sig.direction),
                )
            )

    eng.route_signal = route

    def dfs(i):
        corte = m15.index[i]
        return (
            m15.iloc[max(0, i - 999) : i + 1],
            h1[h1.index <= corte].tail(500),
            h4[h4.index <= corte].tail(300),
            d1[d1.index <= corte].tail(300),
        )

    t0 = time.time()
    eng.on_data(*dfs(start + 499), emitir=False)
    print(f"precarga {time.time() - t0:.1f}s", flush=True)
    t0 = time.time()
    for i in range(start + 500, len(m15)):
        eng.on_data(*dfs(i), emitir=True)
        if (i - start) % 500 == 0:
            print(
                f"  {i - start}/{len(m15) - start} senales={len(ids)} "
                f"{time.time() - t0:.1f}s",
                flush=True,
            )
    print(f"replay {time.time() - t0:.1f}s | senales={len(ids)}", flush=True)

    # Produccion
    path = f"./pivotradar_data/{symbol.lower()}/pivot_core.db"
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    desde = m15.index[start + 500].isoformat()
    prod = {
        str(r[0]): (r[1], r[2], r[3])
        for r in con.execute(
            "select signal_id, detector, entry_time, direction from senales_core "
            "where entry_time >= ?",
            (desde,),
        )
    }
    con.close()

    replay = {r[0]: (r[1], r[2], r[3]) for r in ids}
    comunes = set(prod) & set(replay)
    print(f"produccion={len(prod)} replay={len(replay)} IDs comunes={len(comunes)}")
    print(f"match sobre replay={100 * len(comunes) / max(1, len(replay)):.1f}%")
    print(f"match sobre produccion={100 * len(comunes) / max(1, len(prod)):.1f}%")

    from collections import Counter

    for name, data in (("produccion", prod), ("replay", replay)):
        c = Counter(v[0] for v in data.values())
        print(name, dict(sorted(c.items())))

    # diferencias de entry_time/detector/direction en IDs comunes
    mal = [k for k in comunes if prod[k][0] != replay[k][0] or prod[k][2] != replay[k][2]]
    print(f"IDs comunes con detector/direction distinto={len(mal)}")
    if mal[:3]:
        for k in mal[:3]:
            print("  ", k, prod[k], replay[k])


if __name__ == "__main__":
    main()
