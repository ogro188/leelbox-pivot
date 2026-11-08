#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inspecciona los CSV del escaneo: q minimos y tests cercanos a sobrevivir."""
import csv
import glob
import sys


def num(v, d=1e9):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def main():
    patron = sys.argv[1] if len(sys.argv) > 1 else "results/edge_scan_*_disc.csv"
    for path in sorted(glob.glob(patron)):
        filas = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
        prim = [r for r in filas if r.get("familia") == "primaria" and num(r.get("n"), 0) >= 100]
        prim.sort(key=lambda r: num(r.get("q")))
        print("---", path.split("/")[-1], "| primarios n>=100:", len(prim))
        for r in prim[:8]:
            print(
                "  %-28s h%-2s n=%4s WR=%5.1f be=%5.1f EV=%+6.2f lo=%+6.2f q=%.4f p=%.4f crit=%s"
                % (
                    r["condicion"], r["horizonte"], r["n"], num(r["wr"]), num(r["be"]),
                    num(r["ev"]), num(r["ev_boot_lo"]), num(r["q"]), num(r["p"]),
                    r.get("criterio"),
                )
            )
        low = [r for r in filas if num(r.get("q")) < 0.10]
        print("  q<0.10 en TODOS los tests:", len(low))
        for r in low[:10]:
            print(
                "    %-28s h%-2s n=%4s WR=%5.1f EV=%+6.2f q=%.4f fam=%s"
                % (r["condicion"], r["horizonte"], r["n"], num(r["wr"]), num(r["ev"]),
                   num(r["q"]), r["familia"])
            )
        print()


if __name__ == "__main__":
    main()
