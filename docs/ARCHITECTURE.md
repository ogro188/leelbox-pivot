# Arquitectura técnica

**Sistema:** PIVOT v8 / RADAR v2.0
**Base:** Python 3.11, pandas/numpy, FastAPI, WebSocket, SQLite.
**Modo:** generación de señales; **sin ejecución de órdenes**.

---

## 1. Vista general

```text
┌────────────────────────────────────────────────────────────────────┐
│                         CAPA DE DATOS                              │
│  Deriv WebSocket  │  CSV M15  │  IQ Option público (OTC, read-only) │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│                    FEEDS Y RESAMPLE                                │
│  kernel/feeds/csv.py · csv_resample.py · deriv.py · iqoption_public│
│  M15 → H1/H4/D1 (cerradas + bucket parcial causal)                │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│                    CONTEXTO E INDICADORES                          │
│  ATR 8/14/30 · EMA 20/50 · RSI14 · volumen · sesión · kill zone    │
│  trend D1 · régimen de volatilidad · estructura H1/H4              │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│                    DETECTORES D0–D5                                │
│  D0 estructura · D1 ruptura · D2 sweep · D2_A anticipación          │
│  D3 FVG · D4 order block · D5 MSS H4 + sweep M15                   │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│                    SCORING Y CONFLUENCIAS                          │
│  G1–G4 · calidad_* · salud_tendencial · conf_* · convicción        │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ▼
┌────────────────────────────────────────────────────────────────────┐
│                    SEÑAL Y PERSISTENCIA                            │
│  dirección · entry · expiry · narrativa · features · resultado     │
│  SQLite (señales, resultados, operaciones, dataset ML)             │
└───────────────┬────────────────────────────────────────────────────┘
                │
                ├──► alertas ntfy (gate PIVOT_ALERTAS_LIVE=0)
                ├──► API/WebSocket (dashboard opcional)
                └──► replay / análisis / validación
```

---

## 2. Capas y responsabilidades

### 2.1 Datos

- **`kernel/feeds/csv.py`**: carga CSV y sincroniza M15/H1/H4/D1.
- **`kernel/feeds/csv_resample.py`**: agrega velas M15 a H1/H4/D1 por resample.
- **`kernel/contexto_superior.py`**: construye el contexto H1/H4/D1 causal (velas cerradas + bucket en formación solo con M15 ≤ `decision_time`).
- **`kernel/feeds/deriv.py`**: WebSocket de Deriv; historial y ticks; autenticación opcional por token.
- **`kernel/feeds/iqoption_public.py`**: feed público de IQ Option para OTC; **solo lectura**.
- **`kernel/feeds/iq_public_backfill.py`**: relleno de historia OTC.

### 2.2 Motor

- **`core/motor_v8.py`**: orquesta el ciclo por vela, actualiza indicadores, ejecuta detectores, aplica scoring, persiste y encola alertas.
- **`core/base.py`**: contexto base y helpers.
- **`core/estructuras.py`**: dataclasses `Signal`, `EstructuraRef`.
- **`core/utils.py`**: clamping, claves de patrón, utilidades numéricas.
- **`core/scoring.py`**: métricas G1–G4, calidad y confluencia.
- **`core/hipotesis.py`**: narrativa, objetivo, probabilidad y expiración.
- **`core/alertas.py`**: formateo y envío de alertas (ntfy) con gate live.

### 2.3 Detectores

| Detector | Archivo | Entrada | Salida |
|---|---|---|---|
| D0 | `core/d0_estructura.py` | H1 | Swings, barridos, zonas, contexto estructural |
| D1 | `core/d1_ruptura.py` | M15 + rango | Ruptura con penetración, cuerpo, volumen, retest |
| D2 | `core/d2_sweep.py` | M15 + liquidez | Sweep + reclaim |
| D2_A | `core/d2_anticipacion.py` | M15 + confluencias | Sweep anticipado con FVG/OB/MSS |
| D3 | `core/d3_fvg.py` | M15 | FVG normal/defendido |
| D4 | `core/d4_orderblock.py` | M15 | Order block con impulso y confluencia |
| D5 | `core/d5_mss_sweep.py` | H4 + M15 | MSS H4 alineado con sweep/reclaim M15 |

