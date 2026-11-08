# PIVOT — sistema de trading (extracción sanitizada para revisión externa)

**Estado:** investigación / shadow. **No hay edge confirmado.** El sistema genera señales; no ejecuta órdenes ni mueve dinero real.
**Corte de datos:** 2026-11-07 UTC. **Historia:** 12 meses de velas M15 (2025-11-07 a 2026-11-06).
**Objetivo de este repositorio:** permitir una auditoría independiente del motor, los detectores, el pipeline de validación, los datos y los resultados.

> **Resumen para el analista externo**
>
> PIVOT es un sistema de señales para opciones binarias / forex basado en Smart Money Concepts (sweeps, FVG, order blocks, MSS) en M15/H1/H4/D1. La hipótesis original era que la confluencia de estructura y contexto daba una ventaja direccional explotable con expiraciones de 15–60 minutos.
>
> Los tres análisis independientes realizados hasta ahora **no encontraron edge**:
>
> - 456 tests EURUSD y 448 XAUUSD sobre señales PIVOT: **0 supervivientes** tras BH-FDR al 10 %.
> - 464 tests EURUSD y 454 XAUUSD a nivel de vela: **0 supervivientes**.
> - 168 tests EURUSD y 184 XAUUSD de patrones intradía: **0 supervivientes**.
> - Holdout temporal: EURUSD WR 48,7 %, EV −9,42 %; XAUUSD WR 47,8 %, EV −13,01 %.
> - Resultados reales de producción: EV entre −8,85 % y −18,74 % según activo y horizonte.
>
> El veredicto vigente es **negativo**. La pregunta para el revisor externo no es “¿cómo optimizamos esto?”, sino **“¿hay algún error metodológico, fuga de información o hipótesis con mecanismo que merezca una prueba nueva?”**. Ver [`docs/ANALYST_BRIEF.md`](docs/ANALYST_BRIEF.md).

---

## 1. Qué es PIVOT

PIVOT es un motor modular de análisis de precio que:

1. consume velas M15 (Deriv o CSV) y deriva H1/H4/D1;
2. calcula estructura de mercado y liquidez (D0–D5);
3. aplica filtros de contexto, calidad y confluencia;
4. emite una señal con dirección, entrada, expiración y narrativa;
5. en modo binario, asocia payout, expiry y gestión de riesgo;
6. registra la señal y su resultado para análisis posterior.

**No ejecuta órdenes.** La capa de alertas (ntfy) está desactivada por defecto (`PIVOT_ALERTAS_LIVE=0`). El modo de producción actual es shadow: se generan y registran señales, pero no se opera.

### Detectores

| ID | Patrón | Lógica resumida |
|---|---|---|
| **D0** | Estructura H1 | Swings HH/HL/LH/LL, barridos y zonas de liquidez. Base para el resto. |
| **D1** | Ruptura de rango | Ruptura de un rango de N velas con penetración ATR, cuerpo y volumen; retest opcional. |
| **D2** | Sweep + reclaim | Barrido de liquidez con mecha, recuperación del nivel y cierre de vuelta dentro del rango. |
| **D2_A** | Sweep anticipado | Variante de D2 con mecha menor y confluencias FVG/OB/MSS. |
| **D3** | Fair Value Gap | Gap de precio con tamaño ATR, cuerpo y alineación MSS; variante defendida. |
| **D4** | Order Block | Bloque de órdenes con impulso, cuerpo, no testeado y distancia ATR. |
| **D5** | MSS H4 + sweep M15 | Cambio de estructura H4 alineado con barrido y reclaim en M15. |

Los detectores devuelven siempre una señal; los filtros fallidos se registran como metadatos (`filtros_pasados`, `filtros_fallados`, `direction=0`). El motor descarta `direction == 0` antes del scoring. Esta decisión de diseño permite analizar qué filtros aportan y cuáles no.

### Scoring y contexto

