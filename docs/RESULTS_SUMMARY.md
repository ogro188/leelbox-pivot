# Resumen de resultados

**Corte:** 2026-11-10 UTC. **Re-baseline con contexto causal:** 2026-11-09 UTC. **Extensión forward y ventana móvil:** 2026-11-10 UTC.
**Regla:** un resultado solo se considera confirmado si cumple el criterio estricto de `docs/VALIDATION_PROTOCOL.md`. Los resultados nominales se incluyen para auditoría, no como recomendación.

---

## 1. Tabla global

| Estudio | Activo | Tests | Supervivientes FDR | Estado |
|---|---|---:|---:|---|
| Señales PIVOT (`edge_scan`, descubrimiento) | EURUSD | 456 | **0** | Negativo |
| Señales PIVOT (`edge_scan`, ventana completa) | EURUSD | 456 | **0** | Negativo |
| Señales PIVOT (`edge_scan`, descubrimiento) | XAUUSD | 448 | **0** | Negativo |
| Señales PIVOT (`edge_scan`, ventana completa) | XAUUSD | 456 | **0** | Negativo |
| Velas M15 (`bar_edge`) | EURUSD | 464 | **0** | Negativo |
| Velas M15 (`bar_edge`) | XAUUSD | 462 | **0** | Negativo |
| Patrones intradía (`pattern_edge`) | EURUSD | 168 | **0** | Negativo |
| Patrones intradía (`pattern_edge`) | XAUUSD | 184 | **0** | Negativo |
| OTC (`otc_validate`) | EURUSD-OTC | 88 (h3) | — | Falsificado |
| OTC (`otc_validate`) | XAUUSD-OTC | 133 (h3) | — | Hipótesis, no confirmado |

Ningún test de ningún escaneo alcanzó `q ≤ 0,10` con los criterios adicionales.

**Nota sobre XAUUSD:** los 448 tests son de la ventana de descubrimiento (6.950 señales, hasta 2026-09-30). En la ventana completa (9.070 señales) son 456 tests (220 primarios). En ambas ventanas: 0 supervivientes.

**Nota sobre `bar_edge` y `pattern_edge`:** el baseline anterior usaba ~6 meses de M15; el corte del 9-N usó 12 meses fijos y el del 10-N usa una **ventana móvil de 12 meses** (2025-11-10 → 2026-11-10). Las cifras de `n`, WR y p no son comparables entre cortes. Con la misma ventana, el código anterior y el actual producen exactamente los mismos 464/462 tests. Ver `docs/REFERENCE_FIX.md` y `docs/UPDATE_2026-11-10.md`.

---

## 2. Señales PIVOT — escaneo principal

**Datos:** replay con inicio fijo 2026-05-05 08:30 UTC y extensión hasta 2026-11-10; 9.104 señales EURUSD y 9.070 XAUUSD. Contexto superior causal.
**Descubrimiento:** 2026-05-12 → 2026-09-29; **holdout:** 2026-10-01 → 2026-11-10 (pre-registrado hasta 2026-11-06).
**Payout:** EURUSD 85/86/86/87 %; XAUUSD 81/82/82/83 % (h1–h4).

### 2.1 Descubrimiento y ventana completa

| Activo | Ventana | Tests | Primarios n ≥ 100 | Mejor p | Condición | q |
|---|---|---|---:|---:|---|---:|
| EURUSD | Descubrimiento | 456 | 220 | 0,2803 | `det_d5` h4 (n=255, WR 55,3 %, EV +3,40 %) | 1,000 |
| EURUSD | Completa | 456 | 224 | 0,0761 | `det_d5` h4 (n=331, WR 57,4 %, EV +7,34 %) | 1,000 |
| XAUUSD | Descubrimiento | 448 | 220 | 0,7020 | `tipo_a` h4 (n=405, WR 53,3 %, EV −2,40 %) | 1,000 |
| XAUUSD | Completa | 456 | 220 | 0,9090 | `tipo_a` h4 (n=520, WR 51,7 %, EV −5,33 %) | 1,000 |

### 2.2 “Casi” que no es

`det_d5` h4 EURUSD:

