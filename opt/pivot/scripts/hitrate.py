#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hit-rate real de las senales: por detector, banda de confianza y tipo.

Usa el resultado medido sobre velas CERRADAS (tabla senales_resultados):
el retorno de la vela h posterior a la entrada, en la direccion anunciada.
Para un detector con payout P el break-even esta en 1/(1+P): 85% -> 54.1%.

Uso: python3 scripts/hitrate.py [horizonte]   (horizonte default 1)
"""
import glob
import sqlite3
import sys
from collections import defaultdict


def cargar(horizonte):
    filas = []
    for db in sorted(glob.glob("/opt/pivot/pivotradar_data/*/pivot_core.db")):
        activo = db.split("/")[-2].upper()
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        q = """
            SELECT s.detector, s.symbol, s.direction, s.tipo,
                   s.hipotesis_prob_min, s.hipotesis_prob_max, s.conviccion,
                   s.regimen_volatilidad, s.entry_time,
                   r.retorno, r.mfe, r.mae
            FROM senales_core s
            JOIN senales_resultados r ON r.signal_id = s.signal_id
            WHERE r.horizonte = ?
        """
        for (det, sym, dr, tipo, pmin, pmax, conv, reg, et, ret, mfe, mae) in con.execute(q, (horizonte,)):
            filas.append({
                "activo": sym or activo, "detector": det or "?", "dir": dr,
                "tipo": tipo or "?", "pmin": pmin, "pmax": pmax,
                "conv": conv, "reg": reg or "-", "ret": ret or 0.0,
                "mfe": mfe or 0.0, "mae": mae or 0.0,
            })
        con.close()
    return filas


def tabla(titulo, grupos, filas):
    print("\n%s" % titulo)
    print("  %-14s %-11s %5s %7s %7s %8s %8s" % (
        "grupo", "detector", "n", "acierto", "brk-even", "ret.med", "mfe/mae"))
    for g, sub in grupos.items():
        for det in sorted(set(f["detector"] for f in sub)):
            s = [f for f in sub if f["detector"] == det]
            n = len(s)
            if not n:
                continue
            wins = sum(1 for f in s if f["ret"] > 0)
            hr = 100.0 * wins / n
            br = 100.0 / 1.85
            rm = sum(f["ret"] for f in s) / n
            mfe = sum(f["mfe"] for f in s) / n
            mae = sum(f["mae"] for f in s) / n
            flag = ""
            if n >= 5 and hr < br + 2:
                flag = "  <- bajo break-even"
            print("  %-14s %-11s %5d %6.1f%% %7.1f%% %8.1f %5.1f/%-5.1f%s" % (
                g, det, n, hr, br, rm, mfe, mae, flag))


def main():
    horizonte = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    filas = cargar(horizonte)
    print("=" * 88)
    print("HIT-RATE MEDIDO SOBRE VELAS CERRADAS - horizonte %d vela(s) posterior(es) a la entrada"
          % horizonte)
    print("Total de senales con resultado: %d" % len(filas))
    if not filas:
        print("\nSin datos todavia. La tabla se llena sola: cada senal necesita que cierre")
        print("la vela siguiente (+1 barra extra de latencia por registro).")
        return

    g = defaultdict(list)
    for f in filas:
        g["TODAS"].append(f)
    tabla("POR DETECTOR", g, filas)

    g = defaultdict(list)
    for f in filas:
        g["TODAS"].append(f)
    for f in filas:
        banda = int((f["pmin"] or 0) // 10) * 10
        g["banda %d-%d%%" % (banda, banda + 9)].append(f)
    tabla("POR BANDA DE CONFIANZA DECLARADA (comprueba si el score predice acierto)", g, filas)

    g = defaultdict(list)
    for f in filas:
        g["TODAS"].append(f)
        g["tipo " + f["tipo"]].append(f)
        g[f["activo"]].append(f)
        g["conv " + str(f["conv"])].append(f)
    tabla("POR TIPO / ACTIVO / CONVICCION", g, filas)
    print("\nNota: 'acierto' = la vela siguiente cerro en la direccion anunciada.")
    print("Con payout 85%% necesitas >54.1%% de acierto medio para no perder dinero.")


if __name__ == "__main__":
    main()