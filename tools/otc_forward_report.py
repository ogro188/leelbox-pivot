#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reporte de forward test para activos OTC de PIVOT (solo lectura).

Toma una copia consistente de la SQLite (incluye WAL), aplica el filtro de
senales limpias y reporta winrate, retorno bruto, EV binario al payout real,
break-even y desglose por dia / direccion / horizonte.

Uso:
    python3 otc_forward_report.py
    python3 otc_forward_report.py --symbol EURUSD-OTC --detector D2_ANTICIPACION --payout 0.85
    python3 otc_forward_report.py --detector "" --all-detectors
"""
import argparse
import math
import os
import sqlite3
import tempfile
from datetime import datetime, timezone

BASE = "./pivotradar_data"
CLEAN = "julianday(s.created_at) >= julianday(s.entry_time) + (15.0/1440.0)"
POINTS_PER_PIP = 10.0


def snapshot(symbol):
    src = os.path.join(BASE, symbol.lower(), "pivot_core.db")
    if not os.path.exists(src):
        raise SystemExit(f"No existe la base: {src}")
    tmp = tempfile.mkdtemp(prefix="pivot-otc-report-")
    dst = os.path.join(tmp, "pivot_core.db")
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    con.backup(out)
    out.close()
    con.close()
    return tmp, dst


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def stats(vals, payout):
    n = len(vals)
    if n == 0:
        return None
    wins = sum(1 for v in vals if v > 0)
    wr = wins / n
    lo, hi = wilson(wins, n)
    avg = sum(vals) / n
    ev = wr * (1.0 + payout) - 1.0
    be = (1.0 / wr - 1.0) if wr > 0 else float("inf")
    need = None
    if wr > 0.5:
        need = math.ceil((1.96 * math.sqrt(wr * (1.0 - wr)) / (wr - 0.5)) ** 2)
    return {
        "n": n,
        "wins": wins,
        "wr": wr,
        "lo": lo,
        "hi": hi,
        "avg": avg,
        "ev": ev,
        "be": be,
        "need": need,
    }


def fmt(st, payout):
    if st is None:
        return "sin datos"
    need = f"{st['need']}" if st["need"] is not None else "n/a"
    return (
        f"n={st['n']:4d} wr={st['wr'] * 100:5.1f}% "
        f"(IC95 {st['lo'] * 100:4.1f}-{st['hi'] * 100:4.1f}%) "
        f"bruto={st['avg']:+6.2f} pips EV@{payout:.0%}={st['ev'] * 100:+6.1f}% "
        f"BE={st['be'] * 100:5.1f}% n_need~{need}"
    )


def rows_for(con, detector, horizon):
    sql = f"""
        select r.retorno, r.mfe, r.mae, s.direction, substr(s.entry_time, 1, 10)
        from senales_resultados r
        join senales_core s on s.signal_id = r.signal_id
        where r.horizonte = ? and {CLEAN}
    """
    params = [horizon]
    if detector:
        sql += " and s.detector = ?"
        params.append(detector)
    sql += " order by s.entry_time"
    return list(con.execute(sql, tuple(params)))


def evaluar(con, symbol, detector, horizon, payout):
    rows = rows_for(con, detector, horizon)
    vals = [float(r[0]) / POINTS_PER_PIP for r in rows if r[0] is not None]
    label = f"{symbol} / {detector or 'TODOS'} / h{horizon}"
    print("=" * 100)
    print(label)
    print("=" * 100)
    total = con.execute("select count(*) from senales_core").fetchone()[0]
    clean = con.execute(f"select count(*) from senales_core s where {CLEAN}").fetchone()[0]
    rango = con.execute(
        f"select min(s.entry_time), max(s.entry_time) from senales_core s where {CLEAN}"
    ).fetchone()
    print(f"señales core={total} limpias={clean} rango={rango[0]} -> {rango[1]}")
    st = stats(vals, payout)
    print("GLOBAL: " + fmt(st, payout))
    if st is None:
        print()
        return

    if st["need"] is not None and st["n"] < st["need"]:
        print(
            f"  -> muestra insuficiente: faltan ~{st['need'] - st['n']} senales "
            f"para que el IC95 inferior supere 50%"
        )
    elif st["lo"] > 0.5:
        print("  -> IC95 inferior > 50%: edge estadisticamente positivo")
    else:
        print("  -> IC95 incluye 50%: no significativo todavia")

    print("  por dia:")
    dias = {}
    for r in rows:
        if r[0] is None:
            continue
        dias.setdefault(r[4], []).append(float(r[0]) / POINTS_PER_PIP)
    acum = []
    for d in sorted(dias):
        acum.extend(dias[d])
        s = stats(dias[d], payout)
        sa = stats(acum, payout)
        print(
            f"    {d} n={s['n']:3d} wr={s['wr'] * 100:5.1f}% "
            f"avg={s['avg']:+6.2f} EV={s['ev'] * 100:+6.1f}%  "
            f"| acum n={sa['n']:4d} wr={sa['wr'] * 100:5.1f}% "
            f"EV={sa['ev'] * 100:+6.1f}%"
        )

    print("  por direccion:")
    for direction, name in ((1, "CALL"), (-1, "PUT")):
        v = [
            float(r[0]) / POINTS_PER_PIP
            for r in rows
            if r[0] is not None and r[3] == direction
        ]
        s = stats(v, payout)
        print(f"    {name}: " + fmt(s, payout))

    print("  por horizonte:")
    for h in (1, 2, 3, 4):
        hrows = rows_for(con, detector, h)
        hv = [float(r[0]) / POINTS_PER_PIP for r in hrows if r[0] is not None]
        s = stats(hv, payout)
        print(f"    h{h}: " + fmt(s, payout))
    print()


def main():
    parser = argparse.ArgumentParser(description="Reporte forward test OTC (solo lectura)")
    parser.add_argument("--symbol", default="EURUSD-OTC")
    parser.add_argument("--detector", default="D2_ANTICIPACION")
    parser.add_argument("--horizon", type=int, default=2)
    parser.add_argument("--payout", type=float, default=0.85, help="payout real, ej. 0.85")
    parser.add_argument(
        "--all-detectors",
        action="store_true",
        help="ignora --detector y reporta todos los detectores",
    )
    args = parser.parse_args()

    print(f"Generado: {datetime.now(timezone.utc).isoformat()}")
    tmp, db = snapshot(args.symbol)
    try:
        con = sqlite3.connect(db)
        if args.all_detectors:
            detectores = [
                r[0] for r in con.execute(
                    "select distinct detector from senales_core order by detector"
                )
            ]
        else:
            detectores = [args.detector]
        for det in detectores:
            evaluar(con, args.symbol.upper(), det, args.horizon, args.payout)
        con.close()
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
