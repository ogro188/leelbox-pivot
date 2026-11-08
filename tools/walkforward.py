#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Estabilidad temporal de un filtro: EV por mes y holdout temporal.

No selecciona: evalua condiciones YA elegidas por edge_scan. Sirve para ver si
el edge es estable o esta concentrado en un mes.

Uso:
  python3 walkforward.py --signals out/eurusd_signals.csv \
      --conditions h4_y_h1_alineados,h4_pullback --horizons 1,2,3,4
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, ".")
from edge_scan import condiciones, preparar, evaluar, cargar  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", required=True)
    ap.add_argument("--conditions", required=True)
    ap.add_argument("--horizons", default="1,2,3,4")
    ap.add_argument("--payout", type=float, default=0.85)
    ap.add_argument("--payouts-by-h", default="",
                    help="8 payouts 0-1 separados por coma para h1..h8; sobreescribe --payout")
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--bootstrap", type=int, default=1000)
    args = ap.parse_args()
    payouts_by_h = None
    if args.payouts_by_h:
        payouts_by_h = [float(x) for x in args.payouts_by_h.split(",") if x.strip()]
        if len(payouts_by_h) != 8:
            raise SystemExit("--payouts-by-h necesita exactamente 8 valores")

    filas = cargar([args.signals])
    preparar(filas)
    symbol = filas[0]["symbol"]
    mapa = {n: f for _, n, f in condiciones(filas)}

    nombres = [n.strip() for n in args.conditions.split(",") if n.strip()]
    hs = [int(x) for x in args.horizons.split(",")]
    meses = sorted({r["_date"][:7] for r in filas})
    rng = np.random.default_rng(20261106)

    filas_out = []
    print(f"===== {symbol} | estabilidad mensual | payout {args.payout:.0%} =====")
    for nombre in nombres:
        fn = mapa.get(nombre)
        if fn is None:
            print(f"AVISO condicion desconocida: {nombre}")
            continue
        print(f"\n-- {nombre}")
        print(f"{'h':>2s} {'periodo':8s} {'n':>5s} {'WR':>6s} {'IC95':>13s} {'EV%':>7s} {'boot95':>16s}")
        for h in hs:
            pago_h = payouts_by_h[h - 1] if (payouts_by_h and h <= len(payouts_by_h)) else args.payout
            total = evaluar(filas, fn, h, pago_h, rng, args.bootstrap)
            for periodo in meses + ["TOTAL"]:
                if periodo == "TOTAL":
                    sub = filas
                else:
                    sub = [r for r in filas if r["_date"][:7] == periodo]
                res = evaluar(sub, fn, h, pago_h, rng, args.bootstrap)
                if res is None:
                    continue
                filas_out.append({
                    "symbol": symbol, "condicion": nombre, "horizonte": h,
                    "periodo": periodo, **res,
                })
                print(
                    f"{h:2d} {periodo:8s} {res['n']:5d} {res['wr']:6.1f} "
                    f"{res['wr_lo']:5.1f}-{res['wr_hi']:5.1f} {res['ev']:+7.2f} "
                    f"({res['ev_boot_lo']:+6.2f},{res['ev_boot_hi']:+6.2f})"
                )
        # consistencia: meses con EV>0 y n>=30
        for h in hs:
            evs = [r for r in filas_out if r["condicion"] == nombre and r["horizonte"] == h
                   and r["periodo"] != "TOTAL" and r["n"] >= 30]
            if evs:
                pos = sum(1 for r in evs if r["ev"] > 0)
                print(f"   h{h}: meses n>=30={len(evs)} con EV>0={pos}")

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"walkforward_{symbol.lower()}.csv")
    campos = ["symbol", "condicion", "horizonte", "periodo", "n", "wins", "wr", "wr_lo", "wr_hi", "be", "payout", "ev", "ev_boot_lo", "ev_boot_hi", "p"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in filas_out:
            w.writerow({k: (round(r[k], 4) if isinstance(r.get(k), float) else r.get(k)) for k in campos})
    print(f"\nGuardado {path}")


if __name__ == "__main__":
    main()
