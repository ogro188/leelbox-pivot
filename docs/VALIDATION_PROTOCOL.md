# Protocolo de validación

**Versión:** 2026-11-07
**Estado:** pre-registrado antes de mirar los resultados de cada familia. Cualquier cambio posterior debe documentarse y volver a correr el análisis completo.

Este documento describe cómo se evaluó PIVOT y qué reglas debe cumplir cualquier hipótesis nueva antes de pasar a demo o dinero real.

---

## 1. Principios

1. **Separación temporal estricta.** Nunca k-fold aleatorio, nunca mezclar pasado y futuro.
2. **Una familia de tests, una corrección.** Cada estudio define su familia antes de mirar los p-valores.
3. **Etiquetas declaradas.** La implementación usa el close de la vela de señal como referencia de entrada y el close de `t+h` como salida. Es un supuesto **optimista** (no modela gap de open ni slippage); el auditor debe decidir si invalida o solo refuerza el veredicto negativo.
4. **Payout real por horizonte.** No se usa un 85 % fijo para todos los activos/horizontes.
5. **Bootstrap por día.** Las señales del mismo día están correlacionadas; el remuestreo se hace por día, no por señal.
6. **Holdout intacto.** El período de holdout no participa en selección, umbrales ni tuning.
7. **Sin optimización de TP/SL.** El escaneo principal es binario a expiración fija. El análisis de salidas es separado y no se usa para seleccionar.
8. **Reproducibilidad.** Todo resultado debe poder recalcularse desde los CSV incluidos.

---

## 2. Datos y cortes temporales

### 2.1 Historia M15

- **Rango:** 2025-11-07 → 2026-11-06.
- **EURUSD:** 24.202 velas M15.
- **XAUUSD:** 23.140 velas M15.
- **Fuente:** Deriv (`frxEURUSD`, `frxXAUUSD`), velas públicas.
- **Máximo disponible:** la API devolvió 12 meses para M15; no se pudieron obtener 24.

### 2.2 Cortes por estudio

| Estudio | Descubrimiento | Purga | Validación / holdout | Test |
|---|---|---|---|---|
| Señales PIVOT (6 meses) | 2026-05-12 → 2026-09-29 | 2026-09-30 | 2026-10-01 → 2026-11-06 | — |
| Velas M15 (12 meses) | 2025-11-07 → 2026-09-30 | — | 2026-10-01 → 2026-11-06 | — |
| Patrones intradía (12 meses) | 2025-11-07 → 2026-04-30 | — | 2026-05-01 → 2026-07-31 | 2026-08-01 → 2026-11-06 |
| OTC | — | — | — | 2026-11-01 → 2026-11-07 (retrospectivo) |

**Importante:** los cortes no son intercambiables. El escaneo de señales PIVOT usa 6 meses porque el replay con el motor real en proceso se hizo sobre esa ventana (82,5 %/80,6 % de overlap con producción); los escaneos de velas y patrones usan los 12 meses completos y tienen sus propios cortes. No se debe comparar un p-valor de un estudio con el q-valor de otro.

---

## 3. Etiquetas y horizontes

- **h1:** +15 min (1 vela M15).
- **h2:** +30 min.
- **h3:** +45 min.
- **h4:** +60 min.
- **h5–h8:** +75 a +120 min; solo exploratorias, sin FDR.

Etiqueta binaria implementada en `tools/feature_replay.py`:

```text
entry = close[t]                    # cierre de la vela de señal
ret_h = (close[t+h] − entry) / point × direction
win_h = 1 si ret_h > 0, si no 0     # empate = 0
```

- `direction = +1` (CALL/long) o `−1` (PUT/short).
- La señal se emite al cierre de la vela `t`; el timestamp `entry_time` es el **inicio** de esa vela y `decision_time = entry_time + 15 min` es su cierre. La alerta, la sesión y cualquier medición de latencia usan `decision_time`.
- El contexto H1/H4/D1 es causal: velas cerradas + bucket en formación agregado solo con M15 cuyo cierre es `<= decision_time` (`kernel/contexto_superior.py`). No se usa el OHLC completo del bucket con M15 futuras.
- La entrada de referencia es el **close de la vela de señal**, no el open de `t+1`. Es un supuesto optimista: el open siguiente suele coincidir, pero puede saltar; no se modela gap ni slippage.
- No hay chequeo explícito de continuidad temporal: el horizonte se cuenta por **posición** en el CSV (`pos + h`). Si faltara una vela, el horizonte se desplazaría. Los M15 incluidos no tienen duplicados ni nulos, pero los fines de semana no existen.
- No se usa el high/low para la etiqueta principal. `mfe_h*`/`mae_h*` se calculan desde `pos` hasta `pos+h` **incluyendo la vela de señal**, por lo que pueden capturar excursiones anteriores a la entrada; se usan solo para análisis de salidas, nunca para win/loss.
- En el escaneo a nivel de vela (`bar_edge.py`) la etiqueta es `close[t+h]/close[t] − 1` con dirección fija o calculada; se documenta en cada familia.
- En el escaneo de patrones (`pattern_edge.py`) la etiqueta es `close[t+h]/open[t+1] − 1`, con chequeo de continuidad por `epoch` y dirección del evento (base o fade). Es el único escaneo que usa el open siguiente como entrada.
- En OTC la etiqueta usa el mismo esquema, con el precio de entrada de la señal y payout real por señal.

