#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descarga historia M15/H1/H4/D1 de Deriv para el analisis de edge.

Solo lectura: no toca ., no escribe en pivotradar_data y no reinicia
ningun servicio. Guarda CSV en --out-dir.

Uso:
    python3 fetch_history.py --symbol EURUSD --months 6
    python3 fetch_history.py --symbol XAUUSD --months 6
"""
import argparse
import asyncio
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, ".")

from kernel.feeds.deriv import DerivConfig, DerivFeed  # noqa: E402

GRAN = {"M15": 900, "H1": 3600, "H4": 14400, "D1": 86400}
SEED_COUNT = {"H1": 600, "H4": 300, "D1": 500}


async def fetch_page(feed, symbol, granularity, count, end="latest"):
    """Pide una pagina de velas y espera la respuesta por req_id."""
    req_id = feed._next_request_id()
    fut = asyncio.get_running_loop().create_future()
    feed._pending_history[req_id] = fut
    payload = {
        "ticks_history": symbol,
        "granularity": granularity,
        "count": int(count),
        "style": "candles",
        "end": str(end),
        "req_id": req_id,
    }
    await feed.ws.send(json.dumps(payload))
    return await asyncio.wait_for(fut, timeout=45)


def limpiar(rows, granularity):
    """Normaliza, filtra epochs invalidos y deduplica por epoch."""
    out = {}
    for row in rows:
        try:
            epoch = int(row["epoch"])
        except (KeyError, TypeError, ValueError):
            continue
        # La API a veces devuelve una vela sintetica con epoch no multiplo.
        if granularity and epoch % granularity != 0:
            continue
        out[epoch] = {
            "epoch": epoch,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row.get("volume", 0) or 0),
        }
    return out


async def descargar(symbol, months, out_dir):
    with open(f"./activos/{symbol.lower()}.json", "r", encoding="utf-8") as f:
        cfg = json.load(f)
    instrumento = (cfg.get("fuente_config") or {}).get("instrumento", symbol)
    print(f"[{symbol}] instrumento={instrumento}", flush=True)

    feed = DerivFeed(DerivConfig(symbol=instrumento, timeframes=["M15"]))
    ok = await feed.connect()
    if not ok:
        raise RuntimeError(f"No se pudo conectar a Deriv para {symbol}")
    task = asyncio.create_task(feed.run())
    await asyncio.sleep(1.0)

    os.makedirs(out_dir, exist_ok=True)
    ahora = int(time.time())
    objetivo = ahora - int(months * 30.5 * 86400)

    try:
        # --- M15 paginado ---
        m15 = {}
        end = "latest"
        for page in range(40):
            try:
                rows = await fetch_page(feed, instrumento, 900, 5000, end)
            except Exception as exc:
                print(f"[{symbol}] M15 page {page} ERROR {exc!r}; reintento", flush=True)
                await asyncio.sleep(2)
                try:
                    rows = await fetch_page(feed, instrumento, 900, 5000, end)
                except Exception as exc2:
                    print(f"[{symbol}] M15 page {page} ERROR2 {exc2!r}; corto", flush=True)
                    break
            nuevos = limpiar(rows, 900)
            if not nuevos:
                break
            m15.update(nuevos)
            epochs = sorted(nuevos)
            print(
                f"[{symbol}] M15 page {page:02d} n={len(nuevos):4d} "
                f"first={datetime.fromtimestamp(epochs[0], timezone.utc):%Y-%m-%d %H:%M} "
                f"last={datetime.fromtimestamp(epochs[-1], timezone.utc):%Y-%m-%d %H:%M}",
                flush=True,
            )
            if epochs[0] <= objetivo:
                break
            end = str(epochs[0] - 1)
            await asyncio.sleep(0.4)

        # --- superiores oficiales (una pagina cada uno) ---
        superiores = {}
        for tf in ("H1", "H4", "D1"):
            try:
                rows = await fetch_page(
                    feed, instrumento, GRAN[tf], SEED_COUNT[tf], "latest"
                )
            except Exception as exc:
                print(f"[{symbol}] {tf} ERROR {exc!r}", flush=True)
                rows = []
            superiores[tf] = limpiar(rows, GRAN[tf])
            if superiores[tf]:
                es = sorted(superiores[tf])
                print(
                    f"[{symbol}] {tf} n={len(es)} "
                    f"{datetime.fromtimestamp(es[0], timezone.utc):%Y-%m-%d} -> "
                    f"{datetime.fromtimestamp(es[-1], timezone.utc):%Y-%m-%d}",
                    flush=True,
                )
            await asyncio.sleep(0.3)
    finally:
        feed.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # --- guardar ---
    def guardar(nombre, data):
        path = os.path.join(out_dir, f"{symbol.lower()}_{nombre}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f, fieldnames=["epoch", "datetime", "open", "high", "low", "close", "volume"]
            )
            w.writeheader()
            for epoch in sorted(data):
                row = dict(data[epoch])
                row["datetime"] = datetime.fromtimestamp(
                    epoch, timezone.utc
                ).isoformat()
                w.writerow(row)
        print(f"[{symbol}] guardado {path} ({len(data)} velas)", flush=True)
        return path

    path_m15 = guardar("M15", m15)
    for tf in ("H1", "H4", "D1"):
        guardar(tf, superiores[tf])

    es = sorted(m15)
    if es:
        print(
            f"[{symbol}] rango M15: "
            f"{datetime.fromtimestamp(es[0], timezone.utc).isoformat()} -> "
            f"{datetime.fromtimestamp(es[-1], timezone.utc).isoformat()}",
            flush=True,
        )
    return path_m15


def main():
    parser = argparse.ArgumentParser(description="Descarga historia Deriv para analisis")
    parser.add_argument("--symbol", default="EURUSD")
    parser.add_argument("--months", type=float, default=6.0)
    parser.add_argument("--out-dir", default="data")
    args = parser.parse_args()
    asyncio.run(descargar(args.symbol.upper(), args.months, args.out_dir))


if __name__ == "__main__":
    main()
