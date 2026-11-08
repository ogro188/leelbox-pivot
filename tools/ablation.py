#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ablacion H4-only / H1-only / H4+H1 / PIVOT / PIVOT+H4+H1.

Mide el aporte incremental de cada capa. Las variantes H4/H1 se evaluan en
cada cierre M15 con entrada al cierre; PIVOT usa las senales del replay.

Sin lookahead: la EMA del timeframe superior se calcula con los cierres
finalizados de las velas anteriores mas el precio actual (vela en curso).
"""
import argparse
import csv
import math
import os
import sys
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
from edge_scan import wilson, norm_sf, aint, afloat, sgn  # noqa: E402

DATA = "data"


def ema_series(vals, span):
    return pd.Series(vals).ewm(span=span, adjust=False).mean().to_numpy()


def tendencia_actual(m15, regla, span_corto=20, span_largo=50):
    """Devuelve sign(EMA_corta - EMA_larga) en cada cierre M15, sin lookahead."""
    c = m15["close"].to_numpy(dtype=float)
    idx = m15.index
    bucket = idx.floor(regla)
    # cierre final por bucket (el ultimo M15 del bucket)
    fin = {}
    for k, b in enumerate(bucket):
        fin[b] = c[k]
    buckets = sorted(fin)
    valores = np.array([fin[b] for b in buckets], dtype=float)
    e_corto = ema_series(valores, span_corto)
    e_largo = ema_series(valores, span_largo)
    pos = {b: k for k, b in enumerate(buckets)}
    corto_prev = np.empty(len(c))
    largo_prev = np.empty(len(c))
    for k, b in enumerate(bucket):
        j = pos[b]
        if j == 0:
            corto_prev[k] = e_corto[0]
            largo_prev[k] = e_largo[0]
        else:
            corto_prev[k] = e_corto[j - 1]
            largo_prev[k] = e_largo[j - 1]
    a_c = 2.0 / (span_corto + 1.0)
    a_l = 2.0 / (span_largo + 1.0)
    corto = a_c * c + (1 - a_c) * corto_prev
    largo = a_l * c + (1 - a_l) * largo_prev
    return np.sign(corto - largo).astype(int), corto - largo


def etiquetas(c, h):
    n = len(c)
    out = np.full(n, np.nan)
    out[:n - h] = c[h:] - c[:n - h]
    return out


def stats(ret, wins, dates, payout, B=2000, seed=1):
    ret = np.asarray(ret, dtype=float)
    ok = ~np.isnan(ret)
    n = int(ok.sum())
    if n < 30:
        return None
    k = int(np.nansum(wins[ok]))
    wr = 100.0 * k / n
    lo, hi = wilson(k, n)
    be = 100.0 / (1.0 + payout)
    z = (wr - be) / 100.0 * math.sqrt(n) / math.sqrt(be / 100.0 * (1 - be / 100.0))
    p = norm_sf(z)
    dias = defaultdict(lambda: [0, 0.0])
    for d, w in zip(np.asarray(dates)[ok], np.asarray(wins)[ok]):
        dias[d][0] += 1
        dias[d][1] += w
    day_n = np.array([v[0] for v in dias.values()], dtype=float)
    day_w = np.array([v[1] for v in dias.values()], dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(day_n), size=(B, len(day_n)))
    wr_boot = day_w[idx].sum(axis=1) / day_n[idx].sum(axis=1)
    ev_boot = payout * wr_boot - (1 - wr_boot)
    ev = payout * (k / n) - (1 - k / n)
    return {
        "n": n, "wins": k, "wr": wr, "wr_lo": lo, "wr_hi": hi, "be": be,
        "ev": 100 * ev,
        "ev_boot_lo": 100 * float(np.percentile(ev_boot, 2.5)),
        "ev_boot_hi": 100 * float(np.percentile(ev_boot, 97.5)),
        "p": p,
    }


def evaluar_variante(nombre, dirs, c, fechas, payout, hs=(1, 2, 3, 4, 5, 6, 7, 8), payouts_by_h=None):
    res = []
    for h in hs:
        d = np.asarray(dirs, dtype=float)
        ret = etiquetas(c, h)
        ret = np.where(d == 0, np.nan, ret * d)
        wins = np.where(np.isnan(ret), np.nan, (ret > 0).astype(float))
        pago_h = payouts_by_h[h - 1] if (payouts_by_h and h <= len(payouts_by_h)) else payout
        s = stats(ret, wins, fechas, pago_h)
        if s:
            res.append({"variante": nombre, "horizonte": h, "payout": 100.0 * pago_h, **s})
    return res


def cargar(symbol):
    m15 = pd.read_csv(
        os.path.join(DATA, f"{symbol.lower()}_M15.csv"),
        parse_dates=["datetime"], index_col="datetime",
    )
    m15.index = pd.to_datetime(m15.index, utc=True)
    return m15[["open", "high", "low", "close", "volume"]].astype(float)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--signals", default="", help="CSV de feature_replay (PIVOT)")
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--payout", type=float, default=0.85)
    ap.add_argument("--payouts-by-h", default="",
                    help="8 payouts 0-1 separados por coma para h1..h8; sobreescribe --payout")
    ap.add_argument("--bootstrap", type=int, default=2000)
    args = ap.parse_args()
    payouts_by_h = None
    if args.payouts_by_h:
        payouts_by_h = [float(x) for x in args.payouts_by_h.split(",") if x.strip()]
        if len(payouts_by_h) != 8:
            raise SystemExit("--payouts-by-h necesita exactamente 8 valores")
    symbol = args.symbol.upper()
    m15 = cargar(symbol)
    c = m15["close"].to_numpy(dtype=float)
    fechas = np.array([str(t.date()) for t in m15.index])

    d4, diff4 = tendencia_actual(m15, "4h")
    d1, diff1 = tendencia_actual(m15, "1h")
    print(f"[{symbol}] H4 signos {dict(zip(*np.unique(d4, return_counts=True)))} | H1 {dict(zip(*np.unique(d1, return_counts=True)))}")

    resultados = []
    resultados += evaluar_variante("H4_only", d4, c, fechas, args.payout, hs=range(1, 9), payouts_by_h=payouts_by_h)
    resultados += evaluar_variante("H1_only", d1, c, fechas, args.payout, hs=range(1, 9), payouts_by_h=payouts_by_h)
    ambos = np.where((d4 == d1) & (d4 != 0), d4, 0)
    resultados += evaluar_variante("H4_H1", ambos, c, fechas, args.payout, hs=range(1, 9), payouts_by_h=payouts_by_h)
    resultados += evaluar_variante("siempre_long", np.ones(len(c), dtype=int), c, fechas, args.payout, hs=range(1, 9), payouts_by_h=payouts_by_h)

    if args.signals:
        with open(args.signals, newline="", encoding="utf-8") as f:
            piv = []
            vistos = set()
            for r in csv.DictReader(f):
                rid = r.get("id")
                if rid:
                    if rid in vistos:
                        continue
                    vistos.add(rid)
                piv.append(r)
        # PIVOT puro
        for h in range(1, 9):
            rets, wins, ds = [], [], []
            for r in piv:
                v = afloat(r.get(f"ret_h{h}"))
                w = aint(r.get(f"win_h{h}"))
                if v is None or w is None:
                    continue
                rets.append(v)
                wins.append(w)
                ds.append(r.get("date"))
            pago_h = payouts_by_h[h - 1] if (payouts_by_h and h <= len(payouts_by_h)) else args.payout
            s = stats(rets, np.array(wins, dtype=float), np.array(ds), pago_h)
            if s:
                resultados.append({"variante": "PIVOT", "horizonte": h, "payout": 100.0 * pago_h, **s})
        # PIVOT + H4/H1 alineados
        for h in range(1, 9):
            rets, wins, ds = [], [], []
            for r in piv:
                d = aint(r.get("direction"))
                h4 = sgn(afloat(r.get("ctx_h4_ema20_vs_50_atr")))
                h1 = sgn(afloat(r.get("ctx_h1_ema20_vs_50_atr")))
                if d not in (1, -1) or h4 != d or h1 != d:
                    continue
                v = afloat(r.get(f"ret_h{h}"))
                w = aint(r.get(f"win_h{h}"))
                if v is None or w is None:
                    continue
                rets.append(v)
                wins.append(w)
                ds.append(r.get("date"))
            pago_h = payouts_by_h[h - 1] if (payouts_by_h and h <= len(payouts_by_h)) else args.payout
            s = stats(rets, np.array(wins, dtype=float), np.array(ds), pago_h)
            if s:
                resultados.append({"variante": "PIVOT_H4_H1", "horizonte": h, "payout": 100.0 * pago_h, **s})

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, f"ablation_{symbol.lower()}.csv")
    campos = ["variante", "horizonte", "n", "wins", "wr", "wr_lo", "wr_hi", "be", "payout", "ev", "ev_boot_lo", "ev_boot_hi", "p"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in resultados:
            w.writerow({k: (round(r[k], 4) if isinstance(r.get(k), float) else r.get(k)) for k in campos})

    print(f"\n===== ABLACION {symbol} (payout {args.payout:.0%}) =====")
    print(f"{'variante':14s} h  n      WR     IC95          EV%     boot95")
    for r in resultados:
        print(
            f"{r['variante']:14s} {r['horizonte']} {r['n']:6d} {r['wr']:5.1f} "
            f"{r['wr_lo']:5.1f}-{r['wr_hi']:5.1f} {r['ev']:+6.2f} "
            f"({r['ev_boot_lo']:+6.2f},{r['ev_boot_hi']:+6.2f})"
        )
    print(f"\nGuardado {path}")


if __name__ == "__main__":
    main()
