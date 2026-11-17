# Precisión de detectores — reglas, bugs y WR/EV

**Fecha:** 2026-11-10 UTC
**Corpus:** ventana móvil de 12 meses, replay 2026-05-12 → 2026-11-10; 9.104 señales EURUSD y 9.070 XAUUSD.
**Estado:** shadow. Producción intacta. Este documento audita; no cambia reglas, filtros ni emisión.
**Herramienta:** [`tools/detector_precision.py`](../tools/detector_precision.py).

---

## 1. Resumen ejecutivo

1. **La mayoría de las señales no cumple todos los filtros que el propio detector declara.** El 81,4 % de las señales EURUSD y el 82,8 % de las XAUUSD falla al menos un filtro. El volumen explica una parte: el CSV de mercado tiene `volume = 0` en el 100 % de las velas, por lo que los filtros y scores que dependen de volumen están sistemáticamente rotos.
2. **Hay tres bugs de ventana confirmados:** D1 usa 5 velas aunque el parámetro es 4; D2 y D5 usan 5 velas previas y se saltan la inmediatamente anterior al sweep (deberían usar 6).
3. **D5 tiene además metadata rota y duplicados:** `sweep_bars_ago = 0` y `sweep_volume_ratio = 0,0` en el 100 % de sus señales; 136/331 EURUSD y 133/308 XAUUSD son el mismo sweep emitido una vela después.
4. **D2_ANTICIPACION no tiene bug de ventana.** Usa correctamente 6 velas. Las 124/8 discrepancias son cierres exactamente en el nivel barrido (`close == nivel`), no una ventana de 5 velas. Se documenta la convención, pero no se corrige la ventana.
5. **D3 y D4 reproducen su geometría al 100 %.** El problema de D3 es predictivo, no de detección. D4 tiene muy pocas señales y duplica el mismo order block en velas consecutivas.
6. **Corregir las ventanas no crea edge.** D1 añade 351/334 señales que siguen negativas; D2 añade 232/256 que empeoran el EV; D5 elimina 61/52 señales y el subconjunto que queda sigue sin significación. Son correcciones de correctitud, no una mejora de precisión predictiva.
7. **Ningún gate definitorio es robusto en ambos activos y periodos.** El único subconjunto con bootstrap por día > 0 en la ventana completa es D5 EURUSD `cuerpo >= 0,55 & distancia <= 1 ATR` h4 (n=83, WR 65,1 %, EV +21,7 %, bootstrap [+5,6, +37,6]), pero es post-hoc, solo EURUSD, y en el holdout el bootstrap vuelve a cruzar cero ([−0,3, +67,3]). No se promueve.
8. **Decisión:** mantener shadow, no modificar `core/` ni producción sin confirmación explícita. Los gates de abajo quedan pre-registrados solo para datos posteriores al 2026-11-10.

---

## 2. Método

### 2.1 Datos y etiquetas

- M15: EURUSD 24.226 velas y XAUUSD 23.160 velas (2025-11-10 → 2026-11-10).
- Señales: `results/eurusd_signals.csv` (9.104) y `results/xauusd_signals.csv` (9.070), 177 columnas.
- Etiquetas usadas: `win_h3`/`ret_h3` (cierre a +45 min) y `win_h4`/`ret_h4` (cierre a +60 min). La auditoría recalcula el retorno close-to-close desde M15 y verifica que coincide con el CSV.
- Payout: EURUSD 85/86/86/87 % (h1–h4); XAUUSD 81/82/82/83 %.
- Break-even: EURUSD h3 53,76 %, h4 53,48 %; XAUUSD h3 54,95 %, h4 54,64 %.

Las etiquetas son close-to-close, no el tick de expiración real de una opción binaria. Un empate (`ret == 0`) se cuenta como no-ganado, criterio conservador. Esto afecta pocas señales (28/27 EURUSD, 6/7 XAUUSD para h3/h4).

### 2.2 Periodos

- Descubrimiento: 2026-05-12 → 2026-09-30.
- Purga: 2026-09-30.
- Holdout: 2026-10-01 → 2026-11-10.

El holdout ya fue observado en el corte 10-N. **No se usa para seleccionar gates.** Cualquier gate que se proponga abajo se pre-registra para datos posteriores al 2026-11-10, no para este holdout.

### 2.3 Estadística

