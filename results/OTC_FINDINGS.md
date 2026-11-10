# OTC — Validación retrospectiva con payout real

**Fecha:** 2026-11-07 (UTC)
**Datos:** 2026-11-01 a 2026-11-07, 581 velas M15 por activo (~6 días).
**Fuente:** bases SQLite del colector IQ Option público (solo lectura) y del motor OTC. **Las bases originales no se distribuyen.**
**Payout:** real por señal, tomado del último tick anterior a la creación de la señal.

## Calidad de la muestra

| Activo | Señales | Con h3 | Payout medio | `created_at − entry_time` |
|---|---:|---:|---:|---|
| EURUSD-OTC | 342 | 283 | 84,97 % (82 % en 12–18 UTC, 86 % fuera) | p50 15,1 min; solo 3 >20 min |
| XAUUSD-OTC | 332 | 279 | 86,00 % | p50 15,1 min; solo 2 >20 min |

Todas las señales cumplen `created_at >= entry_time + 15 min` (señal limpia); el retraso máximo es 60,8 min en 3 y 2 señales, despreciable.

**Convención de latencia:** `entry_time` es la apertura de la vela M15; la señal se crea al cierre. Por eso `created_at − entry_time` tiene un p50 estructural de ~15 min. Medida contra `decision_time = entry_time + 15 min`, la latencia real es de ~0,1 min (p50) y el máximo ronda 45,8 min en los casos extremos. La tabla anterior usa `entry_time` porque el análisis OTC se congeló antes del re-baseline; no afecta a las etiquetas ni al EV.

## Resultados h3 (45 min) con payout real

| Activo | Filtro | n | WR | IC95 Wilson | Payout | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---:|---|
| EURUSD-OTC | Todas | 283 | 52,30 % | 46,5–58,0 | 84,97 % | −3,31 % | −17,75 a +5,24 |
| EURUSD-OTC | D2_ANTICIPACION | 88 | 53,41 % | 43,1–63,5 | 84,77 % | −1,39 % | −26,39 a +21,32 |
| EURUSD-OTC | h1 alineado | 116 | 51,72 % | 42,7–60,6 | 84,66 % | −4,59 % | −19,23 a +14,00 |
| EURUSD-OTC | h4+h1 alineados | 81 | 50,62 % | 40,0–61,2 | 84,86 % | −6,59 % | −22,32 a +11,65 |
| XAUUSD-OTC | Todas | 279 | 50,18 % | 44,3–56,0 | 86,00 % | −6,67 % | −13,01 a −0,53 |
| XAUUSD-OTC | D2_ANTICIPACION | 90 | 45,56 % | 35,6–55,8 | 86,00 % | −15,27 % | −26,11 a −3,28 |
| XAUUSD-OTC | h1 alineado | 133 | 60,90 % | 52,4–68,8 | 86,00 % | +13,28 % | −3,04 a +25,16 |
| XAUUSD-OTC | h4+h1 alineados | 101 | 56,44 % | 46,7–65,7 | 86,00 % | +4,97 % | −26,73 a +17,38 |

Break-even: 54,05 % a payout 85 %, 54,95 % a 82 %, 53,76 % a 86 %.

## Candidato EURUSD-OTC / D2_ANTICIPACION

- n=88, WR 53,41 %, payout 84,77 %, **EV −1,39 %**; IC95 43,1–63,5 %.
- Por dirección: CALL n=39, WR 53,8 %, EV −0,67 %; PUT n=49, WR 53,1 %, EV −1,96 %. No hay edge en ninguna de las dos direcciones.
- Por día (h3): +18,4 % (n=11), −2,7 % (n=19), +34,3 % (n=15), +17,1 % (n=19), **−41,4 % (n=22)**, −100 % (n=2). El resultado agregado depende de un solo día.
- La ventana 12–18 UTC (n=27, WR 59,3 %, EV +7,85 %) es **post-hoc**: al recorrer todas las ventanas de 6 h, el EV va de −25,8 % a +42,7 %; la mejor es 15–21 UTC (n=18, WR 77,8 %, EV +42,7 %). Con n≈20 por ventana, el máximo es ruido de selección.
- **Conclusión:** el edge inicial de +2,1 % (n=85) no se confirmó. El candidato está falsificado con la muestra ampliada.

## XAUUSD-OTC / h1 alineado (el único positivo)

- n=133, WR 60,90 %, EV +13,28 %, bootstrap −3,04 a +25,16 (cruza cero).
- Por dirección: CALL n=99, WR 57,6 %, EV +7,09 %; PUT n=34, WR 70,6 %, EV +31,29 %. Ambas positivas, pero PUT con n=34.
- Por día (h3): +32,0 % (n=31), +0,75 % (n=24), −1,53 % (n=34), +21,1 % (n=43), −100 % (n=1). Dos días fuertes, uno plano y uno levemente negativo.
- **No es el candidato pre-registrado** (el candidato era EURUSD-OTC / D2_ANTICIPACION), tiene solo 5 días y el IC95 inferior (52,4 %) no supera el break-even de 53,76 %.
- En Deriv live el payout de XAUUSD es menor (81 % a 15 min, 82 % a 30 min, 83 % a 60 min), así que el break-even sube a 54,6–54,9 %; el edge se reduce.

## Veredicto OTC

No hay edge confirmado en la muestra OTC. El candidato EURUSD-OTC / D2_ANTICIPACION queda **cerrado en su forma actual** (EV negativo y dependiente de un día). La única señal positiva, XAUUSD-OTC / h1 alineado, es una hipótesis nueva para forward test, no una promoción: requiere ≥300 señales out-of-sample, consistencia por día/semana y IC95 inferior > break-even antes de considerar demo.

## Limitaciones

- Solo ~6 días de histórico OTC (581 velas M15); no alcanza para un backtest de meses.
- H4 tiene ~35 velas y H1 ~145; EMA20/50 se puede calcular, pero con poco warmup. La EMA50 de H1 necesita ~50 horas, así que los filtros de contexto solo son válidos desde el 3 de noviembre; la muestra efectiva es de ~4 días, no 6.
- D1 no alcanza 205 velas → `trend_d1` queda NEUTRO en OTC.
- El payout es el de IQ Option; no es transferible a Deriv.
- El forward test del candidato EURUSD-OTC sigue abierto en shadow; este análisis es retrospectivo y no reemplaza la revisión semanal del 2026-11-13.
