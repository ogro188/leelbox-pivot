#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2 — Liquidity Sweep + Reclaim (intravela). Filtros informacionales."""
from core.estructuras import Signal
from core.base import Contexto, Detector
from core.utils import clamp_0_100


class DetectorD2(Detector):
    nombre = "D2"

    def detectar(self, ctx: Contexto) -> Signal:
        close0 = ctx._i_close(ctx.df_m15, 0)
        open0 = ctx._i_open(ctx.df_m15, 0)
        high0 = ctx._i_high(ctx.df_m15, 0)
        low0 = ctx._i_low(ctx.df_m15, 0)
        if close0 == 0 or high0 == 0 or low0 == 0:
            return None
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return None

        sweep_bar = -1
        sweep_dir = 0
        wick_found = 0.0
        vol_found = 0.0
        level = 0.0
        equal_hl = False
        sweep_detected = False

        # Ventana de UNA sola vela: con range(1, 3) el mismo barrido se
        # detectaba primero como vela 1 y una barra despues como vela 2
        # (90 repeticiones en 182 senales).
        for i in range(1, 2):
            hi = ctx._i_high(ctx.df_m15, i)
            li = ctx._i_low(ctx.df_m15, i)
            if hi == 0 or li == 0:
                continue
            oi = ctx._i_open(ctx.df_m15, i)
            ci = ctx._i_close(ctx.df_m15, i)
            ri = hi - li
            if ri <= 0:
                continue

            ph = ctx._i_high(ctx.df_m15, i + 2)
            pl = ctx._i_low(ctx.df_m15, i + 2)
            for k in range(i + 2, i + ctx.inp_sweep_n + 1):
                hk = ctx._i_high(ctx.df_m15, k)
                lk = ctx._i_low(ctx.df_m15, k)
                if hk == 0 or lk == 0:
                    break
                if hk > ph:
                    ph = hk
                if lk < pl:
                    pl = lk

            if ph == 0 or pl == 0:
                continue

            per_high = hi > ph and ci < ph
            per_low = li < pl and ci > pl
            if not per_high and not per_low:
                continue

            if per_high:
                wr = (hi - max(oi, ci)) / ri
                dc = -1
                lc = ph
            else:
                wr = (min(oi, ci) - li) / ri
                dc = 1
                lc = pl

            if wr < ctx.inp_sweep_wick_min:
                continue

            eq = False
            for j in range(i + 1, i + ctx.inp_equal_hl_window + 1):
                hj = ctx._i_high(ctx.df_m15, j)
                lj = ctx._i_low(ctx.df_m15, j)
                if hj == 0 or lj == 0:
                    break
                if per_high:
                    if abs(hj - lc) <= ctx.inp_equal_hl_tol * atr14:
                        eq = True
                        break
                else:
                    if abs(lj - lc) <= ctx.inp_equal_hl_tol * atr14:
                        eq = True
                        break
            if eq:
                equal_hl = True

            sweep_bar = i
            sweep_dir = dc
            wick_found = wr
            vol_found = ctx.get_volume_ratio(i, ctx.inp_sweep_n)
            level = lc
            sweep_detected = True
            break

        sig = Signal()
        sig.entry_time = ctx._i_time(ctx.df_m15, 0)
        sig.entry_bar_shift = 0
        sig.direction = sweep_dir if sweep_detected else 0
        sig.entry_price = close0
        sig.detector = self.nombre
        sig.es_intravela = True
        sig.level_swept = level
        sig.sweep_wick_ratio = wick_found
        sig.sweep_volume_ratio = vol_found
        sig.sweep_bars_ago = sweep_bar if sweep_detected else 0
        sig.equal_hl_detected = equal_hl
        sig.atr14 = atr14 / ctx.point
        sig.session = ctx.session
        sig.kill_zone = ctx.kill_zone
        sig.estructura_direccion = ctx.estructura.dir_estructura if ctx.estructura else "NEUTRO"
        sig.g1_compresion = ctx.g1
        sig.g2_persistencia = ctx.g2
        sig.g4_agotamiento = ctx.g4
        sig.regimen_volatilidad = ctx.regimen_vol

        # Filtros informacionales
        if not sweep_detected:
            sig.filtros_fallados.append("sin_sweep")
        else:
            sig.filtros_pasados.append("sweep_detectado")

        sig.filtro_wick_ratio = wick_found
        if wick_found >= ctx.inp_sweep_wick_min:
            sig.filtros_pasados.append("wick_ratio")
        else:
            sig.filtros_fallados.append("wick_ratio")

        sig.filtro_sweep_reciente = sweep_bar != -1 and sweep_bar <= 2
        if sig.filtro_sweep_reciente:
            sig.filtros_pasados.append("sweep_reciente")
        else:
            sig.filtros_fallados.append("sweep_reciente")

        sig.filtro_distancia_nivel = abs(close0 - level) / atr14 if atr14 > 0 else 0
        if sig.filtro_distancia_nivel <= 2.0:
            sig.filtros_pasados.append("distancia_nivel")
        else:
            sig.filtros_fallados.append("distancia_nivel")

        br_reclaim = abs(close0 - open0) / (high0 - low0) if (high0 - low0) > 0 else 0
        sig.reclaim_body_ratio = br_reclaim
        sig.filtro_reclaim_ratio = br_reclaim
        reclaim_ok = (sweep_dir == 1 and close0 > open0 and close0 > level) or \
                      (sweep_dir == -1 and close0 < open0 and close0 < level)
        if reclaim_ok and br_reclaim >= ctx.inp_reclaim_body_min:
            sig.filtros_pasados.append("reclaim")
        else:
            sig.filtros_fallados.append("reclaim")

        # Campos observacionales
        sig.velocidad_aproximacion = self._calcular_velocidad_aproximacion(ctx, level, sweep_bar)
        sig.toques_nivel = self._contar_toques_nivel(ctx, level, sweep_dir)
        sig.displacement_post_sweep = self._detectar_displacement(ctx, sweep_bar, sweep_dir)

        sig.tipo = self.clasificar(sig, ctx)
        return sig

    def clasificar(self, sig: Signal, ctx: Contexto) -> str:
        if sig.equal_hl_detected and sig.sweep_wick_ratio > 0.70 and sig.sweep_volume_ratio > 1.80 and sig.reclaim_body_ratio > 0.70:
            return "A"
        if sig.sweep_wick_ratio > 0.65 and sig.sweep_volume_ratio > 1.50 and sig.reclaim_body_ratio > 0.60:
            return "B"
        if sig.sweep_wick_ratio > ctx.inp_sweep_wick_min and sig.reclaim_body_ratio > ctx.inp_reclaim_body_min:
            return "C"
        return "D"

    def _calcular_velocidad_aproximacion(self, ctx: Contexto, nivel: float, sweep_bar: int) -> float:
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0 or ctx.df_m15 is None:
            return 50.0
        for i in range(sweep_bar + 1, min(sweep_bar + 11, len(ctx.df_m15))):
            close_i = ctx._i_close(ctx.df_m15, i)
            if close_i == 0:
                continue
            dist = abs(close_i - nivel)
            if dist > atr14 * 2.0:
                velas = i - sweep_bar
                if velas <= 0:
                    return 50.0
                velocidad = (dist / atr14) / velas
                if velocidad > 1.5:
                    return 95.0
                elif velocidad > 1.0:
                    return 80.0
                elif velocidad > 0.6:
                    return 60.0
                elif velocidad > 0.3:
                    return 40.0
                else:
                    return 20.0
        return 50.0

    def _contar_toques_nivel(self, ctx: Contexto, nivel: float, direction: int) -> int:
        if ctx.df_m15 is None:
            return 0
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return 0
        tol = ctx.inp_equal_hl_tol * atr14
        toques = 0
        for i in range(1, ctx.inp_equal_hl_window + 1):
            if i >= len(ctx.df_m15):
                break
            if direction == -1:
                h = ctx._i_high(ctx.df_m15, i)
                if h > 0 and abs(h - nivel) <= tol:
                    toques += 1
            else:
                l = ctx._i_low(ctx.df_m15, i)
                if l > 0 and abs(l - nivel) <= tol:
                    toques += 1
        return toques

    def _detectar_displacement(self, ctx: Contexto, sweep_bar: int, direction: int) -> bool:
        if ctx.df_m15 is None:
            return False
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return False
        for i in range(max(0, sweep_bar - 2), sweep_bar):
            o = ctx._i_open(ctx.df_m15, i)
            c = ctx._i_close(ctx.df_m15, i)
            h = ctx._i_high(ctx.df_m15, i)
            l = ctx._i_low(ctx.df_m15, i)
            if h == 0 or l == 0 or o == 0 or c == 0:
                continue
            rango = h - l
            if rango <= 0:
                continue
            cuerpo = abs(c - o)
            if cuerpo / rango < 0.65:
                continue
            direccion_ok = (direction == 1 and c > o) or (direction == -1 and c < o)
            if not direccion_ok:
                continue
            if cuerpo >= atr14 * 1.2:
                return True
        return False