| Ventana | n | WR | EV | p | Bootstrap 95 % |
|---|---|---:|---:|---:|---|
| Descubrimiento | 255 | 55,3 % | +3,40 % | 0,2803 | [−10,24, +17,05] |
| Ventana completa | 331 | 57,4 % | +7,34 % | 0,0761 | [−4,60, +19,47] |

El resultado completo lo aporta octubre (n=59, WR 67,8 %, EV +26,78 %); julio fue −23,0 % y la extensión de noviembre −1,0 %. **No es un hallazgo pre-registrado ni confirmado.**

### 2.3 Holdout

Ventana extendida (2026-10-01 → 2026-11-10):

| Activo | h | n | WR | IC95 | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---|
| EURUSD | h3 base | 2.107 | 48,6 % | 46,5–50,7 | −9,60 % | [−15,18, −4,28] |
| XAUUSD | h3 base | 2.048 | 48,2 % | 46,1–50,4 | −12,20 % | [−16,28, −7,90] |

Ventana pre-registrada original (2026-10-01 → 2026-11-06), re-medida con el corpus actualizado:

| Activo | h | n | WR | IC95 | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---|
| EURUSD | h3 base | 1.967 | 48,8 % | 46,6–51,0 | −9,32 % | [−15,30, −3,40] |
| XAUUSD | h3 base | 1.921 | 47,8 % | 45,6–50,1 | −12,93 % | [−16,94, −8,53] |

Las 32 combinaciones a priori evaluadas en holdout son negativas en ambos activos. La extensión forward 9–10/N (140 señales EURUSD, 127 XAUUSD) también es negativa en EURUSD (h3 EV −13,64 %) y prácticamente neutra en XAUUSD (h3 EV −1,12 %, h4 +0,87 %), sin significación. **Es confirmación débil de dos días, no un holdout independiente.**

### 2.4 Producción real

| Activo | h | n | WR | EV |
|---|---|---:|---:|---:|
| EURUSD | 1 | 1.089 | 48,30 % | −10,64 % |
| EURUSD | 2 | 1.006 | 49,01 % | −8,85 % |
| EURUSD | 3 | 959 | 48,07 % | −10,59 % |
| XAUUSD | 1 | 990 | 46,26 % | −16,26 % |
| XAUUSD | 2 | 911 | 47,09 % | −14,29 % |
| XAUUSD | 3 | 878 | 44,65 % | −18,74 % |

Excepciones positivas por detector: EURUSD D2 h2 (n=52, +14,46 %), EURUSD D2 h3 (n=47, +2,89 %), XAUUSD D5 h3 (n=31, +5,68 %). Son submuestras pequeñas, no sobreviven corrección múltiple y no son estables.

### 2.5 Auditoría de detectores

Detalle completo en [`docs/DETECTOR_PRECISION.md`](DETECTOR_PRECISION.md). Resumen:

| Detector | Hallazgo de regla | Veredicto predictivo |
|---|---|---|
| D1 | usa 5 velas en vez de 4; omite 351/334 señales | EV −12,5 % a −14,9 %; corregir no crea edge |
| D2 | usa 5 velas y se salta el shift 2; 72/72 violan la regla de 6 | EV −2,4 % a −8,0 %; el gate cuerpo+distancia queda sin confirmar |
| D5 | misma ventana que D2; 61/52 violan; 136/133 duplicados; metadata en cero | EURUSD h4 +7,3 % nominal, no confirmado; XAUUSD negativo |
| D2A | ventana de 6 correcta; 124/8 cierres exactamente en el nivel | EV −5,2 % a −11,2 %; sin bug de ventana |
| D3 / D3_DEF | geometría 100 % reproducible | EV negativo en ambos activos |
| D4 | geometría 100 %; 2/4 y 12/19 duplicados | muestra ínfima; no concluyente |

El 81,4 %/82,8 % de las señales falla al menos un filtro propio. El volumen del CSV es 0 en el 100 % de las velas, por lo que los filtros y scores de volumen están sistemáticamente rotos. Ningún gate definitorio es robusto en ambos activos y periodos; los candidatos quedan pre-registrados para forward en `docs/DETECTOR_PRECISION.md`, sin promover.