**Contrato de detector:** siempre devuelve una `Signal`. Los filtros duros se convierten en metadatos (`filtros_pasados`, `filtros_fallados`, `direction=0`). El motor filtra `direction == 0` antes de scoring. Esto permite medir el valor incremental de cada filtro y evita que un filtro bloquee silenciosamente el análisis.

### 2.4 Contratos

`kernel/contrato.py` define:

- `Estrategia`: interfaz abstracta (`setup`, `detectar`).
- `Contexto`: snapshot inmutable de mercado (M15/H1/H4/D1, precio, tiempo, buffers).
- `Señal`: campos comunes + spot (`stop_loss`, `take_profit`, `expiracion_velas`) + binario (`expiry_minutes`, `expiry_timestamp`, `payout_pct`, `contract_amount`, `option_type`).
- `BinarySeñal`: señal adaptada a opciones binarias.
- `ActivoInfo`: configuración del instrumento.
- `Overlay`: elementos gráficos.

### 2.5 Estrategias

- **`estrategias/pivot/`**: estrategia principal; parámetros de detectores, scoring y filtros.
- **`estrategias/binary/pivot_binary.py`**: adaptación a binario.
- **`estrategias/ema_cross/`**: estrategia de control.
- **`estrategias/dummy/`**: estrategia vacía para tests.
- **`estrategias/registro.py`**: registro dinámico de plugins.

### 2.6 Backtest y binario

- **`kernel/backtest.py`**: replay barra a barra, multi-timeframe, TP/SL/expiry, slippage, comisión, métricas.
- **`kernel/binary/engine.py`**: contratos binarios con expiración temporal y payout fijo.
- **`kernel/binary/payout.py`**: tablas de payout por broker/activo/expiry.
- **`kernel/binary/risk.py`**: modos de riesgo (fixed, martingala, anti-martingala, Kelly, porcentaje) y límites globales.

### 2.7 Persistencia

`kernel/storage.py` usa SQLite con tablas para:

- `senales_core`: señal, detector, dirección, features, contexto.
- `senales_resultados`: retorno por horizonte, MFE/MAE.
- `operaciones`: operaciones de backtest/spot.
- `backtests`, `metricas`, `logs`.
- dataset ML (`ml_dataset`).

La base de producción **no se incluye** en este repo. Los CSV de señales son la fuente de verdad para el análisis.

### 2.8 API

`kernel/api/app.py` expone FastAPI + WebSocket:

- salud, activos, estrategias, configuración;
- backtest spot/binario;
- historial, señales, consola;
- start/stop de runtime;
- configuración ntfy;
- `/ws` para señales, ticks, velas, estado y consola.

El frontend no se incluye. La API es opcional para la revisión; el foco es el motor y el pipeline de validación.

---

## 3. Ciclo de una señal

1. Llega una vela M15 cerrada.
2. Se actualizan buffers de indicadores (ATR, EMA, RSI, volumen).
3. Se construye el contexto H1/H4/D1 causal: velas cerradas + bucket en formación agregado solo con M15 cuyo cierre es `<= decision_time`.
4. Se ejecutan D0–D5.
5. Se calculan calidad, confluencia, salud tendencial y contexto.
6. Se aplica el gate de dirección (`direction != 0`).
7. Se construye la señal con entry, expiry, objetivo y narrativa.
8. Se persiste y se encola alerta (si el gate live está activo).
9. En análisis, se etiqueta con retornos h1–h8 y se evalúa.

### Zero look-ahead

