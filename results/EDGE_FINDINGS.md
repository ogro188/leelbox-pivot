# EDGE — Veredicto final live (EURUSD / XAUUSD)

**Fecha:** 2026-11-07 UTC
**Alcance:** 6 meses de historia Deriv (2026-05-12 a 2026-11-06), replay con el motor real en proceso (fast_engine validado; 82,5 %/80,6 % de overlap con producción), 8.959 señales EURUSD y 8.932 XAUUSD.
**Estado:** shadow, sin dinero real, producción intacta (`pivot.service` activo, sin reinicios por este análisis).

## 1. Protocolo aplicado

- Detección y contexto: H4, H1, M15; ablación H4-only, H1-only, H4+H1, PIVOT, PIVOT+H4+H1.
- Etiquetas: h1 = cierre a +15 min, h2 = +30, h3 = +45, h4 = +60; h5–h8 solo exploratorias.
- Descubrimiento: 2026-05-12 a 2026-09-29. Purga: 2026-09-30. Holdout: 2026-10-01 a 2026-11-06.
- Screening univariado con 456 tests por activo en la ventana completa; en descubrimiento, 456 tests EURUSD y 448 XAUUSD. En ambos casos, 220 tests primarios con n ≥ 100.
- Corrección BH-FDR al 10 %, IC95 Wilson, block bootstrap por día, payout real por horizonte.
- Criterio estricto de supervivencia: `q ≤ 0,10` + `wr_lo > break-even` + `ev_boot_lo > 0` + `n ≥ 100`.
- Payout usado: EURUSD 85/86/86/87 % (h1–h4); XAUUSD 81/82/82/83 %.
- Break-even: EURUSD 54,05/53,76/53,76/53,48 %; XAUUSD 55,25/54,95/54,95/54,64 %.

## 2. Fidelidad del replay

| Activo | Producción | Replay | Comunes | % de producción | Convicción exacta |
|---|---:|---:|---:|---:|---:|
| EURUSD | 1.869 | 8.959 | 1.541 | 82,5 % | 97,0 % |
| XAUUSD | 1.781 | 8.932 | 1.435 | 80,6 % | 98,2 % |

- Las únicas discrepancias de detector son D3 vs D3_DEF (5 en EURUSD, 3 en XAUUSD), con dirección correcta.
- Etiquetas contra `senales_resultados`: EURUSD 99,34 % de signo, dif media 1,02 puntos, p95 4; XAUUSD 98,74 %, dif media 15,55 puntos, p95 58. La diferencia es el offset de entrada live, no un desfase de horizonte.
- **Limitación:** h4 no se pudo validar contra producción (solo 3 filas EURUSD y 6 XAUUSD). Las conclusiones de h4 son replay-only.

## 3. Resultados del escaneo

**Cero supervivientes estrictos** en descubrimiento y en ventana completa, en ambos activos.

- EURUSD descubrimiento: 456 tests, 220 primarios n ≥ 100, **0 con q < 0,10**. Mejor p: `h4_pullback` h4, n=426, WR 56,1 %, EV +4,91 %, p=0,1385, q=1,000, bootstrap [−6,04, +15,08].
- XAUUSD descubrimiento: 448 tests, 220 primarios, **0 con q < 0,10**. Mejor p: `tipo_a` h4, n=405, WR 53,6 %, EV −1,95 %, p=0,6665, q=1,000.
- XAUUSD ventana completa: 456 tests (228 primarios), **0 con q < 0,10**. El cambio de 448 a 456 se debe a que la ventana completa añade señales de octubre-noviembre y habilita 8 tests más.
- Ningún test de ningún escaneo alcanzó q < 0,10: el mínimo p bruto en descubrimiento fue 0,1385 (EURUSD) y 0,6665 (XAUUSD).

### El “casi” que no es

`det_d5` h4 EURUSD en la ventana completa: n=324, WR 58,0 %, EV +8,51 %, p=0,0503, q=1,000, bootstrap [−3,62, +20,31].

