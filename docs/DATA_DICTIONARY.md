# Diccionario de datos

**Corte:** 2026-11-07 UTC. **Fuente:** Deriv (`frxEURUSD`, `frxXAUUSD`) e IQ Option público para OTC.

Este documento describe los CSV de `data/`, las 176 columnas de `results/*_signals.csv` y las columnas derivadas de los archivos de resultados.

---

## 1. Velas OHLCV (`data/*.csv`)

```text
epoch,datetime,open,high,low,close,volume
```

| Columna | Tipo | Unidad | Descripción |
|---|---|---|---|
| `epoch` | entero | s | Segundos desde 1970-01-01 UTC. |
| `datetime` | ISO 8601 | UTC | Inicio de la vela. |
| `open` | float | precio | Primer precio. |
| `high` | float | precio | Máximo. |
| `low` | float | precio | Mínimo. |
| `close` | float | precio | Último precio. |
| `volume` | float | contratos | Tick volume; Deriv devuelve 0 en forex. No usar como señal. |

Los M15 incluidos no tienen duplicados de `epoch` ni valores nulos. Los fines de semana no hay velas. Los H1/H4 incluidos son muestras recientes; el replay deriva H1/H4 desde M15. Ver `data/README.md`.

---

## 2. Señales (`results/*_signals.csv`)

Una fila por señal. **176 columnas.** Las etiquetas `ret_h*`, `win_h*`, `mfe_h*` y `mae_h*` se calculan después del replay, con el M15 completo.

Convenciones:

- `entry_time` es el **inicio** de la vela de señal; la señal se emite al cierre.
- `entry_price` es el **close** de esa vela. No es el open siguiente.
- `ret_h*` y `mfe/mae` están en **puntos** del activo, no en porcentaje.
- `hipotesis_prob_*` son heurísticas del motor, no probabilidades calibradas.
- Los campos específicos de un detector valen 0 o vacío en señales de otros detectores; no son datos faltantes.

### 2.1 Identidad, tiempo y precio

| Columna | Descripción |
|---|---|
| `id` | Identificador único de la señal (entero de 64 bits serializado como cadena). |
| `entry_time` | Inicio de la vela M15 que genera la señal (UTC, ISO 8601). La señal se emite al cierre de esa vela. |
| `entry_bar_shift` | Desplazamiento de la señal en la cola de medición. **Constante 0 en esta exportación** porque se captura al emitir; no usar. |
| `symbol` | `EURUSD` o `XAUUSD`. |
| `direction` | `1` = CALL/long; `−1` = PUT/short. |
| `entry_price` | Cierre de la vela de señal. Es la referencia de entrada de las etiquetas; **no** es el open siguiente. |
| `idx` | Índice posicional de la vela de señal dentro del M15 (0-based). |
| `date` | Fecha UTC de la vela de señal (`YYYY-MM-DD`). |

### 2.2 Detector y calidad

