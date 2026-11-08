#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audita el replay contra produccion: IDs, detector, direccion y conviccion.

Solo lectura. Se corre cuando termina feature_replay.
"""
import argparse
import csv
import os
import sqlite3
from collections import Counter, defaultdict


def cargar_replay(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--signals", default="")
    args = ap.parse_args()
    symbol = args.symbol.upper()
    path = args.signals or f"results/{symbol.lower()}_signals.csv"

    replay = cargar_replay(path)
    por_id = {r["id"]: r for r in replay}
    desde = min(r["entry_time"] for r in replay)

    db = f"./pivotradar_data/{symbol.lower()}/pivot_core.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    prod = {}
    for sid, et, det, d, conv, reg in con.execute(
        "select signal_id, entry_time, detector, direction, conviccion, regimen_volatilidad "
        "from senales_core where entry_time >= ?", (desde,)
    ):
        prod[str(sid)] = {"entry_time": et, "detector": det, "direction": int(d),
                          "conviccion": str(conv), "regimen": str(reg)}
    con.close()

    comunes = set(prod) & set(por_id)
    print(f"{symbol}: produccion={len(prod)} replay={len(replay)} comunes={len(comunes)}")
    print(f"  match sobre produccion={100*len(comunes)/max(1,len(prod)):.1f}% | sobre replay={100*len(comunes)/max(1,len(replay)):.1f}%")

    mal_det = [k for k in comunes if prod[k]["detector"] != por_id[k]["detector"] or prod[k]["direction"] != int(por_id[k]["direction"])]
    print(f"  detector/direccion distinto en comunes: {len(mal_det)}")
    for k in mal_det[:5]:
        print("   ", k, prod[k], por_id[k]["detector"], por_id[k]["direction"])

    def dist(fuente, campo):
        c = Counter()
        for k in comunes:
            v = fuente[k][campo] if isinstance(fuente[k], dict) else fuente[k].get(campo, "")
            c[str(v)] += 1
        return c

    print("\n  conviccion (comunes):")
    pc = dist(prod, "conviccion")
    rc = Counter(str(por_id[k].get("conviccion", "")) for k in comunes)
    for v in sorted(set(pc) | set(rc)):
        print(f"    {v:8s} prod={pc.get(v,0):4d} replay={rc.get(v,0):4d}")
    coinciden = sum(1 for k in comunes if prod[k]["conviccion"] == str(por_id[k].get("conviccion", "")))
    print(f"    coincidencia exacta={100*coinciden/max(1,len(comunes)):.1f}%")

    print("\n  regimen (comunes):")
    pc = dist(prod, "regimen")
    rc = Counter(str(por_id[k].get("regimen_volatilidad", "")) for k in comunes)
    for v in sorted(set(pc) | set(rc)):
        print(f"    {v:10s} prod={pc.get(v,0):4d} replay={rc.get(v,0):4d}")

    # volumen por detector y dia
    print("\n  senales por detector (replay):")
    for det, n in Counter(r["detector"] for r in replay).most_common():
        print(f"    {det:16s} {n:5d}")
    dias = defaultdict(int)
    for r in replay:
        dias[r["entry_time"][:10]] += 1
    vals = sorted(dias.values())
    if vals:
        print(f"  senales/dia: min={vals[0]} mediana={vals[len(vals)//2]} max={vals[-1]} dias={len(vals)}")
    nulos = sum(1 for r in replay if r.get("ret_h4") in ("", None))
    print(f"  filas sin ret_h4: {nulos}")


if __name__ == "__main__":
    main()
