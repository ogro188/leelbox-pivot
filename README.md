---
doc: README
repo: ogro188/leelbox-pivot
kind: research-archive
audience: [ai-agent, human-auditor]
language: es
status: shadow
verdict: no-edge-confirmed
data_cutoff_utc: 2026-11-07
data_window_utc: 2025-11-07/2026-11-06
assets: [EURUSD, XAUUSD]
timeframes: [M15, H1, H4, D1]
signal_horizons_min: {h1: 15, h2: 30, h3: 45, h4: 60, h5: 75, h6: 90, h7: 105, h8: 120}
license: research-only
---

# PIVOT — sistema de señales M15 para auditoría externa

**Qué es este documento.** Es la entrada única al repositorio. Está escrito para que un agente de IA o un auditor humano pueda entender qué es PIVOT, qué se probó, qué se encontró y qué falta, sin depender de contexto externo.

**Regla de oro:** el veredicto vigente es **negativo**. PIVOT **no tiene edge confirmado**, **no opera con dinero real** y **no debe promoverse**. Este repositorio existe para auditar el método, no para optimizar la estrategia.

---

## 0. Cómo leer este repositorio (instrucciones para un agente de IA)

Si eres un agente automatizado, ejecuta este protocolo:

1. **Lee este README completo.** Contiene el resumen autosuficiente.
2. **No infieras edge por resultados nominales.** Un `p` bruto bajo no es un hallazgo: solo cuenta el criterio estricto de la sección 7.
3. **Distingue tres estados:** `confirmado`, `no confirmado`, `falsificado`. La sección 1.2 tiene la tabla de estado de cada afirmación.
4. **Verifica los datos antes de analizarlos.** Los SHA-256 de la sección 6.3 permiten comprobar que los CSV no fueron alterados.
5. **Respeta las fechas.** El holdout (`2026-10-01 → 2026-11-06`) ya fue observado una vez; no lo reutilices para seleccionar hipótesis.
6. **No mezcles familias de tests.** Señales PIVOT, velas M15, patrones intradía y OTC tienen correcciones FDR independientes.
7. **No optimices TP/SL ni pruebes cientos de variantes.** El protocolo prohíbe ambas cosas en la fase de descubrimiento.
8. **Reporta con evidencia reproducible:** archivo, línea, comando, valor esperado, valor obtenido.

### 0.1 Orden de lectura recomendado

| Orden | Documento | Para qué | Tiempo |
|---:|---|---|---|
| 1 | `README.md` (este) | Contexto, hechos, veredicto | 10 min |
| 2 | [`docs/VALIDATION_PROTOCOL.md`](docs/VALIDATION_PROTOCOL.md) | Reglas pre-registradas y criterios | 15 min |
| 3 | [`docs/EDGE_FINDINGS.md`](docs/EDGE_FINDINGS.md) | Resultados live, holdout y ablación | 15 min |
| 4 | [`docs/OTC_FINDINGS.md`](docs/OTC_FINDINGS.md) | Validación OTC con payout real | 10 min |
| 5 | [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md) | Sesgos y deuda técnica | 10 min |
| 6 | [`docs/REPRODUCIBILITY.md`](docs/REPRODUCIBILITY.md) | Comandos y checksums | 10 min |
| 7 | [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md) | Las 176 columnas | consulta |
| 8 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Diseño interno del motor | consulta |
| 9 | [`docs/ANALYST_BRIEF.md`](docs/ANALYST_BRIEF.md) | Preguntas y entregables de la auditoría | 10 min |

### 0.2 Verificación mínima en 4 comandos

```bash
python -m compileall -q core kernel estrategias scripts tools tests
python -m pytest -q tests/unit                 # esperado: 110 passed
sha256sum data/eurusd_M15.csv data/xauusd_M15.csv   # comparar con la sección 6.3
python tools/edge_scan.py --inputs results/eurusd_signals.csv \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --hasta 2026-09-30 --tag disc --bootstrap 200 --out-dir /tmp/pivot-check
# esperado: 456 tests, 220 primarios, 0 supervivientes estrictos
```

---

## 1. Hechos verificables

### 1.1 Resumen en una tabla

| Hecho | Valor | Dónde verificarlo |
|---|---|---|
| Activos analizados | EURUSD, XAUUSD | `data/` |
| Velas M15 | 24.202 EURUSD / 23.140 XAUUSD | `data/*_M15.csv` |
| Periodo M15 | 2025-11-07 03:00 UTC → 2026-11-06 20:45 UTC | ídem |
| Señales PIVOT del replay | 8.959 EURUSD / 8.932 XAUUSD | `results/*_signals.csv` |
| Columnas por señal | 176 | `docs/DATA_DICTIONARY.md` |
| Ventana del replay | últimas 12.506 / 12.014 velas M15 desde 2026-05-05 08:30 UTC | `results/*_meta.json` |
| Warmup | 500 velas; primera señal 2026-05-12 | ídem |
| Tests unitarios | 110/110 pasan | `tests/unit/` |
| Supervivientes FDR | **0** en todos los escaneos | `results/edge_scan_*`, `bar_edge_*`, `pattern_edge_*` |
| Holdout EURUSD h3 | n=1.959, WR 48,7 %, EV −9,42 % | `docs/EDGE_FINDINGS.md` |
| Holdout XAUUSD h3 | n=1.908, WR 47,8 %, EV −13,01 % | ídem |
| Producción real | EV entre −8,85 % y −18,74 % | ídem |
| Veredicto | **sin edge confirmado; shadow** | este documento |

### 1.2 Estado de cada afirmación

| Afirmación | Estado | Evidencia |
|---|---|---|
| PIVOT supera el break-even en M15 | **No** | Holdout y producción negativos; 0/456 supervivientes |
| El contexto H4/H1 aporta dirección | **No demostrado** | Ablación: PIVOT ≈ `siempre_long` (≤ 0,8 pp) |
| `det_d5` h4 EURUSD es un edge | **No confirmado** | p=0,2803 en descubrimiento; p=0,0503 solo en ventana completa |
| `h4_pullback` h4 EURUSD es un edge | **Falsificado** | +4,91 % en descubrimiento → −2,63 % en ventana completa |
| EURUSD NYOR13 fade h1 | **No confirmado** | n=118, WR 58,47 %, p=0,1676, q=1,0 |
| XAUUSD LOR4 fade h8 | **No concluyente** | n=71, p=0,0037, q=0,697 |
| EURUSD-OTC / D2_ANTICIPACION | **Falsificado** | n=88, EV −1,39 %, depende de un día |
| XAUUSD-OTC / h1 alineado | **Hipótesis abierta** | n=133, EV +13,28 %, IC95 inferior < break-even |
| Look-ahead o leakage | **No detectado, pendiente de auditoría externa** | `docs/ANALYST_BRIEF.md` |