| Columna | Descripción |
|---|---|
| `detector` | Detector que emitió la señal: `D1`, `D2`, `D2_ANTICIPACION`, `D3`, `D3_DEF`, `D4`, `D5`. |
| `tipo` | Clase de calidad del detector: `A` (mejor) a `D` (peor). |
| `cr` | Campo reservado de cuerpo/rango; no se asigna en esta versión. **Constante 0.** |
| `bs` | Fuerza/penetración de la ruptura en unidades de ATR (solo D1). |
| `bs_pips` | Campo reservado; no se asigna. **Constante 0.** |
| `br` | Body ratio de la vela de ruptura: `|close−open| / (high−low)`. |
| `range_break_pips` | Campo reservado; no se asigna. **Constante 0.** |
| `nivel_estructural` | Nivel estructural de referencia usado por el detector (precio). |
| `sweep_wick_ratio` | Mecha del barrido / rango de la vela (0–1). |
| `sweep_volume_ratio` | Volumen del barrido / media de N velas. En estos CSV el volumen de Deriv es 0, así que el ratio queda 0 o 1. |
| `reclaim_body_ratio` | Cuerpo de la vela de reclaim / rango (0–1). |
| `sweep_bars_ago` | Velas desde el barrido hasta la señal. |
| `equal_hl_detected` | `1` si el detector encontró máximos/mínimos iguales en la ventana. |
| `level_swept` | Precio del nivel barrido. |
| `fvg_size_pips` | Campo reservado; no se asigna. **Constante 0.** |
| `fvg_size_atr` | Tamaño del FVG en ATR (solo D3/D3_DEF). |
| `fvg_mitigated` | `1` si el FVG fue mitigado; `0` si no; vacío en señales que no son D3. |
| `fvg_top` | Borde superior del FVG. |
| `fvg_bottom` | Borde inferior del FVG. |
| `ob_high` | Máximo del order block (solo D4). |
| `ob_low` | Mínimo del order block (solo D4). |
| `ob_bars_ago` | Velas desde el order block hasta la señal. |
| `ob_impulse_atr` | Impulso del order block en ATR (solo D4). |
| `ob_confluence` | `1` si el order block tiene confluencia. |
| `mss_aligned` | `1` si el MSS H4 está alineado con la dirección de la señal. |
| `mss_bars_ago_h4` | Velas H4 desde el MSS. |
| `mss_direction` | Dirección del MSS: `ALCISTA`/`BAJISTA`. |
| `mss_level` | Nivel de ruptura del MSS. |
| `atr14` | ATR14 en unidades de precio (no puntos). |
| `spread_pips` | Campo reservado; no se asigna. **Constante 0.** |
| `volume_ratio` | Campo reservado; no se asigna. **Constante 0.** |
| `session` | Sesión: `ASIA`, `LONDON`, `NY`, `NY_OPEN`, `LONDON_CLOSE`, `OUT`. |
| `kill_zone` | Zona de alta actividad: `NONE`, `LONDON_OPEN_KILL`, `NY_OPEN_KILL`, `LONDON_NY_OVERLAP`. |
| `trend_d1` | Tendencia D1: `ALCISTA`/`BAJISTA`/`NEUTRO`. En la muestra solo `NEUTRO`/`BAJISTA` por warmup de EMA200. |
| `vol_expanding` | `1` si ATR corto/medio indica expansión. |
| `vol_compressing` | `1` si ATR corto/medio indica compresión. |
| `calidad_sweep` | Calidad del sweep (0–100). |
| `calidad_mss` | Calidad del MSS (0–100). |
| `calidad_fvg` | Calidad del FVG (0–100). |
| `calidad_ob` | Calidad del order block (0–100). |
| `salud_tendencial` | Salud de la tendencia EMA21/50 (0–100). |
| `g1_compresion` | Métrica G1 de compresión (0–100). |
| `g2_persistencia` | Métrica G2 de persistencia direccional (0–100). |
| `g3_eficiencia` | Métrica G3 de eficiencia; el campo no se copia al CSV. **Constante 0.** |
| `g4_agotamiento` | Métrica G4 de agotamiento (0–100). |
| `conf_sweep_fvg` | Score de confluencia sweep+FVG (0–100). |
| `conf_completa` | Score de confluencia completa (0–100). |
| `es_intravela` | `1` si la señal se generó en procesamiento intrabar; en esta exportación todas son 1. |
| `contexto_estructural` | Score de contexto estructural (0–100). |
| `estructura_direccion` | Dirección de la estructura D0: `ALCISTA`/`BAJISTA`/`NEUTRO`. |
| `distancia_al_sweep` | Distancia al nivel de sweep en puntos. |

### 2.3 Hipótesis y narrativa

| Columna | Descripción |
|---|---|
| `hipotesis_causa` | Texto: causa del setup. |
| `hipotesis_efecto` | Texto: efecto esperado. |
| `hipotesis_razon` | Texto: razones y confluencias. |
| `hipotesis_invalidez` | Texto: condición de invalidación. |
| `hipotesis_expiry_velas` | Expiración sugerida en velas M15 (1–4). |
| `hipotesis_expiry_minutos` | Expiración sugerida en minutos (15–60). |
| `hipotesis_prob_min` | Probabilidad mínima declarada (porcentaje, heurística). |
| `hipotesis_prob_max` | Probabilidad máxima declarada (porcentaje, heurística). |
| `hipotesis_zona` | Zona: `PREMIUM`/`DISCOUNT`/`NEUTRO`. |
| `hipotesis_objetivo` | Precio objetivo sugerido. |
| `hipotesis_texto` | Narrativa completa de la señal. |

