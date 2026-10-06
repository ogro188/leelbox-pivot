# PIVOT — Multi-Timeframe Algorithmic Trading System

## Overview

PIVOT is a modular algorithmic trading system for pattern detection across multiple timeframes (M15, H1, H4, D1). It implements Smart Money Concepts (SMC) / Institutional Price Action detectors (D0–D5) with confluences, a vectorized backtesting engine, FastAPI + WebSocket API, and ML-ready data persistence.

**Key characteristics:**
- Signal generation only (no order execution)
- Plugin architecture for strategies
- Zero look-ahead guarantee in backtesting
- Binary options and spot/forex modes
- ML-ready dataset generation (100+ features per signal)

---

## Architecture

```
pivot/
├── activos/                 # Instrument configs (JSON)
│   ├── eurusd.json
│   ├── xauusd.json
│   ├── eurusd_binary.json  # Binary options configs
│   └── xauusd_binary.json
├── core/                    # Detection engine (D0–D5)
│   ├── d0_estructura.py     # H1 structure (swings, sweeps, zones)
│   ├── d1_ruptura.py        # Range breakout
│   ├── d2_sweep.py          # Liquidity sweep + reclaim
│   ├── d2_anticipacion.py   # Anticipatory sweep + confluences
│   ├── d3_fvg.py            # Fair Value Gap (normal/defended)
│   ├── d4_orderblock.py     # Order Block + confluence
│   ├── d5_mss_sweep.py      # MSS H4 + sweep M15
│   ├── motor_v8.py          # Orchestrator (plugin architecture)
│   ├── scoring.py           # Quality metrics (G1–G4, confluences)
│   ├── hipotesis.py         # Narrative + expiry calculation
│   ├── alertas.py           # Notification engine (ntfy)
│   ├── estructuras.py       # Dataclasses (Signal, EstructuraRef)
│   ├── base.py              # Base Contexto + helpers
│   └── utils.py             # Clamping, pattern keys
├── kernel/                  # System kernel
│   ├── contrato.py          # Base contracts (Estrategia, Contexto, Señal, ActivoInfo, Binary*)
│   ├── core_adapter.py      # Kernel ↔ Core context translation
│   ├── activos_loader.py    # JSON → ActivoInfo loader
│   ├── backtest.py          # BacktestEngine (bar-by-bar, no look-ahead)
│   ├── storage.py           # SQLite persistence (ops, ML dataset, config)
│   ├── feeds/
│   │   ├── csv.py           # CSVFeed, MultiTimeframeFeed
│   │   ├── csv_resample.py  # H1/H4/D1 derivation from M15
│   │   └── deriv.py         # Deriv WebSocket feed
│   └── binary/              # Binary options module
│       ├── payout.py        # Broker payout tables (Deriv, IQOption, Pocket, Quotex)
│       ├── risk.py          # Risk modes (Fixed, Martingale, Anti-Martingale, Kelly, %)
│       └── engine.py        # BinaryBacktestEngine (temporal expiry, fixed payout)
├── estrategias/             # Strategy plugins
│   ├── registro.py          # Dynamic plugin registry
│   ├── pivot/               # Main strategy (D0–D5 confluences + WilsonScorer)
│   └── binary/
│       └── pivot_binary.py  # PIVOT adapted for binary options
├── data/                    # Historical CSVs (EURUSD M15/H1/H4/D1, XAUUSD M15)
├── frontend/                # React + TS + Vite + Tailwind + Zustand
├── tests/
│   ├── unit/                # 81 unit tests
│   └── integration/         # API + backtest integration tests
├── scripts/
│   ├── export_ml_dataset.py # ML dataset export (CSV/Parquet)
│   └── run_deriv_ws.py      # Live WebSocket runner
├── docker-compose.yml       # 2 services (API, Frontend)
├── Dockerfile               # Multi-stage, non-root user
├── docs/                    # Specs, manual y notas de fases
│   ├── especificacion_pivotradar_v8_sin_restricciones.md
│   ├── SPEC_PV_TERMINAL.md  # Frontend redesign spec
│   └── MANUAL_SISTEMA.md    # System manual
└── requirements.txt
```

---

## Core Contracts (`kernel/contrato.py`)

### Abstract Strategy Interface
```python
class Estrategia(ABC):
    nombre: str
    version: str
    timeframes: List[str]      # Required timeframes from Contexto
    eventos: List[str]         # Trigger events (e.g., "candle_close")

    @abstractmethod
    def setup(self, params: dict, activo: ActivoInfo) -> None: ...
    @abstractmethod
    def detectar(self, contexto: Contexto) -> List[Señal]: ...
```

### Contexto (Immutable Market Snapshot)
- `df_m15`, `df_h1`, `df_h4`, `df_d1`: OHLC DataFrames (time-indexed, cropped to current bar)
- `precio`, `tiempo`: Current price and timestamp
- Indicator buffers: `g_atr8/14/30`, `g_ema21/50`, `g_rsi14`, `g_ema50/200_d1`, `g_ema20/50_h4`
- Market state: `session`, `kill_zone`, `trend_d1`, `regimen_vol`
- Injected helpers: `get_volume_ratio`, `detect_mss_h4`, `es_zona_premium_discount`