- Métricas G1–G4: compresión ATR, persistencia, eficiencia y agotamiento.
- Calidad por detector: `calidad_sweep`, `calidad_mss`, `calidad_fvg`, `calidad_ob`.
- Salud tendencial: alineación EMA21/50 y tendencia D1.
- Confluencias: `conf_sweep_fvg`, `conf_completa`.
- Contexto: sesión, kill zone, volatilidad, spread, volumen relativo, trend D1.
- La señal final incluye una narrativa y una expiración sugerida (normalmente 1–4 velas M15).

---

## 2. Arquitectura del repositorio

```text
pivot-trading-system/
├── core/                    # Detectores D0–D5, motor, scoring, hipótesis, alertas
├── kernel/                  # Contratos, backtest, binario, feeds, storage, API
│   ├── binary/              # Payout, riesgo, motor de opciones binarias
│   ├── feeds/               # CSV, resample, Deriv WS, IQ Option público
│   └── api/                 # FastAPI + WebSocket (solo backend)
├── estrategias/             # Plugins: PIVOT, binary, dummy, EMA cross
├── scripts/                 # Runtime de datos y export ML (subset sanitizado)
├── tools/                   # Replay, escaneos, ablación, holdout, OTC
├── data/                    # M15/D1 de 12 meses + muestras H1/H4
├── results/                 # Señales, escaneos, holdout, ablación, OTC
├── docs/                    # Metodología, resultados, brief, diccionario
├── tests/                   # Tests unitarios y de integración
├── activos/                 # Configuración de instrumentos (sanitizada)
├── cli.py
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

### Flujo de una señal

```text
Deriv / CSV M15
      │
      ├── resample H1/H4  ──┐
      ├── D1              ──┤
      ▼                     ▼
 indicadores + contexto  detectores D0–D5
      │                     │
      └──────────┬──────────┘
                 ▼
        filtros + scoring + confluencias
                 ▼
        señal (dirección, entrada, expiry, narrativa)
                 ▼
     storage / alertas (gate) / análisis
