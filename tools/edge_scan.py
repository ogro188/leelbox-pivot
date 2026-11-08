#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Screening univariado pre-registrado con control de multiplicidad.

Para cada condicion (hipotesis H1-H8) y horizonte h1-h8 calcula:
  - n, winrate, IC95 de Wilson,
  - EV binario con payout configurable (por defecto 85%),
  - p-valor unilateral contra el break-even,
  - block bootstrap por dia del EV (2000 remuestreos),
  - sensibilidad del EV a payout -3/+3 pp.

Aplica Benjamini-Hochberg (FDR 10%) sobre la familia primaria h1-h4.

Uso:
  python3 edge_scan.py --inputs out/eurusd_signals.csv out/xauusd_signals.csv
"""
import argparse
import csv
import json
import math
import os
import random
import sys
from collections import defaultdict

import numpy as np

PRIMARY_H = (1, 2, 3, 4)
EXPLOR_H = (5, 6, 7, 8)
Z95 = 1.959963984540054


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
    """Devuelve q-values BH y el conjunto de rechazos a q<=alpha."""
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


def afloat(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def aint(v):
    x = afloat(v)
    return int(x) if x is not None else None


def sgn(x):
    if x is None:
        return 0
    return 1 if x > 0 else (-1 if x < 0 else 0)


def conv_num(v):
    if v in (None, ""):
        return None
    m = {"BAJA": 0, "MEDIA": 1, "ALTA": 2}
    if isinstance(v, str) and v.upper() in m:
        return m[v.upper()]
    try:
        return int(float(v))
    except ValueError:
        return None


def cargar(paths):
    filas = []
    vistos = set()
    for path in paths:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["symbol"] = r.get("symbol") or os.path.basename(path).split("_")[0].upper()
                rid = r.get("id")
                if rid:
                    clave = (r["symbol"], str(rid))
                    if clave in vistos:
                        continue
                    vistos.add(clave)
                filas.append(r)
    return filas


def filtrar_fechas(filas, desde=None, hasta=None):
    """Filtra por date (YYYY-MM-DD). hasta es exclusivo."""
    out = []
    for r in filas:
        d = (r.get("date") or (r.get("entry_time") or "")[:10])
        if desde and d < desde:
            continue
        if hasta and d >= hasta:
            continue
        out.append(r)
    return out


def preparar(filas):
    """Convierte tipos y agrega columnas derivadas por fila."""
    for r in filas:
        d = aint(r.get("direction"))
        r["_dir"] = d if d in (1, -1) else 0
        r["_date"] = r.get("date") or (r.get("entry_time") or "")[:10]
        r["_conv"] = conv_num(r.get("conviccion"))
        r["_h4_ema"] = sgn(afloat(r.get("ctx_h4_ema20_vs_50_atr")))
        r["_h1_ema"] = sgn(afloat(r.get("ctx_h1_ema20_vs_50_atr")))
        r["_h1_dist"] = sgn(afloat(r.get("ctx_h1_ema20_dist_atr")))
        r["_pos50"] = afloat(r.get("ctx_h4_pos50"))
        r["_trend_d1"] = (r.get("trend_d1") or "").upper()
        r["_est_dir"] = (r.get("ctx_estructura_dir") or "").upper()
        r["_est_val"] = aint(r.get("ctx_estructura_valida")) or 0
        r["_session"] = (r.get("session") or "").upper()
        r["_hour"] = aint(r.get("ctx_hour"))
        r["_weekday"] = aint(r.get("ctx_weekday"))
        r["_det"] = (r.get("detector") or "").upper()
        r["_tipo"] = (r.get("tipo") or "").upper()
        # conteo de senales en la misma vela
    por_vela = defaultdict(int)
    for r in filas:
        por_vela[(r["symbol"], r.get("entry_time"))] += 1
    for r in filas:
        r["_n_vela"] = por_vela[(r["symbol"], r.get("entry_time"))]


def terciles(filas, campo):
    vals = sorted(v for v in (afloat(r.get(campo)) for r in filas) if v is not None)
    if len(vals) < 30:
        return (None, None)
    return (vals[len(vals) // 3], vals[2 * len(vals) // 3])


def condiciones(filas):
    """Lista de (hipotesis, nombre, funcion). Pre-registrada antes de mirar EV."""
    conds = []

    def add(hip, nombre, fn):
        conds.append((hip, nombre, fn))

    # --- H1: alineacion H4
    add("H1", "h4_alineado", lambda r: r["_dir"] != 0 and r["_h4_ema"] == r["_dir"])
    add("H1", "h4_contra", lambda r: r["_dir"] != 0 and r["_h4_ema"] == -r["_dir"])
    add("H1", "h4_plano", lambda r: r["_h4_ema"] == 0)

    # --- H2: alineacion H1
    add("H2", "h1_alineado", lambda r: r["_dir"] != 0 and r["_h1_ema"] == r["_dir"])
    add("H2", "h1_contra", lambda r: r["_dir"] != 0 and r["_h1_ema"] == -r["_dir"])
    add("H2", "h1_precio_alineado", lambda r: r["_dir"] != 0 and r["_h1_dist"] == r["_dir"])
    add("H2", "h4_y_h1_alineados", lambda r: r["_dir"] != 0 and r["_h4_ema"] == r["_dir"] and r["_h1_ema"] == r["_dir"])

    # --- H3: pullback dentro de tendencia H4
    add("H3", "h4_pullback", lambda r: (
        r["_dir"] != 0 and r["_h4_ema"] == r["_dir"] and r["_pos50"] is not None and (
            (r["_dir"] == 1 and r["_pos50"] < 0.5) or (r["_dir"] == -1 and r["_pos50"] > 0.5)
        )
    ))
    add("H3", "h4_extension", lambda r: (
        r["_dir"] != 0 and r["_h4_ema"] == r["_dir"] and r["_pos50"] is not None and (
            (r["_dir"] == 1 and r["_pos50"] > 0.8) or (r["_dir"] == -1 and r["_pos50"] < 0.2)
        )
    ))
    add("H3", "pullback_estructura", lambda r: (
        r["_dir"] != 0 and r["_h4_ema"] == r["_dir"] and r["_est_dir"] == ("ALCISTA" if r["_dir"] == 1 else "BAJISTA")
        and r["_pos50"] is not None and (
            (r["_dir"] == 1 and r["_pos50"] < 0.5) or (r["_dir"] == -1 and r["_pos50"] > 0.5)
        )
    ))

    # --- D1 / estructura
    add("H3", "d1_alineado", lambda r: (
        (r["_dir"] == 1 and r["_trend_d1"] == "ALCISTA") or (r["_dir"] == -1 and r["_trend_d1"] == "BAJISTA")
    ))
    add("H3", "d1_contra", lambda r: (
        (r["_dir"] == 1 and r["_trend_d1"] == "BAJISTA") or (r["_dir"] == -1 and r["_trend_d1"] == "ALCISTA")
    ))
    add("H3", "estructura_alineada", lambda r: (
        r["_dir"] != 0 and r["_est_val"] == 1 and r["_est_dir"] == ("ALCISTA" if r["_dir"] == 1 else "BAJISTA")
    ))
    add("H3", "estructura_contra", lambda r: (
        r["_dir"] != 0 and r["_est_val"] == 1 and r["_est_dir"] == ("BAJISTA" if r["_dir"] == 1 else "ALCISTA")
    ))
    add("H3", "sin_estructura", lambda r: r["_est_val"] == 0)

    # --- H4: regimen de volatilidad (terciles)
    lo_atr, hi_atr = terciles(filas, "ctx_atr14_30")
    if lo_atr is not None:
        add("H4", "vol_baja", lambda r, lo=lo_atr: (afloat(r.get("ctx_atr14_30")) is not None and afloat(r.get("ctx_atr14_30")) <= lo))
        add("H4", "vol_alta", lambda r, hi=hi_atr: (afloat(r.get("ctx_atr14_30")) is not None and afloat(r.get("ctx_atr14_30")) > hi))
    lo_rng, hi_rng = terciles(filas, "ctx_h4_range_atr")
    if lo_rng is not None:
        add("H4", "rango_h4_bajo", lambda r, lo=lo_rng: (afloat(r.get("ctx_h4_range_atr")) is not None and afloat(r.get("ctx_h4_range_atr")) <= lo))
        add("H4", "rango_h4_alto", lambda r, hi=hi_rng: (afloat(r.get("ctx_h4_range_atr")) is not None and afloat(r.get("ctx_h4_range_atr")) > hi))

    # --- H5: extension M15
    add("H5", "ema50_cerca", lambda r: (afloat(r.get("ctx_ema50_dist_atr")) is not None and abs(afloat(r.get("ctx_ema50_dist_atr"))) <= 0.5))
    add("H5", "ema50_lejos", lambda r: (afloat(r.get("ctx_ema50_dist_atr")) is not None and abs(afloat(r.get("ctx_ema50_dist_atr"))) > 1.5))
    add("H5", "rsi_no_extremo", lambda r: (
        r["_dir"] != 0 and afloat(r.get("ctx_rsi14")) is not None and (
            (r["_dir"] == 1 and 30 <= afloat(r.get("ctx_rsi14")) < 70) or
            (r["_dir"] == -1 and 30 < afloat(r.get("ctx_rsi14")) <= 70)
        )
    ))
    add("H5", "rsi_extremo_contra", lambda r: (
        r["_dir"] != 0 and afloat(r.get("ctx_rsi14")) is not None and (
            (r["_dir"] == 1 and afloat(r.get("ctx_rsi14")) >= 70) or
            (r["_dir"] == -1 and afloat(r.get("ctx_rsi14")) <= 30)
        )
    ))

    # --- H6: confluencia / calidad
    add("H6", "conviccion_media_alta", lambda r: (r["_conv"] is not None and r["_conv"] >= 1))
    add("H6", "dos_o_mas_vela", lambda r: r["_n_vela"] >= 2)
    for campo, nombre in (
        ("conf_completa", "conf_completa"),
        ("calidad_sweep", "calidad_sweep"),
        ("contexto_estructural", "contexto_estructural"),
        ("salud_tendencial", "salud_tendencial"),
        ("ctx_g1", "g1_compresion"),
        ("ctx_g4", "g4_agotamiento"),
        ("spread_pips", "spread"),
    ):
        lo, hi = terciles(filas, campo)
        if lo is None:
            continue
        if nombre == "spread":
            add("H6", "spread_bajo", lambda r, lo=lo, c=campo: (afloat(r.get(c)) is not None and afloat(r.get(c)) <= lo))
        else:
            add("H6", f"{nombre}_alto", lambda r, hi=hi, c=campo: (afloat(r.get(c)) is not None and afloat(r.get(c)) > hi))
            add("H6", f"{nombre}_bajo", lambda r, lo=lo, c=campo: (afloat(r.get(c)) is not None and afloat(r.get(c)) <= lo))

    # --- H7: sesion / horario
    for ses in sorted({r["_session"] for r in filas if r["_session"]}):
        add("H7", f"sesion_{ses.lower()}", lambda r, s=ses: r["_session"] == s)
    add("H7", "hora_00_06", lambda r: r["_hour"] is not None and 0 <= r["_hour"] < 7)
    add("H7", "hora_07_11", lambda r: r["_hour"] is not None and 7 <= r["_hour"] < 12)
    add("H7", "hora_12_17", lambda r: r["_hour"] is not None and 12 <= r["_hour"] < 18)
    add("H7", "hora_18_23", lambda r: r["_hour"] is not None and 18 <= r["_hour"] <= 23)
    add("H7", "lunes_viernes", lambda r: r["_weekday"] is not None and 0 <= r["_weekday"] <= 4)

    # --- H8: detector (la expiracion se evalua como horizonte)
    for det in sorted({r["_det"] for r in filas if r["_det"]}):
        add("H8", f"det_{det.lower()}", lambda r, d=det: r["_det"] == d)
    for tipo in sorted({r["_tipo"] for r in filas if r["_tipo"]}):
        add("H8", f"tipo_{tipo.lower()}", lambda r, t=tipo: r["_tipo"] == t)

    return conds


def evaluar(filas, cond, h, payout, rng, B=2000):
    sel = [r for r in filas if cond(r)]
    datos = []
    for r in sel:
        win = aint(r.get(f"win_h{h}"))
        if win is None:
            continue
        datos.append((r["_date"], win))
    n = len(datos)
    if n < 30:
        return None
    k = sum(w for _, w in datos)
    wr = 100.0 * k / n
    lo, hi = wilson(k, n)
    be = 100.0 / (1.0 + payout)
    z = (wr - be) / 100.0 * math.sqrt(n) / math.sqrt(be / 100.0 * (1 - be / 100.0))
    p = norm_sf(z)

    dias = defaultdict(lambda: [0, 0])  # dia -> [n, wins]
    for d, w in datos:
        dias[d][0] += 1
        dias[d][1] += w
    day_n = np.array([v[0] for v in dias.values()], dtype=float)
    day_w = np.array([v[1] for v in dias.values()], dtype=float)
    nd = len(day_n)
    idx = rng.integers(0, nd, size=(B, nd))
    num = day_w[idx].sum(axis=1)
    den = day_n[idx].sum(axis=1)
    wr_boot = num / den
    ev_boot = payout * wr_boot - (1.0 - wr_boot)
    ev = payout * (k / n) - (1.0 - k / n)
    ev_lo = float(np.percentile(ev_boot, 2.5))
    ev_hi = float(np.percentile(ev_boot, 97.5))
    return {
        "n": n,
        "dias": nd,
        "wins": k,
        "wr": wr,
        "wr_lo": lo,
        "wr_hi": hi,
        "be": be,
        "payout": 100.0 * payout,
        "ev": 100.0 * ev,
        "ev_boot_lo": 100.0 * ev_lo,
        "ev_boot_hi": 100.0 * ev_hi,
        "ev_payout_m3": 100.0 * ((payout - 0.03) * (k / n) - (1 - k / n)),
        "ev_payout_p3": 100.0 * ((payout + 0.03) * (k / n) - (1 - k / n)),
        "p": p,
    }


def escanear(filas, etiqueta, payout, q=0.10, B=2000, payouts_by_h=None):
    conds = condiciones(filas)
    resultados = []
    rng = np.random.default_rng(20261106)
    for hip, nombre, fn in conds:
        for h in PRIMARY_H + EXPLOR_H:
            pago_h = payouts_by_h[h - 1] if (payouts_by_h and h <= len(payouts_by_h)) else payout
            res = evaluar(filas, fn, h, pago_h, rng, B)
            if res is None:
                continue
            resultados.append({"symbol": etiqueta, "hipotesis": hip, "condicion": nombre, "horizonte": h, **res})

    prim = [r for r in resultados if r["horizonte"] in PRIMARY_H]
    qs = bh_qvalues([r["p"] for r in prim])
    for r, qv in zip(prim, qs):
        r["q"] = qv
    for r in resultados:
        r.setdefault("q", None)

    for r in resultados:
        r["_fam"] = (r["symbol"], r["horizonte"] in PRIMARY_H)
        r["familia"] = "primaria" if r["horizonte"] in PRIMARY_H else "exploratoria"
        r["criterio"] = int(
            r["familia"] == "primaria"
            and r["n"] >= 100
            and r["q"] is not None and r["q"] <= q
            and r["wr_lo"] > r["be"]
            and r["ev_boot_lo"] > 0
        )
    return resultados


def escribir(resultados, path):
    campos = [
        "symbol", "hipotesis", "condicion", "horizonte", "familia", "n", "dias", "wins",
        "wr", "wr_lo", "wr_hi", "be", "payout", "ev", "ev_boot_lo", "ev_boot_hi",
        "ev_payout_m3", "ev_payout_p3", "p", "q", "criterio",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        for r in sorted(resultados, key=lambda x: (x["horizonte"], x["p"])):
            w.writerow({k: (round(r[k], 4) if isinstance(r.get(k), float) else r.get(k)) for k in campos})


def imprimir(resultados, etiqueta, top=25):
    prim = [r for r in resultados if r["familia"] == "primaria"]
    prim.sort(key=lambda r: r["p"])
    print(f"\n===== {etiqueta} | familia primaria h1-h4 (FDR 10%) =====")
    print(f"{'cond':34s} h  n    WR     IC95          EV%    boot95        q      p")
    for r in prim[:top]:
        print(
            f"{r['condicion'][:34]:34s} {r['horizonte']} {r['n']:5d} "
            f"{r['wr']:5.1f} {r['wr_lo']:5.1f}-{r['wr_hi']:5.1f} "
            f"{r['ev']:+6.2f} ({r['ev_boot_lo']:+6.2f},{r['ev_boot_hi']:+6.2f}) "
            f"{r['q']:.4f} {r['p']:.2e}"
        )
    sobre = [r for r in resultados if r["criterio"]]
    print(f"\nSobrevivientes estrictos: {len(sobre)}")
    for r in sobre:
        print(
            f"  {r['hipotesis']} {r['condicion']:32s} h{r['horizonte']} "
            f"n={r['n']} WR={r['wr']:.1f} IC={r['wr_lo']:.1f}-{r['wr_hi']:.1f} "
            f"EV={r['ev']:+.2f}% boot=[{r['ev_boot_lo']:+.2f},{r['ev_boot_hi']:+.2f}] q={r['q']:.3f}"
        )
    exp = [r for r in resultados if r["familia"] == "exploratoria"]
    exp.sort(key=lambda r: r["p"])
    if exp:
        print("\nExploratorio h5-h8 (top 8, sin FDR):")
        for r in exp[:8]:
            print(
                f"  {r['condicion'][:34]:34s} h{r['horizonte']} n={r['n']} "
                f"WR={r['wr']:.1f} IC={r['wr_lo']:.1f}-{r['wr_hi']:.1f} EV={r['ev']:+.2f}%"
            )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inputs", nargs="+", required=True)
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--payout", type=float, default=0.85, help="payout base 0-1")
    ap.add_argument("--payouts-by-h", default="",
                    help="8 payouts 0-1 separados por coma para h1..h8; sobreescribe --payout")
    ap.add_argument("--q", type=float, default=0.10)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--desde", default="", help="fecha inicio YYYY-MM-DD (inclusive)")
    ap.add_argument("--hasta", default="", help="fecha fin YYYY-MM-DD (exclusiva)")
    ap.add_argument("--tag", default="", help="sufijo para los archivos de salida")
    args = ap.parse_args()

    payouts_by_h = None
    if args.payouts_by_h:
        payouts_by_h = [float(x) for x in args.payouts_by_h.split(",") if x.strip()]
        if len(payouts_by_h) != 8:
            raise SystemExit("--payouts-by-h necesita exactamente 8 valores")

    filas = cargar(args.inputs)
    if args.desde or args.hasta:
        filas = filtrar_fechas(filas, args.desde or None, args.hasta or None)
    preparar(filas)
    os.makedirs(args.out_dir, exist_ok=True)
    sufijo = f"_{args.tag}" if args.tag else ""

    todos = []
    por_symbol = defaultdict(list)
    for r in filas:
        por_symbol[r["symbol"]].append(r)
    for sym, grupo in sorted(por_symbol.items()):
        res = escanear(grupo, sym, args.payout, args.q, args.bootstrap, payouts_by_h)
        imprimir(res, sym)
        todos.extend(res)
        escribir(res, os.path.join(args.out_dir, f"edge_scan_{sym.lower()}{sufijo}.csv"))

    if len(por_symbol) > 1:
        res = escanear(filas, "POOL", args.payout, args.q, args.bootstrap, payouts_by_h)
        imprimir(res, "POOL")
        todos.extend(res)
        escribir(res, os.path.join(args.out_dir, f"edge_scan_pool{sufijo}.csv"))

    escribir(todos, os.path.join(args.out_dir, f"edge_scan_all{sufijo}.csv"))
    with open(os.path.join(args.out_dir, f"edge_scan_resumen{sufijo}.json"), "w", encoding="utf-8") as f:
        json.dump({
            "n_filas": len(filas),
            "desde": args.desde or None,
            "hasta": args.hasta or None,
            "por_symbol": {s: len(g) for s, g in por_symbol.items()},
            "payout": args.payout,
            "payouts_by_h": payouts_by_h,
            "q": args.q,
            "tests": len(todos),
            "sobrevivientes": [
                {k: r[k] for k in ("symbol", "hipotesis", "condicion", "horizonte", "n", "wr", "wr_lo", "ev", "ev_boot_lo", "q")}
                for r in todos if r["criterio"]
            ],
        }, f, ensure_ascii=False, indent=2)
    print(f"\nGuardado en {args.out_dir}/edge_scan_*.csv")


if __name__ == "__main__":
    main()
