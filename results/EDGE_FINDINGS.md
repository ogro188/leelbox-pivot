# EDGE — Veredicto final live (EURUSD / XAUUSD)

**Fecha:** 2026-11-07 UTC (re-baseline: 2026-11-09)
**Alcance:** 6 meses de historia Deriv (2026-05-12 a 2026-11-06), replay con el motor real en proceso (fast_engine validado; 82,5 %/80,6 % de overlap con producción medido sobre el replay anterior), 8.957 señales EURUSD y 8.933 XAUUSD. Contexto superior causal (`kernel/contexto_superior.py`); ver `docs/REFERENCE_FIX.md`.
**Estado:** shadow, sin dinero real, producción intacta (`pivot.service` activo, sin reinicios por este análisis).

## 1. Protocolo aplicado

- Detección y contexto: H4, H1, M15; ablación H4-only, H1-only, H4+H1, PIVOT, PIVOT+H4+H1.
- Etiquetas: h1 = cierre a +15 min, h2 = +30, h3 = +45, h4 = +60; h5–h8 solo exploratorias.
- Descubrimiento: 2026-05-12 a 2026-09-29. Purga: 2026-09-30. Holdout: 2026-10-01 a 2026-11-06.
- Screening univariado con 456 tests por activo en la ventana completa; en descubrimiento, 456 tests EURUSD y 448 XAUUSD. Primarios con n ≥ 100: 220 en descubrimiento para ambos activos; en ventana completa, 224 EURUSD y 220 XAUUSD.
- Corrección BH-FDR al 10 %, IC95 Wilson, block bootstrap por día, payout real por horizonte.
- Criterio estricto de supervivencia: `q ≤ 0,10` + `wr_lo > break-even` + `ev_boot_lo > 0` + `n ≥ 100`.
- Payout usado: EURUSD 85/86/86/87 % (h1–h4); XAUUSD 81/82/82/83 %.
- Break-even: EURUSD 54,05/53,76/53,76/53,48 %; XAUUSD 55,25/54,95/54,95/54,64 %.

## 2. Fidelidad del replay

| Activo | Producción | Replay | Comunes | % de producción | Convicción exacta |
|---|---:|---:|---:|---:|---:|
| EURUSD | 1.869 | 8.957 | 1.541 | 82,5 % | 97,0 % |
| XAUUSD | 1.781 | 8.933 | 1.435 | 80,6 % | 98,2 % |

El overlap y la convicción se midieron sobre el replay anterior. El replay corregido cambia 2–3 señales de borde por activo, por lo que el porcentaje es una referencia y no se re-midió contra la DB de producción.

- Las únicas discrepancias de detector son D3 vs D3_DEF (5 en EURUSD, 3 en XAUUSD), con dirección correcta.
- Etiquetas contra `senales_resultados`: EURUSD 99,34 % de signo, dif media 1,02 puntos, p95 4; XAUUSD 98,74 %, dif media 15,55 puntos, p95 58. La diferencia es el offset de entrada live, no un desfase de horizonte. Esos porcentajes provienen de la corrida original contra la DB de producción; en esta extracción sanitizada `results/labels_*.txt` muestra 0 coincidencias porque la DB no se distribuye.
- **Limitación:** h4 no se pudo validar contra producción (solo 3 filas EURUSD y 6 XAUUSD). Las conclusiones de h4 son replay-only.

## 3. Resultados del escaneo

**Cero supervivientes estrictos** en descubrimiento y en ventana completa, en ambos activos.

- EURUSD descubrimiento: 456 tests, 220 primarios n ≥ 100, **0 con q < 0,10**. Mejor p: `det_d5` h4, n=255, WR 55,3 %, EV +3,40 %, p=0,2803, q=1,000, bootstrap [−10,99, +17,42].
- XAUUSD descubrimiento: 448 tests, 220 primarios, **0 con q < 0,10**. Mejor p: `tipo_a` h4, n=405, WR 53,3 %, EV −2,40 %, p=0,7020, q=1,000.
- XAUUSD ventana completa: 456 tests (220 primarios), **0 con q < 0,10**. Mejor p: `tipo_a` h4, n=509, WR 51,9 %, EV −5,08 %, p=0,8960. El cambio de 448 a 456 se debe a que la ventana completa añade señales de octubre-noviembre y habilita 8 tests más.
- Ningún test de ningún escaneo alcanzó q < 0,10: el mínimo p bruto en descubrimiento fue 0,2803 (EURUSD) y 0,7020 (XAUUSD).

