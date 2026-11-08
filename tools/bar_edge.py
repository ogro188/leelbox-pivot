#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Escaneo a nivel de vela (no solo senales PIVOT).

Familias pre-registradas:
  - calendario: hora UTC y dia de la semana,
  - momentum/reversion: retorno de 1,2,4,8,16 velas,
  - RSI14: buckets y estrategia de extremos,
  - volatilidad: percentil ATR y ratio ATR,
  - EMA50: distancia en ATR y estrategia de tendencia,
  - cuerpo/rango: body ratio y rango/ATR.

Cada condicion se evalua en largo y corto para h1-h4, con WR, Wilson,
EV binario, p-valor y bootstrap por dia. Descubrimiento: hasta 2026-09-29.
Holdout: desde 2026-10-01. BH-FDR sobre todos los tests primarios.
"""
import argparse
import csv
import math
import os
from collections import defaultdict

import numpy as np
import pandas as pd

Z95 = 1.959963984540054
PAYOUT = {
    "EURUSD": [0.85, 0.86, 0.86, 0.87],
    "XAUUSD": [0.81, 0.82, 0.82, 0.83],
}


def wilson(k, n, z=Z95):
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    den = 1.0 + z * z / n
    centro = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (100.0 * (centro - half), 100.0 * (centro + half))


def norm_sf(z):
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def bh_qvalues(pvals):
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [1.0] * m
    prev = 1.0
    for rank in range(m, 0, -1):
        idx = order[rank - 1]
        val = pvals[idx] * m / rank
        prev = min(prev, val)
        q[idx] = prev
    return q


def cargar_m15(path):
    df = pd.read_csv(path)
    df["dt"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("epoch").reset_index(drop=True)
    df["day"] = df["dt"].dt.strftime("%Y-%m-%d")
    df["date"] = df["day"]
    df["hour"] = df["dt"].dt.hour
    df["weekday"] = df["dt"].dt.weekday
    df["minute"] = df["dt"].dt.minute

    for h in range(1, 9):
        fwd = df["close"].shift(-h) / df["close"] - 1.0
        valida = (df["epoch"].shift(-h) - df["epoch"]) == h * 900
        df[f"fwd_{h}"] = np.where(valida, fwd, np.nan)

    for L in (1, 2, 4, 8, 16):
        df[f"ret_{L}"] = df["close"] / df["close"].shift(L) - 1.0

    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum((df["high"] - df["close"].shift(1)).abs(),
                   (df["low"] - df["close"].shift(1)).abs()),
    )
    df["atr14"] = tr.rolling(14).mean()
    df["atr_pct"] = df["atr14"] / df["close"]
    df["atr_rank"] = df["atr_pct"].rolling(500, min_periods=100).rank(pct=True)
    df["atr_ratio"] = df["atr14"] / df["atr14"].shift(4)

    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["body_ratio"] = ((df["close"] - df["open"]) / rng).fillna(0.0)
    df["range_atr"] = (df["high"] - df["low"]) / df["atr14"]

    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = (-delta).clip(lower=0)
    ru = up.ewm(alpha=1 / 14, adjust=False).mean()
    rd = down.ewm(alpha=1 / 14, adjust=False).mean()
    rs = ru / rd.replace(0, np.nan)
    df["rsi14"] = 100.0 - 100.0 / (1.0 + rs)

    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema50_dist"] = (df["close"] - df["ema50"]) / df["atr14"]
    df["ema20_slope"] = (df["ema20"] - df["ema20"].shift(4)) / df["atr14"]

    return df


def evaluar(df, mask, dirs, h, payout, rng, B=2000, min_n=50):
    mask = np.asarray(mask, dtype=bool)
    dirs = np.asarray(dirs, dtype=float)
    ret = df[f"fwd_{h}"].to_numpy(dtype=float)
    valido = np.isfinite(ret) & (dirs != 0)
    sel = mask & valido
    n = int(sel.sum())
    if n < min_n:
        return None
    r = ret[sel]
    d = np.sign(dirs[sel])
    win = (r * d > 0)
    k = int(win.sum())
    wr = 100.0 * k / n
    lo, hi = wilson(k, n)
    be = 100.0 / (1.0 + payout)
    z = (wr - be) / 100.0 * math.sqrt(n) / math.sqrt(be / 100.0 * (1 - be / 100.0))
    p = norm_sf(z)

    dias = df["day"].to_numpy()[sel]
    uniq, inv = np.unique(dias, return_inverse=True)
    day_n = np.bincount(inv, minlength=len(uniq)).astype(float)
    day_w = np.bincount(inv, weights=win.astype(float), minlength=len(uniq))
    idx = rng.integers(0, len(uniq), size=(B, len(uniq)))
    num = day_w[idx].sum(axis=1)
    den = day_n[idx].sum(axis=1)
    wr_boot = num / den
    ev_boot = payout * wr_boot - (1.0 - wr_boot)
    ev = payout * (k / n) - (1.0 - k / n)
    return {
        "n": n,
        "dias": len(uniq),
        "wins": k,
        "wr": wr,
        "wr_lo": lo,
        "wr_hi": hi,
        "be": be,
        "payout": 100.0 * payout,
        "ev": 100.0 * ev,
        "ev_boot_lo": 100.0 * float(np.percentile(ev_boot, 2.5)),
        "ev_boot_hi": 100.0 * float(np.percentile(ev_boot, 97.5)),
        "p": p,
    }


def condiciones(df):
    """Devuelve (familia, nombre, mask, dirs) con dirs fijo +1/-1 o por barra."""
    n = len(df)
    out = []

    # --- calendario: hora UTC, largo y corto ---
    for hora in range(24):
        m = (df["hour"] == hora).to_numpy()
        if m.sum() < 100:
            continue
        for d in (1, -1):
            out.append(("calendario", f"hora_{hora:02d}_{'L' if d>0 else 'S'}",
                        m, np.full(n, d)))

    # --- dia de la semana ---
    for wd, nombre in enumerate(("lun", "mar", "mie", "jue", "vie")):
        m = (df["weekday"] == wd).to_numpy()
        if m.sum() < 100:
            continue
        for d in (1, -1):
            out.append(("calendario", f"{nombre}_{'L' if d>0 else 'S'}",
                        m, np.full(n, d)))

    # --- momentum / reversion ---
    for L in (1, 2, 4, 8, 16):
        r = df[f"ret_{L}"].to_numpy(dtype=float)
        valido = np.isfinite(r) & (r != 0)
        signo = np.sign(r)
        for estrategia, dirs in (("mom", signo), ("rev", -signo)):
            m = valido
            out.append(("momentum", f"{estrategia}_{L}", m, dirs))

    # --- RSI buckets y estrategia de extremos ---
    rsi = df["rsi14"].to_numpy(dtype=float)
    buckets = [
        ("rsi_lt30", rsi < 30),
        ("rsi_30_45", (rsi >= 30) & (rsi < 45)),
        ("rsi_45_55", (rsi >= 45) & (rsi < 55)),
        ("rsi_55_70", (rsi >= 55) & (rsi < 70)),
        ("rsi_gt70", rsi > 70),
    ]
    for nombre, m in buckets:
        for d in (1, -1):
            out.append(("rsi", f"{nombre}_{'L' if d>0 else 'S'}", m, np.full(n, d)))
    dirs_mr = np.where(rsi < 30, 1, np.where(rsi > 70, -1, 0))
    dirs_tf = -dirs_mr
    out.append(("rsi", "rsi_reversion", np.isfinite(rsi), dirs_mr))
    out.append(("rsi", "rsi_tendencia", np.isfinite(rsi), dirs_tf))

    # --- volatilidad ---
    rank = df["atr_rank"].to_numpy(dtype=float)
    buckets = [
        ("atr_bajo", rank < 1 / 3),
        ("atr_medio", (rank >= 1 / 3) & (rank < 2 / 3)),
        ("atr_alto", rank >= 2 / 3),
    ]
    for nombre, m in buckets:
        for d in (1, -1):
            out.append(("volatilidad", f"{nombre}_{'L' if d>0 else 'S'}", m, np.full(n, d)))
    ratio = df["atr_ratio"].to_numpy(dtype=float)
    for nombre, m in (
        ("atr_expande", ratio > 1.1),
        ("atr_neutral", (ratio >= 0.9) & (ratio <= 1.1)),
        ("atr_comprime", ratio < 0.9),
    ):
        for d in (1, -1):
            out.append(("volatilidad", f"{nombre}_{'L' if d>0 else 'S'}", m, np.full(n, d)))

    # --- EMA50 distancia y tendencia ---
    dist = df["ema50_dist"].to_numpy(dtype=float)
    buckets = [
        ("ema_lt_m2", dist < -2),
        ("ema_m2_m1", (dist >= -2) & (dist < -1)),
        ("ema_m1_1", (dist >= -1) & (dist <= 1)),
        ("ema_1_2", (dist > 1) & (dist <= 2)),
        ("ema_gt_2", dist > 2),
    ]
    for nombre, m in buckets:
        for d in (1, -1):
            out.append(("ema", f"{nombre}_{'L' if d>0 else 'S'}", m, np.full(n, d)))
    out.append(("ema", "ema_tendencia", np.isfinite(dist), np.sign(dist)))
    out.append(("ema", "ema_reversion", np.isfinite(dist), -np.sign(dist)))

    # --- cuerpo / rango ---
    body = df["body_ratio"].to_numpy(dtype=float)
    for nombre, m in (
        ("body_bajo", body < 1 / 3),
        ("body_medio", (body >= 1 / 3) & (body < 2 / 3)),
        ("body_alto", body >= 2 / 3),
    ):
        for d in (1, -1):
            out.append(("cuerpo", f"{nombre}_{'L' if d>0 else 'S'}", m, np.full(n, d)))
    rng_atr = df["range_atr"].to_numpy(dtype=float)
    for nombre, m in (
        ("rango_bajo", rng_atr < 0.8),
        ("rango_medio", (rng_atr >= 0.8) & (rng_atr <= 1.2)),
        ("rango_alto", rng_atr > 1.2),
    ):
        for d in (1, -1):
            out.append(("cuerpo", f"{nombre}_{'L' if d>0 else 'S'}", m, np.full(n, d)))

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--m15", default="")
    ap.add_argument("--split", default="2026-10-01")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()

    sym = args.symbol.upper()
    path = args.m15 or f"data/{sym.lower()}_M15.csv"
    df = cargar_m15(path)
    payout = PAYOUT[sym]
    rng = np.random.default_rng(20261107)

    desc = df[df["date"] < args.split].reset_index(drop=True)
    hold = df[df["date"] >= args.split].reset_index(drop=True)
    print(f"===== {sym} | velas M15 | descubrimiento {len(desc)} | holdout {len(hold)} =====")
    print(f"rango: {df['date'].min()} a {df['date'].max()}")

    todas = []
    for familia, nombre, mask, dirs in condiciones(desc):
        for h in (1, 2, 3, 4):
            res = evaluar(desc, mask, dirs, h, payout[h - 1], rng, args.bootstrap)
            if res is None:
                continue
            todas.append({"symbol": sym, "familia": familia, "condicion": nombre,
                          "horizonte": h, **res})

    prim = todas
    qs = bh_qvalues([r["p"] for r in prim])
    for r, qv in zip(prim, qs):
        r["q"] = qv
    for r in prim:
        r["criterio"] = int(r["n"] >= 100 and r["q"] <= 0.10
                            and r["wr_lo"] > r["be"] and r["ev_boot_lo"] > 0)

    prim.sort(key=lambda r: r["p"])
    print(f"\ntests: {len(prim)} | supervivientes estrictos: {sum(r['criterio'] for r in prim)}")
    print(f"{'familia':12s} {'condicion':22s} h  n     WR     IC95          EV%     boot95          p       q")
    for r in prim[:25]:
        print(f"{r['familia']:12s} {r['condicion'][:22]:22s} {r['horizonte']} "
              f"{r['n']:5d} {r['wr']:5.1f} {r['wr_lo']:5.1f}-{r['wr_hi']:5.1f} "
              f"{r['ev']:+6.2f} ({r['ev_boot_lo']:+6.2f},{r['ev_boot_hi']:+6.2f}) "
              f"{r['p']:.4f} {r['q']:.4f}")

    sobre = [r for r in prim if r["criterio"]]
    print(f"\nSupervivientes: {len(sobre)}")
    for r in sobre:
        print(f"  * {r['familia']} {r['condicion']} h{r['horizonte']} n={r['n']} "
              f"WR={r['wr']:.1f} EV={r['ev']:+.2f} q={r['q']:.4f}")

    # Holdout de los mejores por p (aunque no sobrevivan), sin reajustar nada
    print("\nHoldout de los 12 mejores por p (informativo, no seleccion):")
    for r in prim[:12]:
        # reconstruir la condicion en holdout
        familia, nombre = r["familia"], r["condicion"]
        elegido = None
        for fam, nom, mask, dirs in condiciones(hold):
            if fam == familia and nom == nombre:
                elegido = (mask, dirs)
                break
        if elegido is None:
            continue
        res = evaluar(hold, elegido[0], elegido[1], r["horizonte"],
                      payout[r["horizonte"] - 1], rng, args.bootstrap)
        if res is None:
            continue
        print(f"  {nombre:22s} h{r['horizonte']} n={res['n']:4d} WR={res['wr']:5.1f} "
              f"EV={res['ev']:+6.2f} boot=[{res['ev_boot_lo']:+6.2f},{res['ev_boot_hi']:+6.2f}]")

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"bar_edge_{sym.lower()}.csv")
    campos = ["symbol", "familia", "condicion", "horizonte", "n", "dias", "wins",
              "wr", "wr_lo", "wr_hi", "be", "payout", "ev", "ev_boot_lo",
              "ev_boot_hi", "p", "q", "criterio"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in prim:
            w.writerow(r)
    print(f"\nGuardado {out}")


if __name__ == "__main__":
    main()
