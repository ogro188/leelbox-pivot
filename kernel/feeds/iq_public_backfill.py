# -*- coding: utf-8 -*-
"""
Velas sintéticas de calentamiento a partir de ``active(id).charts``.

El GraphQL público no entrega OHLC: ``charts.d1`` devuelve ~200 puntos de
precio cada ~8 minutos durante las últimas 24 h. Este módulo los agrupa en
velas M15 y las fusiona con las velas reales construidas desde ticks.

Reglas:
- La vela real siempre gana sobre la sintética en el mismo ``open_time``.
- Las sintéticas solo rellenan huecos; no reemplazan histórico real.
- Cada tramo sintético se desplaza para empalmar con la vela real anterior y
  la siguiente. En un hueco entre dos velas reales el desplazamiento se
  interpola linealmente, para no dejar un salto en ninguno de los dos bordes.
- Si tras la fusión queda un corte mayor a ``max_gap``, se conserva solo la
  racha final. El motor nunca recibe velas no consecutivas.

Las velas sintéticas son una aproximación: sus máximos/mínimos dependen de las
muestras de ~8 min y no deben tratarse como OHLC de exchange.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

M15_SECONDS = 900


def quotes_to_m15(
    quotes: Sequence[Any],
    *,
    now: float,
    timeframe: int = M15_SECONDS,
) -> List[Dict[str, Any]]:
    """Agrupa puntos ``(timestamp, price)`` en velas M15 ya cerradas.

    Acepta diccionarios con ``timestamp``/``price`` o atributos con esos
    nombres. Descarta la vela en curso y los puntos inválidos. No inventa
    buckets vacíos: si no hay muestras, la vela no existe.
    """
    tf = max(1, int(timeframe))
    puntos: Dict[int, float] = {}
    for quote in quotes:
        try:
            if isinstance(quote, dict):
                ts = int(quote["timestamp"])
                price = float(quote["price"])
            else:
                ts = int(quote.timestamp)
                price = float(quote.price)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if price <= 0:
            continue
        puntos[ts] = price

    buckets: Dict[int, Dict[str, Any]] = {}
    for ts in sorted(puntos):
        price = puntos[ts]
        start = ts // tf * tf
        if start + tf > now:
            continue  # vela en curso: el motor solo recibe cerradas
        bar = buckets.get(start)
        if bar is None:
            buckets[start] = {
                "time": start,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
                "sintetica": True,
            }
        else:
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price
    return [buckets[t] for t in sorted(buckets)]


def _alinear_tramos_sinteticos(velas: List[Dict[str, Any]]) -> None:
    """Desplaza cada tramo sintético para empalmar con las velas reales."""
    total = len(velas)
    i = 0
    while i < total:
        if not velas[i].get("sintetica"):
            i += 1
            continue
        j = i
        while j + 1 < total and velas[j + 1].get("sintetica"):
            j += 1

        izquierda = velas[i - 1] if i > 0 else None
        derecha = velas[j + 1] if j + 1 < total else None
        off_izq = (
            float(izquierda["close"]) - float(velas[i]["open"])
            if izquierda is not None
            else None
        )
        off_der = (
            float(derecha["open"]) - float(velas[j]["close"])
            if derecha is not None
            else None
        )

        for k in range(i, j + 1):
            if off_izq is not None and off_der is not None:
                if j > i:
                    frac = (k - i) / float(j - i)
                    offset = off_izq + (off_der - off_izq) * frac
                else:
                    offset = (off_izq + off_der) / 2.0
            elif off_izq is not None:
                offset = off_izq
            elif off_der is not None:
                offset = off_der
            else:
                offset = 0.0

            if offset:
                for campo in ("open", "high", "low", "close"):
                    velas[k][campo] = float(velas[k][campo]) + offset

        i = j + 1


def fusionar_velas(
    reales: Sequence[Dict[str, Any]],
    sinteticas: Sequence[Dict[str, Any]],
    *,
    now: float,
    max_gap: int = 1800,
    timeframe: int = M15_SECONDS,
) -> Tuple[List[Dict[str, Any]], int]:
    """Fusiona velas reales y sintéticas y devuelve ``(velas, n_sinteticas)``.

    - Las reales tienen prioridad en ``open_time`` repetido.
    - Solo se conserva la racha final sin cortes mayores a ``max_gap``.
    - ``n_sinteticas`` cuenta las sintéticas que quedaron en esa racha.
    """
    tf = max(1, int(timeframe))
    gap = max(tf, int(max_gap))

    por_tiempo: Dict[int, Dict[str, Any]] = {}
    for bar in sinteticas:
        try:
            t = int(bar["time"])
        except (KeyError, TypeError, ValueError):
            continue
        if t + tf > now:
            continue
        copia = dict(bar)
        copia["sintetica"] = True
        por_tiempo[t] = copia
    for bar in reales:
        try:
            t = int(bar["time"])
        except (KeyError, TypeError, ValueError):
            continue
        if t + tf > now:
            continue
        copia = dict(bar)
        copia["sintetica"] = False
        por_tiempo[t] = copia

    if not por_tiempo:
        return [], 0

    velas = [por_tiempo[t] for t in sorted(por_tiempo)]

    # El buffer no debe terminar en una vela sintética si hay reales: el poll
    # usa el último open_time para pedir las nuevas y se saltaría la vela real
    # del mismo bucket.
    ultima_real = max(
        (bar["time"] for bar in velas if not bar.get("sintetica")),
        default=None,
    )
    if ultima_real is not None:
        velas = [bar for bar in velas if bar["time"] <= ultima_real]

    # Primero se aísla la racha final; después se alinean los tramos dentro de
    # ella, para no usar como ancla una vela real separada por un hueco.
    inicio = 0
    for idx in range(1, len(velas)):
        if velas[idx]["time"] - velas[idx - 1]["time"] > gap:
            inicio = idx
    velas = velas[inicio:]
    _alinear_tramos_sinteticos(velas)

    n_sinteticas = sum(1 for bar in velas if bar.get("sintetica"))
    return velas, n_sinteticas


__all__ = ["M15_SECONDS", "quotes_to_m15", "fusionar_velas"]
