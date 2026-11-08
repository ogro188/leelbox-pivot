#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EV binario con el payout real de IQ Options (solo lectura).

El collector guarda payout_binary_pct tick a tick. Para cada senal se busca el
payout vigente en el momento de creacion (cierre de la vela M15) y se calcula:

    EV = promedio( ganó ? payout/100 : -1 )

Asi no se asume un payout fijo: se usa el que IQ Options pagaba realmente en
cada entrada. Tambien reporta el payout promedio y el break-even.

Uso:
    python3 payout_ev.py --symbol EURUSD-OTC --detector D2_ANTICIPACION --horizon 3
    python3 payout_ev.py --symbol EURUSD-OTC --all-detectors
"""
import argparse
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone

BASE = "./pivotradar_data"
IQ_DB = os.path.join(BASE, "iq_public", "iq_public.db")
ACTIVOS = "./activos"
CLEAN = "julianday(s.created_at) >= julianday(s.entry_time) + (15.0/1440.0)"


def snapshot(symbol):
    src = os.path.join(BASE, symbol.lower(), "pivot_core.db")
    if not os.path.exists(src):
        raise SystemExit(f"No existe la base: {src}")
    tmp = tempfile.mkdtemp(prefix="pivot-payout-")
    dst = os.path.join(tmp, "pivot_core.db")
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    con.backup(out)
    out.close()
    con.close()
    return tmp, dst


def cargar_activo(symbol):
    path = os.path.join(ACTIVOS, f"{symbol.lower()}.json")
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    fuente = cfg.get("fuente_config") or {}
    return int(fuente.get("active_id")), fuente.get("provider_name") or symbol


def epoch_created(created_at):
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        dt = datetime.fromisoformat(created_at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def nearest_payout(iq, active_id, created_at, window):
    ts = epoch_created(created_at)
    row = iq.execute(
        """
        SELECT payout_binary_pct, ts FROM ticks
        WHERE active_id = ? AND payout_binary_pct IS NOT NULL
          AND ts BETWEEN ? AND ?
        ORDER BY abs(ts - ?) LIMIT 1
        """,
        (active_id, ts - window, ts + window, ts),
    ).fetchone()
    if row is None:
        return None
    return float(row[0])


def stats(rows):
    """rows: lista de (ganó, payout_pct, hora, direccion)."""
    n = len(rows)
    if n == 0:
        return None
    wins = sum(1 for r in rows if r[0])
    wr = wins / n
    payout = sum(r[1] for r in rows) / n / 100.0
    ev = sum((r[1] / 100.0 if r[0] else -1.0) for r in rows) / n
    be = 1.0 / (1.0 + payout)
    return {
        "n": n,
        "wr": wr,
        "payout": payout,
        "ev": ev,
        "be": be,
        "wins": wins,
    }


def fmt(st, label=""):
    if st is None:
        return f"{label}sin datos"
    return (
        f"{label}n={st['n']:4d} wr={st['wr'] * 100:5.1f}% "
        f"payout={st['payout'] * 100:5.1f}% EV={st['ev'] * 100:+6.1f}% "
        f"BE={st['be'] * 100:5.1f}%"
    )


def main():
    parser = argparse.ArgumentParser(description="EV binario con payout real IQ Options")
    parser.add_argument("--symbol", default="EURUSD-OTC")
    parser.add_argument("--detector", default="D2_ANTICIPACION")
    parser.add_argument("--horizon", type=int, default=3)
    parser.add_argument("--window", type=int, default=120, help="segundos de tolerancia")
    parser.add_argument("--all-detectors", action="store_true")
    args = parser.parse_args()

    active_id, provider = cargar_activo(args.symbol)
    tmp, db = snapshot(args.symbol)
    try:
        con = sqlite3.connect(db)
        iq = sqlite3.connect(f"file:{IQ_DB}?mode=ro", uri=True)

        sql = f"""
            select r.horizonte, r.retorno, s.detector, s.direction, s.created_at
            from senales_resultados r
            join senales_core s on s.signal_id = r.signal_id
            where {CLEAN}
        """
        params = []
        if not args.all_detectors:
            sql += " and s.detector = ?"
            params.append(args.detector)
        if args.horizon:
            sql += " and r.horizonte = ?"
            params.append(args.horizon)
        sql += " order by s.created_at"
        raw = list(con.execute(sql, tuple(params)))

        rows = []
        missing = 0
        payouts = []
        for horizon, retorno, detector, direction, created_at in raw:
            if retorno is None:
                continue
            p = nearest_payout(iq, active_id, created_at, args.window)
            if p is None:
                missing += 1
                continue
            payouts.append(p)
            hour = int(created_at[11:13])
            rows.append(
                (
                    float(retorno) > 0,
                    p,
                    hour,
                    detector,
                    int(direction),
                    int(horizon),
                )
            )
        iq.close()
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 100)
    print(
        f"{args.symbol.upper()} ({provider}, active_id={active_id}) | "
        f"detector={args.detector if not args.all_detectors else 'TODOS'} | "
        f"h={args.horizon if args.horizon else 'todos'}"
    )
    print("=" * 100)
    print(f"senales con resultado={len(raw)} | payout encontrado={len(rows)} | sin payout={missing}")
    if payouts:
        payouts.sort()
        print(
            f"payout: min={payouts[0]:.1f}% mediana={payouts[len(payouts)//2]:.1f}% "
            f"max={payouts[-1]:.1f}%"
        )
    print()

    def subset(pred):
        return [r for r in rows if pred(r)]

    print("GLOBAL: " + fmt(stats(rows)))
    print()
    print("por horizonte:")
    for h in sorted({r[5] for r in rows}):
        print("  " + fmt(stats(subset(lambda r, h=h: r[5] == h)), f"h{h}: "))
    print()
    print("por detector:")
    for det in sorted({r[3] for r in rows}):
        print("  " + fmt(stats(subset(lambda r, det=det: r[3] == det)), f"{det:16s} "))
    print()
    print("por direccion:")
    for d, name in ((1, "CALL"), (-1, "PUT")):
        print("  " + fmt(stats(subset(lambda r, d=d: r[4] == d)), f"{name}: "))
    print()
    print("por hora UTC:")
    for h in sorted({r[2] for r in rows}):
        print("  " + fmt(stats(subset(lambda r, h=h: r[2] == h)), f"{h:02d}:00  "))


if __name__ == "__main__":
    main()
