# PIVOT Trading System - Manual de Instalación, Uso y Desinstalación

## 📋 Requisitos Previos

- **Python 3.11+** (recomendado 3.13)
- **Windows 10/11** o **Linux** (Ubuntu 22.04+)
- **Git** para clonar el repositorio
- **4 GB RAM** mínimo (8 GB recomendado para backtests largos)

---

## 🚀 Instalación

### 1. Clonar repositorio
```bash
git clone <url-del-repo>
cd <directorio-proyecto>
```

### 2. Crear entorno virtual
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# Linux/macOS
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instalar dependencias
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

**Dependencias principales** (`requirements.txt`):
```
pandas>=2.0
numpy>=1.24
sqlite3 (built-in)
```

### 4. Verificar instalación
```bash
# Tests unitarios rápidos
.venv\Scripts\python.exe -m pytest tests/unit -q

# Test de integración del backtest
.venv\Scripts\python.exe -m pytest tests/integration/test_backtest.py -q
```

**Resultado esperado**: 50 tests passed en ~5s.

---

## 📁 Estructura del Proyecto

```
├── kernel/              # Motor de backtesting y feeds
│   ├── backtest.py      # BacktestEngine principal
│   ├── feeds/csv.py     # CSVFeed / MultiTimeframeFeed
│   ├── storage.py       # Database (SQLite)
│   └── contrato.py      # Dataclasses: Contexto, Señal, ActivoInfo, ResultadoBacktest
├── core/                # Detectores y base compartida
│   ├── base.py          # Contexto base + helpers _i_high/_i_low/...
│   ├── d0_estructura.py # Proveedor de estructura (pivots H1)
│   └── *.py             # Detectores D1-D5
├── estrategias/
│   └── pivot/           # Estrategia PIVOT (detectores D0-D5)
├── data/                # CSVs de datos históricos
├── tests/               # Unit + Integration tests
└── MANUAL_SISTEMA.md    # Este archivo
```

---

## 💻 Uso Básico

### 1. Preparar datos CSV
Formato requerido (columnas obligatorias):
```csv
timestamp,open,high,low,close,volume
2024-01-01 00:00:00,1.1000,1.1005,1.0995,1.1002,1000
2024-01-01 00:15:00,1.1002,1.1008,1.0998,1.1005,1100
...
```
- Timestamp: ISO 8601 (`YYYY-MM-DD HH:MM:SS`) o Unix epoch
- Timeframe: inferido del nombre del archivo o parámetro explícito

### 2. Ejecutar backtest (script mínimo)
```python
# run_backtest.py
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import tempfile
import os

from kernel.backtest import BacktestEngine
from kernel.feeds.csv import CSVFeed
from kernel.contrato import ActivoInfo
from estrategias.pivot import EstrategiaPivot

# 1. Crear CSV temporal (o usar data/eurusd_m15_real.csv)
fechas = [datetime(2024,1,1)+timedelta(minutes=i*15) for i in range(500)]
precios = [1.1000 + np.sin(i*0.05)*0.001 for i in range(500)]
df = pd.DataFrame({
    'timestamp': [f.strftime('%Y-%m-%d %H:%M:%S') for f in fechas],
    'open': precios, 'high': [p+0.0002 for p in precios],
    'low': [p-0.0002 for p in precios], 'close': precios, 'volume': [100]*500
})
tmp = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv', encoding='utf-8')
df.to_csv(tmp.name, index=False); tmp.close()

# 2. Configurar activo
activo = ActivoInfo(
    simbolo='EURUSD',
    punto=0.00001,
    tick_size=0.00001,
    contract_size=100000,
    session_open='00:00',
    session_close='23:59'
)

# 3. Ejecutar
engine = BacktestEngine(
    estrategia=EstrategiaPivot(),
    activo=activo,
    capital_inicial=10000.0,
    riesgo_por_operacion=0.01,
    slippage_pips=1.0,
comision_lote=0.5
)

feed = CSVFeed(tmp.name, timeframe='M15', symbol='EURUSD')
resultado = engine.ejecutar(feeds={'M15': feed})

# 4. Resultados
print(f"Operaciones: {resultado.total_operaciones}")
print(f"WinRate: {resultado.winrate:.2f}%")
print(f"Profit Factor: {resultado.profit_factor:.2f}")
print(f"Retorno: {resultado.retorno_total:.2f}%")
print(f"Drawdown Max: {resultado.drawdown_maximo:.2f}%")
print(f"Capital Final: {resultado.capital_final:.2f}")

os.unlink(tmp.name)
```

```bash
.venv\Scripts\python.exe run_backtest.py
```

### 3. Multi-timeframe (M15 + H1 + H4)
```python
feed_m15 = CSVFeed('data/eurusd_m15.csv', timeframe='M15', symbol='EURUSD')
feed_h1  = CSVFeed('data/eurusd_h1.csv',  timeframe='H1',  symbol='EURUSD')
feed_h4  = CSVFeed('data/eurusd_h4.csv',  timeframe='H4',  symbol='EURUSD')

resultado = engine.ejecutar(feeds={'M15': feed_m15, 'H1': feed_h1, 'H4': feed_h4})
```

