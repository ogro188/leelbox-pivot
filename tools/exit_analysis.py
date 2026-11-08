#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analisis de salidas TP/SL con MFE/MAE (solo lectura).

Los resultados guardan, para cada horizonte, el retorno al cierre y las
excursiones maxima favorable (MFE) y adversa (MAE). No guardan el orden en
que ocurrieron, asi que para cada combinacion TP/SL se calculan dos cotas:

  optimista: si tocaron TP y SL, se asume que gano TP primero
  pesimista: si tocaron TP y SL, se asume que gano SL primero

Si una combinacion es positiva incluso en la cota pesimista, es un candidato
serio. Si solo es positiva en la optimista, no alcanza.

Uso:
    python3 exit_analysis.py --symbol EURUSD-OTC --detector D2_ANTICIPACION --horizon 2
    python3 exit_analysis.py --symbol EURUSD --horizon 2 --tp 3,5,8,10,15 --sl 3,5,8,10,15
"""
import argparse
import os
import sqlite3
import tempfile

BASE = "./pivotradar_data"
CLEAN = "julianday(s.created_at) >= julianday(s.entry_time) + (15.0/1440.0)"
POINTS_PER_PIP = 10.0


def snapshot(symbol):
    src = os.path.join(BASE, symbol.lower(), "pivot_core.db")
    if not os.path.exists(src):
        raise SystemExit(f"No existe la base: {src}")
    tmp = tempfile.mkdtemp(prefix="pivot-exit-")
    dst = os.path.join(tmp, "pivot_core.db")
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    out = sqlite3.connect(dst)
    con.backup(out)
    out.close()
    con.close()
    return tmp, dst


def cargar(con, detector, horizon):
    sql = f"""
        select r.retorno, r.mfe, r.mae
        from senales_resultados r
        join senales_core s on s.signal_id = r.signal_id
        where r.horizonte = ? and {CLEAN}
    """
    params = [horizon]
    if detector:
        sql += " and s.detector = ?"
        params.append(detector)
    rows = []
    for ret, mfe, mae in con.execute(sql, tuple(params)):
        if ret is None or mfe is None or mae is None:
            continue
        rows.append(
            (
                float(ret) / POINTS_PER_PIP,
                float(mfe) / POINTS_PER_PIP,
                float(mae) / POINTS_PER_PIP,
            )
        )
    return rows


def percentil(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def simular(rows, tp, sl):
    n = len(rows)
    if n == 0:
        return None
    tp_hit = sl_hit = both = neither = 0
    opt = []
    pes = []
    for ret, mfe, mae in rows:
        hit_tp = mfe >= tp
        hit_sl = mae <= -sl
        if hit_tp and hit_sl:
            both += 1
        elif hit_tp:
            tp_hit += 1
        elif hit_sl:
            sl_hit += 1
        else:
            neither += 1

        if hit_tp and hit_sl:
            opt.append(tp)
            pes.append(-sl)
        elif hit_tp:
            opt.append(tp)
            pes.append(tp)
        elif hit_sl:
            opt.append(-sl)
            pes.append(-sl)
        else:
            opt.append(ret)
            pes.append(ret)

    def res(vals):
        wins = sum(1 for v in vals if v > 0)
        gains = sum(v for v in vals if v > 0)
        losses = -sum(v for v in vals if v < 0)
        return {
            "avg": sum(vals) / n,
            "wr": 100.0 * wins / n,
            "pf": gains / losses if losses > 0 else float("inf"),
        }

    return {
        "n": n,
        "tp_hit": tp_hit,
        "sl_hit": sl_hit,
        "both": both,
        "neither": neither,
        "opt": res(opt),
        "pes": res(pes),
    }


def main():
    parser = argparse.ArgumentParser(description="Analisis TP/SL con MFE/MAE")
    parser.add_argument("--symbol", default="EURUSD-OTC")
    parser.add_argument("--detector", default="D2_ANTICIPACION")
    parser.add_argument("--horizon", type=int, default=2)
    parser.add_argument("--tp", default="3,5,8,10,15")
    parser.add_argument("--sl", default="3,5,8,10,15")
    args = parser.parse_args()

    tps = [float(x) for x in args.tp.split(",") if x.strip()]
    sls = [float(x) for x in args.sl.split(",") if x.strip()]

    tmp, db = snapshot(args.symbol)
    try:
        con = sqlite3.connect(db)
        rows = cargar(con, args.detector, args.horizon)
        con.close()
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 118)
    print(
        f"{args.symbol.upper()} / {args.detector or 'TODOS'} / h{args.horizon} "
        f"| n={len(rows)} | TP={tps} SL={sls} (pips)"
    )
    print("=" * 118)
    if not rows:
        print("sin datos")
        return

    rets = [r[0] for r in rows]
    mfes = [r[1] for r in rows]
    maes = [r[2] for r in rows]
    print(
        f"retorno: mediana={percentil(rets, 0.5):+.2f} "
        f"p10={percentil(rets, 0.1):+.2f} p90={percentil(rets, 0.9):+.2f}"
    )
    print(
        f"MFE: mediana={percentil(mfes, 0.5):+.2f} "
        f"p75={percentil(mfes, 0.75):+.2f} p90={percentil(mfes, 0.9):+.2f}"
    )
    print(
        f"MAE: mediana={percentil(maes, 0.5):+.2f} "
        f"p10={percentil(maes, 0.1):+.2f} p25={percentil(maes, 0.25):+.2f}"
    )
    print()
    print(
        f"{'TP':>4s} {'SL':>4s} {'n':>4s} {'P(TP)':>6s} {'P(SL)':>6s} "
        f"{'ambos':>6s} {'ninguno':>7s} {'avg_opt':>8s} {'WR_opt':>6s} "
        f"{'avg_pes':>8s} {'WR_pes':>6s} {'PF_pes':>6s}"
    )
    results = []
    for tp in tps:
        for sl in sls:
            st = simular(rows, tp, sl)
            if st is None:
                continue
            results.append((tp, sl, st))
            print(
                f"{tp:4.0f} {sl:4.0f} {st['n']:4d} "
                f"{100.0 * st['tp_hit'] / st['n']:5.1f}% "
                f"{100.0 * st['sl_hit'] / st['n']:5.1f}% "
                f"{100.0 * st['both'] / st['n']:5.1f}% "
                f"{100.0 * st['neither'] / st['n']:6.1f}% "
                f"{st['opt']['avg']:+8.2f} {st['opt']['wr']:5.1f}% "
                f"{st['pes']['avg']:+8.2f} {st['pes']['wr']:5.1f}% "
                f"{st['pes']['pf']:6.2f}"
            )
    robust = [r for r in results if r[2]["pes"]["avg"] > 0]
    print()
    if robust:
        print("Combinaciones positivas incluso en la cota pesimista:")
        for tp, sl, st in robust:
            print(
                f"  TP={tp:.0f} SL={sl:.0f}: "
                f"avg_pes={st['pes']['avg']:+.2f} pips "
                f"(avg_opt={st['opt']['avg']:+.2f})"
            )
    else:
        print(
            "Ninguna combinacion TP/SL es positiva en la cota pesimista. "
            "No hay asimetria explotable con estos datos."
        )


if __name__ == "__main__":
    main()