- En **descubrimiento** (sin holdout): n=255, WR 55,3 %, EV +3,40 %, p=0,2803, bootstrap [−10,24, +17,05]. No era significativo antes del holdout.
- El +8,51 % de la ventana completa lo aporta octubre (n=59, WR 67,8 %, EV +26,78 %); julio fue −23,0 %.
- D5 es raro en producción (62 señales EURUSD en total) y no tiene filas h4 medidas en la DB.
- **No es un hallazgo pre-registrado ni confirmado; es un artefacto de mirar la ventana completa después.**

`h4_pullback` h4, el mejor de descubrimiento, se desmorona en la ventana completa: pasa de +4,91 % a −2,63 %; octubre −12,61 % y noviembre −26,67 %.

## 4. Ablación: el contexto no aporta edge

Winrate (%) por variante y horizonte (payout por horizonte):

| Variante | EURUSD h1–h4 | XAUUSD h1–h4 |
|---|---|---|
| H4_only | 49,3 / 49,5 / 49,9 / 50,4 | 50,4 / 50,8 / 50,7 / 50,7 |
| H1_only | 49,0 / 49,1 / 49,7 / 49,7 | 49,8 / 49,8 / 49,6 / 49,6 |
| H4+H1 | 49,1 / 49,4 / 49,9 / 50,3 | 50,2 / 50,4 / 50,2 / 50,2 |
| siempre_long | 47,9 / 48,0 / 47,9 / 47,9 | 49,2 / 48,5 / 48,5 / 48,4 |
| PIVOT | 47,6 / 48,5 / 48,1 / 48,7 | 48,2 / 48,6 / 48,5 / 48,7 |
| PIVOT+H4+H1 | 48,3 / 49,1 / 48,6 / 49,6 | 48,9 / 50,0 / 48,7 / 48,2 |

Todos los EV son negativos, entre −5,8 % y −12,8 %. Lo relevante: **PIVOT está al mismo nivel que `siempre_long`** (diferencias ≤ 0,8 pp en ambos activos), sin habilidad direccional medible. El contexto H4/H1 tampoco mejora la dirección; la mejor variante sigue por debajo del break-even. La arquitectura no aporta información predictiva en esta muestra.

## 5. Holdout: confirmación negativa

| Activo | Base h3 | n | WR | IC95 | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---|
| EURUSD | Todas | 1.959 | 48,7 % | 46,5–50,9 | −9,42 % | [−15,36, −3,49] |
| XAUUSD | Todas | 1.908 | 47,8 % | 45,6–50,0 | −13,01 % | [−16,97, −8,57] |

- EURUSD: las 32 combinaciones a priori evaluadas en holdout son negativas. La mejor es `h4_y_h1_alineados` h4: WR 51,8 %, EV −3,21 %, bootstrap [−12,12, +5,08].
- XAUUSD: las 32 combinaciones son negativas. La mejor es `h4_contra` h3: WR 49,0 %, EV −10,83 %.
- No había supervivientes del descubrimiento que evaluar: el holdout confirma que no hay nada que confirmar.

## 6. Contraste independiente con producción

`senales_resultados` real, sin replay, con payout por horizonte:

| Activo | h | n | WR | EV |
|---|---:|---:|---:|---:|
| EURUSD | 1 | 1.089 | 48,30 % | −10,64 % |
| EURUSD | 2 | 1.006 | 49,01 % | −8,85 % |
| EURUSD | 3 | 959 | 48,07 % | −10,59 % |
| XAUUSD | 1 | 990 | 46,26 % | −16,26 % |
| XAUUSD | 2 | 911 | 47,09 % | −14,29 % |
| XAUUSD | 3 | 878 | 44,65 % | −18,74 % |

Por detector, todos negativos salvo tres submuestras pequeñas: EURUSD D2 h2 (n=52, +14,46 %), EURUSD D2 h3 (n=47, +2,89 %) y XAUUSD D5 h3 (n=31, +5,68 %). Son ruido de subgrupo, no edge: no sobreviven corrección por múltiples pruebas y no son estables.