- WR con IC95 Wilson.
- EV con payout por horizonte: `EV = WR × payout − (1 − WR)`.
- Bootstrap por día (no por señal), 2.000 réplicas, semilla 20261110.
- Sin corrección FDR en esta auditoría: es descriptiva y pre-registro, no un escaneo confirmatorio. Los gates se evalúan por separado y no se promueven por p-valor nominal.

### 2.4 Reproducción

```bash
python3 tools/detector_precision.py \
    --symbols eurusd,xauusd \
    --data-dir data --results-dir results \
    --out-dir results/detector_precision
```

Salidas:

- `results/detector_precision/detector_precision_gates.csv`: 468 filas (activo × detector × gate × horizonte × periodo).
- `results/detector_precision/detector_precision_rules.json`: cumplimiento de reglas y duplicados.
- `results/detector_precision/detector_precision_resumen.txt`: resumen legible.

Conteos esperados para validar la herramienta:

| Chequeo | EURUSD | XAUUSD |
|---|---:|---:|
| Señales D1 | 2.950 | 2.930 |
| D1 faltantes con ventana de 4 | 351 | 334 |
| D2 violan ventana de 6 | 72 | 72 |
| D2 faltantes con ventana de 6 | 232 | 256 |
| D5 violan ventana de 6 | 61 | 52 |
| D5 duplicados shift 2 | 136 | 133 |
| D2A cierres exactamente en el nivel | 124 | 8 |
| D3 geometría no reproducida | 0 | 0 |
| D4 geometría no reproducida | 0 | 0 |

---

## 3. Cumplimiento de reglas

### 3.1 Tabla consolidada

| Detector | n EUR / XAU | Regla verificada | Resultado | Veredicto |
|---|---:|---|---|---|
| D1 | 2.950 / 2.930 | ruptura confirmada contra 4 velas (`inp_n_ruptura=4`) | 100 % de las emitidas cumple 4 velas; el código usa 5 velas y omite 351/334 señales | **Bug de ventana** |
| D2 | 594 / 569 | sweep + reclaim contra 6 velas previas | 100 % reproduce la ventana del código; 72/72 violan la ventana de 6; faltan 232/256 | **Bug de ventana** |
| D5 | 331 / 308 | sweep + MSS contra 6 velas previas | 61/52 (18,4 %/16,9 %) violan la ventana de 6; 136/133 duplicados; metadata en cero | **Bug de ventana + metadata + duplicados** |
| D2_ANTICIPACION | 2.451 / 2.604 | mecha rompe rango de 6 velas y cierra adentro | ventana de 6 correcta; 124/8 cierran exactamente en el nivel | **Sin bug de ventana; convención de borde** |
| D3 | 74 / 32 | FVG: dirección, top, bottom, tamaño ATR | 100 % reproducible | **Detección correcta; edge negativo** |
| D3_DEF | 2.700 / 2.608 | ídem | 100 % reproducible | **Detección correcta; edge negativo** |
| D4 | 4 / 19 | order block: high/low, dirección | 100 % reproducible; 2/4 y 12/19 duplicados | **Detección correcta; muestra ínfima + duplicados** |

### 3.2 D1 — ventana de 5 velas en vez de 4

Código: `core/d1_ruptura.py`.

```python
highest_high = ctx._i_high(ctx.df_m15, 1)
lowest_low = ctx._i_low(ctx.df_m15, 1)
for k in range(2, ctx.inp_n_ruptura + 2):   # con inp_n_ruptura=4 -> k=2..5
```

El rango efectivo es shifts 1..5 (5 velas), no 1..4. Consecuencias:

- **No hay falsos positivos de dirección:** las 2.950/2.930 señales emitidas también cumplen la regla de 4 velas.
- **Hay señales omitidas:** 351 EURUSD y 334 XAUUSD (11,9 %/11,4 % del volumen emitido) cumplen la regla de 4 velas pero el código las descarta.
- El `nivel_ruptura`, la penetración y el `range_break_pips` de las señales emitidas se calculan contra el rango de 5 velas, no el de 4. Eso cambia los filtros informacionales, aunque no la dirección.

Impacto predictivo de añadir las señales omitidas (h3/h4):

