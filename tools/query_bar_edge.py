#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Consulta condiciones concretas en los CSV de bar_edge."""
import csv
import sys


def main():
    patrones = sys.argv[1].split(",") if len(sys.argv) > 1 else ["ema"]
    for sym in ("eurusd", "xauusd"):
        path = f"results/bar_edge_{sym}.csv"
        print("=" * 90)
        print(sym.upper())
        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if any(p in r["condicion"] for p in patrones):
                print(
                    "%-14s %-22s h%s n=%5s WR=%5.1f IC=%5.1f-%5.1f be=%5.1f "
                    "EV=%+6.2f boot=[%+6.2f,%+6.2f] p=%.4f q=%.4f"
                    % (
                        r["familia"], r["condicion"], r["horizonte"], r["n"],
                        float(r["wr"]), float(r["wr_lo"]), float(r["wr_hi"]),
                        float(r["be"]), float(r["ev"]), float(r["ev_boot_lo"]),
                        float(r["ev_boot_hi"]), float(r["p"]), float(r["q"]),
                    )
                )
        print()


if __name__ == "__main__":
    main()
