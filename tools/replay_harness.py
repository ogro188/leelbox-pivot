#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Replay determinista del motor PIVOT v8 sobre datos reales de Deriv.

Usa exactamente PivotRadarEngine y el mismo seed que kernel.deriv_runtime,
pero escribe todo en un directorio temporal: nunca toca las bases de produccion.

Ejemplo:
    python3 replay_harness.py --symbol EURUSD --bars 500 --warmup 250

El seed se obtiene con AssetDerivStream (M15/H1/H4/D1 reales). Luego se
reproduce barra a barra desde --warmup y se guardan senales y resultados en
OUT_DIR/pivot_core.db. Al final imprime un resumen JSON.
"""
import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pandas as pd


ROOT = os.environ.get("PIVOT_ROOT", ".")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _leer_config_activo(symbol: str) -> dict:
    path = os.path.join(ROOT, "activos", f"{symbol.lower()}.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _combinar_superior(base, df_m15, tf, corte):
    from kernel.feeds.csv_resample import resamplear_ohlc

    base = base[base.index <= corte] if base is not None and not base.empty else base
    reciente = resamplear_ohlc(df_m15, tf)
    if base is not None and not base.empty:
        combinado = pd.concat([base, reciente])
        combinado = combinado[~combinado.index.duplicated(keep="last")]
        return combinado.sort_index()
    return reciente


async def _fetch_seed(symbol: str, instrumento: str):
    from kernel.activos_loader import cargar_activo
    from kernel.deriv_runtime import AssetDerivStream
    from kernel.feeds.deriv import DerivConfig

    activo = cargar_activo(symbol, activos_dir=os.path.join(ROOT, "activos"))
    stream = AssetDerivStream(
        simbolo=symbol,
        instrumento=instrumento,
        config=DerivConfig(symbol=instrumento, timeframes=["M15"]),
        activo_info=activo,
        serialize_senal=lambda x: x,
        db=None,
    )
    try:
        ok = await stream.start()
        if not ok:
            raise RuntimeError(f"No se pudo iniciar el seed Deriv: {stream.last_error}")
        return {
            "m15": stream._df_m15().copy(),
            "h1": stream._df_h1.copy(),
            "h4": stream._df_h4.copy(),
            "d1": stream._df_d1.copy(),
        }
    finally:
        await stream.stop()


def fetch_seed(symbol: str) -> dict:
    cfg = _leer_config_activo(symbol)
    instrumento = (cfg.get("fuente_config") or {}).get("instrumento", symbol)
    # AssetDerivStream construye su motor con data_dir relativo. Cambiamos a
    # un directorio temporal para que el seed no escriba en produccion.
    seed_dir = tempfile.mkdtemp(prefix="pivot-replay-seed-")
    old_cwd = os.getcwd()
    os.chdir(seed_dir)
    try:
        return asyncio.run(_fetch_seed(symbol, instrumento))
    finally:
        os.chdir(old_cwd)
        shutil.rmtree(seed_dir, ignore_errors=True)


def run_replay(symbol: str, data: dict, out_dir: str, warmup: int) -> dict:
    from core.motor_v8 import PivotRadarEngine

    cfg = _leer_config_activo(symbol)
    point = float(cfg.get("point") or 0.00001)
    df_m15 = data["m15"]
    base_h1 = data["h1"]
    base_h4 = data["h4"]
    base_d1 = data["d1"]
    if len(df_m15) < 60:
        raise RuntimeError(f"Seed M15 insuficiente: {len(df_m15)} velas")
    if warmup < 55 or warmup >= len(df_m15):
        raise RuntimeError(f"warmup invalido: {warmup} (seed={len(df_m15)})")

    db_path = os.path.join(out_dir, "pivot_core.db")
    if os.path.exists(db_path):
        raise RuntimeError(f"Ya existe {db_path}; use un OUT_DIR nuevo")
    os.makedirs(out_dir, exist_ok=True)

    engine = PivotRadarEngine(
        symbol=symbol,
        ntfy_topic="",  # replay silencioso: no envia notificaciones
        ntfy_server="http://127.0.0.1:9",
        modo_test=False,
        point=point,
        data_dir=out_dir,
    )

    def dfs(i: int):
        corte = df_m15.index[i]
        d = df_m15.iloc[: i + 1]
        return (
            d,
            _combinar_superior(base_h1, d, "H1", corte),
            _combinar_superior(base_h4, d, "H4", corte),
            _combinar_superior(base_d1, d, "D1", corte),
        )

    # Precarga sin emitir; despues replay con emision y persistencia en OUT_DIR.
    engine.on_data(*dfs(warmup - 1), emitir=False)
    for i in range(warmup, len(df_m15)):
        engine.on_data(*dfs(i), emitir=True)

    con = sqlite3.connect(db_path)
    q = lambda sql: con.execute(sql).fetchone()[0]
    resumen = {
        "symbol": symbol,
        "seed_m15": len(df_m15),
        "seed_h1": len(base_h1),
        "seed_h4": len(base_h4),
        "seed_d1": len(base_d1),
        "warmup": warmup,
        "replay_bars": len(df_m15) - warmup,
        "senales_core": q("select count(*) from senales_core"),
        "cola_total": q("select count(*) from cola_senales"),
        "cola_pendientes": q("select count(*) from cola_senales where processed=0"),
        "resultados_total": q("select count(*) from senales_resultados"),
        "resultados_por_horizonte": dict(con.execute(
            "select horizonte, count(*) from senales_resultados group by horizonte order by horizonte"
        ).fetchall()),
    }
    con.close()
    return resumen


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay PIVOT v8 sobre datos reales de Deriv")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--bars", type=int, default=500, help="velas M15 a sembrar (maximo util ~500)")
    parser.add_argument("--warmup", type=int, default=250, help="velas usadas como precarga")
    parser.add_argument(
        "--out-dir",
        default="",
        help="directorio de salida (debe no existir); por defecto /tmp/pivot-replay-<symbol>-<ts>",
    )
    args = parser.parse_args()

    symbol = args.symbol.upper()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = args.out_dir or f"/tmp/pivot-replay-{symbol.lower()}-{ts}"
    if os.path.abspath(out_dir).startswith("./pivotradar_data"):
        raise SystemExit("OUT_DIR no puede estar dentro de pivotradar_data de produccion")

    print(f"[replay] seed {symbol} ...", flush=True)
    data = fetch_seed(symbol)
    if args.bars and args.bars < len(data["m15"]):
        data["m15"] = data["m15"].tail(args.bars)
    print(
        f"[replay] seed M15={len(data['m15'])} H1={len(data['h1'])} "
        f"H4={len(data['h4'])} D1={len(data['d1'])}",
        flush=True,
    )
    resumen = run_replay(symbol, data, out_dir, args.warmup)
    resumen["out_dir"] = out_dir
    summary_path = os.path.join(out_dir, "summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(resumen, f, indent=2, ensure_ascii=False)
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(f"[replay] DB temporal: {os.path.join(out_dir, 'pivot_core.db')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
