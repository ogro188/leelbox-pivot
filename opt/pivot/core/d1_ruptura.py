#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D1 — Ruptura de rango (intravela). Filtros informacionales."""
from core.estructuras import Signal
from core.base import Contexto, Detector
from core.utils import clamp_0_100


class DetectorD1(Detector):
    nombre = "D1"

    def detectar(self, ctx: Contexto) -> Signal:
        high0 = ctx._i_high(ctx.df_m15, 0)
        low0 = ctx._i_low(ctx.df_m15, 0)
        close0 = ctx._i_close(ctx.df_m15, 0)
        open0 = ctx._i_open(ctx.df_m15, 0)
        if high0 == 0 or low0 == 0 or close0 == 0:
            return None
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
        if atr14 <= 0:
            return None

        highest_high = ctx._i_high(ctx.df_m15, 1)
        lowest_low = ctx._i_low(ctx.df_m15, 1)
        for k in range(2, ctx.inp_n_ruptura + 2):
            h = ctx._i_high(ctx.df_m15, k)
            l = ctx._i_low(ctx.df_m15, k)
            if h == 0 or l == 0:
                break
            if h > highest_high:
                highest_high = h
            if l < lowest_low:
                lowest_low = l

        direction = 0
        nivel_ruptura = 0.0
        penetracion = 0.0
        # Ruptura confirmada: exige CIERRE fuera del rango, no basta la mecha.
        # (Antes bastaba high0/low0: una vela que rompia por mecha y cerraba
        # adentro contaba como ruptura; en la muestra medida el 49% de las
        # senales asi generadas cerro de vuelta dentro del rango.)
        if high0 > highest_high and close0 > highest_high:
            direction = 1
            nivel_ruptura = highest_high
            penetracion = (close0 - highest_high) / atr14
        elif low0 < lowest_low and close0 < lowest_low:
            direction = -1
            nivel_ruptura = lowest_low
            penetracion = (lowest_low - close0) / atr14

        sig = Signal()
        sig.entry_time = ctx._i_time(ctx.df_m15, 0)
        sig.entry_bar_shift = 0
        sig.direction = direction
        sig.entry_price = close0
        sig.detector = self.nombre
        sig.es_intravela = True
        sig.nivel_estructural = nivel_ruptura
        sig.atr14 = atr14 / ctx.point
        sig.session = ctx.session
        sig.kill_zone = ctx.kill_zone
        sig.estructura_direccion = ctx.estructura.dir_estructura if ctx.estructura else "NEUTRO"
        sig.g1_compresion = ctx.g1
        sig.g2_persistencia = ctx.g2
        sig.g4_agotamiento = ctx.g4
        sig.regimen_volatilidad = ctx.regimen_vol

        # Filtros informacionales
        if direction == 0:
            sig.filtros_fallados.append("sin_direccion")
        else:
            sig.filtros_pasados.append("direccion_valida")

        sig.filtro_penetracion_atr = penetracion
        if penetracion >= ctx.inp_d1_atr_threshold:
            sig.filtros_pasados.append("penetracion_atr")
        else:
            sig.filtros_fallados.append("penetracion_atr")

        rango0 = high0 - low0
        br0 = abs(close0 - open0) / rango0 if rango0 > 0 else 0
        sig.br = br0
        sig.bs = penetracion
        sig.filtro_body_ratio = br0
        if br0 >= ctx.inp_body_ratio_min:
            sig.filtros_pasados.append("body_ratio")
        else:
            sig.filtros_fallados.append("body_ratio")

        if ctx.inp_d1_use_volume:
            vol_ratio_signal = ctx.get_volume_ratio_cached(0, 20)
            sig.filtro_volumen_ratio = vol_ratio_signal
            if vol_ratio_signal >= ctx.inp_d1_min_volume:
                sig.filtros_pasados.append("volumen")
            else:
                sig.filtros_fallados.append("volumen")

        if ctx.inp_d1_use_retest:
            retested = False
            if direction == 1:
                if low0 <= nivel_ruptura and close0 > nivel_ruptura:
                    retested = True
            else:
                if high0 >= nivel_ruptura and close0 < nivel_ruptura:
                    retested = True
            sig.filtro_retest = retested
            if retested:
                sig.filtros_pasados.append("retest")
            else:
                sig.filtros_fallados.append("retest")

        sig.tipo = self.clasificar(sig, ctx)
        return sig

    def clasificar(self, sig: Signal, ctx: Contexto) -> str:
        br = sig.br
        bs = sig.bs
        session = sig.session
        if session in ("ASIA", "OUT"):
            if br > 0.70 and bs > 0.80:
                return "B"
            return "D"
        if br > 0.70 and bs > 0.80:
            return "A"
        if br > 0.60 and bs > 0.50:
            return "B"
        if br > ctx.inp_body_ratio_min and bs > 0.30:
            return "C"
        return "D"