---

## 4. Familias de tests

### 4.1 Señales PIVOT (`edge_scan.py`)

Condiciones pre-registradas, agrupadas por hipótesis:

| Grupo | Hipótesis | Ejemplos |
|---|---|---|
| H1 | Alineación H4 | `h4_alineado`, `h4_contra`, `h4_plano` |
| H2 | Alineación H1 | `h1_alineado`, `h1_contra`, `h4_y_h1_alineados` |
| H3 | Pullback / estructura / D1 | `h4_pullback`, `d1_alineado`, `estructura_alineada` |
| H4 | Volatilidad | `vol_baja`, `vol_alta`, `rango_h4_bajo`, `rango_h4_alto` |
| H5 | Extensión M15 | `ema50_cerca`, `ema50_lejos`, `rsi_no_extremo`, `rsi_extremo_contra` |
| H6 | Confluencia / calidad | `conf_completa_alto`, `calidad_sweep_alto`, `g1_compresion_alto`, `spread_bajo` |
| H7 | Sesión / horario | `sesion_ny`, `hora_07_11`, `lunes_viernes` |
| H8 | Detector / tipo | `det_d2`, `det_d5`, `tipo_a`, etc. |

Cada condición se evalúa en h1–h8. **La familia primaria es h1–h4.** h5–h8 se reportan como exploratorias y no entran en el FDR.

- **Tests por activo:** 456 EURUSD / 448 XAUUSD.
- **Primarios con n ≥ 100:** 220 por activo (el resto se reporta pero no se usa para el criterio estricto).
- **FDR:** Benjamini–Hochberg al 10 % sobre todos los tests primarios del activo.

### 4.2 Velas M15 (`bar_edge.py`)

Familias pre-registradas:

- calendario: hora UTC (0–23) y día de la semana;
- momentum/reversión: retorno de 1, 2, 4, 8 y 16 velas;
- RSI14: buckets y estrategia de extremos;
- volatilidad: percentil ATR y ratio ATR;
- EMA50: distancia en ATR y estrategia de tendencia/reversión;
- cuerpo/rango: body ratio y rango/ATR.

Cada condición se evalúa en largo y corto para h1–h4. **464 tests EURUSD / 462 XAUUSD**, FDR 10 % sobre todos los tests primarios del activo. La corrida usa 12 meses de M15; el baseline anterior de 454 tests XAUUSD usaba ~6 meses y no es comparable (ver `docs/REFERENCE_FIX.md`).

### 4.3 Patrones intradía (`pattern_edge.py`)

| Familia | Definición |
|---|---|
| **ARB** | Ruptura del rango asiático 00:00–06:45 UTC en Londres 07:00–10:45. |
| **LOR3** | Opening range Londres 07:00–07:45; ruptura 08:00–11:00. |
| **LOR4** | Opening range Londres 07:00–08:45; ruptura 08:00–11:00. |
| **NYOR12** | Opening range Nueva York 12:00–12:45; ruptura 13:00–16:00. |
| **NYOR13** | Opening range Nueva York 13:00–13:45; ruptura 14:00–17:00. |
| **SWEEP** | Falso breakout de 20 velas (barrido y retorno) y breakout exitoso como control. |
| **CLOSE** | Momentum de cierre: close position > 0.8 o < 0.2 y rango > 1 ATR. |
| **PDH** | Ruptura del máximo/mínimo del día anterior en Londres. |

Cada evento se evalúa en dirección `base` y `fade` para h1–h8. **168 tests EURUSD / 184 XAUUSD**, FDR 10 % sobre todos los tests primarios.

### 4.4 OTC (`otc_validate.py`)

- Fuente: `iq_public.db` (colector IQ Option público, solo lectura) + `pivot_core.db` de cada OTC.
- Payout **real por señal**: último tick anterior a la creación de la señal.
- Solo señales limpias: `created_at >= entry_time + 15 min`.
- Ventana: 2026-11-01 → 2026-11-07 (~6 días, 581 velas M15 por activo).
- h3 (45 min) como horizonte principal; h1/h2/h4 como exploratorios.
- Bootstrap por día.

---

## 5. Estadística

### 5.1 Winrate e intervalo

- Winrate: `WR = wins / n`.
- IC95 de Wilson para proporción.
- Break-even: `BE = 100 / (1 + payout)`.
  - EURUSD: 54,05 / 53,76 / 53,76 / 53,48 % para h1–h4.
  - XAUUSD: 55,25 / 54,95 / 54,95 / 54,64 % para h1–h4.

