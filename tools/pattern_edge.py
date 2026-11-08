#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Patrones intradia con mecanismo explicito, sobre velas M15.

Familias:
  - ARB: ruptura del rango asiatico (00:00-06:45 UTC) en Londres (07:00-10:45).
  - LOR: ruptura del opening range de Londres (07:00-07:45 / 07:00-08:00).
  - NYOR: ruptura del opening range de Nueva York (12:00-12:45 / 13:00-13:45).
  - SWEEP: falso breakout de 20 velas (barrido y retorno) y breakout exitoso.
  - CLOSE: momentum de cierre (close_pos y rango/ATR).
  - PDH: ruptura del maximo/minimo del dia anterior en Londres.

Entrada: open de la vela siguiente a la senal (sin look-ahead).
Salida: close de la vela t+h (h=1..8).
Protocolo: descubrimiento -> validacion -> test; BH-FDR en descubrimiento.
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
    "EURUSD": [0.85, 0.86, 0.86, 0.87, 0.87, 0.87, 0.87, 0.87],
    "XAUUSD": [0.81, 0.82, 0.82, 0.83, 0.83, 0.83, 0.83, 0.83],
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


def cargar(path):
    df = pd.read_csv(path)
    df["dt"] = pd.to_datetime(df["datetime"], utc=True)
    df = df.sort_values("epoch").reset_index(drop=True)
    df["day"] = df["dt"].dt.strftime("%Y-%m-%d")
    df["hour"] = df["dt"].dt.hour
    df["minute"] = df["dt"].dt.minute
    tr = np.maximum(
        df["high"] - df["low"],
        np.maximum((df["high"] - df["close"].shift(1)).abs(),
                   (df["low"] - df["close"].shift(1)).abs()),
    )
    df["atr14"] = tr.rolling(14).mean()
    df["range_atr"] = (df["high"] - df["low"]) / df["atr14"]
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    df["close_pos"] = ((df["close"] - df["low"]) / rng).fillna(0.5)
    df["prior_high20"] = df["high"].shift(1).rolling(20).max()
    df["prior_low20"] = df["low"].shift(1).rolling(20).min()
    df["prev_day_high"] = df.groupby("day")["high"].transform("max").shift(1)
    df["prev_day_low"] = df.groupby("day")["low"].transform("min").shift(1)
    # Ojo: prev_day_high/low con shift(1) global no alinea por dia; se corrige abajo.
    df["prev_day_high"] = np.nan
    df["prev_day_low"] = np.nan
    dias = df["day"].unique()
    for i in range(1, len(dias)):
        d, ant = dias[i], dias[i - 1]
        m = df["day"] == d
        a = df["day"] == ant
        df.loc[m, "prev_day_high"] = df.loc[a, "high"].max()
        df.loc[m, "prev_day_low"] = df.loc[a, "low"].min()
    return df


def eventos_arb(df):
    """Ruptura del rango asiatico en la sesion de Londres."""
    out = []
    for dia, g in df.groupby("day", sort=True):
        asi = g[(g["hour"] >= 0) & (g["hour"] < 7)]
        lon = g[(g["hour"] >= 7) & (g["hour"] < 11)]
        if len(asi) < 20 or len(lon) < 4:
            continue
        hi, lo = asi["high"].max(), asi["low"].min()
        atr = float(lon["atr14"].iloc[0])
        if not np.isfinite(atr) or atr <= 0:
            continue
        ancho = (hi - lo) / atr
        for _, row in lon.iterrows():
            if row["close"] > hi:
                out.append((int(row.name), 1, "ARB", ancho, "break"))
                break
            if row["close"] < lo:
                out.append((int(row.name), -1, "ARB", ancho, "break"))
                break
    return out


