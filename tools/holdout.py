#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Confirma en holdout los filtros descubiertos en el tramo de descubrimiento.

Los umbrales (terciles) se calculan SOLO con descubrimiento y se congelan;
el holdout nunca participa en la seleccion. Reporta:

  1) supervivientes estrictos del edge_scan de descubrimiento, evaluados en holdout,
  2) hipotesis a priori H1/H2 (aunque no sobrevivieran), como control,
  3) baseline del holdout.

Uso:
  python3 holdout.py --signals out/eurusd_signals.csv \
      --scan out/edge_scan_eurusd_discovery.csv --split 2026-10-01
"""
import argparse
import csv
import os
import sys

import numpy as np

sys.path.insert(0, ".")
from edge_scan import (  # noqa: E402
    cargar, preparar, condiciones, evaluar, filtrar_fechas, aint,
)

APRIORI = [
    "h4_alineado", "h1_alineado", "h4_y_h1_alineados", "h4_pullback",
    "h4_contra", "h1_contra", "d1_alineado", "estructura_alineada",
]


def leer_supervivientes(path):
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if aint(r.get("criterio")) == 1:
                out.append((r["condicion"], int(r["horizonte"])))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signals", required=True)
    ap.add_argument("--scan", default="", help="edge_scan CSV del tramo de descubrimiento")
    ap.add_argument("--split", required=True, help="fecha YYYY-MM-DD: holdout desde aqui")
    ap.add_argument("--desc-hasta", default="",
                    help="fecha fin descubrimiento exclusiva (default: --split)")
    ap.add_argument("--payout", type=float, default=0.85)
    ap.add_argument("--payouts-by-h", default="",
                    help="8 payouts 0-1 separados por coma para h1..h8; sobreescribe --payout")
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()
    payouts_by_h = None
    if args.payouts_by_h:
        payouts_by_h = [float(x) for x in args.payouts_by_h.split(",") if x.strip()]
        if len(payouts_by_h) != 8:
            raise SystemExit("--payouts-by-h necesita exactamente 8 valores")

    filas = cargar([args.signals])
    preparar(filas)
    desc_hasta = args.desc_hasta or args.split
    desc = [r for r in filas if r["_date"] < desc_hasta]
    hold = [r for r in filas if r["_date"] >= args.split]
    symbol = filas[0]["symbol"]

    conds = condiciones(desc)
    mapa = {n: f for _, n, f in conds}
    rng = np.random.default_rng(20261106)

    print(f"===== {symbol} | split {args.split} =====")
    if not desc or not hold:
        print(f"AVISO: descubrimiento={len(desc)} holdout={len(hold)}; split invalido")
        return
    print(f"descubrimiento: {len(desc)} senales ({desc[0]['_date']}..{max(r['_date'] for r in desc)})")
    print(f"holdout:        {len(hold)} senales ({hold[0]['_date']}..{max(r['_date'] for r in hold)})")

    def linea(tag, nombre, h, res):
        print(
            f"  {tag:9s} {nombre[:30]:30s} h{h} n={res['n']:4d} WR={res['wr']:5.1f} "
            f"IC={res['wr_lo']:4.1f}-{res['wr_hi']:4.1f} EV={res['ev']:+6.2f}% "
            f"boot=[{res['ev_boot_lo']:+6.2f},{res['ev_boot_hi']:+6.2f}] p={res['p']:.4f}"
        )

    out = []

    # Baseline holdout
    pago_h3 = payouts_by_h[2] if (payouts_by_h and len(payouts_by_h) >= 3) else args.payout
    base = evaluar(hold, lambda r: True, 3, pago_h3, rng, args.bootstrap)
    if base:
        linea("BASE", "TODAS", 3, base)
        out.append({"symbol": symbol, "bloque": "base", "condicion": "TODAS",
                    "horizonte": 3, **base})

    # Supervivientes del descubrimiento
    sobre = leer_supervivientes(args.scan)
    print(f"\nSupervivientes estrictos en descubrimiento: {len(sobre)}")
    for nombre, h in sobre:
        fn = mapa.get(nombre)
        if fn is None:
            continue
        pago_h = payouts_by_h[h - 1] if (payouts_by_h and h <= len(payouts_by_h)) else args.payout
        res = evaluar(hold, fn, h, pago_h, rng, args.bootstrap)
        if res is None:
            print(f"  AVISO {nombre} h{h}: holdout insuficiente")
            continue
        linea("SELECCION", nombre, h, res)
        out.append({"symbol": symbol, "bloque": "seleccion", "condicion": nombre,
                    "horizonte": h, **res})

    # Hipotesis a priori: se reportan todas, sin seleccion
    print("\nHipotesis a priori en holdout (sin seleccion):")
    for nombre in APRIORI:
        fn = mapa.get(nombre)
        if fn is None:
            continue
        for h in (1, 2, 3, 4):
            pago_h = payouts_by_h[h - 1] if (payouts_by_h and h <= len(payouts_by_h)) else args.payout
            res = evaluar(hold, fn, h, pago_h, rng, args.bootstrap)
            if res is None:
                continue
            linea("APRIORI", nombre, h, res)
            out.append({"symbol": symbol, "bloque": "apriori", "condicion": nombre,
                        "horizonte": h, **res})

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"holdout_{symbol.lower()}.csv")
    campos = ["symbol", "bloque", "condicion", "horizonte", "n", "wins", "wr",
              "wr_lo", "wr_hi", "be", "payout", "ev", "ev_boot_lo", "ev_boot_hi", "p"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in out:
            w.writerow({k: (round(r[k], 4) if isinstance(r.get(k), float) else r.get(k))
                        for k in campos})
    print(f"\nGuardado {path}")


if __name__ == "__main__":
    main()
