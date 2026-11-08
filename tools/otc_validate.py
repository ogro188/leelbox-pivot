#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Valida filtros concretos en OTC con el payout REAL de cada senal.

No hace screening masivo: recibe condiciones ya elegidas en el replay live y
las evalua sobre las senales OTC historicas (6 dias). Reporta WR, IC95, EV
con payout real por senal y block bootstrap por dia.

Uso:
  python3 otc_validate.py --features out/otc_features.csv \
      --conditions det_d2_anticipacion,h4_y_h1_alineados,h4_pullback
"""
import argparse
import csv
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, ".")
from edge_scan import condiciones, preparar, cargar, wilson, aint, afloat  # noqa: E402


def evaluar_otc(filas, cond, h, B=2000, seed=7):
    sel = []
    for r in filas:
        if not cond(r):
            continue
        w = aint(r.get(f"win_h{h}"))
        p = afloat(r.get("payout_pct"))
        if w is None or p is None:
            continue
        sel.append((r["_date"], w, p / 100.0))
    n = len(sel)
    if n < 20:
        return None
    k = sum(w for _, w, _ in sel)
    wr = 100.0 * k / n
    lo, hi = wilson(k, n)
    evs = np.array([(p if w else -1.0) for _, w, p in sel])
    ev = 100.0 * evs.mean()
    be = 100.0 * float(np.mean([1.0 / (1.0 + p) for _, _, p in sel]))

    dias = defaultdict(lambda: [0, 0.0])
    for d, w, p in sel:
        dias[d][0] += 1
        dias[d][1] += (p if w else -1.0)
    day_n = np.array([v[0] for v in dias.values()], dtype=float)
    day_ev = np.array([v[1] for v in dias.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(day_n), size=(B, len(day_n)))
    boot = day_ev[idx].sum(axis=1) / day_n[idx].sum(axis=1)
    return {
        "n": n, "dias": len(day_n), "wins": k, "wr": wr, "wr_lo": lo, "wr_hi": hi,
        "be": be, "payout_medio": 100.0 * float(np.mean([p for _, _, p in sel])),
        "ev": ev,
        "ev_boot_lo": 100.0 * float(np.percentile(boot, 2.5)),
        "ev_boot_hi": 100.0 * float(np.percentile(boot, 97.5)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="results/otc_features.csv")
    ap.add_argument("--conditions", default="det_d2_anticipacion,h4_y_h1_alineados,h4_pullback,h4_alineado,h1_alineado")
    ap.add_argument("--horizons", default="1,2,3,4")
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--out", default="results/otc_validation.csv")
    args = ap.parse_args()

    filas = cargar([args.features])
    preparar(filas)
    for r in filas:
        r["symbol"] = r.get("symbol") or "OTC"
    mapa = {n: f for _, n, f in condiciones(filas)}
    hs = [int(x) for x in args.horizons.split(",")]
    resultados = []

    for sym in sorted({r["symbol"] for r in filas}):
        grupo = [r for r in filas if r["symbol"] == sym]
        print(f"\n===== {sym} | payout real por senal =====")
        base = evaluar_otc(grupo, lambda r: True, 3, args.bootstrap)
        if base:
            print(f"  todas h3: n={base['n']} WR={base['wr']:.1f}% IC={base['wr_lo']:.1f}-{base['wr_hi']:.1f} "
                  f"payout={base['payout_medio']:.1f}% be={base['be']:.1f}% EV={base['ev']:+.2f}% "
                  f"boot=[{base['ev_boot_lo']:+.2f},{base['ev_boot_hi']:+.2f}]")
            resultados.append({"symbol": sym, "condicion": "TODAS", "horizonte": 3, **base})
        for nombre in [n.strip() for n in args.conditions.split(",") if n.strip()]:
            fn = mapa.get(nombre)
            if fn is None:
                print(f"  AVISO condicion desconocida {nombre}")
                continue
            for h in hs:
                res = evaluar_otc(grupo, fn, h, args.bootstrap)
                if res is None:
                    continue
                resultados.append({"symbol": sym, "condicion": nombre, "horizonte": h, **res})
                print(f"  {nombre[:30]:30s} h{h} n={res['n']:3d} WR={res['wr']:5.1f}% "
                      f"IC={res['wr_lo']:4.1f}-{res['wr_hi']:4.1f} payout={res['payout_medio']:4.1f}% "
                      f"EV={res['ev']:+6.2f}% boot=[{res['ev_boot_lo']:+6.2f},{res['ev_boot_hi']:+6.2f}]")

    campos = ["symbol", "condicion", "horizonte", "n", "dias", "wins", "wr", "wr_lo", "wr_hi", "be", "payout_medio", "ev", "ev_boot_lo", "ev_boot_hi"]
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in resultados:
            w.writerow({k: (round(r[k], 4) if isinstance(r.get(k), float) else r.get(k)) for k in campos})
    print(f"\nGuardado {args.out}")


if __name__ == "__main__":
    main()