### 2.4 Ciclo de vida y medición

| Columna | Descripción |
|---|---|
| `signal_age_bars` | Edad de la señal en velas; 0 al emitir. |
| `measured` | Lista serializada de 4 booleanos (h1–h4) de la medición live; en replay todos `False`. |
| `retorno` | Lista serializada de retornos live h1–h4 en puntos; en replay todos 0. |
| `mfe` | Lista serializada de MFE live h1–h4; en replay todos 0. |
| `mae` | Lista serializada de MAE live h1–h4; en replay todos 0. |
| `medido_cerrado` | Lista de 4 booleanos de medición con velas cerradas; en replay todos `False`. |
| `retorno_cerrado` | Retornos con velas cerradas; en replay todos 0. |
| `mfe_cerrado` | MFE con velas cerradas; en replay todos 0. |
| `mae_cerrado` | MAE con velas cerradas; en replay todos 0. |
| `gap_detected` | `1` si se detectó gap; no usado en esta exportación. |
| `completada` | `1` si la señal terminó su ciclo de medición; en replay todas 0. |
| `conviccion` | Convicción heurística: `ALTA`/`MEDIA`/`BAJA`. |
| `velocidad_aproximacion` | Score de velocidad de aproximación al nivel (20–95). |
| `toques_nivel` | Número de toques previos al nivel. |
| `displacement_post_sweep` | `1` si hubo desplazamiento después del sweep. |
| `regimen_volatilidad` | `NORMAL`/`EXPANSION`/`COMPRESION`/`EXTREMO`. |
| `invalidez_estructural` | Precio de invalidación estructural. |
| `objetivo_estructural` | Precio del objetivo estructural; 0 si no hay nivel. |
| `objetivo_operativo` | Precio del objetivo operativo (extremos de la vela). |
| `invalidez_operativa` | Precio de invalidación operativa. |
| `csv_written` | Flag interno de persistencia; 0 en replay. |

### 2.5 Filtros del detector

| Columna | Descripción |
|---|---|
| `filtros_pasados` | Lista separada por comas de filtros superados. |
| `filtros_fallados` | Lista separada por comas de filtros fallados. |
| `filtro_penetracion_atr` | Valor de penetración usado por D1. |
| `filtro_body_ratio` | Body ratio usado por D1. |
| `filtro_volumen_ratio` | Ratio de volumen usado por D1. |
| `filtro_retest` | `1` si pasó retest. |
| `filtro_wick_ratio` | Wick ratio usado por D2. |
| `filtro_reclaim_ratio` | Reclaim body ratio usado por D2. |
| `filtro_sweep_reciente` | `1` si el sweep está dentro de la ventana. |
| `filtro_distancia_nivel` | Distancia al nivel en puntos. |
| `filtro_fvg_size_atr` | Tamaño FVG/ATR. |
| `filtro_fvg_body_ratio` | Body ratio de la vela del FVG. |
| `filtro_fvg_dir_ok` | `1` si la dirección del FVG es válida. |
| `filtro_ob_impulse` | Impulso del OB en ATR. |
| `filtro_ob_body_ratio` | Body ratio de la vela del OB. |
| `filtro_ob_tested` | `1` si el OB ya fue testeado. |
| `filtro_ob_entering` | `1` si el precio entra al OB. |
| `filtro_ob_distancia` | Distancia al OB en ATR/puntos. |
| `filtro_mss_aligned` | `1` si MSS alineado. |
| `filtro_mss_reciente` | `1` si MSS reciente. |
| `filtro_confluencias` | Número de confluencias (0–3). |

### 2.6 Contexto de mercado