---

## 3. Ablación

Winrate h1–h4 (%):

| Variante | EURUSD | XAUUSD |
|---|---|---|
| H4_only | 49,2 / 49,8 / 49,7 / 49,7 | 51,0 / 51,0 / 51,0 / 50,9 |
| H1_only | 49,2 / 49,4 / 49,8 / 49,6 | 50,4 / 50,3 / 50,0 / 50,0 |
| H4+H1 | 49,2 / 49,7 / 49,9 / 49,7 | 51,0 / 50,9 / 50,7 / 50,7 |
| siempre_long | 48,7 / 48,8 / 48,8 / 48,7 | 50,5 / 50,0 / 49,9 / 50,0 |
| PIVOT | 47,6 / 48,5 / 48,1 / 48,8 | 48,2 / 48,7 / 48,6 / 48,8 |
| PIVOT+H4+H1 | 47,8 / 48,3 / 47,6 / 48,5 | 48,3 / 49,3 / 48,1 / 47,8 |

EV: todos negativos, entre −6,8 % y −12,7 %. PIVOT está igual o por debajo de `siempre_long` (hasta 2,3 pp). **No hay habilidad direccional medible.**

---

## 4. Escaneo a nivel de vela

**Datos:** ventana móvil de 12 meses M15 (2025-11-10 → 2026-11-10); descubrimiento hasta 2026-09-30; holdout desde 2026-10-01.
**Familias:** calendario, momentum/reversión, RSI14, volatilidad, EMA50, cuerpo/rango.

| Activo | Tests | Supervivientes | Top nominal (p) |
|---|---:|---:|---|
| EURUSD | 464 | **0** | `rsi_lt30_L` h3: n=880, WR 55,8 %, EV +3,78 %, p=0,1133, q=1,0 |
|  |  |  | `hora_16_S` h4: n=920, WR 55,3 %, EV +3,46 %, p=0,1303, q=1,0 |
| XAUUSD | 462 | **0** | `hora_21_S` h2: n=122, WR 59,0 %, EV +7,41 %, p=0,1830, q=1,0 |
|  |  |  | `hora_21_S` h1: n=183, WR 57,4 %, EV +3,85 %, p=0,2813, q=1,0 |

**Cambio de ventana:** el baseline anterior usaba ~6 meses (n≈428 por hora); el corte del 9-N usó 12 meses fijos (n≈928 por hora) y el actual usa una ventana móvil de 12 meses. Las cifras no son comparables entre cortes. Con la misma ventana, el código anterior y el actual producen exactamente los mismos 464/462 tests; `bar_edge.py` no usa el contexto superior. **No hay candidato promovible.**

---

## 5. Patrones intradía

**Datos:** ventana móvil de 12 meses M15 (2025-11-10 → 2026-11-10); descubrimiento 2025-11-10 → 2026-04-30; validación 2026-05-01 → 2026-07-31; test 2026-08-01 → 2026-11-10.

| Activo | Tests | Supervivientes | Top nominal (p) |
|---|---:|---:|---|
| EURUSD | 168 | **0** | `LOR3 break fade` h8: n=112, WR 65,2 %, EV +21,88 %, p=0,0065, q=0,764 |
|  |  |  | `NYOR13 break fade` h2: n=116, WR 62,9 %, EV +17,05 %, p=0,0238, q=0,764 |
| XAUUSD | 184 | **0** | `LOR4 break fade` h8: n=70, WR 70,0 %, EV +28,10 %, p=0,0049, q=0,907 |
|  |  |  | `LOR3 break fade` h6: n=113, WR 64,6 %, EV +18,22 %, p=0,0167, q=1,0 |

### NYOR13 fade h1 (EURUSD)

- n=118, WR 58,47 %, EV +8,18 %, IC95 49,45–66,96, p=0,1676, q=1,0.
- No sobrevive FDR ni el criterio de IC inferior > break-even.
- Las ventanas de validación/test de la corrida original fueron positivas, pero no son confirmatorias y no se usaron para seleccionar.
- **Estado:** hipótesis exploratoria, no edge.