| Activo | Conjunto | n | h3 WR / EV | h4 WR / EV |
|---|---|---:|---|---|
| EURUSD | emitidas (5 velas) | 2.950 | 45,8 % / −14,9 % | 46,8 % / −12,5 % |
| EURUSD | añadidas (4 velas) | 351 | 46,7 % / −13,1 % | 46,7 % / −12,6 % |
| XAUUSD | emitidas (5 velas) | 2.930 | 47,8 % / −13,1 % | 47,9 % / −12,4 % |
| XAUUSD | añadidas (4 velas) | 334 | 46,7 % / −15,0 % | 50,3 % / −8,0 % |

Las añadidas siguen negativas. Corregir D1 es correctitud, no edge.

### 3.3 D2 — se salta la vela inmediatamente anterior al sweep

Código: `core/d2_sweep.py`.

```python
for i in range(1, 2):                 # sweep en shift 1
    ph = ctx._i_high(ctx.df_m15, i + 2)   # empieza en shift 3
    for k in range(i + 2, i + ctx.inp_sweep_n + 1):
        # k = 3..7, no 2..7
```

Con `inp_sweep_n=6`, el rango previo debería ser shifts 2..7 (6 velas). El código usa 3..7 (5 velas) y **omite el shift 2**, la vela inmediatamente anterior al sweep. Consecuencias:

- 72/72 señales EURUSD y 72/72 XAUUSD (12,1 %/12,7 %) no cumplen la regla corregida: el sweep se evaluó contra un rango más estrecho.
- 232/256 señales adicionales cumplen la regla corregida y no se emitieron.
- El conjunto corregido sería 594 − 72 + 232 = 754 EURUSD y 569 − 72 + 256 = 753 XAUUSD (antes de otros filtros).

Impacto predictivo:

| Activo | Conjunto | n | h3 WR / EV | h4 WR / EV |
|---|---|---:|---|---|
| EURUSD | se mantiene | 522 | 51,3 % / −4,5 % | 51,7 % / −3,3 % |
| EURUSD | se elimina (viola 6) | 72 | 51,4 % / −4,4 % | 55,6 % / +3,9 % |
| EURUSD | se añade (6 velas) | 232 | 49,1 % / −8,6 % | 48,3 % / −9,7 % |
| XAUUSD | se mantiene | 497 | 52,7 % / −4,1 % | 50,1 % / −8,3 % |
| XAUUSD | se elimina (viola 6) | 72 | 38,9 % / −29,2 % | 51,4 % / −6,0 % |
| XAUUSD | se añade (6 velas) | 256 | 45,3 % / −17,5 % | 50,8 % / −7,1 % |

En EURUSD, las señales que la regla corregida elimina son mejores que las que añade; el EV agregado empeora. En XAUUSD, eliminar las 72 mejora el h3 pero añadir 256 lo empeora. **Corregir la ventana no mejora la precisión predictiva.**

### 3.4 D5 — misma ventana que D2, más metadata rota y duplicados

Código: `core/d5_mss_sweep.py`.

- Usa el mismo patrón `i + 2` que D2. Para sweep en shift 1 cubre 3..7; para shift 2 cubre 4..8. Debería cubrir 2..7 y 3..8.
- 61/331 EURUSD (18,4 %) y 52/308 XAUUSD (16,9 %) violan la ventana corregida.
- **Metadata:** no asigna `sig.sweep_bars_ago` ni `sig.sweep_volume_ratio`. Quedan en 0 y 0,0 en el 100 % de las señales. `calcular_calidad_sweep` usa `bars_ago=0` (máximo de 15 puntos por recencia) y `vol=0` (0 de 10 puntos por volumen). El score de calidad está mal.
- **Duplicados:** el mismo sweep se detecta en shift 1 y, una vela después, en shift 2. Son 136/331 EURUSD (41,1 %) y 133/308 XAUUSD (43,2 %). El latch del motor no los bloquea porque el `signal_id` incluye el timestamp de la vela.

Impacto de la corrección de ventana:

| Activo | Conjunto | n | h3 WR / EV | h4 WR / EV |
|---|---|---:|---|---|
| EURUSD | se mantiene | 270 | 52,6 % / −2,2 % | 56,7 % / +6,0 % |
| EURUSD | se elimina (viola 6) | 61 | 54,1 % / +0,6 % | 60,7 % / +13,4 % |
| XAUUSD | se mantiene | 256 | 48,8 % / −11,1 % | 48,8 % / −10,6 % |
| XAUUSD | se elimina (viola 6) | 52 | 44,2 % / −19,5 % | 42,3 % / −22,6 % |