```

### Componentes principales

| Componente | Archivo | Función |
|---|---|---|
| Motor | `core/motor_v8.py` | Orquesta datos, indicadores, detectores, scoring y persistencia. |
| Contratos | `kernel/contrato.py` | `Estrategia`, `Contexto`, `Señal`, `ActivoInfo`, `BinarySeñal`. |
| Backtest | `kernel/backtest.py` | Replay barra a barra, multi-timeframe, TP/SL/expiry, métricas. |
| Binario | `kernel/binary/engine.py` | Contratos binarios, expiración temporal, payout fijo, riesgo. |
| Payout | `kernel/binary/payout.py` | Tablas de payout por broker, activo y expiración. |
| Riesgo | `kernel/binary/risk.py` | Fixed, martingala, anti-martingala, Kelly, porcentaje. |
| Feeds | `kernel/feeds/` | CSV, resample, Deriv WebSocket, IQ Option público (solo lectura). |
| Persistencia | `kernel/storage.py` | SQLite: señales, resultados, operaciones, dataset ML. |
| API | `kernel/api/app.py` | FastAPI + WebSocket; solo backend, sin frontend en este repo. |
| Estrategia | `estrategias/pivot/` | Plugin PIVOT con parámetros y scoring. |
| Replay | `tools/feature_replay.py` | Genera señales + 176 columnas de features y etiquetas. |

### Reglas de diseño relevantes para la auditoría

1. **Zero look-ahead:** los timeframes superiores se recortan con `searchsorted(side="left")`; solo se usan velas cerradas.
2. **Señal en cierre:** la referencia de entrada es el **close de la vela de señal**; la salida es el close de `t+h`. Es un supuesto optimista: en la práctica se entraría en el open siguiente, que suele coincidir pero puede saltar. El sesgo de gap/slippage no se modela.
3. **Sin Órdenes:** el sistema no ejecuta; la capa de alertas está apagada por defecto.
4. **Trazabilidad:** cada señal conserva detector, features, filtros y narrativa.
5. **Replay verificable:** `fast_engine.py` replica la lógica del motor y se compara contra el motor sin acelerar.

---

## 3. Datos

| Archivo | Velas | Rango | Fuente |
|---|---:|---|---|
| `data/eurusd_M15.csv` | 24.202 | 2025-11-07 → 2026-11-06 | Deriv `frxEURUSD` |
| `data/xauusd_M15.csv` | 23.140 | 2025-11-07 → 2026-11-06 | Deriv `frxXAUUSD` |
| `data/*_D1.csv` | 257 / 256 | 2025-11-10 → 2026-11-05 | Deriv |
| `data/*_H1.csv`, `*_H4.csv` | 440/425 y 214 | muestras recientes | Deriv |

- La API de Deriv devolvió **12 meses como máximo** para M15; no fue posible obtener 24.
- Los CSV H1/H4 incluidos **no** cubren 12 meses: son las últimas páginas disponibles. El replay deriva H1/H4 desde M15; los CSV H1/H4 son solo una muestra de contraste.
- Los CSV contienen solo OHLCV público. No hay IDs de cuenta, tokens ni datos personales.
- `tools/fetch_history.py` documenta la descarga. Requiere red y el feed de Deriv; no toca producción.
- `tools/feature_replay.py` deriva H1/H4 desde M15 y usa el D1 incluido.

### Señales precalculadas

| Archivo | Filas | Columnas | Uso |
|---|---:|---:|---|
| `results/eurusd_signals.csv` | 8.959 | 176 | Replay PIVOT + features + etiquetas h1–h8 |
| `results/xauusd_signals.csv` | 8.932 | 176 | Ídem |

Las columnas se describen en [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md). Las señales incluyen features de detector, contexto, calidad, confluencia, narrativa y retornos/MFE/MAE por horizonte.

---

## 4. Protocolo de validación

El protocolo está pre-registrado en [`docs/VALIDATION_PROTOCOL.md`](docs/VALIDATION_PROTOCOL.md). Resumen:

- **Separación temporal:** descubrimiento → purga → validación/holdout → test. Nunca k-fold aleatorio.
- **Etiquetas:** h1 = +15 min, h2 = +30, h3 = +45, h4 = +60; h5–h8 solo exploratorias.
- **Estadística:** IC95 de Wilson, p-valor unilateral contra break-even, BH-FDR al 10 %, block bootstrap por día.
- **Superviviente estricto:** `q ≤ 0,10` **y** `wr_lo > break-even` **y** `ev_boot_lo > 0` **y** `n ≥ 100`.
- **Payout real por horizonte**, no un 85 % fijo: EURUSD 85/86/86/87 %; XAUUSD 81/82/82/83 % para h1–h4.
- **Sin optimización de TP/SL** en el escaneo principal; el análisis de salidas es posterior y separado.
- **Sensibilidad:** se reporta EV con payout −3/+3 pp.
- **Ablación:** H4-only, H1-only, H4+H1, PIVOT, PIVOT+H4+H1 y `siempre_long` como control.

### Cortes temporales usados

| Estudio | Descubrimiento | Validación | Test / holdout |
|---|---|---|---|
| Señales PIVOT (6 meses) | 2026-05-12 → 2026-09-29 | — | 2026-10-01 → 2026-11-06 |
| Velas M15 (12 meses) | hasta 2026-09-30 | — | 2026-10-01 → 2026-11-06 |
| Patrones intradía (12 meses) | 2025-11-07 → 2026-04-30 | 2026-05-01 → 2026-07-31 | 2026-08-01 → 2026-11-06 |
| OTC | — | — | 2026-11-01 → 2026-11-07 (solo forward retrospectivo) |

Los cortes no son intercambiables: cada estudio tiene su propia familia de tests y su propia corrección.

---

## 5. Resultados

### 5.1 Señales PIVOT — escaneo principal

| Activo | Tests | Primarios n ≥ 100 | Supervivientes FDR | Mejor p bruto |
|---|---:|---:|---:|---|
| EURUSD | 456 | 220 | **0** | 0,1385 (`h4_pullback` h4) |
| XAUUSD | 448 | 220 | **0** | 0,6665 (`tipo_a` h4) |

La tabla usa la ventana de **descubrimiento**: 456 tests EURUSD y 448 XAUUSD. En la **ventana completa**, XAUUSD pasa a 456 tests (228 primarios) porque octubre-noviembre habilita 8 combinaciones más; sigue con **0 supervivientes**.

Ningún test alcanzó `q < 0,10`. El “casi” `det_d5` h4 EURUSD (n=324, WR 58,0 %, EV +8,51 %, p=0,0503) no era significativo en descubrimiento (p=0,2803) y su resultado completo depende de octubre. **No es un hallazgo confirmado.**

### 5.2 Holdout

| Activo | Horizonte | n | WR | IC95 | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---|
| EURUSD | h3 (base) | 1.959 | 48,7 % | 46,5–50,9 | −9,42 % | [−15,36, −3,49] |
| XAUUSD | h3 (base) | 1.908 | 47,8 % | 45,6–50,0 | −13,01 % | [−16,97, −8,57] |

Las 32 combinaciones a priori evaluadas en holdout son negativas en ambos activos.

### 5.3 Ablación

Winrate h1–h4 (%):

| Variante | EURUSD | XAUUSD |
|---|---|---|
| H4_only | 49,3 / 49,5 / 49,9 / 50,4 | 50,4 / 50,8 / 50,7 / 50,7 |
| H1_only | 49,0 / 49,1 / 49,7 / 49,7 | 49,8 / 49,8 / 49,6 / 49,6 |
| H4+H1 | 49,1 / 49,4 / 49,9 / 50,3 | 50,2 / 50,4 / 50,2 / 50,2 |
| siempre_long | 47,9 / 48,0 / 47,9 / 47,9 | 49,2 / 48,5 / 48,5 / 48,4 |
| PIVOT | 47,6 / 48,5 / 48,1 / 48,7 | 48,2 / 48,6 / 48,5 / 48,7 |
| PIVOT+H4+H1 | 48,3 / 49,1 / 48,6 / 49,6 | 48,9 / 50,0 / 48,7 / 48,2 |

Todos los EV son negativos (−5,8 % a −12,8 %). PIVOT está al mismo nivel que `siempre_long` (diferencias ≤ 0,8 pp): **no hay habilidad direccional medible** en esta muestra.

### 5.4 Producción real

Resultados de `senales_resultados` (sin replay), payout por horizonte:

| Activo | h | n | WR | EV |
|---|---:|---:|---:|---:|
| EURUSD | 1 | 1.089 | 48,30 % | −10,64 % |
| EURUSD | 2 | 1.006 | 49,01 % | −8,85 % |
| EURUSD | 3 | 959 | 48,07 % | −10,59 % |
| XAUUSD | 1 | 990 | 46,26 % | −16,26 % |
| XAUUSD | 2 | 911 | 47,09 % | −14,29 % |
| XAUUSD | 3 | 878 | 44,65 % | −18,74 % |

Por detector, casi todas las submuestras son negativas. Las tres excepciones positivas (EURUSD D2 h2/h3 y XAUUSD D5 h3) tienen n=52/47/31, no sobreviven corrección por múltiples pruebas y no son estables.

### 5.5 Escaneo a nivel de vela

Familias: calendario/hora/día, momentum/reversión, RSI14, volatilidad/ATR, EMA50, cuerpo/rango.

| Activo | Tests | Supervivientes FDR | Mejores señales nominales |
|---|---:|---:|---|
| EURUSD | 464 | **0** | `hora_20_L` h4: n=344, WR 60,8 %, EV +13,61 %, p=0,0034, q=1,0; `hora_16_S` h4: n=428, WR 59,6 %, EV +11,41 %, p=0,0057, q=1,0 |
| XAUUSD | 454 | **0** | `hora_09_L` h4: n=428, WR 60,7 %, EV +11,17 %, p=0,0056, q=1,0; `hora_16_S` h4: n=422, WR 58,8 %, EV +7,55 %, p=0,0444, q=1,0 |

Las mejores horas de descubrimiento se caen en holdout o no sobreviven FDR. `hora_20_L` h4 y `ema_gt_2_S` h4 EURUSD son las únicas con signo positivo en ambos períodos, pero sin significancia tras corrección. **No son candidatos promovibles.**

### 5.6 Patrones intradía

Familias: ARB (rango asiático), LOR (opening range Londres), NYOR (opening range Nueva York), SWEEP (falso breakout de 20 velas), CLOSE (momentum de cierre), PDH (máximo/mínimo del día anterior).

| Activo | Tests | Supervivientes FDR | Mejor p bruto |
|---|---:|---:|---|
| EURUSD | 168 | **0** | `LOR3 break fade` h8: n=114, WR 64,9 %, EV +21,39 %, p=0,0072, q=0,717 |
| XAUUSD | 184 | **0** | `LOR4 break fade` h8: n=71, WR 70,4 %, EV +28,87 %, p=0,0037, q=0,697 |

El candidato más comentado, **NYOR13 fade h1** (EURUSD, fade de la ruptura del opening range 13:00–13:45, expiry 15 min), tiene en descubrimiento:

- n=118, WR 58,47 %, EV +8,18 %, IC95 49,45–66,96, p=0,1676, q=1,0.

No sobrevive FDR. Las ventanas posteriores fueron positivas en la corrida original, pero **no son confirmatorias** y no se usaron para seleccionar. Es una hipótesis abierta, no un edge.

### 5.7 OTC (IQ Option, solo lectura)

| Activo | Filtro | n | WR | Payout | EV | Bootstrap 95 % |
|---|---|---:|---:|---:|---:|---|
| EURUSD-OTC | D2_ANTICIPACION h3 | 88 | 53,41 % | 84,77 % | −1,39 % | [−26,39, +21,32] |
| XAUUSD-OTC | h1 alineado h3 | 133 | 60,90 % | 86,00 % | +13,28 % | [−3,04, +25,16] |

- **EURUSD-OTC / D2_ANTICIPACION:** cerrado/falsificado. EV negativo y dependiente de un solo día.
- **XAUUSD-OTC / h1 alineado:** única señal positiva, pero con 5 días efectivos, IC95 inferior 52,4 % < break-even 53,76 % y bootstrap que cruza cero. **Hipótesis para forward test, no promoción.**

Detalle completo en [`docs/OTC_FINDINGS.md`](docs/OTC_FINDINGS.md).

---

## 6. Hipótesis abiertas (no confirmadas)

| Hipótesis | Evidencia | Estado |
|---|---|---|
| EURUSD NYOR13 fade h1 | n=118, WR 58,5 %, EV +8,18 %, p=0,168 | Exploratoria; requiere OOS y FDR |
| EURUSD `hora_20_L` h4 / `ema_gt_2_S` h4 | Nominal, positivo en descubrimiento y holdout | Sin significancia; probable ruido |
| XAUUSD LOR4 fade h8 | n=71, WR 70,4 %, EV +28,9 %, p=0,0037, q=0,697 | Muestra pequeña; no concluyente |
| XAUUSD-OTC h1 alineado h3 | n=133, WR 60,9 %, EV +13,3 %, IC cruza BE | Forward test en shadow |

Ninguna de estas hipótesis debe promoverse a demo o dinero real sin el protocolo de [`docs/VALIDATION_PROTOCOL.md`](docs/VALIDATION_PROTOCOL.md).

---

## 7. Reproducibilidad

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Tests (los de integración pueden requerir datos/DB)
python -m pytest -q

# Replay de señales (precalculado en results/; ~26 min por activo)
python tools/feature_replay.py --symbol EURUSD --out-dir results
python tools/feature_replay.py --symbol XAUUSD --out-dir results

# Escaneo de señales
python tools/edge_scan.py \
  --inputs results/eurusd_signals.csv \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --hasta 2026-09-30 --tag disc --out-dir results

# Escaneo a nivel de vela y patrones
python tools/bar_edge.py --symbol EURUSD --bootstrap 300
python tools/pattern_edge.py --symbol EURUSD --bootstrap 300

# Análisis completo (si se regeneran las señales)
bash tools/run_full_analysis.sh
```

Notas:
- Ejecutar desde la raíz del repositorio; las rutas de `tools/` son relativas.
- `feature_replay.py` puede generar las señales sin las bases SQLite de producción; la validación de etiquetas contra `senales_resultados` devuelve `db no existe` si no se aporta `pivotradar_data/`.
- `fetch_history.py` requiere red y el feed de Deriv; la API limita M15 a 12 meses.
- Los tests de integración que dependen de la API/DB pueden requerir configuración adicional; ver `tests/`.

Más detalle: [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md).

---

## 8. Qué se sanitizó

Este repositorio es una **extracción limpia**, no un volcado de producción. Se excluyeron o neutralizaron:

- `.env` y cualquier credencial; el código lee `DERIV_APP_ID` / `DERIV_API_TOKEN` del entorno.
- Bases SQLite de producción (`pivotradar_data/`), WAL/SHM, logs y backups.
- IDs de cuenta, tokens, topics privados de notificación y rutas absolutas del host.
- Frontend, servicios systemd y scripts operativos de backup/monitorización.
- Datos personales o de cuenta: los CSV solo contienen OHLCV público.

Antes de publicar se ejecutó un escaneo de secretos y se revisó que no quedaran tokens, contraseñas, emails, IPs privadas ni IDs de cuenta. Si encuentras algún residuo, repórtalo de inmediato.

---

## 9. Limitaciones principales

- **12 meses es el máximo** que devolvió la API para M15; no hay 24 meses.
- El replay cubre ~82 % de las señales de producción y emite señales extra; las conclusiones se apoyan también en la base de producción.
- **h4 no está validado contra producción** (solo 3 filas EURUSD y 6 XAUUSD); las conclusiones de h4 son replay-only.
- D1 EMA200 no existe antes de ~septiembre 2026; `trend_d1` es NEUTRO en los primeros meses.
- OTC tiene ~6 días de historia y warmup insuficiente para H1/H4; la muestra efectiva es ~4 días.
- El modelo binario asume payout fijo por horizonte y resolución al close; no modela ticks, empates ni slippage intravela.
- Los escaneos exploratorios (velas, patrones, OTC) tienen familias de tests distintas; no deben mezclarse con el escaneo principal.
- El `DATABASE_URL` de producción apuntaba a una base efímera en `/tmp`; es un riesgo operativo, no un resultado de investigación.

Detalle: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

---

## 10. Preguntas para el analista externo

1. ¿Hay look-ahead, leakage o un desfase de etiquetas en `feature_replay.py`, `fast_engine.py`, `edge_scan.py`, `bar_edge.py` o `pattern_edge.py`?
2. ¿La familia de tests y el BH-FDR están bien definidos? ¿El bootstrap por día respeta la dependencia intra-día?
3. ¿Los splits temporales y la purga son suficientes? ¿Hay contaminación entre descubrimiento, validación y test?
4. ¿La entrada al close de la vela de señal (o al open siguiente) y la salida al close `t+h` son ejecutables con el payout y la expiración reales? ¿Cuánto sesga el supuesto de entrada?
5. ¿El replay es suficientemente fiel (82 % de overlap) o el sesgo de selección invalida las conclusiones?
6. ¿Alguna de las hipótesis abiertas tiene mecanismo económico/estadístico suficiente para un forward test?
7. ¿Qué haría falta para demostrar edge con `n ≥ 300`, IC95 inferior > break-even y bootstrap inferior > 0?
8. ¿Hay bugs, decisiones de diseño o supuestos que inflen o escondan el resultado?

El brief completo, con entregables y plan de revisión, está en [`docs/ANALYST_BRIEF.md`](docs/ANALYST_BRIEF.md).

---

## 11. Aviso

Este repositorio es material de investigación y revisión. **No es asesoramiento financiero.** No opera con dinero real, no garantiza resultados y no debe usarse para promover productos de inversión. Las opciones binarias tienen riesgo de pérdida total; muchas jurisdicciones las restringen.

Licencia: propietaria, solo para revisión. Ver [`LICENSE`](LICENSE).