### XAUUSD LOR4 fade h8

- n=70, WR 70,0 %, EV +28,10 %, p=0,0049, q=0,907.
- Muestra pequeña; no sobrevive FDR. **No concluyente.**

---

## 6. OTC

**Datos:** 2026-11-01 → 2026-11-07, 581 velas M15 por activo (~6 días). No se re-ejecutó en el corte del 10-N; sigue congelado.
**Payout:** real por señal (IQ Option).

| Activo | Filtro | n | WR | IC95 | Payout | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---:|---|
| EURUSD-OTC | Todas h3 | 283 | 52,30 % | 46,5–58,0 | 84,97 % | −3,31 % | [−17,75, +5,24] |
| EURUSD-OTC | D2_ANTICIPACION h3 | 88 | 53,41 % | 43,1–63,5 | 84,77 % | −1,39 % | [−26,39, +21,32] |
| XAUUSD-OTC | Todas h3 | 279 | 50,18 % | 44,3–56,0 | 86,00 % | −6,67 % | [−13,01, −0,53] |
| XAUUSD-OTC | h1 alineado h3 | 133 | 60,90 % | 52,4–68,8 | 86,00 % | +13,28 % | [−3,04, +25,16] |

- **EURUSD-OTC / D2_ANTICIPACION:** falsificado. EV negativo, dependiente de un día; la ventana 12–18 UTC es post-hoc.
- **XAUUSD-OTC / h1 alineado:** positivo, pero solo 5 días efectivos, IC95 inferior 52,4 % < break-even 53,76 %, bootstrap cruza cero. **No promovido.**

---

## 7. Candidatos y estado

| Candidato | Evidencia | Decisión |
|---|---|---|
| `det_d5` h4 EURUSD | Ventana completa +7,34 %, descubrimiento +3,40 %, q=1,0 y bootstrap cruza cero | Archivar; no confirmado |
| `h4_pullback` h4 EURUSD | Mejor p en el baseline anterior; +0,05 % en descubrimiento y −8,24 % en ventana completa | Falsificado |
| `hora_20_L` h4 EURUSD | Con ventana móvil: n=736, WR 55,3 %, EV +3,41 %, p=0,1607, q=1,0; no es top nominal | Archivar; no promovible |
| `ema_gt_2_S` h4 EURUSD | Con ventana móvil: n=3.737, WR 52,2 %, EV −2,94 %, p=0,9738, q=1,0; el signo positivo del baseline de 6 meses no se reproduce | Archivar; no promovible |
| NYOR13 fade h1 EURUSD | n=118, p=0,168, q=1,0 | Hipótesis exploratoria |
| LOR4 fade h8 XAUUSD | n=70, p=0,0049, q=0,907 | Muestra pequeña; no concluyente |
| XAUUSD-OTC h1 alineado h3 | n=133, EV +13,3 %, IC cruza BE | Forward test en shadow |

---

## 8. Artefactos

| Archivo | Contenido |
|---|---|
| `results/summary.txt` | Resumen de scan, ablación, holdout y OTC. |
| `results/scan_*_full.txt`, `scan_*_disc.txt` | Salidas de los escaneos. |
| `results/edge_scan_*.csv` | Tests de señales PIVOT. |
| `results/ablation_*.csv` | Ablación. |
| `results/holdout_*.csv` | Holdout. |
| `results/bar_edge_*.csv` | Escaneo a nivel de vela. |
| `results/pattern_edge_*.csv` | Patrones intradía. |
| `results/otc_validation.csv` | Validación OTC. |
| `results/walkforward_eurusd.csv` | Estabilidad mensual. |
| `results/eurusd_signals.csv`, `xauusd_signals.csv` | Señales + features + etiquetas. |
| `results/*_meta.json` | Metadatos del replay. |
| `results/labels_*.txt` | Validación de etiquetas contra producción. |
| `docs/REFERENCE_FIX.md` | Corrección de referencias y re-baseline antes/después. |
| `docs/UPDATE_2026-11-10.md` | Extensión forward y ventana móvil del corte actual. |