### Señal (Spot/Forex) & BinarySeñal (Binary Options)
- Common: `estrategia`, `simbolo`, `direccion` (1=LONG/CALL, -1=SHORT/PUT), `precio`, `tiempo`, `confianza`, `narrativa`, `contexto`
- Spot: `stop_loss`, `take_profit`, `expiracion_velas`
- Binary: `expiry_minutes`, `expiry_timestamp`, `payout_pct`, `contract_amount`, `option_type`
- **Informational filters (v8.1+)**: `filtros_pasados`, `filtros_fallados`, `filtro_penetracion_atr`, `filtro_wick_ratio`, `filtro_fvg_size_atr`, `filtro_ob_impulse`, `filtro_mss_reciente`, etc.
- `direction = 0` = no valid pattern (filtered before scoring)

---

## Detectors D0–D5

| ID | File | Pattern | Key Thresholds (Informational) |
|----|------|---------|--------------------------------|
| **D0** | `d0_estructura.py` | H1 structure (swings, sweeps, zones) | Base for all detectors |
| **D1** | `d1_ruptura.py` | Range breakout (n bars) | `penetracion_atr ≥ 0.5`, `body_ratio ≥ 0.4`, `volumen ≥ 1.2×`, `retest` |
| **D2** | `d2_sweep.py` | Liquidity sweep + reclaim | `wick_ratio ≥ 0.55`, `sweep_reciente ≤ 2`, `distancia ≤ 2×ATR`, `reclaim_body ≥ 0.55` |
| **D2_A** | `d2_anticipacion.py` | Anticipatory sweep + confluences | `wick_ratio ≥ 0.33`, confluences FVG/OB/MSS (≥2) |
| **D3** | `d3_fvg.py` | Fair Value Gap (normal/defended) | `fvg_size_atr ≥ 0.20`, `body_ratio ≥ 0.55`, `dir_ok`, MSS aligned |
| **D4** | `d4_orderblock.py` | Order Block + confluence | `ob_body ≥ 0.40`, `impulse ≥ 0.70×ATR`, `no_tested`, `entering`, `distancia ≤ 2×ATR` |
| **D5** | `d5_mss_sweep.py` | MSS H4 + sweep M15 | `mss_aligned`, `mss_reciente ≤ 12`, `wick_ratio ≥ 0.55`, `sweep_reciente ≤ 2`, `distancia ≤ 2×ATR`, `reclaim ≥ 0.55` |

**v8.1 Change**: All detectors return `Signal` always (never `None` for filter failures). Hard filters converted to informational metadata. Motor filters `direction == 0` before scoring.

---

## Scoring & Confluences (`core/scoring.py`)

- **G-Metrics**: G1 (ATR compression), G2 (persistence), G3 (efficiency), G4 (exhaustion)
- **Quality Metrics**: `calidad_sweep`, `calidad_mss`, `calidad_fvg`, `calidad_ob` (0–100)
- **Trend Health**: `salud_tendencial` (EMA21/50 alignment + D1 trend)
- **Confluences**: `conf_sweep_fvg`, `conf_completa` (multi-detector alignment)
- **Conviction**: `BAJA`/`MEDIA`/`ALTA` (≥4 of: MSS aligned, equal HL, OB confluence, kill zone, conf_completa ≥60, contexto_estructural ≥70, max quality ≥70)

---

## Binary Options Module (`kernel/binary/`)

### Payout Tables (`payout.py`)
- 5 brokers: Deriv, IQOption, Pocket, Quotex, Generic
- 15+ symbols × 7 expiries (1m, 5m, 10m, 15m, 30m, 60m, EOD)
- `get_payout_table(broker, symbol) → PayoutTable`

### Risk Management (`risk.py`)
| Mode | Behavior |
|------|----------|
| `FIXED` | Constant amount per trade |
| `MARTINGALE` | ×2 after loss, reset on win (max steps configurable) |
| `ANTI_MARTINGALE` | ×1.5 after win, reset on loss |
| `KELLY` | Fractional Kelly (p×b−q)/b × fraction, min winrate/payout guards |
| `PERCENTAGE` | % of current capital |

Global limits: `max_daily_loss_pct`, `max_daily_trades`, `max_concurrent_trades`, `max_total_exposure_pct`

### Engine (`engine.py`)
- `BinaryBacktestEngine`: Bar-by-bar replay, temporal expiry, fixed payout
- Contract lifecycle: open → wait for expiry_timestamp → resolve (WIN/LOSS) → PnL
- Risk manager integration per signal
- Equity curve + binary-specific metrics (ROI%, payout_promedio, total_invertido)

---

## Backtesting Engine (`kernel/backtest.py`)

