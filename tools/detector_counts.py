#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compara detectores del replay vs produccion."""
import csv
import sqlite3
from collections import Counter


def main():
    for sym in ("eurusd", "xauusd"):
        print("=" * 60)
        print(sym.upper())
        con = sqlite3.connect(f"file:./pivotradar_data/{sym}/pivot_core.db?mode=ro", uri=True)
        prod = Counter(d for (d,) in con.execute("select detector from senales_core"))
        con.close()
        rep = Counter()
        with open(f"results/{sym}_signals.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rep[r["detector"]] += 1
        print(f"{'detector':20s} {'produccion':>10s} {'replay':>8s}")
        for d in sorted(set(prod) | set(rep)):
            print(f"{d[:20]:20s} {prod.get(d, 0):10d} {rep.get(d, 0):8d}")
        print()


if __name__ == "__main__":
    main()
