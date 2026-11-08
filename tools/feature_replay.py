#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replay de 6 meses que captura TODAS las features de contexto y etiquetas.

No toca produccion: motor en proceso, DB nula, sin alertas, sin measure_returns.
Usa fast_engine, validado contra el motor sin acelerar (ver tools/fast_engine.py).

Salidas:
  OUT/{symbol}_signals.csv   una fila por senal con features + etiquetas h1..h8
  OUT/{symbol}_meta.json    rango, barras, config y validacion de etiquetas

Etiquetas: retorno close-to-close desde el cierre de la vela de entrada,
ajustado por direccion y expresado en puntos. h1=+15min ... h8=+120min.
"""
import argparse
import csv
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone

import pandas as pd

sys.path.insert(0, ".")
sys.path.insert(0, ".")

from core.motor_v8 import PivotRadarEngine, MAX_PENDING_SIGNALS  # noqa: E402
from kernel.feeds.csv_resample import resamplear_ohlc  # noqa: E402
from core.estructuras import Signal  # noqa: E402
import dataclasses  # noqa: E402
import fast_engine  # noqa: E402

DATA = "data"


class NullDB:
    async def guardar_senal_core(self, *a, **k):
        return None

    async def guardar_cola_senal(self, *a, **k):
        return None

    async def guardar_resultado_senal(self, *a, **k):
        return None

    async def marcar_cola_procesada(self, *a, **k):
        return None


def cargar(symbol, m15_path=None, d1_path=None):
    m15_path = m15_path or os.path.join(DATA, f"{symbol.lower()}_M15.csv")
    d1_path = d1_path or os.path.join(DATA, f"{symbol.lower()}_D1.csv")
    m15 = pd.read_csv(
        m15_path,
        parse_dates=["datetime"], index_col="datetime",
    )
    m15.index = pd.to_datetime(m15.index, utc=True)
    m15 = m15[["open", "high", "low", "close", "volume"]].astype(float)
    h1 = resamplear_ohlc(m15, "H1")
    h4 = resamplear_ohlc(m15, "H4")
    d1 = pd.read_csv(
        d1_path,
        parse_dates=["datetime"], index_col="datetime",
    )
    d1.index = pd.to_datetime(d1.index, utc=True)
    d1 = d1[["open", "high", "low", "close", "volume"]].astype(float)
    return m15, h1, h4, d1


def scalarizar(sig):
    out = {}
    for f in dataclasses.fields(sig):
        if f.name.startswith("_"):
            continue
        v = getattr(sig, f.name)
        if isinstance(v, bool):
            out[f.name] = int(v)
        elif isinstance(v, (int, float, str)) or v is None:
            out[f.name] = v
        elif isinstance(v, datetime):
            out[f.name] = v.isoformat()
        elif isinstance(v, (list, tuple)):
            out[f.name] = ",".join(str(x) for x in v)
    return out


def _ema_last(values, span):
    if len(values) == 0:
        return 0.0
    return float(pd.Series(values).ewm(span=span, adjust=False).mean().to_numpy()[-1])


def features_contexto(eng, sig):
    """Features de contexto calculadas con el estado del motor en la senal."""
    out = {}
    atr14 = eng.g_atr14_buffer[0] if eng.g_atr14_buffer else 0.0
    atr8 = eng.g_atr8_buffer[0] if eng.g_atr8_buffer else 0.0
    atr30 = eng.g_atr30_buffer[0] if eng.g_atr30_buffer else 0.0
    entry = float(sig.entry_price)
    out["ctx_atr14_px"] = atr14
    out["ctx_atr14_points"] = atr14 / eng.point if eng.point else 0.0
    out["ctx_atr8_14"] = atr8 / atr14 if atr14 > 0 else 0.0
    out["ctx_atr14_30"] = atr14 / atr30 if atr30 > 0 else 0.0

    ema21 = eng.g_ema21_buffer
    ema50 = eng.g_ema50_buffer
    out["ctx_ema21"] = ema21[0] if ema21 else 0.0
    out["ctx_ema50"] = ema50[0] if ema50 else 0.0
    out["ctx_ema50_dist_atr"] = (entry - ema50[0]) / atr14 if (ema50 and atr14 > 0) else 0.0
    out["ctx_ema21_slope_atr"] = ((ema21[0] - ema21[3]) / atr14) if (len(ema21) > 3 and atr14 > 0) else 0.0
    out["ctx_ema21_vs_50_atr"] = ((ema21[0] - ema50[0]) / atr14) if (ema21 and ema50 and atr14 > 0) else 0.0
    out["ctx_rsi14"] = eng.g_rsi14_buffer[0] if eng.g_rsi14_buffer else 0.0

    e20 = eng.g_ema20_h4_buffer
    e50 = eng.g_ema50_h4_buffer
    out["ctx_h4_ema20_dist_atr"] = (entry - e20[0]) / atr14 if (e20 and atr14 > 0) else 0.0
    out["ctx_h4_ema20_vs_50_atr"] = ((e20[0] - e50[0]) / atr14) if (e20 and e50 and atr14 > 0) else 0.0
    out["ctx_h4_ema20_slope_atr"] = ((e20[0] - e20[4]) / atr14) if (len(e20) > 4 and atr14 > 0) else 0.0

    d50 = eng.g_ema50_d1_buffer
    d200 = eng.g_ema200_d1_buffer
    out["ctx_d1_ema50_dist_atr"] = (entry - d50[0]) / atr14 if (d50 and atr14 > 0) else 0.0
    out["ctx_d1_ema50_vs_200_atr"] = ((d50[0] - d200[0]) / atr14) if (d50 and d200 and atr14 > 0) else 0.0

    h4 = eng.df_h4
    if h4 is not None and len(h4) >= 50 and atr14 > 0:
        hi = float(h4["high"].iloc[-50:].max())
        lo = float(h4["low"].iloc[-50:].min())
        rng = hi - lo
        out["ctx_h4_pos50"] = (entry - lo) / rng if rng > 0 else 0.5
        out["ctx_h4_range_atr"] = rng / atr14
        out["ctx_h4_dist_high_atr"] = (hi - entry) / atr14
        out["ctx_h4_dist_low_atr"] = (entry - lo) / atr14
        try:
            h4_open = h4.index[-1]
            out["ctx_m15_into_h4"] = int((pd.Timestamp(sig.entry_time) - h4_open).total_seconds() // 900)
        except Exception:
            out["ctx_m15_into_h4"] = -1
    else:
        out["ctx_h4_pos50"] = 0.5
        out["ctx_h4_range_atr"] = 0.0
        out["ctx_h4_dist_high_atr"] = 0.0
        out["ctx_h4_dist_low_atr"] = 0.0
        out["ctx_m15_into_h4"] = -1

    h1 = eng.df_h1
    if h1 is not None and len(h1) >= 60 and atr14 > 0:
        c = h1["close"].to_numpy(dtype=float)
        h1_20 = _ema_last(c, 20)
        h1_50 = _ema_last(c, 50)
        out["ctx_h1_ema20_dist_atr"] = (entry - h1_20) / atr14
        out["ctx_h1_ema20_vs_50_atr"] = (h1_20 - h1_50) / atr14
    else:
        out["ctx_h1_ema20_dist_atr"] = 0.0
        out["ctx_h1_ema20_vs_50_atr"] = 0.0

    est = eng.g_estructura
    out["ctx_estructura_valida"] = int(bool(getattr(est, "valida", False)))
    out["ctx_estructura_dir"] = getattr(est, "dir_estructura", "NEUTRO")
    out["ctx_estructura_zona"] = int(bool(getattr(est, "en_zona", False)))
    out["ctx_pending"] = len(eng.g_pending_signals)
    out["ctx_g1"] = eng.g_g1
    out["ctx_g2"] = eng.g_g2
    out["ctx_g3"] = eng.g_g3
    out["ctx_g4"] = eng.g_g4
    dt = pd.Timestamp(sig.entry_time)
    out["ctx_hour"] = dt.hour
    out["ctx_weekday"] = dt.weekday()
    return out


def etiquetas(m15, pos, entry, direction, point, max_h=8):
    out = {}
    close = m15["close"].to_numpy(dtype=float)
    high = m15["high"].to_numpy(dtype=float)
    low = m15["low"].to_numpy(dtype=float)
    n = len(close)
    for h in range(1, max_h + 1):
        j = pos + h
        if j >= n:
            out[f"ret_h{h}"] = None
            out[f"win_h{h}"] = None
            out[f"mfe_h{h}"] = None
            out[f"mae_h{h}"] = None
            continue
        ci = float(close[j])
        ret = (ci - entry) / point
        if direction < 0:
            ret = -ret
        out[f"ret_h{h}"] = ret
        out[f"win_h{h}"] = 1 if ret > 0 else 0
        # MFE/MAE replicando measure_returns: vela de entrada .. vela +h
        mfe = entry
        mae = entry
        for b in range(pos, j + 1):
            hh = float(high[b])
            ll = float(low[b])
            if direction == 1:
                mfe = max(mfe, hh)
                mae = min(mae, ll)
            else:
                mfe = min(mfe, ll)
                mae = max(mae, hh)
        out[f"mfe_h{h}"] = (mfe - entry) / point * (1 if direction > 0 else -1)
        out[f"mae_h{h}"] = (mae - entry) / point * (1 if direction > 0 else -1)
    return out


def validar_etiquetas(symbol, filas, max_h=4):
    """Compara ret_h1..h4 con senales_resultados de produccion para IDs comunes."""
    path = f"./pivotradar_data/{symbol.lower()}/pivot_core.db"
    if not os.path.exists(path):
        return {"error": "db no existe"}
    import sqlite3
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    ids = [str(r["id"]) for r in filas[:5000]]
    if not ids:
        con.close()
        return {"n": 0}
    q = ",".join("?" * len(ids))
    prod = {}
    for sid, h, ret in con.execute(
        f"select signal_id, horizonte, retorno from senales_resultados where signal_id in ({q})",
        ids,
    ):
        prod[(str(sid), int(h))] = float(ret)
    con.close()

    por_id = {str(r["id"]): r for r in filas}
    difs = []
    signos = 0
    total = 0
    for (sid, h), ret_prod in prod.items():
        if h > max_h:
            continue
        r = por_id.get(sid)
        if r is None or r.get(f"ret_h{h}") is None:
            continue
        ret_replay = float(r[f"ret_h{h}"])
        difs.append(abs(ret_replay - ret_prod))
        if (ret_replay > 0) == (ret_prod > 0):
            signos += 1
        total += 1
    difs.sort()
    return {
        "n_comunes": total,
        "signo_coincide_pct": round(100.0 * signos / total, 2) if total else None,
        "dif_media": round(sum(difs) / len(difs), 8) if difs else None,
        "dif_p95": round(difs[int(len(difs) * 0.95)], 8) if difs else None,
        "dif_max": round(difs[-1], 8) if difs else None,
        "exactos_pct": round(100.0 * sum(1 for d in difs if d < 1e-6) / len(difs), 2) if difs else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--out-dir", default="results")
    ap.add_argument("--warmup", type=int, default=500)
    ap.add_argument("--limit", type=int, default=0, help="limitar velas (0=todas)")
    ap.add_argument("--desde", default="", help="ISO fecha de inicio opcional")
    ap.add_argument(
        "--m15", default="",
        help="CSV M15 alternativo (por defecto data/{symbol}_M15.csv)",
    )
    ap.add_argument(
        "--d1", default="",
        help="CSV D1 alternativo (por defecto data/{symbol}_D1.csv)",
    )
    args = ap.parse_args()
    symbol = args.symbol.upper()

    m15, h1, h4, d1 = cargar(symbol, args.m15 or None, args.d1 or None)
    os.makedirs(args.out_dir, exist_ok=True)
    fast_engine.install_fast_engine(PivotRadarEngine)

    tmp = tempfile.mkdtemp(prefix=f"pivot-features-{symbol.lower()}-")
    point = 1e-5 if symbol == "EURUSD" else 0.01
    eng = PivotRadarEngine(
        symbol=symbol, ntfy_topic="", ntfy_server="http://127.0.0.1:9",
        modo_test=False, point=point, data_dir=tmp,
    )
    eng.db = NullDB()
    eng.alertas.send_ntfy_message = lambda *a, **k: False
    eng.alertas.queue_alert = lambda *a, **k: None
    eng.alertas.process_alert_queue = lambda: None
    eng.alertas.build_alert_text = lambda sig: ""

    filas = []

    def route(sig):
        from core.utils import clamp_0_100
        sig.calidad_sweep = clamp_0_100(sig.calidad_sweep)
        sig.calidad_mss = clamp_0_100(sig.calidad_mss)
        sig.calidad_fvg = clamp_0_100(sig.calidad_fvg)
        sig.calidad_ob = clamp_0_100(sig.calidad_ob)
        sig.salud_tendencial = clamp_0_100(sig.salud_tendencial)
        sig.contexto_estructural = clamp_0_100(sig.contexto_estructural)
        if len(eng.g_pending_signals) >= MAX_PENDING_SIGNALS:
            old = eng.g_pending_signals.pop(0)
            eng.g_pending_ids.discard(old.id)
        eng.g_pending_signals.append(sig)
        eng.g_pending_ids.add(sig.id)
        if getattr(eng, "_emitir", False):
            fila = scalarizar(sig)
            fila.update(features_contexto(eng, sig))
            filas.append(fila)

    eng.route_signal = route

    pos_por_ts = {ts: k for k, ts in enumerate(m15.index)}
    estado = {"i": 0}

    def shift_returns():
        """Replica el ciclo de vida de measure_returns sin medir ni escribir DB.

        Actualiza entry_bar_shift de las pendientes (lo usa la confluencia) y
        marca completada la senal a los 5 compases, igual que produccion.
        """
        if not getattr(eng, "_emitir", True):
            return
        actual = estado["i"]
        keep = []
        for s in eng.g_pending_signals:
            if s.completada:
                continue
            p = pos_por_ts.get(pd.Timestamp(s.entry_time))
            if p is None:
                s.completada = True
                continue
            nuevo = actual - p
            if nuevo < 0:
                s.completada = True
                continue
            s.entry_bar_shift = nuevo
            if nuevo <= 0:
                keep.append(s)
                continue
            if nuevo > 5:
                s.completada = True
                keep.append(s)
                continue
            if nuevo >= 5:
                # A shift=5 ya se midio h4 en produccion: completa pero
                # permanece un ciclo mas en la lista, igual que el keep real.
                s.completada = True
                keep.append(s)
                continue
            keep.append(s)
        eng.g_pending_signals = keep
        eng.g_pending_ids = {s.id for s in keep}

    eng.measure_returns = shift_returns

    if args.desde:
        desde = pd.Timestamp(args.desde).tz_localize("UTC") if pd.Timestamp(args.desde).tzinfo is None else pd.Timestamp(args.desde)
        inicio = int(m15.index.searchsorted(desde))
    else:
        inicio = args.warmup
    inicio = max(inicio, args.warmup)
    fin = len(m15) - 9
    if args.limit:
        fin = min(fin, inicio + args.limit)
    print(f"[{symbol}] M15={len(m15)} replay {inicio}..{fin} ({fin - inicio} velas)", flush=True)

    def dfs(i):
        corte = m15.index[i]
        return (
            m15.iloc[max(0, i - 999):i + 1],
            h1[h1.index <= corte].tail(500),
            h4[h4.index <= corte].tail(300),
            d1[d1.index <= corte].tail(300),
        )

    t0 = time.time()
    estado["i"] = inicio - 1
    eng.on_data(*dfs(inicio - 1), emitir=False)
    for i in range(inicio, fin):
        estado["i"] = i
        eng.on_data(*dfs(i), emitir=True)
        if (i - inicio) % 500 == 0 and i > inicio:
            dt = time.time() - t0
            print(
                f"  {i - inicio}/{fin - inicio} senales={len(filas)} "
                f"{dt:.0f}s ({dt / max(1, i - inicio):.3f} s/bar)",
                flush=True,
            )
    print(f"[{symbol}] replay {time.time() - t0:.0f}s senales={len(filas)}", flush=True)

    # Etiquetas
    sin_pos = 0
    for fila in filas:
        ts = pd.Timestamp(fila["entry_time"])
        pos = pos_por_ts.get(ts)
        if pos is None:
            sin_pos += 1
            continue
        fila.update(etiquetas(
            m15, pos, float(fila["entry_price"]), int(fila["direction"]),
            point, max_h=8,
        ))
        # features temporales utiles
        fila["idx"] = pos
        fila["date"] = str(m15.index[pos].date())
    if sin_pos:
        print(f"[{symbol}] AVISO {sin_pos} senales sin posicion en M15", flush=True)

    # Ordenar por tiempo e id
    filas.sort(key=lambda r: (r.get("idx", 0), str(r.get("id"))))
    campos = []
    vistos = set()
    for fila in filas:
        for k in fila:
            if k not in vistos:
                vistos.add(k)
                campos.append(k)
    path_csv = os.path.join(args.out_dir, f"{symbol.lower()}_signals.csv")
    with open(path_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        for fila in filas:
            w.writerow(fila)
    print(f"[{symbol}] guardado {path_csv} ({len(filas)} filas, {len(campos)} columnas)", flush=True)

    validacion = validar_etiquetas(symbol, filas)
    meta = {
        "symbol": symbol,
        "m15_total": len(m15),
        "replay_inicio": str(m15.index[inicio]),
        "replay_fin": str(m15.index[fin - 1]) if fin > inicio else None,
        "velas_replay": fin - inicio,
        "warmup": args.warmup,
        "senales": len(filas),
        "sin_pos": sin_pos,
        "segundos": round(time.time() - t0, 1),
        "point": point,
        "columnas": campos,
        "validacion_etiquetas": validacion,
    }
    path_meta = os.path.join(args.out_dir, f"{symbol.lower()}_meta.json")
    with open(path_meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[{symbol}] validacion etiquetas: {json.dumps(validacion, ensure_ascii=False)}", flush=True)
    print(f"[{symbol}] meta {path_meta}", flush=True)


if __name__ == "__main__":
    main()