def eventos_or(df, h0, h1, b0, b1, nombre):
    """Opening range [h0,h1) y ruptura en [b0,b1)."""
    out = []
    for dia, g in df.groupby("day", sort=True):
        rg = g[(g["hour"] >= h0) & (g["hour"] < h1)]
        br = g[(g["hour"] >= b0) & (g["hour"] < b1)]
        if len(rg) < 2 or len(br) < 2:
            continue
        hi, lo = rg["high"].max(), rg["low"].min()
        atr = float(br["atr14"].iloc[0])
        if not np.isfinite(atr) or atr <= 0:
            continue
        ancho = (hi - lo) / atr
        for _, row in br.iterrows():
            if row["close"] > hi:
                out.append((int(row.name), 1, nombre, ancho, "break"))
                break
            if row["close"] < lo:
                out.append((int(row.name), -1, nombre, ancho, "break"))
                break
    return out


def eventos_sweep(df):
    out = []
    hi = df["prior_high20"].to_numpy(dtype=float)
    lo = df["prior_low20"].to_numpy(dtype=float)
    h = df["high"].to_numpy(dtype=float)
    l = df["low"].to_numpy(dtype=float)
    c = df["close"].to_numpy(dtype=float)
    o = df["open"].to_numpy(dtype=float)
    rng = np.maximum(h - l, 1e-12)
    for i in range(len(df)):
        if not (np.isfinite(hi[i]) and np.isfinite(lo[i])):
            continue
        # barrido alcista fallido: mecha arriba y cierre de vuelta dentro
        if h[i] > hi[i] and c[i] < hi[i]:
            wick = (h[i] - max(o[i], c[i])) / rng[i]
            out.append((i, -1, "SWEEP", wick, "sweep"))
        # barrido bajista fallido
        elif l[i] < lo[i] and c[i] > lo[i]:
            wick = (min(o[i], c[i]) - l[i]) / rng[i]
            out.append((i, 1, "SWEEP", wick, "sweep"))
        # breakout exitoso (control)
        elif c[i] > hi[i]:
            out.append((i, 1, "SWEEP", 0.0, "breakout"))
        elif c[i] < lo[i]:
            out.append((i, -1, "SWEEP", 0.0, "breakout"))
    return out


def eventos_close(df):
    out = []
    cp = df["close_pos"].to_numpy(dtype=float)
    ra = df["range_atr"].to_numpy(dtype=float)
    for i in range(len(df)):
        if not (np.isfinite(ra[i]) and ra[i] > 1.0):
            continue
        if cp[i] > 0.8:
            out.append((i, 1, "CLOSE", cp[i], "momentum"))
        elif cp[i] < 0.2:
            out.append((i, -1, "CLOSE", cp[i], "momentum"))
    return out


def eventos_pdh(df):
    out = []
    for dia, g in df.groupby("day", sort=True):
        lon = g[(g["hour"] >= 7) & (g["hour"] < 11)]
        if len(lon) < 1:
            continue
        row = lon.iloc[0]
        hi, lo = row["prev_day_high"], row["prev_day_low"]
        if not (np.isfinite(hi) and np.isfinite(lo)):
            continue
        if row["close"] > hi:
            out.append((int(row.name), 1, "PDH", 0.0, "break"))
        elif row["close"] < lo:
            out.append((int(row.name), -1, "PDH", 0.0, "break"))
    return out


def construir_eventos(df, symbol):
    ev = []
    ev += eventos_arb(df)
    ev += eventos_or(df, 7, 8, 8, 11, "LOR3")
    ev += eventos_or(df, 7, 9, 8, 11, "LOR4")
    ev += eventos_or(df, 12, 13, 13, 16, "NYOR12")
    ev += eventos_or(df, 13, 14, 14, 17, "NYOR13")
    ev += eventos_sweep(df)
    ev += eventos_close(df)
    ev += eventos_pdh(df)
    return ev