### El “casi” que no es

`det_d5` h4 EURUSD en la ventana completa: n=324, WR 58,0 %, EV +8,51 %, p=0,0503, q=1,000, bootstrap [−3,76, +21,10].

- En **descubrimiento** (sin holdout): n=255, WR 55,3 %, EV +3,40 %, p=0,2803, bootstrap [−10,99, +17,42]. No era significativo antes del holdout.
- El +8,51 % de la ventana completa lo aporta octubre (n=59, WR 67,8 %, EV +26,78 %); julio fue −23,0 %.
- D5 es raro en producción (62 señales EURUSD en total) y no tiene filas h4 medidas en la DB.
- **No es un hallazgo pre-registrado ni confirmado; es un artefacto de mirar la ventana completa después.**

`h4_pullback` h4, el “mejor” de descubrimiento en el baseline anterior, se desmorona en la ventana completa: pasa de +0,05 % a −7,19 %; octubre −17,31 % y noviembre −28,08 %.

## 4. Ablación: el contexto no aporta edge

Winrate (%) por variante y horizonte (payout por horizonte):

| Variante | EURUSD h1–h4 | XAUUSD h1–h4 |
|---|---|---|
| H4_only | 49,3 / 49,9 / 49,9 / 49,8 | 51,0 / 51,2 / 51,0 / 51,0 |
| H1_only | 49,2 / 49,5 / 50,0 / 49,8 | 50,5 / 50,4 / 50,1 / 50,2 |
| H4+H1 | 49,3 / 49,9 / 50,2 / 49,9 | 51,1 / 51,1 / 50,8 / 50,8 |
| siempre_long | 48,7 / 48,8 / 48,8 / 48,7 | 50,6 / 50,1 / 50,0 / 50,2 |
| PIVOT | 47,6 / 48,5 / 48,1 / 48,7 | 48,2 / 48,6 / 48,5 / 48,7 |
| PIVOT+H4+H1 | 47,8 / 48,5 / 47,8 / 48,8 | 48,5 / 49,4 / 48,1 / 47,7 |

Todos los EV son negativos, entre −6,2 % y −12,8 %. Lo relevante: **PIVOT está igual o por debajo de `siempre_long`** (hasta 2,4 pp por debajo en XAUUSD h1), sin habilidad direccional medible. El contexto H4/H1 tampoco mejora la dirección; la mejor variante sigue por debajo del break-even. La arquitectura no aporta información predictiva en esta muestra.

## 5. Holdout: confirmación negativa

| Activo | Base h3 | n | WR | IC95 | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---|
| EURUSD | Todas | 1.960 | 48,7 % | 46,5–50,9 | −9,47 % | [−15,41, −3,54] |
| XAUUSD | Todas | 1.911 | 47,8 % | 45,5–50,0 | −13,05 % | [−17,01, −8,59] |

- EURUSD: las 32 combinaciones a priori evaluadas en holdout son negativas. La mejor es `d1_alineado` h4: WR 50,9 %, EV −4,82 %, bootstrap [−13,26, +2,95].
- XAUUSD: las 32 combinaciones son negativas. La mejor es `d1_alineado` h2: WR 49,6 %, EV −9,75 %, bootstrap [−17,83, −2,28].
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

1. 456 tests por activo en la ventana completa (448 en descubrimiento XAUUSD), 0 supervivientes tras FDR; ningún q < 0,10.
2. Holdout de 1.960/1.911 señales, EV −9,47 %/−13,05 %, IC95 enteramente negativo.
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
- [`docs/REFERENCE_FIX.md`](../docs/REFERENCE_FIX.md) — corrección de referencias y re-baseline.
- Herramientas: `tools/feature_replay.py`, `tools/fast_engine.py`, `tools/edge_scan.py`, `tools/ablation.py`, `tools/holdout.py`, `tools/walkforward.py`, `tools/summarize.py`, `tools/validate_labels.py`, `tools/prod_wr.py`.
