#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Winrate real por horizonte y detector desde senales_resultados (produccion)."""
import sqlite3
import sys

PAYOUT = {
    "EURUSD": {1: 0.85, 2: 0.86, 3: 0.86, 4: 0.87},
    "XAUUSD": {1: 0.81, 2: 0.82, 3: 0.82, 4: 0.83},
}


def main():
    for sym in ("eurusd", "xauusd"):
        path = f"./pivotradar_data/{sym}/pivot_core.db"
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        print("=" * 70)
        print(sym.upper())
        q = """
        select r.horizonte, s.detector, count(*) n,
               sum(case when r.retorno > 0 then 1 else 0 end) wins,
               avg(r.retorno) ret
        from senales_resultados r
        join senales_core s on s.signal_id = r.signal_id
        where r.horizonte between 1 and 4
        group by r.horizonte, s.detector
        order by r.horizonte, n desc
        """
        filas = con.execute(q).fetchall()
        print(f"{'h':>2s} {'detector':18s} {'n':>6s} {'WR':>6s} {'EV@pay':>8s} {'ret_med':>9s}")
        for h, det, n, wins, ret in filas:
            if n < 30:
                continue
            wr = 100.0 * wins / n
            p = PAYOUT[sym.upper()].get(h, 0.85)
            ev = wr * p - (100.0 - wr)
            print(f"{h:2d} {det[:18]:18s} {n:6d} {wr:6.2f} {ev:+8.2f} {ret:+9.3f}")
        # total por horizonte
        print("-" * 70)
        q2 = """
        select r.horizonte, count(*) n,
               sum(case when r.retorno > 0 then 1 else 0 end) wins
        from senales_resultados r
        where r.horizonte between 1 and 4
        group by r.horizonte order by r.horizonte
        """
        for h, n, wins in con.execute(q2):
            wr = 100.0 * wins / n
            p = PAYOUT[sym.upper()].get(h, 0.85)
            ev = wr * p - (100.0 - wr)
            print(f"TOTAL h{h}: n={n:6d} WR={wr:6.2f}% EV={ev:+8.2f}%")
        print()
        con.close()


if __name__ == "__main__":
    main()