| Columna | Descripción |
|---|---|
| `ctx_atr14_px` | ATR14 en precio. |
| `ctx_atr14_points` | ATR14 en puntos. |
| `ctx_atr8_14` | ATR8/ATR14. |
| `ctx_atr14_30` | ATR14/ATR30. |
| `ctx_ema21` | EMA21 M15. |
| `ctx_ema50` | EMA50 M15. |
| `ctx_ema50_dist_atr` | (entry − EMA50)/ATR14. |
| `ctx_ema21_slope_atr` | Pendiente EMA21 (3 velas)/ATR14. |
| `ctx_ema21_vs_50_atr` | (EMA21−EMA50)/ATR14. |
| `ctx_rsi14` | RSI14 M15. |
| `ctx_h4_ema20_dist_atr` | (entry − EMA20 H4)/ATR14. |
| `ctx_h4_ema20_vs_50_atr` | (EMA20 H4 − EMA50 H4)/ATR14. |
| `ctx_h4_ema20_slope_atr` | Pendiente EMA20 H4/ATR14. |
| `ctx_d1_ema50_dist_atr` | (entry − EMA50 D1)/ATR14. |
| `ctx_d1_ema50_vs_200_atr` | (EMA50 D1 − EMA200 D1)/ATR14. |
| `ctx_h4_pos50` | Posición en el rango de 50 velas H4 (0–1). |
| `ctx_h4_range_atr` | Rango H4 50 velas/ATR14. |
| `ctx_h4_dist_high_atr` | Distancia al máximo H4 50 velas/ATR14. |
| `ctx_h4_dist_low_atr` | Distancia al mínimo H4 50 velas/ATR14. |
| `ctx_m15_into_h4` | Velas M15 transcurridas dentro de la H4 actual. |
| `ctx_h1_ema20_dist_atr` | (entry − EMA20 H1)/ATR14. |
| `ctx_h1_ema20_vs_50_atr` | (EMA20 H1 − EMA50 H1)/ATR14. |
| `ctx_estructura_valida` | `1` si la estructura D0 es válida. |
| `ctx_estructura_dir` | Dirección de estructura D0. |
| `ctx_estructura_zona` | `1` si el precio está en zona estructural. |
| `ctx_pending` | Número de señales pendientes en la cola. |
| `ctx_g1` | Copia de G1 en el contexto. |
| `ctx_g2` | Copia de G2 en el contexto. |
| `ctx_g3` | Copia de G3 en el contexto. |
| `ctx_g4` | Copia de G4 en el contexto. |
| `ctx_hour` | Hora UTC (0–23). |
| `ctx_weekday` | Día de la semana (0=lunes). |

### 2.8 Etiquetas

| Columna | Descripción |
|---|---|
| `ret_h1` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h1. |
| `win_h1` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h1. |
| `mfe_h1` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h1. |
| `mae_h1` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h1. |
| `ret_h2` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h2. |
| `win_h2` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h2. |
| `mfe_h2` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h2. |
| `mae_h2` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h2. |
| `ret_h3` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h3. |
| `win_h3` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h3. |
| `mfe_h3` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h3. |
| `mae_h3` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h3. |
| `ret_h4` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h4. |
| `win_h4` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h4. |
| `mfe_h4` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h4. |
| `mae_h4` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h4. |
| `ret_h5` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h5. |
| `win_h5` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h5. |
| `mfe_h5` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h5. |
| `mae_h5` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h5. |
| `ret_h6` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h6. |
| `win_h6` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h6. |
| `mfe_h6` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h6. |
| `mae_h6` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h6. |
| `ret_h7` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h7. |
| `win_h7` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h7. |
| `mfe_h7` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h7. |
| `mae_h7` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h7. |
| `ret_h8` | Retorno en puntos desde `entry_price` hasta `close[t+h]`, ajustado por dirección. Horizonte h8. |
| `win_h8` | `1` si `ret_h > 0`; `0` si no (empate = 0). Horizonte h8. |
| `mfe_h8` | Máxima excursión favorable en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h8. |
| `mae_h8` | Máxima excursión adversa en puntos desde `pos` hasta `pos+h`, **incluyendo la vela de señal**. Horizonte h8. |

---

## 3. Columnas constantes o no pobladas

Estas columnas existen en el esquema pero **no deben usarse** en un análisis nuevo sin corregir el código que las genera:

| Columna | Estado |
|---|---|
| `cr` | Constante 0; no asignada. |
| `bs_pips` | Constante 0; no asignada. |
| `range_break_pips` | Constante 0; no asignada. |
| `fvg_size_pips` | Constante 0; no asignada. |
| `spread_pips` | Constante 0; no asignada. |
| `volume_ratio` | Constante 0; no asignada. |
| `g3_eficiencia` | Constante 0; `g_g3` no se copia a la señal. |
| `entry_bar_shift` | Constante 0 en el CSV; se captura antes de actualizar la cola. |
| `measured`, `retorno`, `mfe`, `mae` | Listas de medición live; en replay todas `False`/0. |
| `medido_cerrado`, `retorno_cerrado`, `mfe_cerrado`, `mae_cerrado` | Ídem; no se usan en el replay. |
| `completada`, `csv_written`, `gap_detected` | Flags de producción; 0 en replay. |
| `es_intravela` | Constante 1 en esta exportación. |

