# PIVOT Trading System - Ejemplo End-to-End

Este documento demuestra el uso completo del sistema PIVOT desde backtesting hasta despliegue en producción.

## 📋 Tabla de Contenidos

1. [Inicio Rápido](#inicio-rápido)
2. [Backtesting con Datos Históricos](#backtesting-con-datos-históricos)
3. [Ejecución en Vivo](#ejecución-en-vivo)
4. [API REST](#api-rest)
5. [Despliegue con Docker](#despliegue-con-docker)
6. [Monitoreo y Alertas](#monitoreo-y-alertas)

---

## 🚀 Inicio Rápido

### Prerrequisitos

```bash
# Python 3.11+
python --version

# Instalar dependencias
pip install -r requirements.txt

# Verificar instalación
python -c "import kernel; print('✅ Kernel OK')"
python -c "import core; print('✅ Core OK')"
python -c "from estrategias.pivot import EstrategiaPivot; print('✅ Estrategia Pivot OK')"
```

### Estructura del Proyecto

```
pivot/
├── kernel/              # Núcleo del sistema
│   ├── contrato.py      # Tipos base (ABCs)
│   ├── api/             # API FastAPI
│   ├── backtest.py      # Motor de backtesting
│   ├── feeds/           # Data feeds (CSV, Deriv)
│   ├── storage.py       # Persistencia SQLite
│   └── core_adapter.py  # Adaptador detectores D0-D5
├── core/                # Detectores D0-D5
│   ├── d0_estructura.py
│   ├── d1_ruptura.py
│   ├── d2_sweep.py
│   ├── d3_fvg.py
│   ├── d4_orderblocks.py
│   └── d5_mss.py
├── estrategias/         # Estrategias plugin
│   ├── pivot/           # ⭐ Estrategia principal
│   ├── ema_cross/
│   └── dummy/
├── tests/               # Tests unitarios e integración
├── data/                # Datos históricos CSV
├── docker-compose.yml   # Orquestación Docker
└── Dockerfile           # Imagen Docker
```

---

## 📊 Backtesting con Datos Históricos

### Opción 1: Script Python Directo

```python
from kernel.feeds.csv import CSVFeed
from kernel.backtest import BacktestEngine
from estrategias.pivot import EstrategiaPivot

# Cargar datos históricos
feed = CSVFeed('data/eurusd_m15.csv', timeframe='15m')

# Configurar estrategia
estrategia = EstrategiaPivot(
    risk_percent=1.0,      # 1% riesgo por operación
    tp_pips=30,            # Take profit 30 pips
    sl_pips=15,            # Stop loss 15 pips
    min_confianza=0.65     # Confianza mínima 65%
)

# Crear motor de backtest
engine = BacktestEngine(
    feed=feed,
    estrategia=estrategia,
    capital_inicial=10000,
    slippage_pips=1,
    comision_por_lote=7
)

# Ejecutar backtest
resultado = engine.ejecutar()

# Mostrar resultados
print(f"\n{'='*60}")
print(f"RESULTADOS DEL BACKTEST")
print(f"{'='*60}")
print(f"Capital Inicial:  ${resultado.capital_inicial:,.2f}")
print(f"Capital Final:    ${resultado.capital_final:,.2f}")
print(f"Retorno Total:    {resultado.retorno_total*100:+.2f}%")
print(f"Operaciones:      {resultado.total_operaciones}")
print(f"Win Rate:         {resultado.win_rate*100:.1f}%")
print(f"Profit Factor:    {resultado.profit_factor:.2f}")
print(f"Sharpe Ratio:     {resultado.sharpe_ratio:.2f}")
print(f"Drawdown Máx:     {resultado.drawdown_max*100:.2f}%")
print(f"{'='*60}\n")
```

### Opción 2: Usando Test Existente

```bash
# Ejecutar test de backtest con estrategia Pivot
python test_pivot_backtest.py

# Salida esperada:
# ✅ Backtest completado exitosamente
# Operaciones: XX | Win Rate: XX.X% | Profit Factor: X.XX
```

### Opción 3: Vía API REST

```bash
# Iniciar servidor API
python -m uvicorn kernel.api.app:app --host 0.0.0.0 --port 8000

# Ejecutar backtest vía API
curl -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "activo": "EURUSD",
    "estrategia": "pivot",
    "desde": "2024-01-01",
    "hasta": "2024-12-31",
    "timeframe": "15m",
    "capital_inicial": 10000,
    "parametros": {
      "risk_percent": 1.0,
      "tp_pips": 30,
      "sl_pips": 15
    }
  }'
```

---

## 🎯 Ejecución en Vivo

### Configuración de Deriv API

1. **Obtener credenciales**:
   - Ve a https://app.deriv.com/account/api-token
   - Crea un token con permisos: `read`, `trade`
   - Anota tu App ID (o usa 123456 para testing)

2. **Variables de entorno**:

```bash
export DERIV_APP_ID=123456
export DERIV_API_TOKEN=tu_token_aqui
export DATABASE_URL=sqlite:///data/storage/pivot.db
```

### Iniciar Sistema en Vivo

```bash
# Opción A: Usando docker-compose (recomendado)
docker-compose up -d

# Opción B: Servicios individuales
# 1. API Backend
python -m uvicorn kernel.api.app:app --host 0.0.0.0 --port 8000 &

# 2. WebSocket Feed (Deriv)
python kernel/feeds/deriv.py &

# 3. Frontend (desde carpeta frontend)
cd frontend && npm run build && npm preview --host 0.0.0.0 --port 3000
```

### Suscribirse a Activos

```python
from kernel.feeds.deriv import DerivFeed

# Crear feed en vivo
feed = DerivFeed(
    app_id=123456,
    api_token='tu_token',
    activos=['EURUSD', 'GBPUSD', 'XAUUSD'],
    timeframes=['15m', '1h', '4h']
)

# Suscribirse y procesar
async def main():
    await feed.conectar()
    await feed.suscribir('EURUSD')
    
    # Procesar ticks en tiempo real
    async for tick in feed.ticks('EURUSD'):
        print(f"{tick['symbol']} @ {tick['price']}")
    
    await feed.desconectar()

# Ejecutar
import asyncio
asyncio.run(main())
```

---

## 🔌 API REST

La API FastAPI proporciona endpoints completos para operar el sistema.

### Endpoints Disponibles

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/health` | Health check del sistema |
| GET | `/api/assets` | Lista de activos disponibles |
| GET | `/api/assets/{symbol}` | Detalles de un activo |
| GET | `/api/strategies` | Estrategias registradas |
| POST | `/api/backtest` | Ejecutar backtest |
| GET | `/api/backtest/{id}` | Resultados de backtest |
| POST | `/api/live/start` | Iniciar trading en vivo |
| POST | `/api/live/stop` | Detener trading en vivo |
| GET | `/api/positions` | Posiciones abiertas |
| GET | `/api/history` | Historial de operaciones |
| GET | `/api/metrics` | Métricas en tiempo real |
| GET | `/api/equity-curve` | Curva de capital |

### Ejemplos de Uso

#### Health Check

```bash
curl http://localhost:8000/api/health
# {"status": "healthy", "timestamp": "2024-01-15T10:30:00"}
```

#### Listar Activos

```bash
curl http://localhost:8000/api/assets
# [{"symbol": "EURUSD", "name": "Euro/US Dollar", ...}]
```

#### Listar Estrategias

```bash
curl http://localhost:8000/api/strategies
# ["pivot", "ema_cross", "dummy"]
```

#### Ejecutar Backtest

```bash
curl -X POST http://localhost:8000/api/backtest \
  -H "Content-Type: application/json" \
  -d '{
    "activo": "EURUSD",
    "estrategia": "pivot",
    "desde": "2024-01-01",
    "hasta": "2024-12-31",
    "timeframe": "15m",
    "capital_inicial": 10000
  }'
```

#### Obtener Posiciones Abiertas

```bash
curl http://localhost:8000/api/positions
# [{"id": 1, "symbol": "EURUSD", "tipo": "COMPRA", "precio": 1.0850, ...}]
```

---

## 🐳 Despliegue con Docker

### Construir Imagen

```bash
# Build manual
docker build -t pivot-trading:latest .

# Build con docker-compose
docker-compose build
```

### Ejecutar con Docker Compose

```bash
# Iniciar todos los servicios
docker-compose up -d

# Ver logs
docker-compose logs -f

# Ver estado
docker-compose ps

# Detener
docker-compose down

# Reiniciar
docker-compose restart
```

### Variables de Entorno

Crea un archivo `.env` en la raíz:

```bash
# Deriv API
DERIV_APP_ID=123456
DERIV_API_TOKEN=tu_token_secreto

# Base de datos
DATABASE_URL=sqlite:///app/data/storage/pivot.db

# Logs
LOG_LEVEL=INFO

# Puertos
API_PORT=8000
WS_PORT=8765
FRONTEND_PORT=3000
```

### Producción

```bash
# Build optimizado para producción
docker-compose -f docker-compose.yml build --no-cache

# Deploy en servidor remoto
scp docker-compose.yml user@server:/opt/pivot/
ssh user@server "cd /opt/pivot && docker-compose up -d"

# Actualizar deployment
ssh user@server "cd /opt/pivot && docker-compose pull && docker-compose up -d"
```

---

## 📈 Monitoreo y Alertas

### Logs en Tiempo Real

```bash
# Ver logs de API
docker-compose logs -f pivot-api

# Ver logs de WebSocket
docker-compose logs -f pivot-ws

# Ver logs combinados
docker-compose logs -f | grep -E "(ERROR|WARNING|INFO)"
```

### Métricas Clave

Accede vía API:

```bash
# Métricas en tiempo real
curl http://localhost:8000/api/metrics

# Respuesta:
# {
#   "capital_actual": 10250.50,
#   "posiciones_abiertas": 2,
#   "pnl_dia": 125.30,
#   "win_rate": 0.65,
#   "operaciones_hoy": 5
# }
```

### Alertas Configurables

El sistema soporta alertas por:
- Drawdown máximo alcanzado
- Profit target diario/semanal
- Número máximo de operaciones
- Errores de conexión

Configurar en `kernel/storage.py`:

```python
from kernel.storage import Storage

db = Storage()

# Configurar alertas
db.configurar_alerta(
    tipo='drawdown_max',
    umbral=0.05,  # 5% drawdown
    accion='email'
)

db.configurar_alerta(
    tipo='profit_target',
    umbral=500,  # $500 profit
    accion='notification'
)
```

---

## 🧪 Testing

### Ejecutar Tests

```bash
# Todos los tests
pytest tests/ -v

# Solo unitarios
pytest tests/unit -v

# Solo integración
pytest tests/integration -v

# Con coverage
pytest tests/ --cov=kernel --cov=core --cov=estrategias --cov-report=html

# Ver reporte HTML
open htmlcov/index.html
```

### Coverage Esperado

- **Detectores D0-D5**: >90%
- **Backtest Engine**: >85%
- **Estrategia Pivot**: >80%
- **API**: >75%
- **Total**: >80%

---

## 📚 Recursos Adicionales

- [Documentación Completa](docs/)
- [Manual Técnico](docs/MANUAL.md)
- [Ejemplos de Estrategias](estrategias/)
- [Reportes de Backtest](data/reports/)

---

## 🆘 Soporte

Para issues o preguntas:
1. Revisa la documentación en `docs/`
2. Ejecuta tests para verificar instalación
3. Revisa logs en `docker-compose logs`
4. Abre un issue en GitHub

---

**PIVOT Trading System v2.0** - De prototipo roto a sistema profesional 9/10 🚀