En EURUSD, la corrección elimina señales que en bruto eran mejores; el subconjunto que queda sigue sin bootstrap > 0. En XAUUSD, la corrección mejora algo el h3 pero sigue negativo. Otra vez: correctitud, no edge.

Al deduplicar D5 (quitar los 136/133 del shift 2), el agregado EURUSD h4 pasa de n=331, WR 57,4 %, EV +7,3 % a n=195, WR 56,4 %, EV +5,5 %; XAUUSD h4 pasa a n=175, WR 46,9 %, EV −14,3 %. La señal positiva de D5 EURUSD no depende solo de los duplicados, pero se debilita.

### 3.5 D2_ANTICIPACION — no hay bug de ventana

Código: `core/d2_anticipacion.py`.

```python
prior_high = ctx._i_high(ctx.df_m15, 1)
for k in range(2, ctx.inp_sweep_n + 1):   # inp_sweep_n=6 -> k=2..6
```

El rango es shifts 1..6: **6 velas, correcto**. Las 124 EURUSD y 8 XAUUSD que la verificación estricta marca como “no cumplen” tienen `close == prior_high` o `close == prior_low` exactamente. El código usa `>`/`<` para el cierre adentro, así que acepta el cierre en el nivel; la verificación estricta usa `>`/`<` y lo rechaza. No es una ventana de 5 velas.

Si se adoptara la convención estricta (“el cierre debe quedar estrictamente adentro”), se eliminarían 124/8 señales. En EURUSD h4 esas señales tienen WR 54,0 %, EV +1,0 %, frente a 50,3 %/−6,0 % del resto; eliminarlas empeoraría el agregado. No hay razón predictiva para cambiarlo. Se documenta la convención y se deja como está.

### 3.6 D3 y D4 — geometría correcta

- **D3/D3_DEF:** dirección, `fvg_top`, `fvg_bottom` y `fvg_size_atr` se reproducen al 100 % en ambos activos. El problema es que el FVG no predice; no es un bug de detección.
- **D4:** `ob_high`/`ob_low` se reproducen al 100 %, pero solo hay 4 señales EURUSD y 19 XAUUSD; 2/4 y 12/19 son el mismo OB emitido en velas consecutivas (el bucle `range(2,5)` lo encuentra en shifts distintos). La muestra es demasiado pequeña para concluir nada.

---

## 4. Auditoría de filtros

### 4.1 Filtros que más fallan

| Detector | Filtro | EURUSD | XAUUSD |
|---|---|---:|---:|
| D1 | volumen | 100,0 % | 100,0 % |
| D1 | penetración ATR | 65,6 % | 66,9 % |
| D1 | body ratio | 14,5 % | 16,8 % |
| D1 | retest | 0,7 % | 0,7 % |
| D2 | reclaim | 78,8 % | 79,8 % |
| D2 | distancia al nivel | 2,0 % | 2,8 % |
| D5 | reclaim | 81,3 % | 81,8 % |
| D2A | confluencia OB | 98,9 % | 98,7 % |
| D2A | confluencia FVG | 93,1 % | 93,7 % |
| D2A | confluencia MSS | 69,9 % | 70,0 % |
| D2A | wick ratio | 35,1 % | 38,6 % |
| D3_DEF | tamaño FVG | 36,1 % | 38,2 % |
| D3_DEF | body FVG | 22,4 % | 24,5 % |
| D3_DEF | dirección FVG | 0,7 % | 1,1 % |

### 4.2 Subconjuntos que cumplen todos los filtros definitorios

| Detector | Subconjunto | EURUSD | XAUUSD |
|---|---|---:|---:|
| D1 | penetración + body + retest | 982 (33,3 %) | 925 (31,6 %) |
| D2 | reclaim | 126 (21,2 %) | 115 (20,2 %) |
| D5 | reclaim | 62 (18,7 %) | 56 (18,2 %) |
| D2A | confluencias >= 2 | 63 (2,6 %) | 58 (2,2 %) |
| D3_DEF | tamaño + body + dirección | 1.481 (54,9 %) | 1.384 (53,1 %) |

Ninguno de estos subconjuntos supera el break-even de forma robusta. El detalle de WR/EV está en la sección 5.

### 4.3 El problema del volumen

El CSV de Deriv no trae volumen: `volume = 0` en las 24.226/23.160 velas. Eso rompe:

