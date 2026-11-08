# Resumen de resultados

**Corte:** 2026-11-07 UTC
**Regla:** un resultado solo se considera confirmado si cumple el criterio estricto de `docs/VALIDATION_PROTOCOL.md`. Los resultados nominales se incluyen para auditoría, no como recomendación.

---

## 1. Tabla global

| Estudio | Activo | Tests | Supervivientes FDR | Estado |
|---|---:|---:|---:|---|
| Señales PIVOT (`edge_scan`) | EURUSD | 456 | **0** | Negativo |
| Señales PIVOT (`edge_scan`) | XAUUSD | 448 | **0** | Negativo |
| Velas M15 (`bar_edge`) | EURUSD | 464 | **0** | Negativo |
| Velas M15 (`bar_edge`) | XAUUSD | 454 | **0** | Negativo |
| Patrones intradía (`pattern_edge`) | EURUSD | 168 | **0** | Negativo |
| Patrones intradía (`pattern_edge`) | XAUUSD | 184 | **0** | Negativo |
| OTC (`otc_validate`) | EURUSD-OTC | 88 (h3) | — | Falsificado |
| OTC (`otc_validate`) | XAUUSD-OTC | 133 (h3) | — | Hipótesis, no confirmado |

Ningún test de ningún escaneo alcanzó `q ≤ 0,10` con los criterios adicionales.

**Nota sobre XAUUSD:** los 448 tests de la tabla son de la ventana de descubrimiento (6.952 señales, hasta 2026-09-30). En la ventana completa (8.932 señales) son 456 tests (228 primarios); la diferencia son 8 combinaciones que solo tienen muestra suficiente al añadir octubre-noviembre. En ambas ventanas: 0 supervivientes.

---

## 2. Señales PIVOT — escaneo principal

**Datos:** replay de 6 meses (2026-05-12 → 2026-11-06), 8.959 señales EURUSD y 8.932 XAUUSD.
**Descubrimiento:** 2026-05-12 → 2026-09-29; **holdout:** 2026-10-01 → 2026-11-06.
**Payout:** EURUSD 85/86/86/87 %; XAUUSD 81/82/82/83 % (h1–h4).

### 2.1 Descubrimiento

| Activo | Tests | Primarios n ≥ 100 | Mejor p | Condición | q |
|---|---:|---:|---:|---|---:|
| EURUSD | 456 | 220 | 0,1385 | `h4_pullback` h4 (n=426, WR 56,1 %, EV +4,91 %) | 1,000 |
| XAUUSD | 448 | 220 | 0,6665 | `tipo_a` h4 (n=405, WR 53,6 %, EV −1,95 %) | 1,000 |

### 2.2 “Casi” que no es

`det_d5` h4 EURUSD:

| Ventana | n | WR | EV | p | Bootstrap 95 % |
|---|---:|---:|---:|---:|---|
| Descubrimiento | 255 | 55,3 % | +3,40 % | 0,2803 | [−10,24, +17,05] |
| Ventana completa | 324 | 58,0 % | +8,51 % | 0,0503 | [−3,62, +20,31] |

El resultado completo lo aporta octubre (n=59, WR 67,8 %, EV +26,78 %); julio fue −23,0 %. **No es un hallazgo pre-registrado ni confirmado.**

### 2.3 Holdout

| Activo | h | n | WR | IC95 | EV | Bootstrap 95 % |
|---|---:|---:|---:|---|---:|---|
| EURUSD | h3 base | 1.959 | 48,7 % | 46,5–50,9 | −9,42 % | [−15,36, −3,49] |
| XAUUSD | h3 base | 1.908 | 47,8 % | 45,6–50,0 | −13,01 % | [−16,97, −8,57] |

Las 32 combinaciones a priori evaluadas en holdout son negativas en ambos activos.

### 2.4 Producción real

| Activo | h | n | WR | EV |
|---|---:|---:|---:|---:|
| EURUSD | 1 | 1.089 | 48,30 % | −10,64 % |
| EURUSD | 2 | 1.006 | 49,01 % | −8,85 % |
| EURUSD | 3 | 959 | 48,07 % | −10,59 % |
| XAUUSD | 1 | 990 | 46,26 % | −16,26 % |
| XAUUSD | 2 | 911 | 47,09 % | −14,29 % |
| XAUUSD | 3 | 878 | 44,65 % | −18,74 % |

Excepciones positivas por detector: EURUSD D2 h2 (n=52, +14,46 %), EURUSD D2 h3 (n=47, +2,89 %), XAUUSD D5 h3 (n=31, +5,68 %). Son submuestras pequeñas, no sobreviven corrección múltiple y no son estables.

---

## 3. Ablación

Winrate h1–h4 (%):