### 5.2 P-valor

P-valor unilateral contra el break-even:

```text
z = (WR − BE) / 100 × sqrt(n) / sqrt(BE/100 × (1 − BE/100))
p = 1 − Φ(z)
```

Se contrasta la hipótesis `WR > BE` (dirección de edge), no `WR ≠ BE`.

### 5.3 FDR

- Benjamini–Hochberg al 10 %.
- Se aplica **dentro de cada activo y estudio**, sobre la familia primaria.
- No se aplica sobre los tests exploratorios h5–h8.
- Un q-valor de 1,0 significa que el test no es significativo tras corrección; no significa que el p-valor sea 1.

### 5.4 Block bootstrap por día

- Unidad de remuestreo: **día**.
- Se remuestrean días con reemplazo (B=2000 en los análisis principales; B=300 en corridas exploratorias).
- Para cada réplica se recalcula `WR` y `EV = payout × WR − (1 − WR)`.
- Se reporta el intervalo percentil 2,5–97,5 %.
- Esto preserva la dependencia intra-día y evita tratar señales del mismo día como independientes.

### 5.5 Sensibilidad al payout

Para cada test se reporta:

- `ev_payout_m3`: EV con payout −3 pp.
- `ev_payout_p3`: EV con payout +3 pp.

Un candidato debe seguir positivo con payout −3 pp para ser considerado robusto.

---

## 6. Criterio de supervivencia

Un test sobrevive si cumple **todas** estas condiciones:

```text
familia primaria (h1–h4)
n ≥ 100
q ≤ 0,10
wr_lo > break-even
ev_boot_lo > 0
```

No se acepta “p < 0,05” sin FDR. No se acepta un IC que cruce el break-even. No se acepta un bootstrap que cruce cero. No se acepta n < 100 para promoción, aunque se reporte.

### Holdout

- Se evalúan los supervivientes del descubrimiento y, como control, las hipótesis a priori H1/H2.
- Los umbrales (terciles) se calculan **solo** en descubrimiento y se congelan.
- El holdout no se usa para elegir condiciones, direcciones, horarios ni payouts.
- Si no hay supervivientes, el holdout se reporta igual como confirmación negativa del baseline.

### Ablación

Variantes evaluadas:

- `H4_only`: tendencia H4, entrada en cada cierre M15.
- `H1_only`: tendencia H1.
- `H4_H1`: ambas alineadas.
- `PIVOT`: señales del replay.
- `PIVOT_H4_H1`: señales PIVOT con ambas alineaciones.
- `siempre_long`: control sin habilidad direccional.

Si PIVOT no supera a `siempre_long`, no hay evidencia de habilidad direccional.

---

## 7. Regla de decisión para promover una hipótesis

Antes de pasar a demo o dinero real, una hipótesis debe cumplir:

1. mecanismo predictivo explícito, definido antes de mirar los datos;
2. validación out-of-sample con `n ≥ 300`;
3. IC95 inferior > break-even;
4. bootstrap por día con EV inferior > 0;
5. positividad en ≥ 4 de 5 meses y en ≥ 70 % de las semanas;
6. sensibilidad positiva con payout −3 pp;
7. h1–h3 validados contra producción (no solo replay);
8. revisión independiente del código y de las etiquetas.

Si no se cumple, se mantiene en shadow y no se promueve.

---

## 8. Anti-patrones prohibidos

- k-fold aleatorio o validación cruzada estándar sobre series temporales.
- Optimizar TP/SL y reportar el mejor resultado sin corrección.
- Elegir la ventana horaria/sesión después de ver el EV.
- Usar el holdout para ajustar umbrales.
- Reportar el mejor p-valor de un subgrupo como si fuera el test principal.
- Mezclar señales de replay con señales de producción sin declararlo.
- Usar un payout fijo de 85 % para todos los activos/horizontes.
- Ignorar el solapamiento de señales y tratar cada una como independiente.
- Promover un candidato por un resultado positivo aislado en un día o semana.

---

## 9. Comandos de referencia

```bash
# Señales PIVOT: descubrimiento y holdout
python tools/edge_scan.py \
  --inputs results/eurusd_signals.csv \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --hasta 2026-09-30 --tag disc --out-dir results
python tools/holdout.py \
  --signals results/eurusd_signals.csv \
  --scan results/edge_scan_eurusd_disc.csv \
  --split 2026-10-01 --desc-hasta 2026-09-30 \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --out-dir results

# Velas M15
python tools/bar_edge.py --symbol EURUSD --bootstrap 300

# Patrones intradía
python tools/pattern_edge.py --symbol EURUSD --bootstrap 300

# OTC (requiere las DB de OTC, no incluidas)
python tools/otc_context.py
python tools/otc_validate.py
```

Los archivos de resultados incluidos en `results/` permiten auditar los números sin volver a correr el replay completo.
