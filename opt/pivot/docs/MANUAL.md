# RADAR v2.0 — Manual de Instrucciones

## 1. Instalación

### Requisitos
- Python 3.10+
- Node.js 18+ (solo para frontend)

### Backend
```bash
cd radar
pip install -r requirements.txt
```

### Frontend
```bash
cd radar/frontend
npm install
```

---

## 2. Estructura del Sistema

```
radar/
├── kernel/                 # Motor core
│   ├── contrato.py         # Tipos y ABCs
│   ├── feeds/              # Fuentes de datos
│   │   ├── datafeed.py     # Multi-TF cache
│   │   ├── deriv.py        # WebSocket Deriv
│   │   └── csv.py          # Backtest CSV
│   ├── indicadores.py      # EMA, ATR, RSI con cache
│   ├── tiempo.py           # Sesiones y kill zones
│   ├── señales.py          # Dedup, latch, MFE/MAE
│   ├── storage.py          # SQLite WAL + writer async
│   ├── backtest.py         # Replay barra a barra
│   ├── runtime.py          # 1 hilo por activo
│   ├── alertas.py          # ntfy.sh
│   ├── consola.py          # Logs buffer+file+WS
│   └── api/                # FastAPI + WebSocket
├── estrategias/            # Plugins
│   ├── dummy/              # Estrategia de prueba
│   ├── ema_cross/          # Cruce de medias
│   └── pivot/              # (vacío — port por aparte)
├── activos/                # Config JSON por activo
├── frontend/               # React 18 + TS + Vite
├── data/                   # SQLite + CSVs
└── cli.py                  # Punto de entrada
```

---

## 3. Configuración

### 3.1 Agregar un activo
Crear `activos/MIACTIVO.json`:
```json
{
  "simbolo": "GBPUSD",
  "nombre": "Libra/Dólar",
  "point": 0.00001,
  "decimales": 5,
  "pip": 0.0001,
  "fuente_tipo": "deriv",
  "fuente_config": {"instrumento": "frxGBPUSD"},
  "timeframes": ["M15", "H1", "H4", "D1"],
  "horario_broker_utc": 2
}
```

### 3.2 Configurar notificaciones push
Ir a `/config` en el frontend o hacer POST:
```bash
curl -X POST http://localhost:8000/api/config/ntfy   -H "Content-Type: application/json"   -d '{"topic": "mi-topic-secreto", "server": "https://ntfy.sh"}'
```

---

## 4. Uso

### 4.1 Arrancar backend
```bash
python cli.py
```
API en http://localhost:8000

### 4.2 Arrancar frontend (desarrollo)
```bash
cd frontend
npm run dev
```
En http://localhost:5173

### 4.3 Arrancar frontend (producción)
```bash
cd frontend
npm run build
```
El backend sirve `frontend/dist/` automáticamente.

---

## 5. Flujo de trabajo

### En vivo
1. Ir al Hub (`/`)
2. Click en un activo → ActivoPage
3. Click "Start" → el runtime se conecta a Deriv
4. Las señales aparecen en tiempo real vía WebSocket
5. Las alertas push llegan al móvil (si configuraste ntfy)

### Backtest
1. Ir a `/backtest`
2. Seleccionar activo, estrategia, fechas
3. Ajustar parámetros (se generan automático desde schema)
4. Click "Ejecutar Backtest"
5. Resultados: métricas + equity curve

---

## 6. CSV para Backtest

Formato aceptado (columnas case-insensitive):
```csv
time,open,high,low,close,volume
2024-01-01 00:00:00,1.08500,1.08550,1.08450,1.08520,1200
```

También acepta: `timestamp`, `date`, `datetime`, `ts` como columna de tiempo.

Guardar en `data/EURUSD.csv`.

---

## 7. Agregar una estrategia

1. Crear carpeta `estrategias/mi_estrategia/`
2. Crear `__init__.py` con:
```python
from estrategias.base import Estrategia, Contexto, Señal

class MiEstrategia(Estrategia):
    nombre = "mi_estrategia"
    version = "1.0"
    timeframes = ["M15"]
    eventos = ["candle_close"]
    parametros = {
        "param1": {"tipo": "int", "default": 14, "min": 1, "max": 100, "label": "Período"}
    }

    def setup(self, params, activo):
        self.param1 = params.get("param1", 14)
        self.activo = activo

    def detectar(self, ctx: Contexto) -> list[Señal]:
        # Tu lógica aquí
        return []
```
3. Reiniciar el backend. Aparece automáticamente en `/estrategias`.

---

## 8. Endpoints API

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/api/assets` | Listar activos |
| POST | `/api/assets/{s}/start` | Iniciar runtime |
| POST | `/api/assets/{s}/stop` | Detener runtime |
| GET | `/api/assets/{s}/history?tf=M15&count=200` | Velas históricas |
| GET | `/api/assets/{s}/signals` | Señales del activo |
| GET | `/api/assets/{s}/consola` | Logs del activo |
| GET | `/api/strategies` | Estrategias disponibles |
| POST | `/api/backtest` | Lanzar backtest |
| GET | `/api/backtest/{id}` | Estado/resultado |
| POST | `/api/config/ntfy` | Configurar alertas |
| WS | `/ws` | WebSocket en tiempo real |

---

## 9. Troubleshooting

| Problema | Solución |
|----------|----------|
| "No module named 'kernel'" | Ejecutar desde la raíz del proyecto, no desde subcarpetas |
| WebSocket no conecta | Verificar que backend esté en 8000, frontend en 5173 |
| No llegan alertas ntfy | Verificar topic y que el móvil esté suscrito |
| CSV backtest falla | Verificar formato de fecha y columnas OHLCV |
| SQLite locked | Esperar 1-2s, el writer async maneja retry automático |

---

## 10. Arquitectura resumida

- **1 hilo por activo** → aislamiento total
- **1 hilo writer SQLite** → cola thread-safe, batches de 50
- **FastAPI async** → endpoints no bloquean
- **WebSocket único** → broadcast a todos los clientes
- **Cache de indicadores** → invalidación por TF
- **Latch + Dedup** → evita señales duplicadas en misma vela

---

**Versión:** 2.0-corr | **Fecha:** 2026-08-06
