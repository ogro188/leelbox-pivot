#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Evaluacion limpia de las senales PIVOT sobre bases de produccion (solo lectura).

Una senal es "limpia" si se creo al cierre de su vela de entrada o despues:
    julianday(created_at) >= julianday(entry_time) + 15/1440

Uso:
    python3 eval_clean.py
    python3 eval_clean.py --symbol XAUUSD --spread 3 --payout 0.80
    python3 eval_clean.py --horizonte 2 --detalle

No escribe en las bases: abre SQLite en modo read-only.
"""
import argparse
import os
import sqlite3

BASE = "./pivotradar_data"
CLEAN = "julianday(s.created_at) >= julianday(s.entry_time) + (15.0/1440.0)"

# Spread asumido por activo, en pips. 10 puntos = 1 pip en EURUSD y XAUUSD.
SPREAD_DEFAULT = {"EURUSD": 1.0, "XAUUSD": 3.0}


def _stats(vals):
    n = len(vals)
    if n == 0:
        return None
    wins = sum(1 for v in vals if v > 0)
    gains = sum(v for v in vals if v > 0)
    losses = -sum(v for v in vals if v < 0)
    return {
        "n": n,
        "wr": 100.0 * wins / n,
        "avg": sum(vals) / n,
        "pf": gains / losses if losses > 0 else float("inf"),
    }


def _fmt(st):
    if st is None:
        return "sin datos"
    return (
        f"n={st['n']:4d} wr={st['wr']:5.1f}% "
        f"bruto={st['avg']:+6.2f} pips PF={st['pf']:5.2f}"
    )


def _net_stats(vals, spread):
    net = [v - spread for v in vals]
    st = _stats(net)
    if st is not None:
        st["avg"] = sum(net) / len(net)
    return st


def evaluar(symbol, horizons, detalle, spread, payout):
    path = os.path.join(BASE, symbol.lower(), "pivot_core.db")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    print("=" * 92)
    print(f"{symbol}  spread={spread:.1f} pips  payout={payout:.0%}  db={path}")
    print("=" * 92)
    total = con.execute("select count(*) from senales_core").fetchone()[0]
    clean = con.execute(
        f"select count(*) from senales_core s where {CLEAN}"
    ).fetchone()[0]
    print(f"senales core={total} limpias={clean} ({100.0 * clean / total:.1f}%)")

    for h in horizons:
        vals = [
            float(x[0]) / 10.0
            for x in con.execute(
                f"""select r.retorno from senales_resultados r
                    join senales_core s on s.signal_id = r.signal_id
                    where r.horizonte=? and {CLEAN}""",
                (h,),
            )
            if x[0] is not None
        ]
        st = _stats(vals)
        net = _net_stats(vals, spread)
        print(f"  h{h}: " + _fmt(st))
        if net is not None:
            ev = (net["wr"] / 100.0) * (1.0 + payout) - 1.0
            print(
                f"      neto: n={net['n']} wr={net['wr']:.1f}% "
                f"avg={net['avg']:+.2f} pips PF={net['pf']:.2f} "
                f"EV={ev * 100:+.1f}%"
            )

    if detalle:
        print("  por detector (h2):")
        for (det,) in con.execute(
            "select distinct detector from senales_core order by detector"
        ):
            vals = [
                float(x[0]) / 10.0
                for x in con.execute(
                    f"""select r.retorno from senales_resultados r
                        join senales_core s on s.signal_id = r.signal_id
                        where r.horizonte=2 and s.detector=? and {CLEAN}""",
                    (det,),
                )
                if x[0] is not None
            ]
            st = _stats(vals)
            net = _net_stats(vals, spread)
            if st is None:
                continue
            ev = (net["wr"] / 100.0) * (1.0 + payout) - 1.0
            print(
                f"    {det:16s} n={st['n']:4d} wr={st['wr']:5.1f}% "
                f"bruto={st['avg']:+6.2f} neto={net['avg']:+6.2f} "
                f"PF={net['pf']:5.2f} EV={ev * 100:+6.1f}%"
            )

    con.close()
    print()


def main():
    parser = argparse.ArgumentParser(description="Evaluacion limpia PIVOT (solo lectura)")
    parser.add_argument("--symbol", default="", help="EURUSD, XAUUSD o vacio para ambos")
    parser.add_argument("--spread", type=float, default=None, help="spread en pips")
    parser.add_argument("--payout", type=float, default=0.80, help="payout binario (0.80 = 80%%)")
    parser.add_argument("--horizonte", type=int, default=0, help="evaluar solo ese horizonte")
    parser.add_argument("--detalle", action="store_true", help="incluir desglose por detector")
    args = parser.parse_args()

    symbols = [args.symbol.upper()] if args.symbol else ["EURUSD", "XAUUSD"]
    horizons = [args.horizonte] if args.horizonte else [1, 2, 3, 4]
    for symbol in symbols:
        spread = args.spread if args.spread is not None else SPREAD_DEFAULT.get(symbol, 1.0)
        evaluar(symbol, horizons, args.detalle, spread, args.payout)


if __name__ == "__main__":
    main()