- **D1:** `get_volume_ratio_cached` devuelve 1,0 cuando no hay volumen; el umbral `>= 1,2` nunca se cumple. El filtro de volumen falla en el 100 % de las señales. Es informacional, no bloquea la emisión, pero el score y el tipo pierden una dimensión.
- **D2:** `sweep_volume_ratio = 1,0`. El clasificador exige `> 1,80` para A y `> 1,50` para B; **D2 no puede generar tipos A/B**. En los datos, D2 solo tiene C/D.
- **D2A:** `sweep_volume_ratio = 1,0`; el clasificador exige `> 1,50`/`> 1,20`; **D2A tampoco puede generar A/B**. Solo tiene C/D.
- **D5:** no asigna el campo; queda 0,0. El clasificador de D5 no usa volumen, así que sí puede generar A/B, pero `calidad_sweep` pierde los 10 puntos de volumen y suma los 15 de recencia por `bars_ago=0`.
- **`tipo` no es monótono:** en EURUSD h3, A 43,4 %, B 47,8 %, C 49,3 %, D 48,3 %; en XAUUSD h3, A 49,6 %, B 46,6 %, C 47,7 %, D 49,0 %. El tipo no ordena por calidad predictiva.

**Conclusión:** mientras el feed no traiga volumen real, los filtros y scores de volumen no son evidencia de nada. No se debe usar `tipo A/B` como criterio de promoción. Si se corrige la metadata de D5, el campo debe quedar en `null`/`NaN` cuando no hay volumen, no en 0.

---

## 5. Precisión predictiva por detector

### 5.1 Agregado (todas las señales del detector)

| Activo | Detector | n | h3 WR | h3 EV | h3 bootstrap | h4 WR | h4 EV | h4 bootstrap |
|---|---|---:|---:|---:|---|---:|---:|---|
| EURUSD | D1 | 2.950 | 45,8 % | −14,9 % | [−19,0, −10,9] | 46,8 % | −12,5 % | [−16,1, −9,0] |
| EURUSD | D2 | 594 | 51,4 % | −4,5 % | [−11,4, +2,7] | 52,2 % | −2,4 % | [−10,0, +5,3] |
| EURUSD | D2A | 2.451 | 51,0 % | −5,2 % | [−8,9, −1,5] | 50,5 % | −5,6 % | [−9,5, −1,7] |
| EURUSD | D3 | 74 | 41,9 % | −22,1 % | [−44,0, −1,7] | 37,8 % | −29,2 % | [−50,0, −9,0] |
| EURUSD | D3_DEF | 2.700 | 46,9 % | −12,8 % | [−16,8, −8,8] | 47,9 % | −10,5 % | [−14,2, −6,6] |
| EURUSD | D5 | 331 | 52,9 % | −1,7 % | [−13,8, +9,7] | 57,4 % | +7,3 % | [−5,1, +19,7] |
| XAUUSD | D1 | 2.930 | 47,8 % | −13,1 % | [−16,6, −9,7] | 47,9 % | −12,4 % | [−15,8, −8,8] |
| XAUUSD | D2 | 569 | 51,0 % | −7,2 % | [−14,8, +0,8] | 50,3 % | −8,0 % | [−15,5, −1,0] |
| XAUUSD | D2A | 2.604 | 48,9 % | −11,0 % | [−15,1, −6,7] | 48,5 % | −11,2 % | [−14,7, −7,4] |
| XAUUSD | D3 | 32 | 46,9 % | −14,7 % | [−49,4, +23,3] | 46,9 % | −14,2 % | [−42,8, +15,9] |
| XAUUSD | D3_DEF | 2.608 | 48,8 % | −11,2 % | [−14,6, −7,7] | 50,0 % | −8,6 % | [−11,7, −5,4] |
| XAUUSD | D5 | 308 | 48,0 % | −12,6 % | [−22,5, −1,5] | 47,7 % | −12,7 % | [−24,2, −1,5] |

Solo D5 EURUSD h4 tiene EV puntual positivo con bootstrap que no cruza cero en la ventana completa, y no sobrevive al holdout ni se replica en XAUUSD. D2 es el único detector con EV cercano a cero en ambos activos, pero sigue negativo; D1, D2A y D3/D3_DEF son claramente negativos.

### 5.2 Gates definitorios (mejor subconjunto de cada detector)

