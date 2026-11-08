#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extrae la ventana exacta de M15 usada por el replay original.

El replay de 6 meses no usó el CSV completo de 12 meses: usó las últimas
12.506 filas (EURUSD) o 12.014 filas (XAUUSD), que empiezan el
2026-05-05 08:30 UTC. Este script copia ese subconjunto sin reescribir los
valores, para que `feature_replay.py --m15 ...` reproduzca el mismo rango.

No toca producción. Solo lee `data/` y escribe en `--out-dir`.
"""
import argparse
import csv
import os

ROWS_POR_DEFECTO = {
    "EURUSD": 12506,
    "XAUUSD": 12014,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", required=True, choices=["EURUSD", "XAUUSD"])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument(
        "--rows", type=int, default=0,
        help="número de velas finales (0 = valor histórico del replay)",
    )
    ap.add_argument(
        "--source", default="",
        help="CSV M15 de origen (por defecto data/{symbol}_M15.csv)",
    )
    ap.add_argument(
        "--d1", action="store_true",
        help="copiar también el D1 completo al directorio de salida",
    )
    args = ap.parse_args()

    symbol = args.symbol.upper()
    rows = args.rows or ROWS_POR_DEFECTO[symbol]
    source = args.source or os.path.join("data", f"{symbol.lower()}_M15.csv")
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)
    destino = os.path.join(out_dir, f"{symbol.lower()}_M15.csv")

    with open(source, newline="", encoding="utf-8") as f:
        lector = csv.reader(f)
        cabecera = next(lector)
        filas = list(lector)

    if rows > len(filas):
        raise SystemExit(
            f"{source} tiene {len(filas)} velas; no se pueden extraer {rows}"
        )
    if "datetime" not in cabecera:
        raise SystemExit(f"{source} no tiene columna datetime: {cabecera}")

    seleccion = filas[-rows:]
    with open(destino, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, lineterminator="\n")
        escritor.writerow(cabecera)
        escritor.writerows(seleccion)

    print(
        f"{symbol}: {len(seleccion)} velas -> {destino} "
        f"({seleccion[0][cabecera.index('datetime')]} .. "
        f"{seleccion[-1][cabecera.index('datetime')]})"
    )

    if args.d1:
        d1_origen = os.path.join("data", f"{symbol.lower()}_D1.csv")
        d1_destino = os.path.join(out_dir, f"{symbol.lower()}_D1.csv")
        with open(d1_origen, newline="", encoding="utf-8") as f:
            contenido = f.read()
        with open(d1_destino, "w", newline="", encoding="utf-8") as f:
            f.write(contenido)
        print(f"{symbol}: D1 copiado -> {d1_destino}")


if __name__ == "__main__":
    main()