### 4. Parámetros de estrategia
```python
params = {
    "confianza_minima": 50.0,      # 40-90 (default 50)
    "reward_ratio_min": 1.5,       # 1.0-5.0
    "usar_kill_zones": True,
    "usar_trend_d1": True,
    "pivot_depth": 2,
    "pivot_lookback": 24
}
resultado = engine.ejecutar(feeds=..., params_estrategia=params)
```

### 5. Persistencia de resultados (SQLite)
```python
from kernel.storage import Database
import asyncio

db = Database('backtests.db')
db.initialize()

# Guardar resultado
asyncio.run(db.guardar_backtest(resultado, params))

# Consultar histórico
senales = asyncio.run(db.obtener_senales_core(symbol='EURUSD', limite=100))
```

---

## ⚙️ Configuración Avanzada

### ActivoInfo - Parámetros por símbolo
```python
ActivoInfo(
    simbolo='EURUSD',           # Símbolo
    punto=0.00001,              # Tamaño de 1 punto (0.00001 = 0.1 pip)
    tick_size=0.00001,          # Tamaño mínimo de tick
    contract_size=100000,       # Tamaño de contrato (1 lote estándar)
    session_open='00:00',       # Apertura sesión broker
    session_close='23:59',      # Cierre sesión broker
    # Para metales/índices ajustar punto/tick_size/contract_size
)
```

### BacktestEngine - Parámetros de riesgo
```python
BacktestEngine(
    estrategia=...,
    activo=...,
    capital_inicial=10000.0,        # Capital inicial
    riesgo_por_operacion=0.01,      # 1% por operación
    slippage_pips=1.0,              # Slippage estimado (pips)
    comision_lote=7.0,              # Comisión por lote redondo (USD)
    max_operaciones_simultaneas=3   # Límite posiciones abiertas
)
```

---

## 🧪 Testing

| Comando | Descripción |
|---------|-------------|
| `pytest tests/unit -q` | Tests unitarios (50 tests, ~5s) |
| `pytest tests/integration/test_backtest.py -q` | Backtest integration (8 tests, ~80s) |
| `pytest tests/ -q --tb=short` | Suite completa (excluye test 6 meses) |

> **Nota**: `test_backtest_genera_operaciones.py` usa 6 meses de datos reales (~17k velas) y tarda **30+ minutos**. Ejecutar solo en validación final.

---

## 🗑️ Desinstalación

### Limpieza completa
```bash
# 1. Desactivar entorno virtual
deactivate

# 2. Eliminar entorno virtual
rm -rf .venv          # Linux/macOS
rmdir /s .venv        # Windows PowerShell

# 3. Eliminar bases de datos y archivos generados
rm -f *.db backtests.db test_ml_export.csv

# 4. (Opcional) Eliminar repositorio clonado
cd ..
rm -rf <directorio-proyecto>
```

### Limpieza selectiva (mantener código)
```bash
# Solo entorno virtual y DBs
deactivate
rm -rf .venv
rm -f *.db
```

---

## 🔧 Troubleshooting

| Problema | Solución |
|----------|----------|
| `ModuleNotFoundError: pandas` | `pip install -r requirements.txt` dentro de `.venv` |
| `FileNotFoundError: data/eurusd_m15_real.csv` | El test de 6 meses requiere datos reales; usar CSV sintético o colocar archivo en `data/` |
| `UnicodeEncodeError` en Windows | Usar `chcp 65001` en PowerShell o evitar emojis en prints |
| Tests lentos (>5 min) | Ejecutar solo `tests/unit` + `test_backtest.py` para CI rápido |
| `asyncio.run(db.initialize())` falla | `db.initialize()` es **síncrono**, no usar `asyncio.run()` |

---

## 📝 Licencia y Soporte

- **Licencia**: Propietaria / Uso interno
- **Versión**: 2.0 (BacktestEngine v2.0, cache numpy, sin look-ahead)
- **Contacto**: Equipo de Desarrollo PIVOT

---

## 📌 Checklist de Puesta en Producción

- [ ] Entorno virtual creado y dependencias instaladas
- [ ] Tests unitarios pasan (`pytest tests/unit -q`)
- [ ] Test backtest básico pasa (`pytest tests/integration/test_backtest.py -q`)
- [ ] Datos CSV válidos en `data/` con columnas correctas
- [ ] Parámetros `ActivoInfo` ajustados al broker/símbolo
- [ ] Base de datos SQLite inicializada (`Database('prod.db').initialize()`)
- [ ] Logs configurados (`logging.basicConfig(level=logging.INFO)`)

---

*Generado automáticamente - PIVOT Trading System v2.0*