### 1.3 Veredicto

Tres fuentes independientes coinciden:

1. **Escaneo masivo:** 456 tests EURUSD y 448 XAUUSD sobre señales PIVOT, más 464/454 tests a nivel de vela y 168/184 de patrones. **Cero supervivientes** tras BH-FDR al 10 % con los criterios adicionales.
2. **Holdout temporal:** 1.959 señales EURUSD y 1.908 XAUUSD, EV negativo con intervalo de confianza enteramente negativo.
3. **Producción real:** 959–1.089 resultados EURUSD y 878–990 XAUUSD según horizonte, todos con EV negativo.

La habilidad direccional de PIVOT es estadísticamente indistinguible del drift incondicional. **No hay base para promover ningún filtro a demo ni a dinero real.**

---

## 2. Definiciones y notación

### 2.1 Términos

| Término | Definición operativa |
|---|---|
| **Señal** | Evento emitido por un detector D0–D5 con `direction != 0` tras los filtros. |
| **n** | Número de señales (u operaciones) de un test. |
| **WR** | Win rate: `wins / n`. |
| **Payout (`p`)** | Ganancia neta por unidad apostada si gana. `p=0,85` significa +85 %; si pierde, −100 %. |
| **Break-even (BE)** | WR mínimo para EV=0 con un payout dado. |
| **EV** | Valor esperado por operación, en fracción del stake. |
| **h1…h8** | Horizonte de salida: +15, +30, +45, +60, +75, +90, +105, +120 minutos. h1–h4 son confirmatorios; h5–h8 exploratorios. |
| **p bruto** | p-valor unilateral de un test individual, sin corregir. |
| **q (q-valor)** | p ajustado por Benjamini-Hochberg (FDR). |
| **Primario** | Test de la familia con `n ≥ 100`. |
| **Superviviente estricto** | Test que cumple **las cuatro** condiciones de la sección 7.3. |
| **MFE / MAE** | Máxima excursión favorable / adversa dentro del horizonte, en puntos. |
| **OTC** | Contrato sintético de IQ Option, fuera de horario de mercado. Solo lectura. |

### 2.2 Fórmulas

```text
WR       = wins / n
EV       = WR * payout - (1 - WR)
BE       = 1 / (1 + payout)
q        = BH-FDR(p, familia)          # Benjamini-Hochberg, α = 0,10
IC95     = Wilson(WR, n)
bootstrap = percentiles 2,5 / 97,5 de 2.000 remuestreos por día UTC
```

Break-even por payout:

| Payout | Break-even WR |
|---:|---:|
| 81 % | 55,25 % |
| 82 % | 54,95 % |
| 83 % | 54,64 % |
| 84 % | 54,35 % |
| 85 % | 54,05 % |
| 86 % | 53,76 % |
| 87 % | 53,48 % |

### 2.3 Convenciones

- **Zona horaria:** todo en UTC. Los CSV usan timestamps ISO-8601 con offset `+00:00`.
- **Puntos vs pips:** EURUSD `point=1e-5` (1 pip = 10 puntos); XAUUSD `point=0,01`.
- **Etiquetas:** `ret_hN` en puntos, ajustado por dirección. `win_hN ∈ {0,1}`.
- **Signo:** dirección `+1` = long/CALL; `−1` = short/PUT.

---

## 3. Qué es y qué no es PIVOT

### 3.1 Es

- Un motor modular de análisis de precio M15 con contexto H1/H4/D1.
- Un conjunto de detectores de Smart Money Concepts: barridos, FVG, order blocks, MSS.
- Un generador de señales con dirección, entrada de referencia, expiración y narrativa.
- Un pipeline de validación estadística con separación temporal, FDR y bootstrap.
- Un archivo de investigación reproducible, con datos y resultados versionados.

### 3.2 No es

- **No ejecuta órdenes.** No hay integración de ejecución ni claves de trading.
- **No opera con dinero real.** El modo actual es shadow.
- **No tiene edge confirmado.** Ver sección 1.
- **No es asesoramiento financiero.**
- **No incluye el frontend, los servicios systemd ni la base de producción.**
- **No es una estrategia optimizada.** Es el objeto de una auditoría.

---

## 4. Arquitectura

### 4.1 Estructura

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

### 4.2 Flujo de una señal