- **Bar-by-bar replay** with strict temporal isolation
- Multi-timeframe: M15 base + H1/H4/D1 derived via resample (precomputed once, cropped per bar)
- **Zero look-ahead**: `searchsorted(side="left")` for higher TFs (only closed candles)
- Position management: TP/SL/expiry, max concurrent trades, slippage, commission
- Metrics: winrate, profit_factor, Sharpe/Sortino, max_drawdown, streaks, equity curve
- ML dataset persistence: each closed trade → SQLite with detector combo, features, outcome

---

## API (`kernel/api/app.py`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | System status |
| `/api/assets` | GET | Available instruments + real-time state |
| `/api/strategies` | GET | Registered strategies |
| `/api/strategies/{name}` | GET | Strategy details + params |
| `/api/backtest` | POST | Run backtest (spot or binary) |
| `/api/assets/{sym}/history` | GET | Historical candles |
| `/api/assets/{sym}/signals` | GET | Recent signals |
| `/api/assets/{sym}/consola` | GET | Runtime logs |
| `/api/assets/{sym}/start` | POST | Start runtime (live or replay) |
| `/api/assets/{sym}/stop` | POST | Stop runtime |
| `/api/assets/{sym}/ntfy` | GET/POST | Per-asset ntfy config |
| `/api/assets/{sym}/ntfy/test` | POST | Send test ntfy (bypasses live gate) |
| `/api/config/ntfy` | POST | Global ntfy config |
| `/api/config` | GET | Global system config |
| `/ws` | WS | Real-time signal stream (`signal`, `tick`, `candle`, `status`, `consola`) |

**Frontend (dev)**: `cd frontend && npm run dev` → http://localhost:5173  
Vite proxies `/api` and `/ws` → `http://localhost:8000` (backend).

---

## Signal origin (`senales_core.fuente`)

| `fuente` | Origin | ntfy live |
|----------|--------|-----------|
| `deriv` | Live Deriv stream (`motor_v8` / `deriv_runtime`) | Only if `PIVOT_ALERTAS_LIVE=1` |
| `replay` | CSV replay runtime (`_replay_asset`) | Never |
| `live_csv` | Replay from `data/live_*_m15.csv` | Never |
| `backtest` | `POST /api/backtest` | Never |

Legacy rows with `tipo LIKE 'PIVOT_%'` are backfilled to `fuente='replay'`.

### Alerts gate

```bash
# .env — default OFF (safe for testing)
PIVOT_ALERTAS_LIVE=0   # set 1 only when trading live with real Deriv data
```

- Replay/backtest never send ntfy.
- `POST .../ntfy/test` forces a send for connectivity checks only.
- `.env.example` documents the flag; copy to `.env` and set `1` to go live.

### CSV preference

Charts/replay prefer `data/live_{sym}_m15.csv` over `data/{sym}_m15.csv`.  
**Never** treats `{sym}_m15_real.csv` as live market data (that file is synthetic test data).

---

## Quick Start

```bash
# Dependencies
pip install -r requirements.txt
pip install pytest pytest-cov

# Env
cp .env.example .env   # fill DERIV_* tokens; keep PIVOT_ALERTAS_LIVE=0 while testing

# Docs & specs
docs/  # specifications, system manual and phase notes

# Unit tests
pytest tests/unit -v

# Integration tests
pytest tests/integration -v

# Manual backtest (spot)
python test_pivot_backtest.py

# API server (backend :8000)
python -m cli
# Swagger: http://localhost:8000/docs
# WS: ws://localhost:8000/ws

# Frontend (dev :5173)
cd frontend && npm install && npm run dev
# http://localhost:5173  (proxies /api and /ws to :8000)
```

---

## ML Dataset Export

```bash
python scripts/export_ml_dataset.py --symbol EURUSD --output ml_dataset.parquet
```

Output: Parquet with 50+ features per trade (detector combo, qualities, G-metrics, confluences, regime, session, outcome).

---

## Testing

```bash
# Unit tests (81 tests, ~10s)
pytest tests/unit -v

# Integration tests (API + backtest, ~60s)
pytest tests/integration -v

# Specific test
pytest tests/unit/test_alertas_gate.py -v
pytest tests/unit/test_binary.py -v
pytest tests/integration/test_backtest.py::TestBacktestEngine -v
```

**Coverage**: 81 unit tests + integration tests. CI runs unit tests; integration tests require data files.

---

## Design Rules (Non-Negotiable)

1. **Zero Look-ahead**: `_slice_tf()` uses `searchsorted(side="left")` for all higher TFs — only closed candles included
2. **Tests Require Assertions**: No "no exception" tests; explicit outcome assertions
3. **Metrics Require Commands**: No undocumented numbers in docs
4. **Radar Pure**: Only D0–D5 detectors gate signals; session/spread/vol adjust confidence, never block
5. **No Silent Failures**: Critical path (signal → persistence) must surface errors

---

## License

Proprietary — no `LICENSE` file in repo. Internal use only. No redistribution without authorization.