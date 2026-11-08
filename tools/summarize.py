#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resume los CSV de edge_scan, ablation, holdout y OTC en una tabla corta."""
import argparse
import csv
import glob
import os


def leer(path):
    if not path or not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def edge(path, top=12, min_n=100):
    filas = leer(path)
    if not filas:
        return
    prim = [r for r in filas if r.get("familia") == "primaria" and num(r.get("n")) >= min_n]
    prim.sort(key=lambda r: num(r.get("p"), 1.0))
    print(f"\n-- {os.path.basename(path)} | tests={len(filas)} primarios n>={min_n}={len(prim)}")
    print(f"{'condicion':32s} h  n     WR     IC95          pay%  EV%     boot95          q")
    for r in prim[:top]:
        print(
            f"{r['condicion'][:32]:32s} {r['horizonte']} {int(num(r['n'])):5d} "
            f"{num(r['wr']):5.1f} {num(r['wr_lo']):5.1f}-{num(r['wr_hi']):5.1f} "
            f"{num(r.get('payout')):4.1f} {num(r['ev']):+6.2f} "
            f"({num(r['ev_boot_lo']):+6.2f},{num(r['ev_boot_hi']):+6.2f}) "
            f"{num(r['q'],1):.3f}"
        )
    sobre = [r for r in filas if r.get("criterio") == "1"]
    print(f"   supervivientes estrictos: {len(sobre)}")
    for r in sobre:
        print(
            f"   * {r['condicion']} h{r['horizonte']} n={r['n']} WR={num(r['wr']):.1f} "
            f"EV={num(r['ev']):+.2f}% boot=[{num(r['ev_boot_lo']):+.2f},{num(r['ev_boot_hi']):+.2f}] "
            f"q={num(r['q'],1):.3f}"
        )


def ablation(path):
    filas = leer(path)
    if not filas:
        return
    print(f"\n-- {os.path.basename(path)}")
    print(f"{'variante':14s} h  n      WR     pay%  EV%     boot95")
    for r in filas:
        if int(num(r["horizonte"])) in (1, 2, 3, 4):
            print(
                f"{r['variante']:14s} {r['horizonte']} {int(num(r['n'])):6d} "
                f"{num(r['wr']):5.1f} {num(r.get('payout')):4.1f} {num(r['ev']):+6.2f} "
                f"({num(r['ev_boot_lo']):+6.2f},{num(r['ev_boot_hi']):+6.2f})"
            )


def holdout(path, min_n=30):
    filas = leer(path)
    if not filas:
        return
    print(f"\n-- {os.path.basename(path)}")
    for r in filas:
        if num(r.get("n")) < min_n:
            continue
        print(
            f"  {r['bloque']:9s} {r['condicion'][:30]:30s} h{r['horizonte']} "
            f"n={int(num(r['n'])):4d} WR={num(r['wr']):5.1f} "
            f"IC={num(r['wr_lo']):4.1f}-{num(r['wr_hi']):4.1f} "
            f"EV={num(r['ev']):+6.2f}% boot=[{num(r['ev_boot_lo']):+6.2f},{num(r['ev_boot_hi']):+6.2f}]"
        )


def otc(path):
    filas = leer(path)
    if not filas:
        return
    print(f"\n-- {os.path.basename(path)}")
    for r in filas:
        if num(r.get("n")) < 20:
            continue
        print(
            f"  {r['symbol']:12s} {r['condicion'][:30]:30s} h{r['horizonte']} "
            f"n={int(num(r['n'])):3d} WR={num(r['wr']):5.1f} "
            f"payout={num(r['payout_medio']):4.1f}% EV={num(r['ev']):+6.2f}% "
            f"boot=[{num(r['ev_boot_lo']):+6.2f},{num(r['ev_boot_hi']):+6.2f}]"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()
    d = args.out_dir
    for path in sorted(glob.glob(os.path.join(d, "edge_scan_*.csv"))):
        if "all" in os.path.basename(path):
            continue
        edge(path)
    for path in sorted(glob.glob(os.path.join(d, "ablation_*.csv"))):
        ablation(path)
    for path in sorted(glob.glob(os.path.join(d, "holdout_*.csv"))):
        holdout(path)
    otc(os.path.join(d, "otc_validation.csv"))


if __name__ == "__main__":
    main()
