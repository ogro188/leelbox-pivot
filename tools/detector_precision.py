#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auditoria de precision de los detectores PIVOT.

Mide dos cosas distintas:

1. Cumplimiento de reglas (deteccion vs reglas): ventanas de D1/D2/D5/D2A,
   geometria de D3, campos obligatorios y duplicados del mismo evento.
2. Precision predictiva (WR/EV): por detector, gate, horizonte y periodo
   (descubrimiento / holdout), con IC Wilson y bootstrap por dia.

No modifica produccion ni el motor. Solo lee `data/` y `results/` y escribe
en `--out-dir`.

Uso:
  python3 tools/detector_precision.py \
      --symbols eurusd,xauusd \
      --data-dir data --results-dir results \
      --out-dir results/detector_precision

Salidas:
  detector_precision_gates.csv    una fila por activo/detector/gate/h/periodo
  detector_precision_rules.json   cumplimiento de reglas y duplicados
  detector_precision_resumen.txt  resumen legible
"""
import argparse
import csv
import json
import math
import os

import numpy as np
import pandas as pd

Z = 1.959963984540054
PAYOUTS = {
    "eurusd": {1: 0.85, 2: 0.86, 3: 0.86, 4: 0.87},
    "xauusd": {1: 0.81, 2: 0.82, 3: 0.82, 4: 0.83},
}
TOL = 1e-9


# ---------------------------------------------------------------------------
# Carga y etiquetas
# ---------------------------------------------------------------------------
def cargar_m15(path):
    m = pd.read_csv(path, parse_dates=["datetime"])
    if m["datetime"].dt.tz is None:
        m["datetime"] = m["datetime"].dt.tz_localize("UTC")
    else:
        m["datetime"] = m["datetime"].dt.tz_convert("UTC")
    m = m.sort_values("datetime").drop_duplicates("datetime").set_index("datetime")
    return m


def cargar_senales(path):
    s = pd.read_csv(path)
    s["entry_time"] = pd.to_datetime(s["entry_time"], utc=True)
    s["_date"] = s["entry_time"].dt.strftime("%Y-%m-%d")
    return s


def retorno(m, pos, direction, h):
    c = m["close"].to_numpy(dtype=float)
    j = pos + h
    if pos < 0 or j >= len(c):
        return None
    r = (c[j] - c[pos]) / c[pos] * 100.0
    return r if direction > 0 else -r


def agregar_etiquetas(m, df):
    df = df.copy()
    pos = m.index.get_indexer(df["entry_time"])
    df["_pos"] = pos
    for h in (3, 4):
        df[f"_ret_h{h}"] = [
            retorno(m, int(p), int(d), h)
            for p, d in zip(pos, df["direction"])
        ]
    return df


# ---------------------------------------------------------------------------
# Estadistica
# ---------------------------------------------------------------------------
def wilson(k, n):
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    den = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / den
    h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / den
    return (100 * (c - h), 100 * (c + h))


def bootstrap_ev_por_dia(wins, days, payout, n_boot, rng):
    """Bootstrap de EV remuestreando dias completos (no senales sueltas)."""
    if n_boot <= 0 or len(wins) == 0:
        return (float("nan"), float("nan"))
    uniq = np.unique(days)
    idx = {d: i for i, d in enumerate(uniq)}
    codes = np.array([idx[d] for d in days], dtype=int)
    day_n = np.bincount(codes, minlength=len(uniq)).astype(float)
    day_w = np.bincount(codes, weights=wins.astype(float), minlength=len(uniq))
    out = []
    for _ in range(n_boot):
        pick = rng.integers(0, len(uniq), len(uniq))
        n = day_n[pick].sum()
        if n <= 0:
            continue
        wr = day_w[pick].sum() / n
        out.append(100 * (wr * payout - (1 - wr)))
    if not out:
        return (float("nan"), float("nan"))
    lo, hi = np.percentile(out, [2.5, 97.5])
    return (round(float(lo), 2), round(float(hi), 2))


def stats(sub, h, payout, n_boot, rng):
    sub = sub[sub[f"_ret_h{h}"].notna()]
    n = len(sub)
    if n == 0:
        return {"n": 0}
    ret = sub[f"_ret_h{h}"].to_numpy(dtype=float)
    wins = ret > 0
    k = int(wins.sum())
    wr = 100.0 * k / n
    ev = wr * payout - (100.0 - wr)
    lo, hi = wilson(k, n)
    b_lo, b_hi = bootstrap_ev_por_dia(
        wins, sub["_date"].to_numpy(), payout, n_boot, rng
    )
    return {
        "n": n,
        "wins": k,
        "wr": round(wr, 2),
        "wr_lo": round(lo, 2),
        "wr_hi": round(hi, 2),
        "ev": round(ev, 2),
        "ev_boot_lo": b_lo,
        "ev_boot_hi": b_hi,
        "dias": int(sub["_date"].nunique()),
    }


def stats_periodos(df, h, payout, split, n_boot, rng):
    out = {}
    for nombre, sub in (
        ("total", df),
        ("descubrimiento", df[df["_date"] < split]),
        ("holdout", df[df["_date"] >= split]),
    ):
        out[nombre] = stats(sub, h, payout, n_boot, rng)
    return out


# ---------------------------------------------------------------------------
# Reglas de deteccion
# ---------------------------------------------------------------------------
def d1_breakout(m, i, n):
    h = m["high"].to_numpy(dtype=float)
    l = m["low"].to_numpy(dtype=float)
    c = m["close"].to_numpy(dtype=float)
    if i < n:
        return 0, 0.0
    hh = h[i - n:i].max()
    ll = l[i - n:i].min()
    if h[i] > hh and c[i] > hh:
        return 1, hh
    if l[i] < ll and c[i] < ll:
        return -1, ll
    return 0, 0.0


def sweep_at(m, i, prior_start_shift, prior_end_shift, sweep_shift):
    """Sweep contra un rango previo explicito (shifts relativos a i)."""
    h = m["high"].to_numpy(dtype=float)
    l = m["low"].to_numpy(dtype=float)
    o = m["open"].to_numpy(dtype=float)
    c = m["close"].to_numpy(dtype=float)
    if i - prior_end_shift < 0:
        return 0, 0.0, 0.0
    ph = h[i - prior_end_shift:i - prior_start_shift + 1].max()
    pl = l[i - prior_end_shift:i - prior_start_shift + 1].min()
    j = i - sweep_shift
    hi, li, oi, ci = h[j], l[j], o[j], c[j]
    rango = hi - li
    if rango <= 0:
        return 0, 0.0, 0.0
    if hi > ph and ci < ph:
        return -1, ph, (hi - max(oi, ci)) / rango
    if li < pl and ci > pl:
        return 1, pl, (min(oi, ci) - li) / rango
    return 0, 0.0, 0.0


def rango_decision(m, s, meta_path):
    if os.path.exists(meta_path):
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        t0 = pd.Timestamp(meta["replay_inicio"])
        t1 = pd.Timestamp(meta["replay_fin"])
    else:
        t0, t1 = s["entry_time"].min(), s["entry_time"].max()
    lo = int(m.index.get_indexer([t0])[0])
    hi = int(m.index.get_indexer([t1])[0])
    return max(lo, 0), hi


def reglas_d1(m, s, meta_path):
    d = s[s["detector"] == "D1"].copy()
    pos = m.index.get_indexer(d["entry_time"])
    ok4 = ok5 = 0
    for k, idx in enumerate(pos):
        d4, _ = d1_breakout(m, idx, 4)
        d5, _ = d1_breakout(m, idx, 5)
        if d4 == int(d.iloc[k]["direction"]):
            ok4 += 1
        if d5 == int(d.iloc[k]["direction"]):
            ok5 += 1
    lo, hi = rango_decision(m, s, meta_path)
    emitted = set(int(p) for p in pos)
    faltan = []
    for idx in range(max(lo, 5), hi + 1):
        d4, _ = d1_breakout(m, idx, 4)
        d5, _ = d1_breakout(m, idx, 5)
        if d4 != 0 and idx not in emitted:
            faltan.append((m.index[idx], d4, d5))
    return {
        "n": int(len(d)),
        "cumple_ventana_4": ok4,
        "cumple_ventana_5": ok5,
        "direccion_distinta_con_4": int(len(d)) - ok4,
        "faltantes_con_ventana_4": len(faltan),
        "faltantes_long": sum(1 for _, x, _ in faltan if x == 1),
        "faltantes_short": sum(1 for _, x, _ in faltan if x == -1),
        "faltantes_ejemplos": [
            (str(t), x, y) for t, x, y in faltan[:8]
        ],
    }


def reglas_d2(m, s, meta_path):
    d = s[s["detector"] == "D2"].copy()
    pos = m.index.get_indexer(d["entry_time"])
    violan = []
    nivel_ok = 0
    for k, idx in enumerate(pos):
        row = d.iloc[k]
        dc, lc, _ = sweep_at(m, idx, 3, 7, 1)
        dfix, lfix, wfix = sweep_at(m, idx, 2, 7, 1)
        if abs(lc - float(row["level_swept"])) <= TOL and dc == int(row["direction"]):
            nivel_ok += 1
        if dfix != int(row["direction"]) or wfix < 0.55 - TOL:
            violan.append((str(row["entry_time"]), int(row["direction"]), dfix,
                           float(row["level_swept"]), lfix))
    lo, hi = rango_decision(m, s, meta_path)
    emitted = set(int(p) for p in pos)
    faltan = []
    for idx in range(max(lo, 8), hi + 1):
        dfix, lfix, w = sweep_at(m, idx, 2, 7, 1)
        if dfix != 0 and w >= 0.55 - TOL and idx not in emitted:
            faltan.append((m.index[idx], dfix, lfix, w))
    return {
        "n": int(len(d)),
        "reproduce_ventana_codigo": nivel_ok,
        "violan_ventana_6": len(violan),
        "violan_ejemplos": violan[:8],
        "faltantes_ventana_6": len(faltan),
        "faltantes_long": sum(1 for _, x, _, _ in faltan if x == 1),
        "faltantes_short": sum(1 for _, x, _, _ in faltan if x == -1),
        "faltantes_ejemplos": [
            (str(t), x, y, round(w, 4)) for t, x, y, w in faltan[:8]
        ],
    }


def reglas_d5(m, s):
    d = s[s["detector"] == "D5"].copy()
    pos = m.index.get_indexer(d["entry_time"])
    violan = []
    shift_by_signal = {}
    no_repro = 0
    for k, idx in enumerate(pos):
        row = d.iloc[k]
        direction = int(row["direction"])
        level = float(row["level_swept"])
        hit = None
        for sh in (1, 2):
            dc, lc, _ = sweep_at(m, idx, sh + 2, sh + 6, sh)
            if dc == direction and abs(lc - level) <= TOL:
                hit = sh
                break
        if hit is None:
            no_repro += 1
            continue
        shift_by_signal[k] = hit
        dfix, lfix, _ = sweep_at(m, idx, hit + 1, hit + 6, hit)
        if dfix != direction:
            violan.append((str(row["entry_time"]), hit, direction, dfix,
                           level, lfix))
    by_pos = {int(p): k for k, p in enumerate(pos)}
    dups = 0
    for k, idx in enumerate(pos):
        if shift_by_signal.get(k) != 2:
            continue
        prev = by_pos.get(int(idx) - 1)
        if prev is None:
            continue
        if (abs(float(d.iloc[prev]["level_swept"]) - float(d.iloc[k]["level_swept"])) <= TOL
                and int(d.iloc[prev]["direction"]) == int(d.iloc[k]["direction"])):
            dups += 1
    n_shift1 = sum(1 for v in shift_by_signal.values() if v == 1)
    n_shift2 = sum(1 for v in shift_by_signal.values() if v == 2)
    return {
        "n": int(len(d)),
        "barrido_inferido_1": n_shift1,
        "barrido_inferido_2": n_shift2,
        "no_reproduce_ventana_codigo": no_repro,
        "violan_ventana_6": len(violan),
        "violan_ejemplos": violan[:8],
        "duplicados_shift2": dups,
        "sweep_bars_ago_cero": int((d["sweep_bars_ago"] == 0).sum()),
        "sweep_volume_ratio_cero": int((d["sweep_volume_ratio"] == 0).sum()),
    }


def reglas_d2a(m, s):
    d = s[s["detector"] == "D2_ANTICIPACION"].copy()
    pos = m.index.get_indexer(d["entry_time"])
    h = m["high"].to_numpy(dtype=float)
    l = m["low"].to_numpy(dtype=float)
    c = m["close"].to_numpy(dtype=float)
    violan = []
    for k, idx in enumerate(pos):
        if idx < 7:
            continue
        ph = h[idx - 6:idx].max()
        pl = l[idx - 6:idx].min()
        long_ok = h[idx] > ph and c[idx] < ph
        short_ok = l[idx] < pl and c[idx] > pl
        fixed = 0
        if long_ok and not short_ok:
            fixed = -1
        elif short_ok and not long_ok:
            fixed = 1
        if fixed != int(d.iloc[k]["direction"]):
            violan.append((str(d.iloc[k]["entry_time"]),
                           int(d.iloc[k]["direction"]), fixed))
    return {
        "n": int(len(d)),
        "violan_ventana_6": len(violan),
        "violan_ejemplos": violan[:8],
    }


def reglas_d3(m, s):
    out = {}
    for det in ("D3", "D3_DEF"):
        d = s[s["detector"] == det].copy()
        pos = m.index.get_indexer(d["entry_time"])
        h = m["high"].to_numpy(dtype=float)
        l = m["low"].to_numpy(dtype=float)
        bad_dir = bad_top = bad_bot = bad_size = 0
        for k, idx in enumerate(pos):
            if idx < 2:
                continue
            row = d.iloc[k]
            alc = h[idx - 2] < l[idx]
            baj = l[idx - 2] > h[idx]
            if alc:
                dr, top, bot = 1, l[idx], h[idx - 2]
            elif baj:
                dr, top, bot = -1, l[idx - 2], h[idx]
            else:
                dr, top, bot = 0, 0.0, 0.0
            if dr != int(row["direction"]):
                bad_dir += 1
            if abs(top - float(row["fvg_top"])) > TOL:
                bad_top += 1
            if abs(bot - float(row["fvg_bottom"])) > TOL:
                bad_bot += 1
            atr = float(row["ctx_atr14_px"]) if "ctx_atr14_px" in d else 0.0
            if atr > 0 and abs((top - bot) / atr - float(row["fvg_size_atr"])) > 1e-6:
                bad_size += 1
        out[det] = {
            "n": int(len(d)),
            "direccion_no_reproducida": bad_dir,
            "top_no_reproducido": bad_top,
            "bottom_no_reproducido": bad_bot,
            "size_atr_no_reproducido": bad_size,
        }
    return out


def reglas_d4(m, s):
    d = s[s["detector"] == "D4"].copy()
    pos = m.index.get_indexer(d["entry_time"])
    h = m["high"].to_numpy(dtype=float)
    l = m["low"].to_numpy(dtype=float)
    bad = 0
    for k, idx in enumerate(pos):
        row = d.iloc[k]
        ob = int(row["ob_bars_ago"])
        if ob <= 0 or idx - ob < 0:
            bad += 1
            continue
        if abs(h[idx - ob] - float(row["ob_high"])) > TOL:
            bad += 1
        elif abs(l[idx - ob] - float(row["ob_low"])) > TOL:
            bad += 1
    # duplicados: mismo ob_high/low y direccion dentro de 3 velas
    dup = 0
    last = {}
    for k, idx in enumerate(pos):
        row = d.iloc[k]
        key = (int(row["direction"]), round(float(row["ob_high"]), 6),
               round(float(row["ob_low"]), 6))
        if key in last and idx - last[key] <= 3:
            dup += 1
        last[key] = int(idx)
    return {
        "n": int(len(d)),
        "geometria_no_reproducida": bad,
        "duplicados_3_velas": dup,
    }


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------
def serie_true(d):
    return pd.Series(True, index=d.index)


def gates(det, d):
    fall = d["filtros_fallados"].fillna("")
    out = [("todos", serie_true(d))]
    if det == "D1":
        pen = d["filtro_penetracion_atr"] >= 0.50
        body = d["filtro_body_ratio"] >= 0.40
        ret = d["filtro_retest"] > 0
        out += [
            ("penetracion>=0.50", pen),
            ("body>=0.40", body),
            ("retest", ret),
            ("pen&body", pen & body),
            ("pen&body&retest", pen & body & ret),
            ("volumen (siempre falla con volume=0)", d["filtro_volumen_ratio"] >= 1.2),
        ]
    elif det == "D2":
        rec = ~fall.str.contains("reclaim")
        cuerpo = d["filtro_reclaim_ratio"] >= 0.55
        dist = d["filtro_distancia_nivel"] <= 2.0
        out += [
            ("reclaim", rec),
            ("cuerpo>=0.55", cuerpo),
            ("distancia<=2ATR", dist),
            ("reclaim&distancia<=2ATR", rec & dist),
            ("reclaim&distancia<=1ATR", rec & (d["filtro_distancia_nivel"] <= 1.0)),
            ("cuerpo>=0.55&distancia<=1ATR", cuerpo & (d["filtro_distancia_nivel"] <= 1.0)),
        ]
    elif det == "D5":
        rec = ~fall.str.contains("reclaim")
        cuerpo = d["filtro_reclaim_ratio"] >= 0.55
        dist = d["filtro_distancia_nivel"] <= 2.0
        out += [
            ("reclaim", rec),
            ("cuerpo>=0.55", cuerpo),
            ("distancia<=2ATR", dist),
            ("reclaim&distancia<=2ATR", rec & dist),
            ("reclaim&distancia<=1ATR", rec & (d["filtro_distancia_nivel"] <= 1.0)),
            ("cuerpo>=0.55&distancia<=1ATR", cuerpo & (d["filtro_distancia_nivel"] <= 1.0)),
        ]
    elif det == "D2_ANTICIPACION":
        wick = d["filtro_wick_ratio"] >= 0.55
        c1 = d["filtro_confluencias"] >= 1
        c2 = d["filtro_confluencias"] >= 2
        out += [
            ("confluencias>=1", c1),
            ("confluencias>=2", c2),
            ("wick>=0.55", wick),
            ("confluencias>=2&wick>=0.55", c2 & wick),
        ]
    elif det in ("D3", "D3_DEF"):
        sz = d["filtro_fvg_size_atr"] >= 0.20
        body = d["filtro_fvg_body_ratio"] >= 0.55
        dir_ok = d["filtro_fvg_dir_ok"] > 0
        mss = d["filtro_mss_aligned"] > 0
        out += [
            ("size>=0.20ATR", sz),
            ("body>=0.55", body),
            ("dir_ok", dir_ok),
            ("size&body", sz & body),
            ("size&body&dir", sz & body & dir_ok),
            ("size&body&dir&mss", sz & body & dir_ok & mss),
        ]
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="eurusd,xauusd")
    ap.add_argument("--data-dir", default="data")
    ap.add_argument("--results-dir", default="results")
    ap.add_argument("--out-dir", default="results/detector_precision")
    ap.add_argument("--split", default="2026-10-01",
                    help="fecha de corte descubrimiento/holdout (YYYY-MM-DD)")
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=20261110)
    ap.add_argument("--payouts", default="",
                    help="override: eurusd=0.85,0.86,0.86,0.87;xauusd=...")
    args = ap.parse_args()

    payouts = {k: dict(v) for k, v in PAYOUTS.items()}
    if args.payouts:
        for bloque in args.payouts.split(";"):
            if not bloque.strip():
                continue
            sym, vals = bloque.split("=", 1)
            nums = [float(x) for x in vals.split(",")]
            if len(nums) != 4:
                raise SystemExit("cada activo necesita 4 payouts (h1..h4)")
            payouts[sym.strip().lower()] = {i + 1: nums[i] for i in range(4)}

    os.makedirs(args.out_dir, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    filas_gates = []
    reglas = {}
    resumen = []

    for sym in [x.strip().lower() for x in args.symbols.split(",") if x.strip()]:
        m = cargar_m15(os.path.join(args.data_dir, f"{sym}_M15.csv"))
        s = cargar_senales(os.path.join(args.results_dir, f"{sym}_signals.csv"))
        s = agregar_etiquetas(m, s)
        meta_path = os.path.join(args.results_dir, f"{sym}_meta.json")
        reglas[sym] = {
            "D1": reglas_d1(m, s, meta_path),
            "D2": reglas_d2(m, s, meta_path),
            "D5": reglas_d5(m, s),
            "D2_ANTICIPACION": reglas_d2a(m, s),
            "D3": reglas_d3(m, s),
            "D4": reglas_d4(m, s),
        }
        for det in ("D1", "D2", "D2_ANTICIPACION", "D3", "D3_DEF", "D5"):
            d = s[s["detector"] == det].copy()
            if len(d) == 0:
                continue
            for gate_name, mask in gates(det, d):
                mask = mask.reindex(d.index, fill_value=False)
                sub = d[mask]
                for h in (3, 4):
                    st = stats_periodos(sub, h, payouts[sym][h], args.split,
                                        args.bootstrap, rng)
                    for periodo, x in st.items():
                        if x.get("n", 0) == 0:
                            continue
                        filas_gates.append({
                            "symbol": sym,
                            "detector": det,
                            "gate": gate_name,
                            "horizonte": h,
                            "periodo": periodo,
                            **x,
                            "payout": payouts[sym][h],
                        })

    # CSV de gates
    path_gates = os.path.join(args.out_dir, "detector_precision_gates.csv")
    campos = ["symbol", "detector", "gate", "horizonte", "periodo", "n",
              "wins", "wr", "wr_lo", "wr_hi", "ev", "ev_boot_lo",
              "ev_boot_hi", "dias", "payout"]
    with open(path_gates, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for r in filas_gates:
            w.writerow({k: r.get(k, "") for k in campos})

    # JSON de reglas
    path_rules = os.path.join(args.out_dir, "detector_precision_rules.json")
    with open(path_rules, "w", encoding="utf-8") as f:
        json.dump(reglas, f, indent=2, ensure_ascii=False, default=str)

    # Resumen legible
    resumen.append("AUDITORIA DE PRECISION PIVOT")
    resumen.append(f"split descubrimiento/holdout: {args.split}")
    resumen.append(f"bootstrap por dia: {args.bootstrap} replicas")
    resumen.append("")
    for sym, blk in reglas.items():
        resumen.append("=" * 78)
        resumen.append(sym.upper())
        for det, x in blk.items():
            resumen.append(f"-- {det}: {json.dumps(x, ensure_ascii=False)}")
        resumen.append("")
    resumen.append("=" * 78)
    resumen.append("GATES (total / descubrimiento / holdout, h3 y h4)")
    for sym in [x.strip().lower() for x in args.symbols.split(",") if x.strip()]:
        resumen.append("")
        resumen.append(sym.upper())
        for det in ("D1", "D2", "D2_ANTICIPACION", "D3", "D3_DEF", "D5"):
            rows = [r for r in filas_gates
                    if r["symbol"] == sym and r["detector"] == det]
            if not rows:
                continue
            resumen.append(f"-- {det}")
            for gate_name in dict.fromkeys(r["gate"] for r in rows):
                for h in (3, 4):
                    partes = []
                    for periodo in ("total", "descubrimiento", "holdout"):
                        x = next((r for r in rows
                                  if r["gate"] == gate_name
                                  and r["horizonte"] == h
                                  and r["periodo"] == periodo), None)
                        if x is None:
                            continue
                        partes.append(
                            f"{periodo[:3]} n={x['n']} WR={x['wr']:.1f} "
                            f"EV={x['ev']:+.1f} boot[{x['ev_boot_lo']:+.1f},{x['ev_boot_hi']:+.1f}]"
                        )
                    if partes:
                        resumen.append(f"   {gate_name} h{h}: " + " | ".join(partes))
    path_res = os.path.join(args.out_dir, "detector_precision_resumen.txt")
    with open(path_res, "w", encoding="utf-8") as f:
        f.write("\n".join(resumen) + "\n")

    print(f"OK: {path_gates}")
    print(f"OK: {path_rules}")
    print(f"OK: {path_res}")


if __name__ == "__main__":
    main()