| Activo | Detector | Gate | n | h | WR | EV | Bootstrap |
|---|---|---|---:|---:|---:|---:|---|
| EURUSD | D1 | pen + body + retest | 982 | h4 | 46,1 % | −13,7 % | [−19,9, −7,5] |
| XAUUSD | D1 | pen + body + retest | 925 | h4 | 49,5 % | −9,4 % | [−15,6, −3,2] |
| EURUSD | D2 | cuerpo >= 0,55 & dist <= 1 ATR | 146 | h4 | 55,5 % | +3,8 % | [−11,4, +19,2] |
| XAUUSD | D2 | cuerpo >= 0,55 & dist <= 1 ATR | 144 | h4 | 58,3 % | +6,8 % | [−6,7, +20,6] |
| EURUSD | D2A | confluencias >= 2 | 63 | h3 | 60,3 % | +12,2 % | [−16,0, +37,2] |
| XAUUSD | D2A | confluencias >= 2 | 58 | h3 | 44,8 % | −18,4 % | [−44,2, +7,4] |
| EURUSD | D3 | size + body + dir | 37 | h3 | 46,0 % | −14,5 % | [−43,2, +12,6] |
| XAUUSD | D3 | size + body + dir | 14 | h3 | 57,1 % | +4,0 % | [−48,0, +54,0] |
| EURUSD | D3_DEF | size + body + dir | 1.481 | h4 | 48,5 % | −9,2 % | [−14,0, −4,6] |
| XAUUSD | D3_DEF | size + body + dir | 1.384 | h4 | 49,7 % | −9,0 % | [−13,6, −4,5] |
| EURUSD | D5 | cuerpo >= 0,55 & dist <= 1 ATR | 83 | h4 | 65,1 % | +21,7 % | [+5,6, +37,6] |
| XAUUSD | D5 | cuerpo >= 0,55 & dist <= 1 ATR | 87 | h4 | 51,7 % | −5,3 % | [−23,1, +13,6] |

Lectura:

- **D1:** ningún gate se acerca al break-even. El mejor sigue 4–9 pp por debajo.
- **D2:** `cuerpo >= 0,55 & dist <= 1 ATR` es positivo en ambos activos y en h3/h4, pero el IC y el bootstrap cruzan cero. Es el gate más consistente de la auditoría, pero no está confirmado.
- **D2A:** `confluencias >= 2` es positivo en EURUSD y negativo en XAUUSD. No se replica.
- **D3/D3_DEF:** negativo en EURUSD; en XAUUSD solo mejora en la muestra pequeña de D3 (n=14). D3_DEF es negativo en ambos.
- **D5:** el gate de cuerpo + distancia es positivo solo en EURUSD. En XAUUSD es negativo. n=83, holdout n=23, bootstrap del holdout cruza cero.

### 5.3 D5 EURUSD: el “mejor” hallazgo y por qué no se promueve

`D5 · cuerpo >= 0,55 & distancia <= 1 ATR · h4`:

| Periodo | n | WR | IC95 | EV | Bootstrap |
|---|---:|---:|---|---:|---|
| Total | 83 | 65,1 % | 54,3–74,4 | +21,7 % | [+5,6, +37,6] |
| Descubrimiento | 60 | 63,3 % | 50,7–74,4 | +18,4 % | [−1,8, +37,6] |
| Holdout | 23 | 69,6 % | 49,1–84,4 | +30,1 % | [−0,3, +67,3] |

Al deduplicar D5 (quitar los 136 duplicados del shift 2), el gate queda en n=40, WR 70,0 %, EV +30,9 % h4; de esas 40, 34 cumplen la ventana corregida de 6 velas y dan WR 67,6 %, EV +26,5 %. Es todavía más fuerte en punto, pero:

- Es un gate **post-hoc**, elegido después de ver la ventana completa. No estaba pre-registrado.
- Solo funciona en EURUSD; en XAUUSD el mismo gate da EV −5,3 % h4.
- n=40 tras deduplicar, 34 tras corregir la ventana. El IC95 inferior ronda el break-even; el bootstrap del holdout cruza cero.
- El campo `filtro_reclaim_ratio` mide el cuerpo de la vela, no el reclaim completo (no exige cierre más allá del nivel en la dirección del MSS). El “reclaim definitorio” (booleano) con dist <= 1 da n=25, WR 64,0 %, EV +19,7 %, bootstrap [−14,4, +52,4]. Es otra definición y no es más robusta.
- La estabilidad mensual del gate deduplicado es 6/7 meses positivo en h4, pero julio es −6 % y junio +12 % con n=10; no alcanza el criterio de 4/5 meses con n suficiente.

