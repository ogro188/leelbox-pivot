#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D0 — Estructura: pivots H1, sweep maestro, zona de interés, dirección."""
from core.estructuras import EstructuraRef
from core.base import Contexto


class EstructuraProvider:
    """Equivalente a los métodos D0 del motor original."""

    def __init__(self, ctx: Contexto):
        self.ctx = ctx

    def actualizar(self) -> EstructuraRef:
        est = self.ctx.estructura or EstructuraRef()
        self._detectar_pivots(est)
        self._identificar_sweep(est)
        self._definir_zona(est)
        self._determinar_direccion(est)
        est.valida = (
            est.swing_high > 0
            or est.swing_low > 0
            or est.sweep_nivel > 0
        )
        est.timestamp = self.ctx._i_time(self.ctx.df_m15, 0)
        return est

    def _detectar_pivots(self, est: EstructuraRef):
        est.swing_high = 0.0
        est.swing_low = 0.0
        est.swing_high_ant = 0.0
        est.swing_low_ant = 0.0
        df = self.ctx.df_h1
        if df is None or len(df) < 50:
            return
        cache = self.ctx._col_cache(df)
        if cache is None:
            return
        high = cache["high"]
        low = cache["low"]
        n = len(high)
        depth = self.ctx.inp_pivot_depth
        lookback = self.ctx.inp_pivot_lookback
        start = depth + 1
        end = min(lookback - depth, n - depth - 1)
        highs = []
        lows = []

        for i in range(start, end):
            high_i = high[n - (i + 1)]
            if high_i == 0:
                continue
            is_swing = True
            for j in range(1, depth + 1):
                if high[n - (i - j + 1)] >= high_i or high[n - (i + j + 1)] >= high_i:
                    is_swing = False
                    break
            if is_swing:
                highs.append(high_i)

        for i in range(start, end):
            low_i = low[n - (i + 1)]
            if low_i == 0:
                continue
            is_swing = True
            for j in range(1, depth + 1):
                if low[n - (i - j + 1)] <= low_i or low[n - (i + j + 1)] <= low_i:
                    is_swing = False
                    break
            if is_swing:
                lows.append(low_i)

        if highs:
            # highs está en orden cronológico (i crece hacia el pasado): el
            # pivote más reciente es highs[0] y el anterior a ese highs[1].
            # (Antes se tomaba por magnitud: swing_high era siempre el máximo
            # de la ventana, por lo que hh era casi siempre True y la
            # estructura nunca salía ALCISTA ni BAJISTA.)
            est.swing_high = highs[0]
            est.swing_high_ant = highs[1] if len(highs) > 1 else 0.0

        if lows:
            est.swing_low = lows[0]
            est.swing_low_ant = lows[1] if len(lows) > 1 else 0.0

    def _identificar_sweep(self, est: EstructuraRef):
        price = self.ctx._i_close(self.ctx.df_m15, 0)
        atr14 = self.ctx.g_atr14_buffer[0] if self.ctx.g_atr14_buffer else 0.0
        umbral = atr14 * self.ctx.inp_sweep_distancia
        est.sweep_nivel = 0.0
        est.sweep_dir = 0
        if est.swing_high > 0 and abs(price - est.swing_high) < umbral:
            est.sweep_nivel = est.swing_high
            est.sweep_dir = -1
            return
        if est.swing_low > 0 and abs(price - est.swing_low) < umbral:
            est.sweep_nivel = est.swing_low
            est.sweep_dir = 1
            return

    def _definir_zona(self, est: EstructuraRef):
        price = self.ctx._i_close(self.ctx.df_m15, 0)
        atr14 = self.ctx.g_atr14_buffer[0] if self.ctx.g_atr14_buffer else 0.0
        margen = atr14 * self.ctx.inp_zona_margen
        if est.swing_high > 0 and est.swing_low > 0:
            est.zona_alta = max(est.swing_high, est.swing_low) + margen
            est.zona_baja = min(est.swing_high, est.swing_low) - margen
        elif est.swing_high > 0:
            est.zona_alta = est.swing_high + margen
            est.zona_baja = est.swing_high - margen
        elif est.swing_low > 0:
            est.zona_alta = est.swing_low + margen
            est.zona_baja = est.swing_low - margen
        else:
            est.zona_alta = price + margen
            est.zona_baja = price - margen
        est.en_zona = est.zona_baja <= price <= est.zona_alta

    def _determinar_direccion(self, est: EstructuraRef):
        if (
            est.swing_high > 0
            and est.swing_high_ant > 0
            and est.swing_low > 0
            and est.swing_low_ant > 0
        ):
            hh = est.swing_high > est.swing_high_ant
            hl = est.swing_low > est.swing_low_ant
            if hh and hl:
                est.dir_estructura = "ALCISTA"
            elif not hh and not hl:
                est.dir_estructura = "BAJISTA"
            else:
                est.dir_estructura = "NEUTRO"
        else:
            est.dir_estructura = "NEUTRO"