| Variante | EURUSD | XAUUSD |
|---|---|---|
| H4_only | 49,3 / 49,5 / 49,9 / 50,4 | 50,4 / 50,8 / 50,7 / 50,7 |
| H1_only | 49,0 / 49,1 / 49,7 / 49,7 | 49,8 / 49,8 / 49,6 / 49,6 |
| H4+H1 | 49,1 / 49,4 / 49,9 / 50,3 | 50,2 / 50,4 / 50,2 / 50,2 |
| siempre_long | 47,9 / 48,0 / 47,9 / 47,9 | 49,2 / 48,5 / 48,5 / 48,4 |
| PIVOT | 47,6 / 48,5 / 48,1 / 48,7 | 48,2 / 48,6 / 48,5 / 48,7 |
| PIVOT+H4+H1 | 48,3 / 49,1 / 48,6 / 49,6 | 48,9 / 50,0 / 48,7 / 48,2 |

EV: todos negativos, entre −5,8 % y −12,8 %. PIVOT no supera a `siempre_long` (≤ 0,8 pp). **No hay habilidad direccional medible.**

---

## 4. Escaneo a nivel de vela

**Datos:** 12 meses M15; descubrimiento hasta 2026-09-30; holdout desde 2026-10-01.
**Familias:** calendario, momentum/reversión, RSI14, volatilidad, EMA50, cuerpo/rango.

| Activo | Tests | Supervivientes | Top nominal (p) |
|---|---:|---:|---|
| EURUSD | 464 | **0** | `hora_20_L` h4: n=344, WR 60,8 %, EV +13,61 %, p=0,0034, q=1,0 |
|  |  |  | `hora_16_S` h4: n=428, WR 59,6 %, EV +11,41 %, p=0,0057, q=1,0 |
|  |  |  | `rsi_gt70_S` h4: n=370, WR 58,4 %, EV +9,17 %, p=0,0293, q=1,0 |
| XAUUSD | 454 | **0** | `hora_09_L` h4: n=428, WR 60,7 %, EV +11,17 %, p=0,0056, q=1,0 |
|  |  |  | `hora_16_S` h4: n=422, WR 58,8 %, EV +7,55 %, p=0,0444, q=1,0 |

`hora_20_L` h4 y `ema_gt_2_S` h4 EURUSD fueron positivos en descubrimiento y holdout, pero no sobreviven FDR. `hora_16_S` se desplomó en holdout. **No hay candidato promovible.**

---

## 5. Patrones intradía

**Datos:** 12 meses M15; descubrimiento 2025-11-07 → 2026-04-30; validación 2026-05-01 → 2026-07-31; test 2026-08-01 → 2026-11-06.

| Activo | Tests | Supervivientes | Top nominal (p) |
|---|---:|---:|---|
| EURUSD | 168 | **0** | `LOR3 break fade` h8: n=114, WR 64,9 %, EV +21,39 %, p=0,0072, q=0,717 |
|  |  |  | `LOR3 break fade` h4: n=114, WR 63,2 %, EV +18,11 %, p=0,0191, q=0,717 |
|  |  |  | `NYOR13 break fade` h2: n=118, WR 62,7 %, EV +16,64 %, p=0,0256, q=0,717 |
| XAUUSD | 184 | **0** | `LOR4 break fade` h8: n=71, WR 70,4 %, EV +28,87 %, p=0,0037, q=0,697 |
|  |  |  | `LOR3 break fade` h6: n=115, WR 64,3 %, EV +17,76 %, p=0,0183, q=1,0 |

### NYOR13 fade h1 (EURUSD)

- n=118, WR 58,47 %, EV +8,18 %, IC95 49,45–66,96, p=0,1676, q=1,0.
- No sobrevive FDR ni el criterio de IC inferior > break-even.
- Las ventanas de validación/test de la corrida original fueron positivas, pero no son confirmatorias y no se usaron para seleccionar.
- **Estado:** hipótesis exploratoria, no edge.

### XAUUSD LOR4 fade h8

- n=71, WR 70,42 %, EV +28,87 %, p=0,0037, q=0,697.
- Muestra pequeña; no sobrevive FDR. **No concluyente.**

---

## 6. OTC

**Datos:** 2026-11-01 → 2026-11-07, 581 velas M15 por activo (~6 días).
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
| `det_d5` h4 EURUSD | Ventana completa +8,51 %, descubrimiento +3,40 %, depende de octubre | Archivar; no confirmado |
| `h4_pullback` h4 EURUSD | Mejor p en descubrimiento, se desmorona en ventana completa | Archivar |
| `hora_20_L` h4 EURUSD | Nominal, positivo en holdout, q=1,0 | No promovible; posible ruido |
| `ema_gt_2_S` h4 EURUSD | Nominal, positivo en holdout, q=1,0 | No promovible; posible ruido |
| NYOR13 fade h1 EURUSD | n=118, p=0,168, q=1,0 | Hipótesis exploratoria |
| LOR4 fade h8 XAUUSD | n=71, p=0,0037, q=0,697 | Muestra pequeña; no concluyente |
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
