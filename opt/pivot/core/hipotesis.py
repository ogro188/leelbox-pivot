#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Hipótesis narrativa + vencimiento. Lógica idéntica al motor v7.9."""
import math
from core.estructuras import Signal, EstructuraRef
from core.base import Contexto


def calcular_vencimiento(sig: Signal, umbrales: dict) -> int:
    atr = sig.atr14
    det = sig.detector
    alto = umbrales.get("atr_alto", 20)
    medio = umbrales.get("atr_medio", 15)
    if det == "D1":
        return 2 if atr > alto else 1
    if det in ("D2", "D2_ANTICIPACION"):
        if sig.kill_zone != "NONE":
            return 1
        return 1 if atr > medio else 2
    if det in ("D3", "D3_DEF"):
        return 2 if det == "D3_DEF" else (2 if atr > alto else 1)
    if det == "D4":
        return 1 if sig.ob_confluence else 2
    if det == "D5":
        return 2 if sig.kill_zone != "NONE" else 4
    return 2


def generar_hipotesis(sig: Signal, ctx: Contexto, est: EstructuraRef):
    sig.hipotesis_expiry_velas = calcular_vencimiento(sig, {"atr_alto": 20, "atr_medio": 15})
    sig.hipotesis_expiry_minutos = sig.hipotesis_expiry_velas * 15
    ok_zona, zona = ctx.es_zona_premium_discount(sig.entry_price)
    if ok_zona:
        sig.hipotesis_zona = zona

    # Objetivo basado en siguiente nivel estructural
    digits = max(0, int(round(-math.log10(ctx.point)))) if ctx.point > 0 else 5
    if sig.direction == 1:
        if est.swing_high > sig.entry_price:
            sig.hipotesis_objetivo = est.swing_high
            sig.objetivo_estructural = est.swing_high
        elif est.sweep_nivel > sig.entry_price:
            sig.hipotesis_objetivo = est.sweep_nivel
            sig.objetivo_estructural = est.sweep_nivel
        else:
            atr = sig.atr14 * ctx.point
            if atr <= 0:
                atr = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
            sig.hipotesis_objetivo = sig.entry_price + atr * 1.5
            sig.objetivo_estructural = 0.0
    else:
        if est.swing_low > 0 and est.swing_low < sig.entry_price:
            sig.hipotesis_objetivo = est.swing_low
            sig.objetivo_estructural = est.swing_low
        elif est.sweep_nivel > 0 and est.sweep_nivel < sig.entry_price:
            sig.hipotesis_objetivo = est.sweep_nivel
            sig.objetivo_estructural = est.sweep_nivel
        else:
            atr = sig.atr14 * ctx.point
            if atr <= 0:
                atr = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
            sig.hipotesis_objetivo = sig.entry_price - atr * 1.5
            sig.objetivo_estructural = 0.0

    causa = ""
    efecto = ""
    razon = ""
    invalidez = ""
    prob_base = 55
    atr14 = sig.atr14 * ctx.point
    if atr14 <= 0:
        atr14 = ctx.g_atr14_buffer[0] if ctx.g_atr14_buffer else 0.0
    if atr14 <= 0:
        return

    # --- Anclaje operativo al horizonte del contrato (M15 / 15 min) ---
    # Los swings H1 (estructura multi-sesion) se conservan como contexto, pero
    # el objetivo y la invalidacion que ve el usuario deben ser niveles que el
    # precio puede testear en 1-2 velas: extremos de la vela de entrada.
    shift = sig.entry_bar_shift if (sig.entry_bar_shift is not None and sig.entry_bar_shift >= 0) else 0
    h0 = ctx._i_high(ctx.df_m15, shift)
    l0 = ctx._i_low(ctx.df_m15, shift)
    if h0 <= 0 or l0 <= 0:
        h0 = l0 = 0.0
    if h0 > 0:
        if sig.direction == 1:
            objetivo_op = h0 + atr14 * 0.5
            invalidez_op = l0 - atr14 * 0.2
        else:
            objetivo_op = l0 - atr14 * 0.5
            invalidez_op = h0 + atr14 * 0.2
        # D2: si el nivel barrido esta cerca (<=2 ATR) ese nivel es el evento
        if sig.detector in ("D2", "D2_ANTICIPACION") and sig.level_swept > 0:
            if abs(sig.level_swept - sig.entry_price) <= atr14 * 2.0:
                objetivo_op = sig.level_swept
        # D3: el borde del FVG es la invalidacion real (zona mitigada)
        if sig.detector in ("D3", "D3_DEF"):
            if sig.direction == -1 and sig.fvg_top > 0:
                invalidez_op = sig.fvg_top + atr14 * 0.2
            elif sig.direction == 1 and sig.fvg_bottom > 0:
                invalidez_op = sig.fvg_bottom - atr14 * 0.2
        sig.hipotesis_objetivo = objetivo_op
        sig.objetivo_operativo = objetivo_op
        sig.invalidez_estructural = invalidez_op
        sig.invalidez_operativa = invalidez_op

    if sig.detector == "D1":
        dir_ruptura = "alcista" if sig.direction == 1 else "bajista"
        nivel = f"{sig.nivel_estructural:.{digits}f}"
        estructura = sig.estructura_direccion
        invalidez_nivel = f"{sig.invalidez_estructural:.{digits}f}"
        causa = f"Ruptura {dir_ruptura} de {nivel}"
        efecto = f"va a provocar continuación {dir_ruptura} hacia {sig.hipotesis_objetivo:.{digits}f}"
        razon = f"porque la vela actual rompe con fuerza (BR={sig.br:.2f})"
        if sig.salud_tendencial >= 60:
            razon += f" y la salud tendencial es sólida ({sig.salud_tendencial:.0f}/100)"
        razon += f", con tendencia {estructura}"
        if sig.contexto_estructural >= 70:
            razon += f" y contexto estructural favorable ({sig.contexto_estructural:.0f}/100)"
        invalidez = f"Si rompe {invalidez_nivel} en contra, se invalida"
        prob_base = 65
        if sig.br > 0.70: prob_base += 5
        if sig.bs > 1.0: prob_base += 5
        if sig.g1_compresion >= 60: prob_base += 5
        if sig.g2_persistencia >= 60: prob_base += 5
        if sig.kill_zone != "NONE": prob_base += 5

    elif sig.detector in ("D2", "D2_ANTICIPACION"):
        zona_text = sig.hipotesis_zona
        accion = "rebote alcista" if sig.direction == 1 else "rechazo bajista"
        nivel = f"{sig.level_swept:.{digits}f}"
        estructura = sig.estructura_direccion
        invalidez_nivel = f"{sig.invalidez_estructural:.{digits}f}"
        causa = f"Sweep en {nivel} en zona {zona_text}"
        efecto = f"va a provocar {accion} hacia {sig.hipotesis_objetivo:.{digits}f}"
        razon = f"porque el sweep liquida stops (calidad {sig.calidad_sweep:.0f}/100)"
        if sig.toques_nivel >= 2:
            razon += f" con {sig.toques_nivel} toques al nivel"
        if sig.displacement_post_sweep:
            razon += " y displacement confirmado"
        razon += f", tendencia {estructura}"
        if sig.contexto_estructural >= 70:
            razon += f", contexto estructural favorable ({sig.contexto_estructural:.0f}/100)"
        invalidez = f"Si rompe {invalidez_nivel}, se invalida"
        prob_base = 70
        if sig.equal_hl_detected: prob_base += 5
        if sig.hipotesis_zona == "PREMIUM" and sig.direction == -1: prob_base += 5
        if sig.hipotesis_zona == "DISCOUNT" and sig.direction == 1: prob_base += 5
        if sig.kill_zone != "NONE": prob_base += 5
        if sig.sweep_volume_ratio > 1.8: prob_base += 5
        if sig.g4_agotamiento >= 65: prob_base -= 10

    elif sig.detector in ("D3", "D3_DEF"):
        dir_fvg = "BAJISTA" if sig.direction == -1 else "ALCISTA"
        zona_text = sig.hipotesis_zona
        accion = "rechazo bajista" if sig.direction == -1 else "rebote alcista"
        defensa = (
            f"Los {'vendedores' if sig.direction == -1 else 'compradores'} defienden la zona"
            if sig.detector == "D3_DEF"
            else "La zona está activa"
        )
        estructura = sig.estructura_direccion
        invalidez_nivel = f"{sig.invalidez_estructural:.{digits}f}"
        direccion_invalidez = "al alza" if sig.direction == -1 else "a la baja"
        causa = f"FVG {dir_fvg} en zona {zona_text}"
        efecto = f"va a provocar {accion} hacia {sig.hipotesis_objetivo:.{digits}f}"
        razon = f"porque {defensa} (calidad FVG {sig.calidad_fvg:.0f}/100)"
        if sig.fvg_size_atr > 0.4:
            razon += f", tamaño {sig.fvg_size_atr:.2f}×ATR"
        razon += f", tendencia {estructura}"
        if sig.mss_aligned:
            razon += ", MSS H4 alineado"
        if sig.contexto_estructural >= 70:
            razon += f", contexto estructural favorable ({sig.contexto_estructural:.0f}/100)"
        invalidez = f"Si rompe {invalidez_nivel} {direccion_invalidez}, se invalida"
        prob_base = 65
        if sig.detector == "D3_DEF": prob_base += 5
        if sig.hipotesis_zona == "PREMIUM" and sig.direction == -1: prob_base += 5
        if sig.hipotesis_zona == "DISCOUNT" and sig.direction == 1: prob_base += 5
        if sig.kill_zone != "NONE": prob_base += 5
        if sig.g1_compresion >= 60: prob_base += 5
        if sig.mss_aligned: prob_base += 5
        if sig.g4_agotamiento >= 65: prob_base -= 10

    elif sig.detector == "D4":
        accion = "rebote alcista" if sig.direction == 1 else "rechazo bajista"
        nivel = f"{(sig.ob_high + sig.ob_low) / 2.0:.{digits}f}"
        estructura = sig.estructura_direccion
        invalidez_nivel = f"{sig.invalidez_estructural:.{digits}f}"
        causa = f"Order Block en {nivel}"
        efecto = f"va a provocar {accion} hacia {sig.hipotesis_objetivo:.{digits}f}"
        razon = f"porque el OB representa acumulación/distribución (calidad {sig.calidad_ob:.0f}/100)"
        if sig.ob_impulse_atr > 1.5:
            razon += f", impulso {sig.ob_impulse_atr:.2f}×ATR"
        razon += f", tendencia {estructura}"
        if sig.contexto_estructural >= 70:
            razon += f", contexto estructural favorable ({sig.contexto_estructural:.0f}/100)"
        invalidez = f"Si rompe {invalidez_nivel}, se invalida"
        prob_base = 65
        if sig.ob_impulse_atr > 1.5: prob_base += 5
        if sig.ob_bars_ago <= 3: prob_base += 5
        if sig.kill_zone != "NONE": prob_base += 5
        if sig.g1_compresion >= 60: prob_base += 5

    elif sig.detector == "D5":
        dir_mss = sig.mss_direction
        accion = "continuación alcista" if sig.direction == 1 else "continuación bajista"
        nivel = f"{sig.level_swept:.{digits}f}"
        estructura = sig.estructura_direccion
        invalidez_nivel = f"{sig.invalidez_estructural:.{digits}f}"
        causa = f"MSS H4 {dir_mss} con sweep en {nivel}"
        efecto = f"va a provocar {accion} hacia {sig.hipotesis_objetivo:.{digits}f}"
        razon = f"porque el cambio de estructura en H4 (hace {sig.mss_bars_ago_h4} velas) confirma la dirección"
        if sig.calidad_mss >= 70:
            razon += f" (calidad MSS {sig.calidad_mss:.0f}/100)"
        razon += " y el sweep valida la entrada"
        if sig.contexto_estructural >= 70:
            razon += f", contexto estructural favorable ({sig.contexto_estructural:.0f}/100)"
        invalidez = f"Si rompe {invalidez_nivel}, se invalida"
        prob_base = 75
        if sig.mss_bars_ago_h4 <= 4: prob_base += 5
        if sig.kill_zone != "NONE": prob_base += 5
        if sig.g1_compresion >= 60: prob_base += 5
        if sig.g2_persistencia >= 60: prob_base += 5

    if sig.g4_agotamiento >= 65:
        efecto = efecto.replace("va a provocar", "podría provocar")
        razon += " (con cautela por agotamiento del movimiento)"
    elif sig.g4_agotamiento <= 30:
        razon += " (movimiento con energía)"

    prob_base = min(95, max(30, prob_base))
    sig.hipotesis_prob_min = prob_base - 5
    sig.hipotesis_prob_max = prob_base + 5
    sig.hipotesis_prob_min = max(30, sig.hipotesis_prob_min)
    sig.hipotesis_prob_max = min(95, sig.hipotesis_prob_max)

    sig.hipotesis_causa = causa
    sig.hipotesis_efecto = efecto
    sig.hipotesis_razon = razon
    sig.hipotesis_invalidez = invalidez
    sig.hipotesis_texto = causa + "\n" + efecto + "\n" + razon + "\n" + invalidez