## 7. OTC

- **EURUSD-OTC / D2_ANTICIPACION h3:** n=88, WR 53,41 %, payout 84,77 %, EV −1,39 %; bootstrap [−26,39, +21,32]; por día va de +34,3 % a −41,4 %. **Cerrado/falsificado.**
- **XAUUSD-OTC / h1_alineado h3:** n=133, WR 60,90 %, payout 86 %, EV +13,28 %; bootstrap [−3,04, +25,16]; IC95 inferior 52,4 % < break-even 53,76 %; solo 5 días efectivos. **Hipótesis nueva, no promovida.**
- La ventana 12–18 UTC del candidato EURUSD es ruido de selección: todas las ventanas de 6 h dan EV entre −25,8 % y +42,7 %.
- Detalle completo en [`docs/OTC_FINDINGS.md`](OTC_FINDINGS.md).

## 8. Veredicto

**No se encontró edge real.** Las señales M15 de PIVOT, con o sin contexto H4/H1, no superan el break-even de las opciones binarias a los payouts disponibles. La evidencia es consistente en tres fuentes independientes:

1. 456 tests por activo, 0 supervivientes tras FDR; ningún q < 0,10.
2. Holdout de 1.959/1.908 señales, EV −9,42 %/−13,01 %, IC95 enteramente negativo.
3. Resultados reales de producción, EV −8,85 % a −18,74 % según activo y horizonte.

La habilidad direccional de PIVOT es estadísticamente indistinguible del drift incondicional (y a veces peor). No hay base para promover ningún filtro a demo ni a dinero real.

**Decisión:** mantener todo en shadow, no tocar producción, no promover candidatos. El forward test de EURUSD-OTC / D2_ANTICIPACION queda cerrado. XAUUSD-OTC / h1_alineado y `det_d5` h4 quedan como hipótesis de investigación, sin autorización de operación.

## 9. Qué haría falta para cambiar el veredicto

Un edge creíble necesita, antes de mirar los datos:

- una hipótesis con mecanismo predictivo explícito, no otra alineación de contexto;
- validación out-of-sample con n ≥ 300 y IC95 inferior > break-even;
- bootstrap por día con EV inferior > 0;
- positividad en ≥ 4 de 5 meses y en ≥ 70 % de las semanas;
- sensibilidad al payout: seguir positivo con payout −3 pp;
- h1–h3 validados contra producción (h4 hoy no lo está).

Si no se cumple eso, más minería de features solo producirá falsos positivos.

## 10. Limitaciones

- h4 sin validación en producción (3 filas EURUSD, 6 XAUUSD).
- D1 EMA200 no existe antes de ~septiembre 2026; `trend_d1` es NEUTRO en los primeros meses.
- El replay cubre ~82 % de las señales de producción y emite señales extra; las conclusiones se apoyan también en la DB de producción para no depender solo del replay.
- Histórico OTC de ~6 días; solo alcanza para validación forward.
- `DATABASE_URL` sigue apuntando a un archivo SQLite en un directorio temporal; no se tocó.
- Migración USB → eMMC pendiente; no se tocó.

## 11. Artefactos

- `results/summary.txt` — resumen de scan, ablación, holdout y OTC.
- `results/scan_*_full.txt`, `results/scan_*_disc.txt` — escaneos.
- `results/ablation_*.csv` — ablación.
- `results/holdout_*.csv` — holdout.
- `results/labels_*.txt` — validación de etiquetas.
- `results/walkforward_eurusd.csv` — estabilidad mensual.
- [`docs/OTC_FINDINGS.md`](OTC_FINDINGS.md) — informe OTC.
- Herramientas: `tools/feature_replay.py`, `tools/fast_engine.py`, `tools/edge_scan.py`, `tools/ablation.py`, `tools/holdout.py`, `tools/walkforward.py`, `tools/summarize.py`, `tools/validate_labels.py`, `tools/prod_wr.py`.
