# -*- coding: utf-8 -*-
"""Contexto H1/H4/D1 causal para replay y backtest.

El runtime live (``kernel.deriv_runtime.AssetDerivStream``) reconstruye los
timeframes superiores resampleando el buffer de velas M15 **cerradas** y
superponiéndolo a la historia sembrada. Por eso la vela H1/H4/D1 en formación
solo contiene las M15 que ya cerraron en el instante de decisión.

Este módulo replica esa convención:

- las velas superiores **cerradas** salen del frame base precalculado;
- la vela superior **en formación** se agrega desde las M15 incluidas hasta el
  cierre de la vela de señal;
- nunca se usa una M15 posterior al instante de decisión.

La clase es deliberadamente independiente del motor para poder testearla y
reutilizarla en ``tools/feature_replay.py``, ``kernel/backtest.py`` y
``kernel/binary/engine.py``.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from kernel.feeds.csv_resample import resamplear_ohlc

TF_MINUTOS = {"H1": 60, "H4": 240, "D1": 1440}
M15_MINUTOS = 15
_COLUMNAS = ("open", "high", "low", "close", "volume")


def _normalizar(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    """Índice UTC ordenado y columnas OHLCV presentes."""
    if df is None or len(df) == 0:
        return None
    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index, utc=True)
    elif out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    cols = [c for c in _COLUMNAS if c in out.columns]
    if not {"open", "high", "low", "close"}.issubset(cols):
        raise ValueError("El DataFrame debe tener columnas open/high/low/close")
    return out[cols].sort_index()


def _bucket_start(bar_time: pd.Timestamp, tf: str) -> pd.Timestamp:
    """Inicio del bucket superior que contiene la vela M15 ``bar_time``."""
    if tf == "D1":
        return bar_time.normalize()
    if tf == "H4":
        return bar_time.floor("4h")
    if tf == "H1":
        return bar_time.floor("h")
    raise ValueError(f"Timeframe no soportado: {tf}")


class ContextoSuperiorCausal:
    """Genera frames H1/H4/D1 sin datos posteriores al instante de decisión.

    Parameters
    ----------
    df_m15:
        Serie M15 completa. Puede incluir velas futuras; ``frame`` solo toma
        las que corresponden al corte solicitado.
    bases:
        Opcional. Frames superiores de historia larga (por ejemplo el D1 de
        Deriv) para cubrir ventanas que el M15 no alcanza. En el tramo
        solapado manda el resample de M15, igual que en live.
    """

    def __init__(
        self,
        df_m15: pd.DataFrame,
        bases: Optional[Dict[str, pd.DataFrame]] = None,
    ):
        m15 = _normalizar(df_m15)
        if m15 is None:
            raise ValueError("df_m15 vacío")
        self.m15 = m15
        self._bases: Dict[str, pd.DataFrame] = {}

        for tf in TF_MINUTOS:
            reciente = resamplear_ohlc(self.m15, tf)
            base = _normalizar((bases or {}).get(tf))
            if base is not None:
                # La M15 reciente pisa a la historia sembrada en el solape.
                combinado = pd.concat([base, reciente])
                combinado = combinado[~combinado.index.duplicated(keep="last")]
                combinado = combinado.sort_index()
            else:
                combinado = reciente
            self._bases[tf] = combinado

    def frame(self, tf: str, bar_time, tail: int = 500) -> pd.DataFrame:
        """Contexto superior visto al cierre de la vela M15 ``bar_time``.

        ``bar_time`` es la **apertura** de la última vela M15 incluida. El
        instante de decisión es ``bar_time + 15 min``. La última fila puede
        ser una vela superior en formación; su OHLC se calcula solo con las
        M15 cuyo cierre es <= ``bar_time + 15 min``.
        """
        if tf not in TF_MINUTOS:
            raise ValueError(f"Timeframe no soportado: {tf}")

        ts = pd.Timestamp(bar_time)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")

        decision = ts + pd.Timedelta(minutes=M15_MINUTOS)
        inicio = _bucket_start(ts, tf)

        base = self._bases[tf]
        # Filas estrictamente anteriores al bucket actual: están cerradas.
        # Se usa DatetimeIndex.searchsorted para respetar la resolución
        # temporal de pandas (en pandas 3.x el índice puede ser datetime64[us]
        # y Timestamp.value sigue expresado en ns).
        n = int(base.index.searchsorted(inicio, side="left"))
        cerradas = base.iloc[max(0, n - max(0, tail - 1)):n]

        # Vela en formación: M15 desde el inicio del bucket hasta el corte.
        lo = int(self.m15.index.searchsorted(inicio, side="left"))
        hi = int(self.m15.index.searchsorted(decision, side="left"))
        if hi <= lo:
            return cerradas.tail(tail)

        seg = self.m15.iloc[lo:hi]
        fila = {
            "open": float(seg["open"].iloc[0]),
            "high": float(seg["high"].max()),
            "low": float(seg["low"].min()),
            "close": float(seg["close"].iloc[-1]),
            "volume": float(seg["volume"].sum()) if "volume" in seg.columns else 0.0,
        }
        parcial = pd.DataFrame([fila], index=pd.DatetimeIndex([inicio]))
        if cerradas.empty:
            return parcial
        return pd.concat([cerradas, parcial]).tail(tail)


def contexto_superior_causal(
    df_m15: pd.DataFrame,
    tf: str,
    bar_time,
    tail: int = 500,
    bases: Optional[Dict[str, pd.DataFrame]] = None,
) -> pd.DataFrame:
    """Atajo de una sola llamada; para bucles usar ``ContextoSuperiorCausal``."""
    return ContextoSuperiorCausal(df_m15, bases=bases).frame(tf, bar_time, tail=tail)
