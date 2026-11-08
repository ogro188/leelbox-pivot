"""
Sistema de almacenamiento SQLite para operaciones y métricas
"""
import asyncio, sqlite3, logging, json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any
from threading import Lock

logger = logging.getLogger(__name__)

# Unica fuente de verdad del esquema ML: se usa al escribir y al leer.
DDL_SIGNALS_ML_DATASET = """
CREATE TABLE IF NOT EXISTS signals_ml_dataset (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_entrada TEXT NOT NULL,
    timestamp_salida TEXT,
    simbolo TEXT NOT NULL,
    direccion INTEGER NOT NULL,
    detectores_activos TEXT NOT NULL,
    g_atr8 REAL,
    g_atr14 REAL,
    g_atr50 REAL,
    g_ema50_dist REAL,
    g_ema50_angulo REAL,
    g_rsi14 REAL,
    g_d1_trend INTEGER,
    g_h4_trend INTEGER,
    g_volatilidad REAL,
    g_zona TEXT,
    sesion TEXT,
    zona_premium_discount TEXT,
    pnl_puntos REAL,
    razon_salida TEXT,
    fue_ganadora INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
)
"""


class Database:
    """Gestor de base de datos SQLite thread-safe"""
    
    def __init__(self, db_path: str = "data/pivot.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self._initialized = False
    
    def _get_connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.commit()
            self._conn.row_factory = sqlite3.Row
        return self._conn
    
    def initialize(self):
        if self._initialized:
            return
        conn = self._get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""CREATE TABLE IF NOT EXISTS operaciones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estrategia TEXT, simbolo TEXT, timeframe TEXT,
            timestamp_abertura DATETIME, timestamp_cierre DATETIME,
            tipo TEXT, precio_entrada REAL, precio_salida REAL,
            stop_loss REAL, take_profit REAL, cantidad REAL,
            pnl REAL DEFAULT 0, estado TEXT DEFAULT 'ABIERTA',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        
        cursor.execute("""CREATE TABLE IF NOT EXISTS backtests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estrategia TEXT, simbolo TEXT, timeframe TEXT,
            fecha_inicio DATETIME, fecha_fin DATETIME,
            capital_inicial REAL, capital_final REAL,
            retorno_total REAL, win_rate REAL,
            total_operaciones INTEGER, profit_factor REAL,
            sharpe_ratio REAL, drawdown_max REAL,
            parametros JSON, metricas_json JSON,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        
        cursor.execute("""CREATE TABLE IF NOT EXISTS activos_config (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simbolo TEXT UNIQUE, nombre TEXT, tipo TEXT DEFAULT 'FOREX',
            precision INTEGER DEFAULT 5, pip_value REAL,
            spread_promedio REAL, timezone TEXT DEFAULT 'UTC',
            activo BOOLEAN DEFAULT 1
        )""")
        
        cursor.execute("""CREATE TABLE IF NOT EXISTS strategy_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            estrategia TEXT, simbolo TEXT, nivel TEXT,
            mensaje TEXT, contexto JSON,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")
        
        # Tabla para señales del core (migración desde persistencia.py)
        cursor.execute("""CREATE TABLE IF NOT EXISTS senales_core (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT UNIQUE,
            entry_time DATETIME,
            symbol TEXT,
            direction INTEGER,
            entry_price REAL,
            detector TEXT,
            tipo TEXT,
            hipotesis_prob_min REAL,
            hipotesis_prob_max REAL,
            hipotesis_expiry_velas INTEGER,
            conviccion REAL,
            regimen_volatilidad TEXT,
            fuente TEXT DEFAULT 'deriv',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )""")

        # Migración: columna fuente en DBs creadas antes de este cambio
        try:
            cursor.execute("ALTER TABLE senales_core ADD COLUMN fuente TEXT DEFAULT 'deriv'")
        except sqlite3.OperationalError:
            pass

        # Backfill por huella: la etiqueta PIVOT_* solo la genera el replay/backtest
        cursor.execute(
            "UPDATE senales_core SET fuente='replay' "
            "WHERE (fuente IS NULL OR fuente='' OR fuente='deriv') AND tipo LIKE 'PIVOT_%'"
        )

        # Tabla para cola de señales pendientes
        cursor.execute("""CREATE TABLE IF NOT EXISTS cola_senales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT,
            symbol TEXT,
            detector TEXT,
            priority INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            processed BOOLEAN DEFAULT 0
        )""")
        
        # Tabla ML: existe desde la inicializacion para que las lecturas
        # (estadisticas / export) no fallen en una base recien creada.
        # Resultados por horizonte medidos sobre velas CERRADAS.
        cursor.execute("""CREATE TABLE IF NOT EXISTS senales_resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id TEXT,
            horizonte INTEGER,
            retorno REAL,
            mfe REAL,
            mae REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(signal_id, horizonte)
        )""")

        cursor.execute(DDL_SIGNALS_ML_DATASET)

        conn.commit()
        self._initialized = True
        logger.info(f"Base de datos inicializada: {self.db_path}")
    
    async def execute_async(self, query: str, params: tuple = ()):
        loop = asyncio.get_event_loop()
        def _execute():
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return cursor
        return await loop.run_in_executor(None, _execute)
    
    async def fetchall_async(self, query: str, params: tuple = ()) -> List[Dict]:
        loop = asyncio.get_event_loop()
        def _fetch():
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(query, params)
                return [dict(row) for row in cursor.fetchall()]
        return await loop.run_in_executor(None, _fetch)
    
    async def fetchone_async(self, query: str, params: tuple = ()) -> Optional[Dict]:
        loop = asyncio.get_event_loop()
        def _fetch():
            with self._lock:
                conn = self._get_connection()
                cursor = conn.cursor()
                cursor.execute(query, params)
                row = cursor.fetchone()
                return dict(row) if row else None
        return await loop.run_in_executor(None, _fetch)
    
    async def guardar_operacion(self, operacion, estrategia: str):
        self.initialize()
        query = """INSERT INTO operaciones (estrategia, simbolo, timeframe, timestamp_abertura, tipo, precio_entrada, cantidad, stop_loss, take_profit, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        params = (estrategia, operacion.simbolo, str(operacion.timeframe), operacion.timestamp_abertura, str(operacion.tipo), operacion.precio_entrada, operacion.cantidad, operacion.stop_loss, operacion.take_profit, operacion.estado)
        await self.execute_async(query, params)
    
    async def actualizar_operacion_cierre(self, operacion_id: int, operacion):
        self.initialize()
        query = """UPDATE operaciones SET timestamp_cierre=?, precio_salida=?, pnl=?, estado=? WHERE id=?"""
        params = (operacion.timestamp_cierre, operacion.precio_salida, operacion.pnl, operacion.estado, operacion_id)
        await self.execute_async(query, params)
    
    async def obtener_operaciones_abiertas(self, estrategia: str = None) -> List[Dict]:
        self.initialize()
        if estrategia:
            return await self.fetchall_async("SELECT * FROM operaciones WHERE estado='ABIERTA' AND estrategia=?", (estrategia,))
        return await self.fetchall_async("SELECT * FROM operaciones WHERE estado='ABIERTA'")
    
    async def obtener_historico_operaciones(self, estrategia: str = None, simbolo: str = None, limite: int = 1000) -> List[Dict]:
        self.initialize()
        conditions = []
        params = []
        if estrategia:
            conditions.append("estrategia=?")
            params.append(estrategia)
        if simbolo:
            conditions.append("simbolo=?")
            params.append(simbolo)
        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        return await self.fetchall_async(f"SELECT * FROM operaciones {where} ORDER BY timestamp_abertura DESC LIMIT ?", (*params, limite))
    
    async def guardar_backtest(self, resultado, parametros: Dict = None):
        self.initialize()
        metrics = resultado.to_dict() if hasattr(resultado, 'to_dict') else {}
        query = """INSERT INTO backtests (estrategia, simbolo, timeframe, fecha_inicio, fecha_fin, capital_inicial, capital_final, retorno_total, win_rate, total_operaciones, profit_factor, sharpe_ratio, drawdown_max, parametros, metricas_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        params = (
            resultado.estrategia,
            resultado.simbolo,
            getattr(resultado, "timeframe_principal", None),
            getattr(resultado, "periodo_inicio", None),
            getattr(resultado, "periodo_fin", None),
            resultado.capital_inicial,
            resultado.capital_final,
            resultado.retorno_total,
            getattr(resultado, "winrate", None),
            resultado.total_operaciones,
            metrics.get('profit_factor'),
            metrics.get('sharpe_ratio'),
            metrics.get('drawdown_maximo'),
            json.dumps(parametros or {}),
            json.dumps(metrics, default=str),
        )
        await self.execute_async(query, params)
    
    async def obtener_backtests(self, estrategia: str = None, limite: int = 50) -> List[Dict]:
        self.initialize()
        if estrategia:
            return await self.fetchall_async("SELECT * FROM backtests WHERE estrategia=? ORDER BY created_at DESC LIMIT ?", (estrategia, limite))
        return await self.fetchall_async("SELECT * FROM backtests ORDER BY created_at DESC LIMIT ?", (limite,))
    
    async def guardar_activo_config(self, config: Dict[str, Any]):
        self.initialize()
        query = """INSERT OR REPLACE INTO activos_config (simbolo, nombre, tipo, precision, pip_value, spread_promedio, timezone, activo) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        params = (config.get('simbolo'), config.get('nombre'), config.get('tipo', 'FOREX'), config.get('precision', 5), config.get('pip_value'), config.get('spread_promedio'), config.get('timezone', 'UTC'), config.get('activo', 1))
        await self.execute_async(query, params)
    
    async def obtener_activos_config(self) -> List[Dict]:
        self.initialize()
        return await self.fetchall_async("SELECT * FROM activos_config WHERE activo=1")
    
    async def log_strategy(self, estrategia: str, nivel: str, mensaje: str, simbolo: str = None, contexto: Dict = None):
        self.initialize()
        query = """INSERT INTO strategy_logs (estrategia, simbolo, nivel, mensaje, contexto) VALUES (?, ?, ?, ?, ?)"""
        params = (estrategia, simbolo, nivel, mensaje, json.dumps(contexto or {}))
        await self.execute_async(query, params)
    
    # Métodos para señales del core (migración desde persistencia.py)
    async def guardar_senal_core(self, signal_id: str, entry_time: datetime, symbol: str, 
                                  direction: int, entry_price: float, detector: str, tipo: str,
                                  hipotesis_prob_min: float, hipotesis_prob_max: float,
                                  hipotesis_expiry_velas: int, conviccion: float,
                                  regimen_volatilidad: str, fuente: str = "deriv"):
        """Guarda una señal del core en SQLite (reemplaza write_signal_to_csv).

        fuente: 'deriv' (datos de mercado en vivo) | 'replay' | 'backtest' | 'test'
        """
        self.initialize()
        query = """INSERT OR REPLACE INTO senales_core 
            (signal_id, entry_time, symbol, direction, entry_price, detector, tipo,
             hipotesis_prob_min, hipotesis_prob_max, hipotesis_expiry_velas, conviccion,
             regimen_volatilidad, fuente)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        params = (signal_id, entry_time.isoformat(), symbol, direction, entry_price, 
                  detector, tipo, hipotesis_prob_min, hipotesis_prob_max, 
                  hipotesis_expiry_velas, conviccion, regimen_volatilidad, fuente)
        await self.execute_async(query, params)
    
    async def guardar_resultado_senal(self, signal_id, horizonte: int,
                                      retorno: float, mfe: float, mae: float):
        """Persiste el resultado de una senal en una vela cerrada (base del hit-rate)."""
        query = ("INSERT OR REPLACE INTO senales_resultados "
                 "(signal_id, horizonte, retorno, mfe, mae, created_at) "
                 "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)")
        await self.execute_async(query, (str(signal_id), int(horizonte),
                                         float(retorno), float(mfe), float(mae)))

    async def obtener_senales_core(self, symbol: str = None, limite: int = 100) -> List[Dict]:
        """Obtiene señales históricas del core"""
        self.initialize()
        if symbol:
            return await self.fetchall_async(
                "SELECT * FROM senales_core WHERE symbol=? ORDER BY entry_time DESC LIMIT ?",
                (symbol, limite)
            )
        return await self.fetchall_async(
            "SELECT * FROM senales_core ORDER BY entry_time DESC LIMIT ?",
            (limite,)
        )
    
    async def guardar_cola_senal(self, signal_id: str, symbol: str, detector: str, priority: int = 0):
        """Agrega una señal a la cola de pendientes"""
        self.initialize()
        query = """INSERT INTO cola_senales (signal_id, symbol, detector, priority) VALUES (?, ?, ?, ?)"""
        await self.execute_async(query, (signal_id, symbol, detector, priority))
    
    async def obtener_cola_pendientes(self) -> List[Dict]:
        """Obtiene señales pendientes de procesar"""
        self.initialize()
        return await self.fetchall_async(
            "SELECT * FROM cola_senales WHERE processed=0 ORDER BY priority ASC, created_at ASC"
        )
    
    async def marcar_cola_procesada(self, signal_id: str):
        """Marca una señal como procesada"""
        self.initialize()
        await self.execute_async(
            "UPDATE cola_senales SET processed=1 WHERE signal_id=?",
            (signal_id,)
        )
    
    async def cargar_cola_pendientes(self) -> tuple:
        """Carga señales pendientes (retorna dict y set de IDs)"""
        self.initialize()
        pendientes = await self.obtener_cola_pendientes()
        signals_dict = {}
        ids_set = set()
        for p in pendientes:
            signal_id = p['signal_id']
            ids_set.add(signal_id)
            signals_dict[signal_id] = p
        return signals_dict, ids_set
    
    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
    
    # Métodos para ML Dataset (Fase 7.3)
    def guardar_resultado_operacion(self, operacion_dict: dict):
        """
        Guarda resultado de operación en tabla append-only para ML dataset.
        Tabla: signals_ml_dataset
        
        Args:
            operacion_dict: Diccionario con campos:
                - timestamp_entrada, timestamp_salida
                - simbolo, direccion, detectores_activos
                - g_metrics (G1-G4 al momento de entrada)
                - sesion, zona_premium_discount
                - pnl_puntos, razon_salida, fue_ganadora
        """
        with self._lock:
            cursor = self._get_connection().cursor()
            
            cursor.execute(DDL_SIGNALS_ML_DATASET)
            
            # Extraer G metrics si existen
            g_metrics = operacion_dict.get('g_metrics', {})
            
            cursor.execute("""
                INSERT INTO signals_ml_dataset (
                    timestamp_entrada, timestamp_salida, simbolo, direccion,
                    detectores_activos, g_atr8, g_atr14, g_atr50,
                    g_ema50_dist, g_ema50_angulo, g_rsi14, g_d1_trend, g_h4_trend,
                    g_volatilidad, g_zona, sesion, zona_premium_discount,
                    pnl_puntos, razon_salida, fue_ganadora
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                operacion_dict.get('timestamp_entrada'),
                operacion_dict.get('timestamp_salida'),
                operacion_dict.get('simbolo'),
                operacion_dict.get('direccion'),
                json.dumps(operacion_dict.get('detectores_activos', [])),
                g_metrics.get('g_atr8'),
                g_metrics.get('g_atr14'),
                g_metrics.get('g_atr50'),
                g_metrics.get('g_ema50_dist'),
                g_metrics.get('g_ema50_angulo'),
                g_metrics.get('g_rsi14'),
                g_metrics.get('g_d1_trend'),
                g_metrics.get('g_h4_trend'),
                g_metrics.get('g_volatilidad'),
                g_metrics.get('g_zona'),
                operacion_dict.get('sesion'),
                operacion_dict.get('zona_premium_discount'),
                operacion_dict.get('pnl_puntos'),
                operacion_dict.get('razon_salida'),
                1 if operacion_dict.get('fue_ganadora') else 0
            ))
            
            self._get_connection().commit()
    
    def exportar_ml_dataset(self, output_path: str = "ml_dataset.csv") -> int:
        """
        Exporta toda la tabla signals_ml_dataset a CSV para entrenamiento de ML.
        
        Returns:
            Número de filas exportadas
        """
        import pandas as pd
        
        with self._lock:
            df = pd.read_sql_query(
                "SELECT * FROM signals_ml_dataset ORDER BY timestamp_entrada",
                self._get_connection()
            )
        
        if len(df) == 0:
            return 0
        
        df.to_csv(output_path, index=False)
        return len(df)
    
    def obtener_estadisticas_ml_dataset(self) -> dict:
        """Obtiene estadísticas básicas del dataset ML."""
        self.initialize()
        with self._lock:
            cursor = self._get_connection().cursor()
            
            # Total operaciones
            cursor.execute("SELECT COUNT(*) FROM signals_ml_dataset")
            total = cursor.fetchone()[0]
            
            if total == 0:
                return {"total_operaciones": 0}
            
            # Win rate general
            cursor.execute("SELECT AVG(fue_ganadora) FROM signals_ml_dataset WHERE fue_ganadora IS NOT NULL")
            win_rate = cursor.fetchone()[0] or 0
            
            # Operaciones por combinación de detectores
            cursor.execute("""
                SELECT detectores_activos, COUNT(*) as count, AVG(fue_ganadora) as win_rate
                FROM signals_ml_dataset
                GROUP BY detectores_activos
                ORDER BY count DESC
                LIMIT 10
            """)
            top_combinaciones = cursor.fetchall()
            
            return {
                "total_operaciones": total,
                "win_rate_general": round(win_rate, 4),
                "top_combinaciones": [
                    {"detectores": c[0], "count": c[1], "win_rate": round(c[2] or 0, 4)}
                    for c in top_combinaciones
                ]
            }

_db_instance: Optional[Database] = None

def get_database(db_path: str = "data/pivot.db", force_new: bool = False) -> Database:
    global _db_instance
    if force_new or _db_instance is None:
        _db_instance = Database(db_path)
    return _db_instance
