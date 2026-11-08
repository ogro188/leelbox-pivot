#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Valida las etiquetas del replay contra senales_resultados de produccion.

Lee el CSV completo del replay y consulta la DB en bloques de 900 IDs, sin
limitarse a los primeros. Reporta coincidencia de signo, dif media/p95 y
desglose por horizonte.

Uso:
  python3 validate_labels.py --symbol EURUSD
"""
import argparse
import csv
import os
import sqlite3
from collections import defaultdict


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--signals", default="")
    ap.add_argument("--max-h", type=int, default=4)
    args = ap.parse_args()
    symbol = args.symbol.upper()
    path = args.signals or f"results/{symbol.lower()}_signals.csv"

    filas = list(csv.DictReader(open(path, newline="", encoding="utf-8")))
    por_id = {str(r["id"]): r for r in filas}
    ids = list(por_id)
    db = f"./pivotradar_data/{symbol.lower()}/pivot_core.db"
    if not os.path.exists(db):
        raise SystemExit(f"no existe {db}")

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    prod = {}
    for k in range(0, len(ids), 900):
        chunk = ids[k:k + 900]
        q = ",".join("?" * len(chunk))
        for sid, h, ret in con.execute(
            f"select signal_id, horizonte, retorno from senales_resultados where signal_id in ({q})",
            chunk,
        ):
            prod[(str(sid), int(h))] = float(ret)
    con.close()

    difs = []
    signos = 0
    total = 0
    por_h = defaultdict(lambda: [0, 0, []])
    for (sid, h), ret_prod in prod.items():
        if h > args.max_h:
            continue
        r = por_id.get(sid)
        if r is None:
            continue
        v = r.get(f"ret_h{h}")
        if v in (None, ""):
            continue
        ret_rep = float(v)
        d = abs(ret_rep - ret_prod)
        difs.append(d)
        ok = (ret_rep > 0) == (ret_prod > 0)
        signos += 1 if ok else 0
        total += 1
        por_h[h][0] += 1
        por_h[h][1] += 1 if ok else 0
        por_h[h][2].append(d)

    difs.sort()
    print(f"{symbol}: replay={len(filas)} db_ids_con_resultado={len(prod)} comunes={total}")
    if total:
        print(f"  signo coincide: {100.0 * signos / total:.2f}%")
        print(f"  dif media: {sum(difs) / len(difs):.6f} puntos | p95: {difs[int(len(difs) * 0.95)]:.6f} | max: {difs[-1]:.6f}")
        print(f"  exactos (<1e-6): {100.0 * sum(1 for d in difs if d < 1e-6) / len(difs):.2f}%")
        for h in sorted(por_h):
            n, s, ds = por_h[h]
            ds.sort()
            print(f"  h{h}: n={n:5d} signo={100.0 * s / n:6.2f}% dif_media={sum(ds) / len(ds):.4f} p95={ds[int(len(ds) * 0.95)]:.4f}")


if __name__ == "__main__":
    main()