```text
Deriv / CSV M15
      │
      ├── resample H1/H4 ──┐
      ├── D1 ──────────────┤
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

### 4.3 Detectores

| ID | Patrón | Lógica resumida |
|---|---|---|
| **D0** | Estructura H1 | Swings HH/HL/LH/LL, barridos y zonas de liquidez. Base para el resto. |
| **D1** | Ruptura de rango | Ruptura de un rango de N velas con penetración ATR, cuerpo y volumen; retest opcional. |
| **D2** | Sweep + reclaim | Barrido de liquidez con mecha, recuperación del nivel y cierre de vuelta dentro del rango. |
| **D2_A** | Sweep anticipado | Variante de D2 con mecha menor y confluencias FVG/OB/MSS. |
| **D3** | Fair Value Gap | Gap de precio con tamaño ATR, cuerpo y alineación MSS; variante defendida. |
| **D4** | Order Block | Bloque de órdenes con impulso, cuerpo, no testeado y distancia ATR. |
| **D5** | MSS H4 + sweep M15 | Cambio de estructura H4 alineado con barrido y reclaim en M15. |

Los detectores devuelven siempre una señal; los filtros fallidos se registran como metadatos (`filtros_pasados`, `filtros_fallados`, `direction=0`). El motor descarta `direction == 0` antes del scoring.

### 4.4 Componentes principales

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
| API | `kernel/api/app.py` | FastAPI + WebSocket; solo backend, sin frontend. |
| Estrategia | `estrategias/pivot/` | Plugin PIVOT con parámetros y scoring. |
| Replay | `tools/feature_replay.py` | Genera señales + 176 columnas de features y etiquetas. |

### 4.5 Reglas de diseño relevantes para la auditoría

1. **Corte de timeframes superiores:** `searchsorted(side="left")`; solo velas cerradas.
2. **Entrada de referencia:** `close[t]` en `feature_replay.py` y `bar_edge.py`; `open[t+1]` en `pattern_edge.py`. Es un supuesto **optimista** en los dos primeros: no modela gap ni slippage.
3. **Sin órdenes:** el sistema no ejecuta; `PIVOT_ALERTAS_LIVE=0` por defecto.
4. **Trazabilidad:** cada señal conserva detector, features, filtros y narrativa.
5. **Replay verificable:** `tools/fast_engine.py` replica la lógica del motor y se contrasta contra el motor sin acelerar.

---

## 5. Inventario del repositorio

### 5.1 Código

| Ruta | Contenido |
|---|---|
| `core/` | `motor_v8.py`, detectores `d0`–`d5`, `scoring.py`, `estructuras.py`, `hipotesis.py`, `alertas.py`, `utils.py` |
| `kernel/` | `contrato.py`, `backtest.py`, `storage.py`, `metricas_g.py`, `binary/`, `feeds/`, `api/` |
| `estrategias/` | `pivot/`, `binary/`, `dummy/`, `ema_cross/`, `registro.py` |
| `scripts/` | `run_deriv_ws.py`, `iq_public_collector.py`, `export_ml_dataset.py` |
| `tools/` | 26 utilidades de replay, escaneo, validación y OTC (ver 5.2) |
| `tests/unit/` | 10 archivos, 110 tests |
| `tests/integration/` | 3 archivos; dependen de datos/DB no distribuidos |

### 5.2 Herramientas principales

| Herramienta | Función |
|---|---|
| `tools/feature_replay.py` | Replay del motor; genera señales, features y etiquetas h1–h8. |
| `tools/fast_engine.py` | Aceleradores solo para replay; no se importan desde producción. |
| `tools/edge_scan.py` | Screening univariado con BH-FDR y bootstrap por día. |
| `tools/bar_edge.py` | Escaneo a nivel de vela M15 (familias de calendario, RSI, ATR, etc.). |
| `tools/pattern_edge.py` | Patrones intradía con mecanismo explícito y entrada en `open[t+1]`. |
| `tools/ablation.py` | Ablación H4-only, H1-only, H4+H1, PIVOT, PIVOT+H4+H1. |
| `tools/holdout.py` | Confirmación en holdout de los filtros de descubrimiento. |
| `tools/walkforward.py` | Estabilidad mensual de un filtro. |
| `tools/validate_labels.py` | Compara etiquetas del replay con `senales_resultados`. |
| `tools/replay_report.py` | Fidelidad replay vs producción: IDs, detector, dirección, convicción. |
| `tools/make_replay_window.py` | Extrae las últimas 12.506 / 12.014 velas M15 del corpus. |
| `tools/otc_validate.py` | Valida filtros OTC con el payout real de cada señal. |
| `tools/otc_context.py` | Reconstruye features de contexto para señales OTC. |
| `tools/otc_forward_report.py` | Reporte de forward test OTC (solo lectura). |
| `tools/prod_wr.py` | Winrate real por horizonte y detector desde producción. |
| `tools/run_full_analysis.sh` | Pipeline completo: escaneos, ablación, holdout y resumen. |
| `tools/summarize.py` | Resumen tabular de los CSV de resultados. |

### 5.3 Documentación

| Archivo | Contenido | Canónico |
|---|---|---|
| `README.md` | Este documento | Sí |
| `docs/VALIDATION_PROTOCOL.md` | Protocolo pre-registrado, FDR, splits | Sí |
| `docs/EDGE_FINDINGS.md` | Veredicto live, holdout, ablación, producción | Sí |
| `docs/OTC_FINDINGS.md` | Validación OTC y candidatos | Sí |
| `docs/RESULTS_SUMMARY.md` | Resumen tabular de todos los estudios | Sí |
| `docs/LIMITATIONS.md` | Sesgos, datos, etiquetas, deuda técnica | Sí |
| `docs/REPRODUCIBILITY.md` | Comandos, ventana de replay y checksums | Sí |
| `docs/DATA_DICTIONARY.md` | Diccionario de las 176 columnas | Sí |
| `docs/ARCHITECTURE.md` | Arquitectura y ciclo de una señal | Sí |
| `docs/ANALYST_BRIEF.md` | Preguntas y entregables de la auditoría | Sí |
| `docs/archive/` | Documentos históricos | **No**; prevalece el protocolo vigente |

### 5.4 Datos y resultados

| Ruta | Filas | Columnas | Contenido |
|---|---:|---:|---|
| `data/eurusd_M15.csv` | 24.202 | OHLCV + datetime | Velas M15 de 12 meses |
| `data/xauusd_M15.csv` | 23.140 | OHLCV + datetime | Velas M15 de 12 meses |
| `data/*_D1.csv` | 257 / 256 | OHLCV + datetime | Velas diarias |
| `data/*_H1.csv` | 440 / 425 | OHLCV + datetime | Muestras recientes (no 12 meses) |
| `data/*_H4.csv` | 214 / 214 | OHLCV + datetime | Muestras recientes (no 12 meses) |
| `results/eurusd_signals.csv` | 8.959 | 176 | Señales + features + etiquetas |
| `results/xauusd_signals.csv` | 8.932 | 176 | Ídem |
| `results/edge_scan_*_disc.csv` | 456 / 448 | 21 | Tests de descubrimiento |
| `results/edge_scan_*_full.csv` | 456 / 456 | 21 | Tests de ventana completa |
| `results/bar_edge_*.csv` | 464 / 454 | 18 | Escaneo a nivel de vela |
| `results/pattern_edge_*.csv` | 168 / 184 | 20 | Patrones intradía |
| `results/ablation_*.csv` | 48 | 13 | Ablación de contexto |
| `results/holdout_*.csv` | 33 | 15 | Holdout por combinación |
| `results/otc_features.csv` | 673 | 38 | Señales OTC con contexto |
| `results/otc_validation.csv` | 28 | 14 | Validación OTC con payout real |
| `results/walkforward_eurusd.csv` | 14 | 15 | Estabilidad mensual |

Inventario completo y verificable:

```bash
git ls-files | sort                 # 170 archivos versionados
find data results -name '*.csv' -exec wc -l {} +
```

---

## 6. Datos

### 6.1 Velas

| Archivo | Velas | Inicio (UTC) | Fin (UTC) | Fuente |
|---|---:|---|---|---|
| `data/eurusd_M15.csv` | 24.202 | 2025-11-07 03:00 | 2026-11-06 20:45 | Deriv `frxEURUSD` |
| `data/xauusd_M15.csv` | 23.140 | 2025-11-07 03:00 | 2026-11-06 20:45 | Deriv `frxXAUUSD` |
| `data/eurusd_D1.csv` | 257 | 2025-11-10 00:00 | 2026-11-05 00:00 | Deriv |
| `data/xauusd_D1.csv` | 256 | 2025-11-10 00:00 | 2026-11-05 00:00 | Deriv |
| `data/eurusd_H1.csv` | 440 | 2026-10-13 03:00 | 2026-11-06 19:00 | Deriv |
| `data/xauusd_H1.csv` | 425 | 2026-10-13 03:00 | 2026-11-06 19:00 | Deriv |
| `data/eurusd_H4.csv` | 214 | 2026-09-18 04:00 | 2026-11-06 16:00 | Deriv |
| `data/xauusd_H4.csv` | 214 | 2026-09-18 04:00 | 2026-11-06 16:00 | Deriv |

- La API de Deriv devolvió **12 meses como máximo** para M15; no hay 24 meses.
- Los H1/H4 incluidos **no** cubren 12 meses: son las últimas páginas. El replay deriva H1/H4 desde M15; los CSV H1/H4 son solo una muestra de contraste.
- Los CSV contienen solo OHLCV público. Sin IDs de cuenta, tokens ni datos personales.
- `tools/fetch_history.py` documenta la descarga; requiere red y el feed de Deriv.

### 6.2 Señales precalculadas

| Archivo | Filas | Columnas | Rango de señales |
|---|---:|---:|---|
| `results/eurusd_signals.csv` | 8.959 | 176 | 2026-05-12 16:00 → 2026-11-06 18:00 UTC |
| `results/xauusd_signals.csv` | 8.932 | 176 | 2026-05-12 20:00 → 2026-11-06 17:30 UTC |

Cada fila incluye:

- identidad (`id`, `entry_time`, `symbol`, `direction`, `detector`, `tipo`);
- features de detector (sweep, FVG, OB, MSS);
- contexto (ATR, EMA, RSI, sesión, kill zone, trend D1, volatilidad);
- calidad, confluencia, salud tendencial y narrativa;
- `ret_h1…h8`, `win_h1…h8`, `mfe_h1…h8`, `mae_h1…h8`;
- filtros pasados/fallados y flags de diagnóstico.

Diccionario completo: [`docs/DATA_DICTIONARY.md`](docs/DATA_DICTIONARY.md).

### 6.3 Checksums SHA-256

```text
7f1c862cda5c0c12557979cfe606864e75a389f0dd0e572925fe3c2980f92349  data/eurusd_M15.csv
12d93f645b2cdbedcde8b2e1a1e3cb17c0a676ba370ceab626b6b5a6e6220543  data/xauusd_M15.csv
f955ac6b03b374dba00cc51e772bde72a38c353fcd8dbe4ba78fd18dad4695c4  data/eurusd_D1.csv
43b8e6d43f4c5d57e3733815e0eb60e5405842f93d64d4e437b39e30eaaf8e43  data/xauusd_D1.csv
e6e0e925dc835933118df53f6d3696c631552c61fdea2fd83c674e773ec62adc  results/eurusd_signals.csv
ce09399761d0d35ba5d14428c4d57526ad00cad091b74859ed9177ccfc64a9cf  results/xauusd_signals.csv
c4971c39fea7cc56afd8e15467b5a934c05add173df02e8396bd30549828ac30  results/edge_scan_eurusd_disc.csv
77aefd454fbc6a1b02f66c0634dad0bf6331fb0fa56c6a89d7e41c2a9e2ec0c6  results/edge_scan_xauusd_disc.csv
ebe15df523a47d8a30add5f46a6762a6c378e0d6a94a3712cb2be796d5f8c0e6  results/bar_edge_eurusd.csv
dac9b7f73517728372347de7911b925cad6a2549b580d76fb07494a26086d76e  results/pattern_edge_eurusd.csv
f024df32d099862cca3d52c95ff47fd2492cd2d66a8c08a31b3c7c6d602ea7c9  results/otc_validation.csv
3f0acfa5d9dda676e3e366f65d1b15922fbcf1d7ac813e6ddeb2ff7eba789c67  results/otc_features.csv
4fc4460722e2a2ccd14fdf05c19df3104cb45009a35ed232d393aa541dbb26f4  results/walkforward_eurusd.csv
```

Verificación:

```bash
sha256sum data/eurusd_M15.csv data/xauusd_M15.csv \
          results/eurusd_signals.csv results/xauusd_signals.csv
```

### 6.4 Ventana exacta del replay

El replay publicado **no usó los 12 meses completos**. Usó las últimas N velas del M15:

| Activo | Velas M15 | Inicio | Fin | Señales |
|---|---:|---|---|---:|
| EURUSD | 12.506 | 2026-05-05 08:30 UTC | 2026-11-06 20:45 UTC | 8.959 |
| XAUUSD | 12.014 | 2026-05-05 08:30 UTC | 2026-11-06 20:45 UTC | 8.932 |

Warmup: 500 velas. Por eso la primera señal aparece el 2026-05-12. `results/*_meta.json` confirma `m15_total`, `replay_inicio`, `replay_fin` y `senales`.

Para reconstruir la ventana:

```bash
python tools/make_replay_window.py --symbol EURUSD --out-dir /tmp/pivot-repro/data
python tools/make_replay_window.py --symbol XAUUSD --out-dir /tmp/pivot-repro/data
```

---

## 7. Protocolo de validación

El protocolo está pre-registrado en [`docs/VALIDATION_PROTOCOL.md`](docs/VALIDATION_PROTOCOL.md).

### 7.1 Reglas

- **Separación temporal:** descubrimiento → purga → validación/holdout → test. **Nunca k-fold aleatorio.**
- **Etiquetas:** h1 = +15 min, h2 = +30, h3 = +45, h4 = +60; h5–h8 solo exploratorias.
- **Estadística:** IC95 de Wilson, p-valor unilateral contra break-even, BH-FDR al 10 %, block bootstrap por día UTC.
- **Payout real por horizonte**, no un 85 % fijo:
  - EURUSD: 85 / 86 / 86 / 87 % (h1–h4).
  - XAUUSD: 81 / 82 / 82 / 83 % (h1–h4).
- **Sin optimización de TP/SL** en el escaneo principal; el análisis de salidas es posterior y separado.
- **Sensibilidad:** se reporta EV con payout −3/+3 pp.
- **Ablación:** H4-only, H1-only, H4+H1, PIVOT, PIVOT+H4+H1 y `siempre_long` como control.

### 7.2 Cortes temporales

| Estudio | Descubrimiento | Validación | Test / holdout |
|---|---|---|---|
| Señales PIVOT (6 meses) | 2026-05-12 → 2026-09-29 | — | 2026-10-01 → 2026-11-06 |
| Velas M15 (12 meses) | 2025-11-07 → 2026-09-30 | — | 2026-10-01 → 2026-11-06 |
| Patrones intradía (12 meses) | 2025-11-07 → 2026-04-30 | 2026-05-01 → 2026-07-31 | 2026-08-01 → 2026-11-06 |
| OTC | — | — | 2026-11-01 → 2026-11-07 (forward retrospectivo) |

Los cortes **no son intercambiables**: cada estudio tiene su propia familia de tests y su propia corrección.

### 7.3 Criterio de supervivencia

Un test solo se considera confirmado si cumple **las cuatro condiciones**:

```text
q ≤ 0,10
y wr_lo (IC95 Wilson) > break-even
y ev_boot_lo (bootstrap 95 %) > 0
y n ≥ 100
```

Cualquier resultado que no cumpla las cuatro es **nominal**, no confirmado.

### 7.4 Por qué no k-fold

Los datos son una serie temporal con autocorrelación y regímenes. Un k-fold aleatorio filtraría información del futuro al pasado. El protocolo usa cortes cronológicos, purga entre tramos y bootstrap por día.

---

## 8. Resultados

### 8.1 Señales PIVOT — escaneo principal

| Activo | Tests | Primarios n ≥ 100 | Supervivientes FDR | Mejor p bruto |
|---|---:|---:|---:|---|
| EURUSD | 456 | 220 | **0** | 0,1385 (`h4_pullback` h4) |
| XAUUSD (descubrimiento) | 448 | 220 | **0** | 0,6665 (`tipo_a` h4) |
| XAUUSD (ventana completa) | 456 | 228 | **0** | — |

- Ningún test alcanzó `q < 0,10`.
- El “casi” `det_d5` h4 EURUSD (n=324, WR 58,0 %, EV +8,51 %, p=0,0503) **no era significativo en descubrimiento** (p=0,2803) y su resultado completo depende de octubre. **No es un hallazgo confirmado.**
- `h4_pullback` h4 pasa de +4,91 % en descubrimiento a −2,63 % en ventana completa.

### 8.2 Holdout

| Activo | Horizonte | n | WR | IC95 | EV | Bootstrap 95 % |
|---|---|---:|---:|---|---:|---|
| EURUSD | h3 (base) | 1.959 | 48,7 % | 46,5–50,9 | −9,42 % | [−15,36, −3,49] |
| XAUUSD | h3 (base) | 1.908 | 47,8 % | 45,6–50,0 | −13,01 % | [−16,97, −8,57] |

Las 32 combinaciones a priori evaluadas en holdout son negativas en ambos activos. No había supervivientes que confirmar.

### 8.3 Ablación

Winrate h1–h4 (%):

| Variante | EURUSD | XAUUSD |
|---|---|---|
| H4_only | 49,3 / 49,5 / 49,9 / 50,4 | 50,4 / 50,8 / 50,7 / 50,7 |
| H1_only | 49,0 / 49,1 / 49,7 / 49,7 | 49,8 / 49,8 / 49,6 / 49,6 |
| H4+H1 | 49,1 / 49,4 / 49,9 / 50,3 | 50,2 / 50,4 / 50,2 / 50,2 |
| `siempre_long` | 47,9 / 48,0 / 47,9 / 47,9 | 49,2 / 48,5 / 48,5 / 48,4 |
| PIVOT | 47,6 / 48,5 / 48,1 / 48,7 | 48,2 / 48,6 / 48,5 / 48,7 |
| PIVOT+H4+H1 | 48,3 / 49,1 / 48,6 / 49,6 | 48,9 / 50,0 / 48,7 / 48,2 |

Todos los EV son negativos (−5,8 % a −12,8 %). **PIVOT está al mismo nivel que `siempre_long`** (diferencias ≤ 0,8 pp): no hay habilidad direccional medible en esta muestra.

### 8.4 Producción real

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

### 8.5 Escaneo a nivel de vela

Familias: calendario/hora/día, momentum/reversión, RSI14, volatilidad/ATR, EMA50, cuerpo/rango.

| Activo | Tests | Supervivientes FDR | Mejores señales nominales |
|---|---:|---:|---|
| EURUSD | 464 | **0** | `hora_20_L` h4: n=344, WR 60,8 %, EV +13,61 %, p=0,0034, q=1,0; `hora_16_S` h4: n=428, WR 59,6 %, EV +11,41 %, p=0,0057, q=1,0 |
| XAUUSD | 454 | **0** | `hora_09_L` h4: n=428, WR 60,7 %, EV +11,17 %, p=0,0056, q=1,0; `hora_16_S` h4: n=422, WR 58,8 %, EV +7,55 %, p=0,0444, q=1,0 |

Las mejores horas de descubrimiento se caen en holdout o no sobreviven FDR. `hora_20_L` h4 y `ema_gt_2_S` h4 EURUSD son las únicas con signo positivo en ambos períodos, pero sin significancia tras corrección. **No son candidatos promovibles.**

### 8.6 Patrones intradía

Familias: ARB (rango asiático), LOR (opening range Londres), NYOR (opening range Nueva York), SWEEP (falso breakout de 20 velas), CLOSE (momentum de cierre), PDH (máximo/mínimo del día anterior).

| Activo | Tests | Supervivientes FDR | Mejor p bruto |
|---|---:|---:|---|
| EURUSD | 168 | **0** | `LOR3 break fade` h8: n=114, WR 64,9 %, EV +21,39 %, p=0,0072, q=0,717 |
| XAUUSD | 184 | **0** | `LOR4 break fade` h8: n=71, WR 70,4 %, EV +28,87 %, p=0,0037, q=0,697 |

El candidato más comentado, **NYOR13 fade h1** (EURUSD, fade de la ruptura del opening range 13:00–13:45, expiry 15 min), tiene en descubrimiento:

- n=118, WR 58,47 %, EV +8,18 %, IC95 49,45–66,96, p=0,1676, q=1,0.

No sobrevive FDR. Las ventanas posteriores fueron positivas en la corrida original, pero **no son confirmatorias** y no se usaron para seleccionar. Es una hipótesis abierta, no un edge.

### 8.7 OTC (IQ Option, solo lectura)

| Activo | Filtro | n | WR | Payout | EV | Bootstrap 95 % |
|---|---|---:|---:|---:|---:|---|
| EURUSD-OTC | D2_ANTICIPACION h3 | 88 | 53,41 % | 84,77 % | −1,39 % | [−26,39, +21,32] |
| XAUUSD-OTC | h1 alineado h3 | 133 | 60,90 % | 86,00 % | +13,28 % | [−3,04, +25,16] |

- **EURUSD-OTC / D2_ANTICIPACION:** cerrado/falsificado. EV negativo y dependiente de un solo día.
- **XAUUSD-OTC / h1 alineado:** única señal positiva, pero con 5 días efectivos, IC95 inferior 52,4 % < break-even 53,76 % y bootstrap que cruza cero. **Hipótesis para forward test, no promoción.**

La muestra OTC es de ~6 días (581 velas M15 por activo); el warmup de H1/H4 deja una muestra efectiva de ~4 días.

### 8.8 Veredicto

**No hay edge confirmado.** La evidencia es consistente en tres fuentes independientes: escaneos masivos, holdout temporal y resultados reales de producción. PIVOT no supera el break-even de las opciones binarias a los payouts disponibles.

**Decisión:** mantener todo en shadow, no tocar producción, no promover candidatos.

---

## 9. Hipótesis abiertas (no confirmadas)

| Hipótesis | Evidencia | Estado |
|---|---|---|
| EURUSD NYOR13 fade h1 | n=118, WR 58,5 %, EV +8,18 %, p=0,168 | Exploratoria; requiere OOS y FDR |
| EURUSD `hora_20_L` h4 / `ema_gt_2_S` h4 | Nominal, positivo en descubrimiento y holdout | Sin significancia; probable ruido |
| XAUUSD LOR4 fade h8 | n=71, WR 70,4 %, EV +28,9 %, p=0,0037, q=0,697 | Muestra pequeña; no concluyente |
| XAUUSD-OTC h1 alineado h3 | n=133, WR 60,9 %, EV +13,3 %, IC cruza BE | Forward test en shadow |

Ninguna de estas hipótesis debe promoverse a demo o dinero real sin el protocolo de [`docs/VALIDATION_PROTOCOL.md`](docs/VALIDATION_PROTOCOL.md).

---

## 10. Reproducción

### 10.1 Entorno

- Python 3.11 o 3.12.
- Dependencias: `requirements.txt` (pandas, numpy, fastapi, uvicorn, websockets, requests, pytest, httpx, ta, python-dotenv).
- No se necesita cuenta de Deriv para trabajar con los CSV incluidos.
- No se necesita IQ Option para auditar los resultados OTC; las DB originales no se distribuyen.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

El replay original se ejecutó en un host ARM con Python 3.11, pandas 2.2.3 y numpy 2.2.4. La copia sanitizada se validó con Python 3.12, pandas 3.0.6 y numpy 2.5.3. Si aparece una diferencia numérica, revisar primero la versión de pandas/numpy.

### 10.2 Verificación rápida (sin replay)

```bash
# 1. Compilación
python -m compileall -q core kernel estrategias scripts tools tests

# 2. Tests unitarios (esperado: 110 passed)
python -m pytest -q tests/unit

# 3. Escaneo de señales ya calculadas (rápido)
python tools/edge_scan.py \
  --inputs results/eurusd_signals.csv \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --hasta 2026-09-30 --tag disc --out-dir /tmp/pivot-repro

# 4. Holdout
python tools/holdout.py \
  --signals results/eurusd_signals.csv \
  --scan /tmp/pivot-repro/edge_scan_eurusd_disc.csv \
  --split 2026-10-01 --desc-hasta 2026-09-30 \
  --payouts-by-h 0.85,0.86,0.86,0.87,0.87,0.87,0.87,0.87 \
  --out-dir /tmp/pivot-repro

# 5. Escaneo a nivel de vela y patrones (minutos)
python tools/bar_edge.py --symbol EURUSD --bootstrap 300 --out-dir /tmp/pivot-repro
python tools/pattern_edge.py --symbol EURUSD --bootstrap 300 --out-dir /tmp/pivot-repro
```

Los resultados deben coincidir con `results/` en `n`, `wins`, `wr`, `p`, `q` y `criterio`. Puede haber diferencias mínimas por versión de numpy/pandas y por el bootstrap si no se fija semilla.

### 10.3 Replay exacto

```bash
python tools/make_replay_window.py --symbol EURUSD --out-dir /tmp/pivot-repro/data
python tools/make_replay_window.py --symbol XAUUSD --out-dir /tmp/pivot-repro/data

python tools/feature_replay.py \
  --symbol EURUSD \
  --m15 /tmp/pivot-repro/data/eurusd_M15.csv \
  --d1 data/eurusd_D1.csv \
  --warmup 500 \
  --out-dir /tmp/pivot-repro/results

python tools/feature_replay.py \
  --symbol XAUUSD \
  --m15 /tmp/pivot-repro/data/xauusd_M15.csv \
  --d1 data/xauusd_D1.csv \
  --warmup 500 \
  --out-dir /tmp/pivot-repro/results
```

Salidas esperadas:

- `eurusd_signals.csv` / `xauusd_signals.csv` con 8.959 / 8.932 filas y 176 columnas.
- `*_meta.json` con rango, velas, segundos y validación de etiquetas.
- La validación contra producción devuelve `db no existe` si no se aporta `pivotradar_data/`; es esperado.

Tiempo de referencia en el host original: **1.576,8 s** EURUSD y **1.549,6 s** XAUUSD (~26 min por activo). En un x86 moderno suele ser más rápido.

### 10.4 Pipeline completo

```bash
bash tools/run_full_analysis.sh
```

Variables opcionales:

```bash
PYTHON=/ruta/al/python OUT=/tmp/pivot-repro BOOTSTRAP=500 bash tools/run_full_analysis.sh
```

El script:

- ejecuta desde la raíz del repositorio;
- verifica que `PYTHON` tenga pandas/numpy;
- omite los pasos de fidelidad si no existe `pivotradar_data/`;
- escribe escaneos, ablación, holdout y `summary.txt` en `OUT`.

### 10.5 Qué se puede reproducir sin producción

| Elemento | ¿Reproducible? | Nota |
|---|---|---|
| Señales M15 (8.959/8.932) | Sí, con la ventana exacta | ~26 min por activo |
| Escaneos PIVOT | Sí | Desde los CSV de señales |
| Holdout y ablación | Sí | Desde los CSV |
| Escaneos de velas/patrones | Sí | Desde M15 de 12 meses |
| Resultados OTC | Parcial | Faltan las DB originales; solo se auditan los CSV agregados |
| Producción real | No | La DB no se distribuye; se incluyen agregados |
| Fidelidad replay vs producción | No | Requiere `pivotradar_data/` y los IDs de producción |

---

## 11. Trampas, limitaciones y artefactos conocidos

Esta sección es la lista de cosas que un auditor **debe** saber antes de sacar conclusiones.

1. **La entrada de referencia es el close de la vela de señal, no el open siguiente.** `feature_replay.py` usa `entry_price = close[t]`. Es un supuesto **optimista**: en la práctica se entraría en el open de `t+1` o después. El sesgo de gap/slippage no se modela. `pattern_edge.py` sí usa `open[t+1]`, con chequeo de continuidad por `epoch`; `bar_edge.py` usa `close[t] → close[t+h]`.
2. **h4 no está validado contra producción.** Solo hay 3 filas EURUSD y 6 XAUUSD con resultado h4 en la DB. Las conclusiones de h4 son replay-only.
3. **El replay cubre ~82 % de las señales de producción y emite señales extra.** EURUSD 1.541/1.869 (82,5 %); XAUUSD 1.435/1.781 (80,6 %). Las conclusiones se apoyan también en la DB de producción.
4. **D1 EMA200 no existe antes de ~septiembre 2026.** `trend_d1` es NEUTRO en los primeros meses; los filtros que dependen de D1 están ciegos al inicio.
5. **OTC tiene ~6 días de historia y warmup insuficiente.** H4 ~35 velas, H1 ~145; la EMA50 de H1 necesita ~50 horas. La muestra efectiva es ~4 días, no 6.
6. **El horizonte se cuenta por posición (`pos + h`) en `feature_replay.py`.** No hay chequeo explícito de continuidad temporal. Si faltara una vela, el horizonte se desplazaría. Los M15 incluidos no tienen duplicados ni nulos, pero los fines de semana no existen. `pattern_edge.py` sí verifica continuidad por `epoch`.
7. **`mfe_h*`/`mae_h*` incluyen la vela de señal.** Pueden capturar excursiones anteriores a la entrada; no se usan para win/loss.
8. **`results/edge_scan_all_disc.csv` y `edge_scan_all_full.csv` contienen solo XAUUSD.** Son un artefacto de la última corrida por activo, no una concatenación. Los archivos canónicos son `edge_scan_eurusd_*` y `edge_scan_xauusd_*`.
9. **Los tests de integración no son ejecutables tal cual.** `tests/integration/test_backtest_genera_operaciones.py` referencia `data/eurusd_m15_real.csv`, que no se distribuye. Los 110 tests que se reportan son solo `tests/unit`.
10. **Los nombres de CSV son sensibles a mayúsculas en Linux.** El corpus usa `eurusd_M15.csv`; la API y `CSVFeed` resuelven `eurusd_m15.csv` con una búsqueda case-insensitive, pero un `pandas.read_csv` directo con el nombre equivocado falla.
11. **El bootstrap no siempre fija semilla.** Los p y q son estables; los extremos del IC pueden variar en el último decimal.
12. **El modelo binario no modela ticks, empates ni slippage intravela.** Asume payout fijo por horizonte y resolución al close.
13. **12 meses es el máximo de Deriv para M15.** No hay 24 meses; cualquier análisis de ciclo largo está limitado.
14. **Las familias de tests no se mezclan.** Señales PIVOT, velas, patrones y OTC tienen correcciones independientes; sumar p-valores entre ellas invalida el FDR.
15. **El holdout ya fue observado.** No lo reutilices para seleccionar filtros; un nuevo holdout requiere datos posteriores a 2026-11-06.
16. **La DB de producción no se distribuye.** Los números de producción son agregados verificables en `docs/EDGE_FINDINGS.md`, no recalculables desde este repo.
17. **`DATABASE_URL` de producción apuntaba a una base efímera.** Es un riesgo operativo, no un resultado de investigación; no se tocó.

Detalle ampliado: [`docs/LIMITATIONS.md`](docs/LIMITATIONS.md).

---

## 12. Sanitización y seguridad

Este repositorio es una **extracción limpia**, no un volcado de producción. Se excluyeron o neutralizaron:

- `.env` y cualquier credencial; el código lee `DERIV_APP_ID` / `DERIV_API_TOKEN` del entorno.
- Bases SQLite de producción (`pivotradar_data/`), WAL/SHM, logs y backups.
- IDs de cuenta, tokens, topics privados de notificación y rutas absolutas del host.
- Frontend, servicios systemd y scripts operativos de backup/monitorización.
- Datos personales o de cuenta: los CSV solo contienen OHLCV público.

Antes de publicar se ejecutó un escaneo de secretos y se revisó que no quedaran tokens, contraseñas, emails, IPs privadas ni IDs de cuenta. Si encuentras algún residuo, repórtalo de inmediato.

**Nota sobre el historial:** los commits anteriores al reemplazo de `main` conservan el snapshot público de octubre de 2026. Ese historial ya era público y no contiene credenciales reales; sí contiene un nombre de host de Tailscale en `etc/ntfy/server.yml`. Purgarlo exigiría reescribir el historial.

---

## 13. Preguntas para el auditor externo

1. ¿Hay look-ahead, leakage o un desfase de etiquetas en `feature_replay.py`, `fast_engine.py`, `edge_scan.py`, `bar_edge.py` o `pattern_edge.py`?
2. ¿La familia de tests y el BH-FDR están bien definidos? ¿El bootstrap por día respeta la dependencia intra-día?
3. ¿Los splits temporales y la purga son suficientes? ¿Hay contaminación entre descubrimiento, validación y test?
4. ¿La entrada al close de la vela de señal (o al open siguiente) y la salida al close `t+h` son ejecutables con el payout y la expiración reales? ¿Cuánto sesga el supuesto de entrada?
5. ¿El replay es suficientemente fiel (82 % de overlap) o el sesgo de selección invalida las conclusiones?
6. ¿Alguna de las hipótesis abiertas tiene mecanismo económico/estadístico suficiente para un forward test?
7. ¿Qué haría falta para demostrar edge con `n ≥ 300`, IC95 inferior > break-even y bootstrap inferior > 0?
8. ¿Hay bugs, decisiones de diseño o supuestos que inflen o escondan el resultado?

Entregables sugeridos: informe con hallazgos por severidad, evidencia reproducible (archivo/línea/comando), y veredicto explícito sobre si algún resultado cambia. El brief completo está en [`docs/ANALYST_BRIEF.md`](docs/ANALYST_BRIEF.md).

---

## 14. Glosario

| Término | Significado |
|---|---|
| **ARB** | Asian Range Break: ruptura del rango asiático. |
| **LOR** | London Opening Range: rango de apertura de Londres. |
| **NYOR** | New York Opening Range: rango de apertura de Nueva York. |
| **SWEEP** | Falso breakout de 20 velas; barrido de liquidez. |
| **CLOSE** | Momentum de cierre de sesión. |
| **PDH/PDL** | Previous Day High/Low. |
| **FVG** | Fair Value Gap: ineficiencia de precio. |
| **OB** | Order Block: zona de órdenes institucionales. |
| **MSS** | Market Structure Shift: cambio de estructura. |
| **Kill zone** | Ventana horaria de mayor liquidez. |
| **Shadow** | Modo de solo generación/registro de señales, sin ejecución. |
| **Forward test** | Validación sobre datos posteriores al corte, sin reoptimizar. |
| **Purga** | Separación temporal entre descubrimiento y holdout para evitar fuga. |

---

## 15. Mapa de documentación y precedencia

Si dos documentos se contradicen, prevalece este orden:

```text
1. docs/VALIDATION_PROTOCOL.md     # reglas y criterios
2. docs/EDGE_FINDINGS.md           # resultados live/holdout/ablación
3. docs/OTC_FINDINGS.md            # resultados OTC
4. docs/RESULTS_SUMMARY.md         # resumen tabular
5. README.md                       # visión general
6. docs/archive/                   # histórico; nunca prevalece
```

Los documentos de `docs/archive/` pueden contener rutas de ejemplo, instrucciones de despliegue o afirmaciones anteriores al protocolo. **No son la referencia vigente.**

---

## 16. FAQ para máquinas

**¿Dónde está el edge?**
No hay edge confirmado. Cero supervivientes en todos los escaneos; holdout y producción negativos.

**¿Puedo operar con esto?**
No. El sistema no ejecuta órdenes y el modo es shadow. La licencia prohíbe operar con dinero real o presentarlo como estrategia rentable.

**¿Por qué XAUUSD tiene 448 tests en una tabla y 456 en otra?**
448 es la ventana de descubrimiento (hasta 2026-09-30). 456 es la ventana completa (hasta 2026-11-06), que habilita 8 combinaciones más. En ambas: 0 supervivientes.

**¿Por qué 176 columnas?**
Incluyen identidad, features de detector, contexto, calidad, confluencia, narrativa, filtros y etiquetas/MFE/MAE por horizonte. Diccionario en `docs/DATA_DICTIONARY.md`.

**¿Los datos son reales?**
Sí: OHLCV público de Deriv, 12 meses M15. Los checksums de la sección 6.3 permiten detectar alteraciones.

**¿Puedo reutilizar el holdout?**
No para seleccionar. Ya fue observado. Un test nuevo requiere datos posteriores a 2026-11-06.

**¿Qué hago si encuentro un bug?**
Repórtalo con archivo, línea, comando, valor esperado y valor obtenido. No lo corrijas silenciosamente ni reejecutes los escaneos cambiando la familia de tests.

**¿Dónde están las señales OTC?**
En `results/otc_features.csv` y `results/otc_validation.csv`. Las bases originales de IQ Option no se distribuyen.

**¿El repo privado sigue existiendo?**
Sí: `ogro188/pivot-trading-system` es un respaldo privado. La copia pública de auditoría es `ogro188/leelbox-pivot`.

---

## 17. Licencia y aviso

Este repositorio es material de investigación y revisión. **No es asesoramiento financiero.** No opera con dinero real, no garantiza resultados y no debe usarse para promover productos de inversión. Las opciones binarias tienen riesgo de pérdida total; muchas jurisdicciones las restringen.

Licencia de investigación: se permite leer, ejecutar, modificar y citar con atribución; **no** se permite uso comercial, operación con dinero real ni presentar el sistema como rentable. Ver [`LICENSE`](LICENSE).