Además, `fvg_mitigated` es vacío en señales que no son D3, y `ob_*`/`mss_*` valen 0 cuando el detector no es D4/D5. Es herencia del contrato de `Signal`, no pérdida de datos.

---

## 4. Archivos de resultados

### 4.1 `edge_scan_*.csv`

| Columna | Descripción |
|---|---|
| `symbol` | Activo. |
| `hipotesis` | Grupo pre-registrado H1–H8. |
| `condicion` | Condición evaluada. |
| `horizonte` | h1–h8 (h1–h4 primarios). |
| `familia` | `primaria` (h1–h4) o `exploratoria` (h5–h8). |
| `n` | Señales con etiqueta válida. |
| `dias` | Días distintos para el bootstrap. |
| `wins` | Aciertos. |
| `wr` | Winrate (%). |
| `wr_lo`, `wr_hi` | IC95 de Wilson (%). |
| `be` | Break-even (%). |
| `payout` | Payout usado (%). |
| `ev` | EV = payout×WR − (1−WR) (%). |
| `ev_boot_lo`, `ev_boot_hi` | IC95 bootstrap por día (%). |
| `ev_payout_m3`, `ev_payout_p3` | EV con payout −3/+3 pp (%). |
| `p` | p-valor unilateral contra break-even. |
| `q` | Valor BH-FDR. |
| `criterio` | `1` si cumple todos los criterios estrictos. |

### 4.2 `bar_edge_*.csv`

Mismas columnas que `edge_scan` salvo `hipotesis`, `familia`, `ev_payout_m3` y `ev_payout_p3`: `symbol, familia, condicion, horizonte, n, dias, wins, wr, wr_lo, wr_hi, be, payout, ev, ev_boot_lo, ev_boot_hi, p, q, criterio`.

### 4.3 `pattern_edge_*.csv`

Columnas: `symbol, familia, tipo, lado, horizonte, eventos, n, dias, wins, wr, wr_lo, wr_hi, be, payout, ev, ev_boot_lo, ev_boot_hi, p, q, criterio`.

- `familia`: ARB, LOR3, LOR4, NYOR12, NYOR13, SWEEP, CLOSE, PDH.
- `tipo`: `break`, `break_wide`, `base`, `momentum`, etc.
- `lado`: `base` o `fade`.
- `eventos`: eventos detectados antes de exigir etiqueta válida.
- `n`: eventos con etiqueta válida.

### 4.4 `holdout_*.csv`

Columnas: `symbol, bloque, condicion, horizonte, n, wins, wr, wr_lo, wr_hi, be, payout, ev, ev_boot_lo, ev_boot_hi, p`.

- `bloque`: `base`, `apriori` o `superviviente`.

### 4.5 `otc_validation.csv`

Columnas: `symbol, condicion, horizonte, n, dias, wins, wr, wr_lo, wr_hi, be, payout_medio, ev, ev_boot_lo, ev_boot_hi`.

### 4.6 `walkforward_*.csv`

Columnas: `symbol, condicion, horizonte, periodo, n, wins, wr, wr_lo, wr_hi, be, payout, ev, ev_boot_lo, ev_boot_hi, p`.

- `periodo`: mes `YYYY-MM`.

---

## 5. Notas para el auditor

1. `entry_price` es el close de la vela de señal; el open siguiente puede ser distinto. El sesgo de gap/slippage no está modelado.
2. El horizonte se cuenta por posición (`pos+h`), no por diferencia de timestamps. Si faltara una vela, el horizonte se desplazaría.
3. `mfe_h*`/`mae_h*` incluyen la vela de señal; pueden capturar excursiones previas a la entrada. No se usan para win/loss.
4. Los ceros específicos de detector son estructurales, no datos faltantes.
5. Las columnas de la sección 3 no deben usarse sin corregir el código.