- Los timeframes superiores usan `kernel/contexto_superior.py`: velas cerradas + bucket en formación agregado solo con M15 cuyo cierre es `<= decision_time`. Nunca se usa el OHLC completo del bucket con M15 futuras.
- La señal se emite al cierre de `t`. `entry_time` es la apertura; `decision_time = entry_time + 15 min` es el cierre y el instante que usan alerta, sesión y latencia.
- En `feature_replay.py` la referencia de entrada es `close[t]` (supuesto optimista) y la salida es `close[t+h]`, contada por posición (`pos+h`); no hay chequeo explícito de continuidad.
- `pattern_edge.py` sí usa `open[t+1]` como entrada y `close[t+h]` como salida, con chequeo de continuidad por `epoch`. `bar_edge.py` usa `close[t]` → `close[t+h]`.
- El replay usa un motor en proceso, DB nula y alertas desactivadas.

---

## 4. Modelo binario

- **Payout:** tabla por broker/activo/expiry. Para el análisis: EURUSD 85/86/86/87 % y XAUUSD 81/82/82/83 % (h1–h4).
- **Expiry:** temporal; la señal se resuelve en `entry_time + expiry`.
- **Resultado:** WIN si el precio se mueve a favor al expirar; LOSS si no.
- **Riesgo:** el motor soporta varios modos, pero el análisis de edge usa stake fijo y EV por señal.
- **Supuestos:** payout constante, resolución al close, sin ticks intravela, sin empates. Son supuestos conservadores para el análisis, pero deben auditarse contra el broker real.

---

## 5. Modo shadow

- `PIVOT_ALERTAS_LIVE=0` por defecto.
- Replay/backtest nunca envían alertas.
- La producción registra señales y resultados, pero no ejecuta órdenes.
- No se promueve ningún candidato a demo/dinero real sin el protocolo de `VALIDATION_PROTOCOL.md`.

---

## 6. Reglas de diseño

1. **Zero look-ahead** en todos los timeframes.
2. **Tests con assertions**, no solo “no explota”.
3. **Métricas reproducibles**, sin números no documentados.
4. **Radar puro:** solo D0–D5 gatean señales; sesión/spread/vol ajustan confianza, no bloquean.
5. **Sin fallos silenciosos:** la ruta señal → persistencia debe surfacear errores.
6. **Separación investigación/producción:** el análisis no toca la instalación de producción ni reinicia servicios.

---

## 7. Mapa de archivos clave

| Archivo | Qué mirar |
|---|---|
| `core/motor_v8.py` | Ciclo principal, indicadores, filtros, persistencia. |
| `core/d0_estructura.py` … `d5_mss_sweep.py` | Lógica de cada patrón. |
| `core/scoring.py` | G1–G4, calidad, confluencia. |
| `core/hipotesis.py` | Expiry, objetivo, probabilidad, narrativa. |
| `kernel/contrato.py` | Esquema de señal y contexto. |
| `kernel/contexto_superior.py` | Contexto H1/H4/D1 causal. |
| `kernel/backtest.py` | Replay, contexto causal, métricas. |
| `kernel/binary/engine.py` | Resolución binaria y PnL. |
| `kernel/binary/payout.py` | Payouts usados en el análisis. |
| `tools/feature_replay.py` | Features y etiquetas del replay. |
| `tools/edge_scan.py` | Tests de señales, FDR, bootstrap. |
| `tools/bar_edge.py` | Tests a nivel de vela. |
| `tools/pattern_edge.py` | Patrones intradía. |
| `tools/holdout.py` | Holdout con umbrales congelados. |

---

## 8. Deuda técnica conocida

- El replay y la producción no coinciden señal por señal (82 % de overlap); las diferencias están documentadas en `docs/LIMITATIONS.md`.
- h4 no está validado contra producción.
- D1 EMA200 no existe antes de ~septiembre 2026.
- La base de producción apuntaba a `/tmp` (efímera); es un riesgo operativo.
- El frontend y los servicios systemd no se incluyen.
- La API puede requerir dependencias adicionales (`fastapi`, `uvicorn`, `httpx`).
