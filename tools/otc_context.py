#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reconstruye features de contexto para las senales OTC historicas.

Lee (solo lectura) iq_public.db y pivot_core.db de cada OTC, calcula en el
momento de la senal las mismas features que feature_replay, y une:
  - resultado real h1..h4 de senales_resultados,
  - payout binario real del tick mas cercano anterior a la creacion.

Salida: out/otc_features.csv
"""
import argparse
import csv
import os
import sqlite3

import numpy as np
import pandas as pd

IQ_DB = "./pivotradar_data/iq_public/iq_public.db"
OTC_DB = "./pivotradar_data/{sym}/pivot_core.db"


def ema(vals, span):
    return pd.Series(vals).ewm(span=span, adjust=False).mean().to_numpy()


def atr_series(high, low, close, period):
    prev = np.empty_like(close)
    prev[0] = np.nan
    prev[1:] = close[:-1]
    tr = np.maximum(np.maximum(high - low, np.abs(high - prev)), np.abs(low - prev))
    tr[0] = high[0] - low[0]
    return pd.Series(tr).ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()


def rsi_series(close, period=14):
    s = pd.Series(close)
    d = s.diff()
    gain = d.where(d > 0, 0.0)
    loss = (-d).where(d < 0, 0.0)
    ag = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    al = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = ag / al
    return (100.0 - 100.0 / (1.0 + rs)).to_numpy()


def sesion_broker(ts_utc):
    h = (ts_utc.hour + 2) % 24
    if 0 <= h < 7:
        return "ASIA"
    if 7 <= h < 13:
        return "LONDON"
    if 13 <= h < 15:
        return "NY_OPEN"
    if 15 <= h < 16:
        return "LONDON_CLOSE"
    if 16 <= h < 21:
        return "NY"
    return "OUT"


def cargar_bars(con, provider):
    rows = con.execute(
        "select open_time, open, high, low, close from bars "
        "where provider_name=? and timeframe='M15' order by open_time",
        (provider,),
    ).fetchall()
    df = pd.DataFrame(rows, columns=["open_time", "open", "high", "low", "close"])
    df.index = pd.to_datetime(df["open_time"], unit="s", utc=True)
    return df[["open", "high", "low", "close"]].astype(float)


def features_en(df, entry_time, entry_price):
    hist = df[df.index <= entry_time]
    if len(hist) < 60:
        return None
    c = hist["close"].to_numpy(dtype=float)
    h = hist["high"].to_numpy(dtype=float)
    l = hist["low"].to_numpy(dtype=float)
    atr14 = float(atr_series(h, l, c, 14)[-1])
    atr30 = float(atr_series(h, l, c, 30)[-1])
    atr8 = float(atr_series(h, l, c, 8)[-1])
    if atr14 <= 0:
        return None
    ema21 = ema(c, 21)
    ema50 = ema(c, 50)
    rsi = rsi_series(c)
    out = {
        "ctx_atr14_px": atr14,
        "ctx_atr8_14": atr8 / atr14,
        "ctx_atr14_30": atr14 / atr30 if atr30 > 0 else 0.0,
        "ctx_ema50_dist_atr": (entry_price - ema50[-1]) / atr14,
        "ctx_ema21_slope_atr": (ema21[-1] - ema21[-4]) / atr14 if len(ema21) >= 4 else 0.0,
        "ctx_ema21_vs_50_atr": (ema21[-1] - ema50[-1]) / atr14,
        "ctx_rsi14": float(rsi[-1]) if len(rsi) else 0.0,
    }
    h4 = hist.resample("4h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(h4) >= 20:
        e20 = ema(h4["close"].to_numpy(dtype=float), 20)
        e50 = ema(h4["close"].to_numpy(dtype=float), 50)
        out["ctx_h4_ema20_vs_50_atr"] = (e20[-1] - e50[-1]) / atr14
        out["ctx_h4_ema20_dist_atr"] = (entry_price - e20[-1]) / atr14
        out["ctx_h4_ema20_slope_atr"] = (e20[-1] - e20[-5]) / atr14 if len(e20) >= 5 else 0.0
        n = min(50, len(h4))
        hi = float(h4["high"].iloc[-n:].max())
        lo = float(h4["low"].iloc[-n:].min())
        rng = hi - lo
        out["ctx_h4_pos50"] = (entry_price - lo) / rng if rng > 0 else 0.5
        out["ctx_h4_range_atr"] = rng / atr14
        out["ctx_h4_dist_high_atr"] = (hi - entry_price) / atr14
        out["ctx_h4_dist_low_atr"] = (entry_price - lo) / atr14
    h1 = hist.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    if len(h1) >= 60:
        e20 = ema(h1["close"].to_numpy(dtype=float), 20)
        e50 = ema(h1["close"].to_numpy(dtype=float), 50)
        out["ctx_h1_ema20_vs_50_atr"] = (e20[-1] - e50[-1]) / atr14
        out["ctx_h1_ema20_dist_atr"] = (entry_price - e20[-1]) / atr14
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/otc_features.csv")
    ap.add_argument("--symbols", nargs="+", default=["EURUSD-OTC", "XAUUSD-OTC"])
    args = ap.parse_args()

    iq = sqlite3.connect(f"file:{IQ_DB}?mode=ro", uri=True)
    filas = []
    for provider in args.symbols:
        db_path = OTC_DB.format(sym=provider.lower())
        if not os.path.exists(db_path):
            print(f"AVISO no existe {db_path}")
            continue
        bars = cargar_bars(iq, provider)
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        senales = con.execute(
            "select signal_id, entry_time, entry_price, direction, detector, tipo, "
            "conviccion, regimen_volatilidad, created_at from senales_core where direction in (1,-1)"
        ).fetchall()
        pay_rows = iq.execute(
            "select ts, payout_binary_pct from ticks where provider_name=? "
            "and payout_binary_pct is not null order by ts", (provider,)
        ).fetchall()
        pay_ts = np.array([r[0] for r in pay_rows], dtype=float)
        pay_val = np.array([r[1] for r in pay_rows], dtype=float)
        resultados = {}
        for rsid, h, ret in con.execute("select signal_id, horizonte, retorno from senales_resultados"):
            resultados.setdefault(str(rsid), {})[int(h)] = float(ret)
        print(f"[{provider}] senales={len(senales)} bars_m15={len(bars)} ticks_payout={len(pay_ts)}")
        for sid, entry_time, entry_price, direction, detector, tipo, conv, regimen, created_at in senales:
            et = pd.Timestamp(entry_time)
            if et.tzinfo is None:
                et = et.tz_localize("UTC")
            feats = features_en(bars, et, float(entry_price))
            if feats is None:
                continue
            # payout: ultimo tick con payout antes de la creacion de la senal
            ts_limite = et.timestamp() + 900
            if created_at:
                try:
                    ts_limite = pd.Timestamp(created_at, tz="UTC").timestamp()
                except Exception:
                    pass
            idxp = int(np.searchsorted(pay_ts, ts_limite, side="right")) - 1
            payout = float(pay_val[idxp]) if idxp >= 0 else None
            h_utc = et.hour
            fila = {
                "id": str(sid),
                "symbol": provider,
                "entry_time": et.isoformat(),
                "date": str(et.date()),
                "direction": int(direction),
                "detector": detector,
                "tipo": tipo or "",
                "conviccion": conv,
                "regimen_volatilidad": regimen,
                "entry_price": float(entry_price),
                "payout_pct": payout,
                "ctx_hour": h_utc,
                "ctx_weekday": et.weekday(),
                "session": sesion_broker(et),
            }
            fila.update(feats)
            for h in range(1, 5):
                ret = resultados.get(str(sid), {}).get(h)
                fila[f"ret_h{h}"] = ret
                fila[f"win_h{h}"] = (1 if ret > 0 else 0) if ret is not None else None
            filas.append(fila)
        con.close()
    iq.close()

    if not filas:
        print("sin filas")
        return
    campos = []
    vistos = set()
    for f in filas:
        for k in f:
            if k not in vistos:
                vistos.add(k)
                campos.append(k)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(filas)
    print(f"guardado {args.out} ({len(filas)} filas)")
    for sym in args.symbols:
        n = sum(1 for f in filas if f["symbol"] == sym)
        nh3 = sum(1 for f in filas if f["symbol"] == sym and f.get("win_h3") is not None)
        print(f"  {sym}: {n} con contexto, {nh3} con resultado h3")


if __name__ == "__main__":
    main()