**Veredicto:** hipótesis de investigación, no candidato promovible. Se pre-registra para forward (sección 6), no para operar.

### 5.4 Reversión de dirección

- D1 invertido: ~53,3 % EURUSD h3 y 52,2 % XAUUSD h3. Por debajo del break-even (53,76 %/54,95 %). No hay edge.
- D3 invertido: 58,1 % EURUSD h3 (n=74), 60,8 % h4; holdout 60,0 %/66,7 % (n=15). Es inestable y de muestra pequeña; invertir un detector porque falló no es una hipótesis independiente.
- No hay evidencia de un edge de reversión robusto.

---

## 6. Gates pre-registrados para forward

Estos criterios se fijan **antes** de mirar datos posteriores al 2026-11-10. El holdout 2026-10-01 → 2026-11-10 ya fue observado y **no** cuenta como confirmación.

### 6.1 Correctitud (debe cumplirse al 99 %)

| Detector | Criterio | Estado actual |
|---|---|---|
| D1 | 100 % de las señales emitidas cumple la ventana de 4 velas; no se usa la 5.ª vela | las emitidas cumplen 4, pero el código usa 5 y omite 351/334 |
| D2 | ≥ 99 % cumple la ventana de 6 velas (shifts 2..7 para sweep en shift 1) | 87,9 % EURUSD / 87,3 % XAUUSD |
| D5 | ≥ 99 % cumple la ventana de 6 velas; duplicados shift 2 < 1 %; `sweep_bars_ago` en {1,2}; `sweep_volume_ratio` no nulo si hay volumen | 81,6 %/83,1 %; duplicados 41,1 %/43,2 %; metadata 0 en el 100 % |
| D4 | duplicados del mismo OB en ≤ 3 velas < 1 % | 50 % EURUSD / 63,2 % XAUUSD |
| D3/D3_DEF | geometría (dirección, top, bottom, tamaño ATR) ≥ 99,9 % | 100 % |
| D2A | ventana de 6 velas ≥ 99,9 %; convención de cierre en el nivel documentada | ventana correcta; 124/8 cierres exactamente en el nivel |

La corrección de D1/D2/D5/D4 debe evaluarse en shadow como **cambio de correctitud**. No se permite seleccionar gates ni ajustar umbrales usando el mismo tramo forward.

### 6.2 Promoción predictiva (ningún subset se promueve sin esto)

Un gate solo puede pasar a demo si, en datos **posteriores al 2026-11-10** y sin haber sido reajustado:

1. Está pre-registrado antes de mirar ese tramo.
2. Tiene `n >= 100` en el tramo forward.
3. `WR > break-even` con IC95 Wilson inferior > break-even, en h3 **y** h4 (o en el horizonte pre-registrado, con el otro como control).
4. Bootstrap por día con EV inferior > 0.
5. Se replica en el otro activo o tiene un mecanismo explícito que justifique por qué no. Si no se replica, no se promueve.
6. Es positivo en ≥ 4 de 5 meses y en ≥ 70 % de las semanas del tramo forward.
7. Sigue positivo con payout −3 pp.
8. h1–h3 validados contra producción; h4 hoy no está validado (3 filas EURUSD, 6 XAUUSD).

### 6.3 Candidatos pre-registrados para forward (no promovidos)

| ID | Activo | Detector | Gate | Horizonte | Estado |
|---|---|---|---|---|---|
| F1 | EURUSD + XAUUSD | D2 | `filtro_reclaim_ratio >= 0,55` y `filtro_distancia_nivel <= 1,0` | h4 (h3 control) | Positivo en ambos, bootstrap cruza cero; el más consistente |
| F2 | EURUSD | D5 deduplicado | `filtro_reclaim_ratio >= 0,55` y `filtro_distancia_nivel <= 1,0` | h4 | n=40, WR 70,0 %, EV +30,9 %; solo EURUSD; no confirmado |
| F3 | EURUSD | D5 | `reclaim` booleano y `distancia <= 1` | h4 | n=25, WR 64,0 %, EV +19,7 %; muestra insuficiente |
| F4 | EURUSD | D2A | `confluencias >= 2` | h3/h4 | n=63, positivo; XAUUSD negativo; no se replica |

