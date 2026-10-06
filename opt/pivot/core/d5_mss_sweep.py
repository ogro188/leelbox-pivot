#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D5 — Market Structure Shift H4 + Sweep (intravela). Filtros informacionales."""
from core.estructuras import Signal
from core.base import Contexto, Detector


class DetectorD5(Detector):
    nombre = "D5"

    def detectar(self, ctx: Contexto) -> Signal:
        ok_mss, mss_bars, mss_dir, mss_level = ctx.detect_mss_h4()
        mss_dir_int = 1 if mss_dir == "ALCISTA" else -1

        close0 = ctx._i_close(ctx.df_m15, 0)
        open0 = ctx._i_open(ctx.df_m15, 0)
        high0 = ctx._i_high(ctx.df_m15, 0)
        low0 = ctx._i_low(ctx.df_m15, 0)
        if close0 == 0 or high0 == 0 or low0 == 0:
            return None
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return None

        sig = Signal()
        sig.entry_time = ctx._i_time(ctx.df_m15, 0)
        sig.entry_bar_shift = 0
        sig.entry_price = close0
        sig.detector = self.nombre
        sig.es_intravela = True
        sig.atr14 = atr14 / ctx.point
        sig.session = ctx.session
        sig.kill_zone = ctx.kill_zone
        sig.estructura_direccion = ctx.estructura.dir_estructura if ctx.estructura else "NEUTRO"
        sig.g1_compresion = ctx.g1
        sig.g2_persistencia = ctx.g2
        sig.g4_agotamiento = ctx.g4
        sig.regimen_volatilidad = ctx.regimen_vol

        if not ok_mss or mss_bars > ctx.inp_mss_max_age_h4_bars:
            sig.direction = 0
            sig.filtros_fallados.append("sin_mss")
            sig.tipo = "D"
            return sig

        sig.mss_aligned = True
        sig.mss_direction = mss_dir
        sig.mss_bars_ago_h4 = mss_bars
        sig.mss_level = mss_level
        sig.filtro_mss_aligned = True
        sig.filtro_mss_reciente = mss_bars <= ctx.inp_mss_max_age_h4_bars
        if sig.filtro_mss_reciente:
            sig.filtros_pasados.append("mss_reciente")
        else:
            sig.filtros_fallados.append("mss_reciente")

        sweep_bar = -1
        wick_found = 0.0
        level = 0.0
        sweep_detected = False

        for i in range(1, 3):
            hi = ctx._i_high(ctx.df_m15, i)
            li = ctx._i_low(ctx.df_m15, i)
            oi = ctx._i_open(ctx.df_m15, i)
            ci = ctx._i_close(ctx.df_m15, i)
            if hi == 0 or li == 0:
                continue
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

            if mss_dir_int == 1:
                if not (li < pl and ci > pl):
                    continue
                w = (min(oi, ci) - li) / ri
                if w < ctx.inp_sweep_wick_min:
                    continue
                sweep_bar = i
                wick_found = w
                level = pl
                sweep_detected = True
                break
            else:
                if not (hi > ph and ci < ph):
                    continue
                w = (hi - max(oi, ci)) / ri
                if w < ctx.inp_sweep_wick_min:
                    continue
                sweep_bar = i
                wick_found = w
                level = ph
                sweep_detected = True
                break

        if not sweep_detected or sweep_bar > 2 or abs(close0 - level) > atr14 * 2.0:
            sig.direction = 0
            sig.filtros_fallados.append("sin_sweep_valido")
            sig.tipo = "D"
            return sig

        sig.direction = mss_dir_int
        sig.level_swept = level
        sig.sweep_wick_ratio = wick_found
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
        reclaim_ok = (mss_dir_int == 1 and close0 > open0 and close0 > level) or \
                      (mss_dir_int == -1 and close0 < open0 and close0 < level)
        if reclaim_ok and br_reclaim >= ctx.inp_reclaim_body_min:
            sig.filtros_pasados.append("reclaim")
        else:
            sig.filtros_fallados.append("reclaim")

        # Campos observacionales
        sig.velocidad_aproximacion = self._calcular_velocidad_aproximacion(ctx, level, sweep_bar)
        sig.toques_nivel = self._contar_toques_nivel(ctx, level, mss_dir_int)
        sig.displacement_post_sweep = self._detectar_displacement(ctx, sweep_bar, mss_dir_int)

        sig.tipo = self.clasificar(sig, ctx, mss_bars, wick_found, br_reclaim)
        return sig

    def clasificar(self, sig: Signal, ctx: Contexto, mss_bars: int = None, wick: float = None, reclaim: float = None) -> str:
        if mss_bars is None:
            mss_bars = sig.mss_bars_ago_h4
        if wick is None:
            wick = sig.sweep_wick_ratio
        if reclaim is None:
            reclaim = sig.reclaim_body_ratio
        in_kill = sig.kill_zone in ("LONDON_OPEN_KILL", "NY_OPEN_KILL")
        if mss_bars <= 4 and wick > 0.70 and reclaim > 0.70 and in_kill:
            return "A"
        if mss_bars <= 8 and wick > 0.60 and reclaim > 0.60:
            return "B"
        if wick > ctx.inp_sweep_wick_min and reclaim > ctx.inp_reclaim_body_min:
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