def evaluar_eventos(df, eventos, h, payout, rng, B=2000, min_n=30):
    rows = []
    close = df["close"].to_numpy(dtype=float)
    openp = df["open"].to_numpy(dtype=float)
    epoch = df["epoch"].to_numpy(dtype=np.int64)
    n = len(df)
    for i, d, fam, extra, tipo in eventos:
        j = i + 1  # entrada al open siguiente
        k = i + h  # salida al close de t+h
        if j >= n or k >= n:
            continue
        if epoch[k] - epoch[j] != (h - 1) * 900:
            continue
        if not (np.isfinite(openp[j]) and np.isfinite(close[k])):
            continue
        ret = (close[k] - openp[j]) / openp[j]
        rows.append((d, ret, extra, tipo, df["day"].iloc[j]))
    if len(rows) < min_n:
        return None
    rets = np.array([r[1] for r in rows], dtype=float)
    dirs = np.array([r[0] for r in rows], dtype=float)
    win = (rets * dirs > 0)
    n = len(rows)
    k = int(win.sum())
    wr = 100.0 * k / n
    lo, hi = wilson(k, n)
    be = 100.0 / (1.0 + payout)
    z = (wr - be) / 100.0 * math.sqrt(n) / math.sqrt(be / 100.0 * (1 - be / 100.0))
    p = norm_sf(z)
    dias = np.array([r[4] for r in rows])
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
        "n": n, "dias": len(uniq), "wins": k, "wr": wr,
        "wr_lo": lo, "wr_hi": hi, "be": be, "payout": 100.0 * payout,
        "ev": 100.0 * ev,
        "ev_boot_lo": 100.0 * float(np.percentile(ev_boot, 2.5)),
        "ev_boot_hi": 100.0 * float(np.percentile(ev_boot, 97.5)),
        "p": p,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True)
    ap.add_argument("--m15", default="")
    ap.add_argument("--disc-hasta", default="2026-05-01")
    ap.add_argument("--val-hasta", default="2026-08-01")
    ap.add_argument("--bootstrap", type=int, default=1000)
    ap.add_argument("--out-dir", default="results")
    args = ap.parse_args()

    sym = args.symbol.upper()
    path = args.m15 or f"data/{sym.lower()}_M15.csv"
    df = cargar(path)
    print(f"===== {sym} | patrones M15 | {df['day'].min()} a {df['day'].max()} | {len(df)} velas =====")
    eventos = construir_eventos(df, sym)
    print(f"eventos base: {len(eventos)}")

    payout = PAYOUT[sym]
    rng = np.random.default_rng(20261107)

    # Solo eventos con vela siguiente disponible
    eventos = [e for e in eventos if e[0] + 1 < len(df)]

    # particion por dia del evento (entrada)
    desc = [e for e in eventos if df["day"].iloc[e[0] + 1] < args.disc_hasta]
    val = [e for e in eventos if args.disc_hasta <= df["day"].iloc[e[0] + 1] < args.val_hasta]
    test = [e for e in eventos if df["day"].iloc[e[0] + 1] >= args.val_hasta]
    print(f"eventos: descubrimiento={len(desc)} validacion={len(val)} test={len(test)}")

    # Agrupar por familia/tipo/lado/horizonte en lugar de evento individual:
    # el escaneo evento a evento seria demasiado fragmentado. Se agrupa por
    # (familia, tipo, lado, h) y se evalua el conjunto.
    grupos = defaultdict(list)
    for e in desc:
        i, d, fam, extra, tipo = e
        grupos[(fam, tipo, "base")].append((i, d, fam, extra, tipo))
        grupos[(fam, tipo, "fade")].append((i, -d, fam, extra, tipo))

    tests = []
    for (fam, tipo, lado), evs in grupos.items():
        for h in range(1, 9):
            res = evaluar_eventos(df, evs, h, payout[h - 1], rng, args.bootstrap)
            if res is None:
                continue
            tests.append({"symbol": sym, "familia": fam, "tipo": tipo, "lado": lado,
                          "horizonte": h, "eventos": len(evs), **res})

    # Subgrupos por ancho de rango (para ARB y OR): narrow/wide con umbral 1 ATR
    for (fam, tipo, lado), evs in list(grupos.items()):
        if fam not in ("ARB", "LOR3", "LOR4", "NYOR12", "NYOR13"):
            continue
        for nombre, cond in (("narrow", lambda x: x < 1.0), ("wide", lambda x: x >= 1.0)):
            sub = [e for e in evs if cond(e[3])]
            for h in (1, 2, 3, 4):
                res = evaluar_eventos(df, sub, h, payout[h - 1], rng, args.bootstrap)
                if res is None:
                    continue
                tests.append({"symbol": sym, "familia": fam, "tipo": f"{tipo}_{nombre}",
                              "lado": lado, "horizonte": h, "eventos": len(sub), **res})

    # FDR sobre todos los tests de descubrimiento
    qs = bh_qvalues([r["p"] for r in tests])
    for r, qv in zip(tests, qs):
        r["q"] = qv
        r["criterio"] = int(r["n"] >= 30 and r["q"] <= 0.10
                            and r["wr_lo"] > r["be"] and r["ev_boot_lo"] > 0)

    tests.sort(key=lambda r: r["p"])
    print(f"\ntests: {len(tests)} | supervivientes estrictos: {sum(r['criterio'] for r in tests)}")
    print(f"{'familia':8s} {'tipo':16s} {'lado':5s} h  n    WR     IC95          EV%     boot95          p       q")
    for r in tests[:30]:
        print(f"{r['familia']:8s} {r['tipo'][:16]:16s} {r['lado']:5s} {r['horizonte']} "
              f"{r['n']:4d} {r['wr']:5.1f} {r['wr_lo']:5.1f}-{r['wr_hi']:5.1f} "
              f"{r['ev']:+6.2f} ({r['ev_boot_lo']:+6.2f},{r['ev_boot_hi']:+6.2f}) "
              f"{r['p']:.4f} {r['q']:.4f}")

    sobre = [r for r in tests if r["criterio"]]
    print(f"\nSupervivientes: {len(sobre)}")
    for r in sobre:
        print(f"  * {r['familia']} {r['tipo']} {r['lado']} h{r['horizonte']} n={r['n']} "
              f"WR={r['wr']:.1f} EV={r['ev']:+.2f} q={r['q']:.4f}")

    # Validacion y test de los 20 mejores por p (informativo)
    print("\nValidacion/test de los 20 mejores por p (sin reajustar):")
    for r in tests[:20]:
        fam, tipo, lado, h = r["familia"], r["tipo"], r["lado"], r["horizonte"]
        # reconstruir subconjunto en val/test
        def subset(evs):
            out = []
            for e in evs:
                i, d, f, extra, t = e
                if f != fam:
                    continue
                if tipo.startswith(t + "_"):
                    cond = tipo.split("_", 1)[1]
                    if cond == "narrow" and not (extra < 1.0):
                        continue
                    if cond == "wide" and not (extra >= 1.0):
                        continue
                elif t != tipo:
                    continue
                out.append((i, d if lado == "base" else -d, f, extra, t))
            return out
        ev_val = subset(val)
        ev_test = subset(test)
        rv = evaluar_eventos(df, ev_val, h, payout[h - 1], rng, args.bootstrap)
        rt = evaluar_eventos(df, ev_test, h, payout[h - 1], rng, args.bootstrap)
        def fmt(x):
            if x is None:
                return "n<30"
            return f"n={x['n']:3d} WR={x['wr']:5.1f} EV={x['ev']:+6.2f}"
        print(f"  {fam:8s} {tipo:16s} {lado:5s} h{h} | val {fmt(rv)} | test {fmt(rt)}")

    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"pattern_edge_{sym.lower()}.csv")
    campos = ["symbol", "familia", "tipo", "lado", "horizonte", "eventos", "n", "dias",
              "wins", "wr", "wr_lo", "wr_hi", "be", "payout", "ev", "ev_boot_lo",
              "ev_boot_hi", "p", "q", "criterio"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in tests:
            w.writerow(r)
    print(f"\nGuardado {out}")


if __name__ == "__main__":
    main()