F1 es el único con la misma dirección en ambos activos. F2/F3 son exploratorios por tamaño y por usar una definición de cuerpo que no es el reclaim completo. Ninguno se usa para operar.

### 6.4 Qué no se hará

- No se cambiará `core/` ni producción sin confirmación explícita.
- No se reiniciarán servicios.
- No se usará el holdout observado para elegir gates.
- No se optimizarán TP/SL ni se hará k-fold aleatorio.
- No se promoverá nada por un p-valor nominal sin FDR cuando corresponda un escaneo.

---

## 7. Plan de corrección propuesto (sin aplicar)

Los cambios de código quedan pendientes de confirmación. No se aplicaron en este corte.

| Archivo | Cambio propuesto | Motivo |
|---|---|---|
| `core/d1_ruptura.py` | `range(2, ctx.inp_n_ruptura + 1)` para cubrir shifts 1..4 | off-by-one; el parámetro dice 4 |
| `core/d2_sweep.py` | inicializar `ph/pl` en `i + 1` y recorrer `i + 2 .. i + inp_sweep_n` | incluir la vela inmediatamente anterior al sweep |
| `core/d5_mss_sweep.py` | misma ventana que D2; asignar `sweep_bars_ago` y `sweep_volume_ratio`; deduplicar el sweep de shift 2 | ventana, metadata y duplicados |
| `core/d5_mss_sweep.py` | si no hay volumen, dejar `sweep_volume_ratio` en `null`/`NaN` y no puntuar volumen | el feed Deriv no trae volumen |
| `core/d4_orderblock.py` | deduplicar el mismo OB (high/low + dirección) dentro de 3 velas | 2/4 y 12/19 duplicados |
| `core/d2_anticipacion.py` | sin cambio de ventana; solo documentar la convención de cierre en el nivel | no hay bug de ventana |
| `core/scoring.py` | revisar `calcular_calidad_sweep` cuando `bars_ago=0` o `vol=0` | el score actual premia recencia inexistente y castiga volumen ausente |

Cualquier cambio debe ir acompañado de tests unitarios que fijen las ventanas y los conteos de esta tabla, y de una comparación forward en shadow (sin reutilizar el tramo que se usó para elegir el cambio).

---

## 8. Límites

- El holdout 2026-10-01 → 2026-11-10 ya fue observado; no es una confirmación independiente de los gates de la sección 6.
- Las etiquetas son close-to-close, no el tick de expiración de la opción. Los empates se cuentan como no ganados.
- El payout es el real por horizonte, pero puede cambiar; no se modela slippage ni latencia.
- `volume = 0` en todo el CSV; los filtros y scores de volumen no son informativos.
- D4 tiene 4/19 señales; cualquier conclusión sobre D4 es anecdótica.
- D3 estricto tiene 74/32 señales; D3_DEF es la versión con más muestra. Los resultados de D3 no son comparables 1:1 con D3_DEF.
- La auditoría es descriptiva y no aplica FDR; los gates se evalúan por separado y no se promueven por p-valor nominal.
- El replay cubre ~82 % de las señales de producción; las conclusiones se apoyan también en la DB de producción para no depender solo del replay.
- h4 no está validado contra producción (3 filas EURUSD, 6 XAUUSD).
- La extensión forward 9–10/N es de dos días; no alcanza para confirmar nada.

---

## 9. Artefactos

- `results/detector_precision/detector_precision_gates.csv` — 468 filas de gates × horizonte × periodo.
- `results/detector_precision/detector_precision_rules.json` — reglas, ventanas, duplicados y metadata.
- `results/detector_precision/detector_precision_resumen.txt` — resumen legible.
- `tools/detector_precision.py` — herramienta reproducible.
- [`docs/EDGE_FINDINGS.md`](EDGE_FINDINGS.md) — veredicto live y holdout.
- [`docs/RESULTS_SUMMARY.md`](RESULTS_SUMMARY.md) — resumen tabular.
- [`docs/VALIDATION_PROTOCOL.md`](VALIDATION_PROTOCOL.md) — protocolo pre-registrado.
- [`docs/LIMITATIONS.md`](LIMITATIONS.md) — sesgos y deuda técnica.
