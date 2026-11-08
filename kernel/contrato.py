# -*- coding: utf-8 -*-
"""
Kernel de PIVOT - Contratos base para estrategias, contexto y señales.
Este módulo define las interfaces abstractas que todas las estrategias deben implementar.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd


@dataclass
class GMetrics:
    """
    Métricas G precalculadas UNA SOLA VEZ por barra.
    Evita la triplicación de cálculos de indicadores.
    """
    g_atr8: float = 0.0
    g_atr14: float = 0.0
    g_atr50: float = 0.0
    g_ema50_dist: float = 0.0
    g_ema50_angulo: float = 0.0
    g_rsi14: float = 0.0
    g_d1_trend: int = 0
    g_h4_trend: int = 0
    g_volatilidad: float = 1.0
    g_zona: str = "NEUTRAL"  # PREMIUM, DISCOUNT, NEUTRAL


# =============================================================================
# TIPOS BASE PARA SEÑALES Y OVERLAYS
# =============================================================================

@dataclass
class Overlay:
    """Representa un elemento visual a pintar en el chart (TradingView)."""
    tipo: str  # "marker", "line", "box", "label"
    position: str = "aboveBar"  # "aboveBar", "belowBar", "top", "bottom"
    shape: str = "arrowUp"  # "arrowUp", "arrowDown", "circle", "square", etc.
    color: str = "#00ff00"
    text: str = ""
    price: Optional[float] = None
    time: Optional[datetime] = None
    extend: str = "none"  # "none", "left", "right", "both"


@dataclass
class Metrica:
    """Métrica de rendimiento de una estrategia o señal."""
    nombre: str
    valor: float
    unidad: str = "%"
    descripcion: str = ""


@dataclass
class ActivoInfo:
    """Información básica de un activo."""
    simbolo: str
    punto: float  # Valor del punto (ej: 0.00001 para EURUSD)
    tick_size: float
    contract_size: float = 100000
    session_open: str = "00:00"
    session_close: str = "23:59"
    timezone: timezone = field(default_factory=lambda: timezone.utc)
    
    # Propiedades calculadas para compatibilidad con backtest
    @property
    def valor_pip(self) -> float:
        """Retorna el valor de un pip (10 puntos para la mayoría de pares)."""
        # Para EURUSD, GBPUSD, etc: 1 pip = 0.0001
        # Para JPY pairs: 1 pip = 0.01
        if 'JPY' in self.simbolo:
            return 0.01
        return 0.0001
    
    @property
    def tamano_lote(self) -> float:
        """Retorna el tamaño estándar de lote."""
        return self.contract_size
    
    def __post_init__(self):
        if isinstance(self.timezone, str):
            # Convertir string de timezone a objeto timezone
            try:
                from zoneinfo import ZoneInfo
                self.timezone = ZoneInfo(self.timezone)
            except (ImportError, KeyError):
                # ImportError: zoneinfo no disponible; KeyError: ZoneInfoNotFoundError
                self.timezone = timezone.utc


# =============================================================================
# SEÑAL DE TRADING
# =============================================================================

@dataclass
class Señal:
    """
    Representa una señal de trading generada por una estrategia.
    Contiene toda la información necesaria para ejecutar, evaluar y visualizar la operación.
    """
    # Identificación
    estrategia: str
    simbolo: str
    direccion: int  # 1 = LONG, -1 = SHORT
    precio: float
    tiempo: datetime
    
    # Dirección y entrada (ahora sin default para evitar error)
    etiqueta: str = ""  # Tag para clasificar el tipo de setup
    
    # Gestión de la operación
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    expiracion_velas: int = 4  # Número de velas antes de invalidar la señal
    
    # Confianza y scoring
    confianza: Tuple[float, float] = (50.0, 70.0)  # (min, max) porcentaje
    score: float = 0.0  # Score calculado por el motor de scoring
    
    # Contexto y narrativa
    narrativa: str = ""  # Descripción legible del setup
    contexto: Dict[str, Any] = field(default_factory=dict)  # Datos adicionales del contexto
    
    # Visualización
    overlays: List[Overlay] = field(default_factory=list)
    
    # Estado
    activa: bool = True
    resultado: Optional[str] = None  # "WIN", "LOSS", "BREAKEVEN", "EXPIRED"
    pnl: Optional[float] = None  # Resultado en puntos o dinero
    
    # Metadata
    id_señal: Optional[str] = None
    timestamp_creacion: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def __post_init__(self):
        """Genera ID único incluyendo hash de detectores y dirección para evitar colisiones."""
        if self.id_señal is None:
            import hashlib
            
            # Obtener detectores activos de la señal (pueden estar en contexto o como atributo directo)
            detectores_list = getattr(self, 'detectores', [])
            
            # Si no hay atributo directo, buscar en contexto
            if not detectores_list and hasattr(self, 'contexto') and isinstance(self.contexto, dict):
                detectores_list = self.contexto.get('detectores', [])
            
            if isinstance(detectores_list, dict):
                detectores_list = list(detectores_list.keys())
            elif not isinstance(detectores_list, list):
                detectores_list = []
            
            # Crear string único basado en detectores y dirección
            detectores_str = "_".join(sorted([str(d) for d in detectores_list]))
            direccion = self.direccion if hasattr(self, 'direccion') and self.direccion else 0
            contenido = f"{self.estrategia}_{self.simbolo}_{self.tiempo.strftime('%Y%m%d_%H%M')}_{detectores_str}_{direccion}"
            
            # Hash corto para mantener legibilidad pero garantizar unicidad
            hash_suffix = hashlib.md5(contenido.encode()).hexdigest()[:6]
            
            self.id_señal = f"{self.estrategia}_{self.simbolo}_{self.tiempo.strftime('%Y%m%d_%H%M')}_{hash_suffix}"


# =============================================================================
# CONTEXTO DE EJECUCIÓN
# =============================================================================

@dataclass
class IndicadorCache:
    """Cache para indicadores calculados."""
    data: Dict[str, pd.Series] = field(default_factory=dict)
    timestamp: Optional[datetime] = None
    timeframe: str = ""
    
    def invalidate(self):
        self.data.clear()
        self.timestamp = None


@dataclass
class Contexto:
    """
    Snapshot inmutable de todo lo que una estrategia necesita para evaluar el mercado.
    Proporciona acceso a datos históricos, indicadores, y estado del mercado.
    """
    # Información del activo
    activo: Optional[ActivoInfo] = None
    
    # DataFrames por timeframe (índice temporal, columnas: open, high, low, close, volume)
    df_m1:   Optional[pd.DataFrame] = None
    df_m5:   Optional[pd.DataFrame] = None
    df_m15:  Optional[pd.DataFrame] = None
    df_m30:  Optional[pd.DataFrame] = None
    df_h1:   Optional[pd.DataFrame] = None
    df_h4:   Optional[pd.DataFrame] = None
    df_d1:   Optional[pd.DataFrame] = None
    
    # Precio y tiempo actual
    precio: float = 0.0
    tiempo: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Buffers de indicadores (lista con índice 0 = más reciente)
    g_atr8_buffer:   List[float] = field(default_factory=list)
    g_atr14_buffer:  List[float] = field(default_factory=list)
    g_atr30_buffer:  List[float] = field(default_factory=list)
    g_ema21_buffer:  List[float] = field(default_factory=list)
    g_ema50_buffer:  List[float] = field(default_factory=list)
    g_rsi14_buffer:  List[float] = field(default_factory=list)
    g_ema50_d1_buffer:  List[float] = field(default_factory=list)
    g_ema200_d1_buffer: List[float] = field(default_factory=list)
    g_ema20_h4_buffer: List[float] = field(default_factory=list)
    g_ema50_h4_buffer: List[float] = field(default_factory=list)
    g_d1_trend_buffer: List[int] = field(default_factory=list)
    g_h4_trend_buffer: List[int] = field(default_factory=list)
    g_volatilidad_buffer: List[float] = field(default_factory=list)
    g_zona_buffer: List[str] = field(default_factory=list)
    
    # Métricas G precalculadas (opcional, inyectado desde backtest)
    g_metrics: Optional[Any] = None
    
    # Caches de indicadores por timeframe
    _indicadores_cache: Dict[str, IndicadorCache] = field(default_factory=dict, repr=False)
    
    # Estructura y detectores (inyectados desde el core)
    estructura: Optional[object] = None
    mss_cache: Optional[object] = None
    zona_cache: Optional[object] = None
    
    # Métricas de contexto G (calculadas por el motor)
    g1: float = 0.0  # ATR ratio
    g2: float = 0.0  # Volume ratio
    g3: float = 0.0  # Trend strength
    g4: float = 0.0  # Volatility regime
    
    # Contexto temporal y de sesión
    session: str = "OUT"  # "ASIA", "LONDON", "NEWYORK", "OUT"
    kill_zone: str = "NONE"  # "KZ1", "KZ2", "KZ3", "NONE"
    trend_d1: str = "NEUTRO"  # "ALCISTA", "BAJISTA", "NEUTRO"
    regimen_vol: str = "NORMAL"  # "BAJO", "NORMAL", "ALTO"
    
    # Parámetros de configuración
    point: float = 0.00001
    broker_tz_offset: timezone = field(default_factory=lambda: timezone(timedelta(hours=2)))
    
    # Funciones helper inyectadas (desde el motor)
    get_volume_ratio_cached: callable = field(default=lambda *a, **k: 1.0, repr=False)
    get_volume_ratio: callable = field(default=lambda *a, **k: 1.0, repr=False)
    detect_mss_h4: callable = field(default=lambda: (False, 0, "", 0.0), repr=False)
    es_zona_premium_discount: callable = field(default=lambda nivel: (False, "NEUTRO"), repr=False)
    evaluar_contexto_estructural: callable = field(default=lambda *a: (50.0, 0.0), repr=False)
    
    # Métodos helper para acceder a datos
    
    def indicador(self, timeframe: str, tipo: str, params: Dict[str, Any]) -> pd.Series:
        """
        Obtiene un indicador calculado (con caché).
        
        Args:
            timeframe: Timeframe ("M15", "H1", "H4", "D1")
            tipo: Tipo de indicador ("EMA", "ATR", "RSI", etc.)
            params: Parámetros del indicador (ej: {"periodo": 21, "source": "close"})
        
        Returns:
            Serie de Pandas con los valores del indicador
        """
        cache_key = f"{timeframe}_{tipo}_{str(sorted(params.items()))}"
        
        # Verificar caché
        if timeframe in self._indicadores_cache:
            cache = self._indicadores_cache[timeframe]
            if cache_key in cache.data:
                return cache.data[cache_key]
        
        # Calcular indicador (implementación real en kernel/indicadores.py)
        # Por ahora retorna serie vacía - será implementado en Fase 2
        result = self._calcular_indicador(timeframe, tipo, params)
        
        # Guardar en caché
        if timeframe not in self._indicadores_cache:
            self._indicadores_cache[timeframe] = IndicadorCache(timeframe=timeframe)
        self._indicadores_cache[timeframe].data[cache_key] = result
        self._indicadores_cache[timeframe].timestamp = datetime.now(timezone.utc)
        
        return result
    
    def _calcular_indicador(self, timeframe: str, tipo: str, params: Dict[str, Any]) -> pd.Series:
        """Calcula un indicador (stub - implementación completa en Fase 2)."""
        df = getattr(self, f"df_{timeframe.lower()}", None)
        if df is None or len(df) == 0:
            return pd.Series(dtype=float)
        
        # Implementación básica de indicadores comunes
        source = params.get("source", "close")
        periodo = params.get("periodo", 14)
        
        if source not in df.columns:
            return pd.Series(dtype=float)
        
        data = df[source]
        
        if tipo.upper() == "EMA":
            return data.ewm(span=periodo, adjust=False).mean()
        elif tipo.upper() == "SMA":
            return data.rolling(window=periodo).mean()
        elif tipo.upper() == "ATR":
            high = df["high"]
            low = df["low"]
            close_prev = data.shift(1)
            tr = pd.concat([
                high - low,
                (high - close_prev).abs(),
                (low - close_prev).abs()
            ], axis=1).max(axis=1)
            return tr.ewm(span=periodo, adjust=False).mean()
        elif tipo.upper() == "RSI":
            delta = data.diff()
            gain = delta.where(delta > 0, 0).rolling(window=periodo).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=periodo).mean()
            rs = gain / loss
            return 100 - (100 / (1 + rs))
        else:
            # Indicador no soportado
            return pd.Series(dtype=float)
    
    def i_high(self, timeframe: str = "M15", shift: int = 0) -> float:
        """Obtiene el HIGH de una vela específica."""
        df = getattr(self, f"df_{timeframe.lower()}", None)
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["high"])
    
    def i_low(self, timeframe: str = "M15", shift: int = 0) -> float:
        """Obtiene el LOW de una vela específica."""
        df = getattr(self, f"df_{timeframe.lower()}", None)
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["low"])
    
    def i_close(self, timeframe: str = "M15", shift: int = 0) -> float:
        """Obtiene el CLOSE de una vela específica."""
        df = getattr(self, f"df_{timeframe.lower()}", None)
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["close"])
    
    def i_open(self, timeframe: str = "M15", shift: int = 0) -> float:
        """Obtiene el OPEN de una vela específica."""
        df = getattr(self, f"df_{timeframe.lower()}", None)
        if df is None or shift < 0 or shift >= len(df):
            return 0.0
        return float(df.iloc[-(shift + 1)]["open"])
    
    def i_volume(self, timeframe: str = "M15", shift: int = 0) -> int:
        """Obtiene el volumen de una vela específica."""
        df = getattr(self, f"df_{timeframe.lower()}", None)
        if df is None or shift < 0 or shift >= len(df):
            return 0
        col = "tick_volume" if "tick_volume" in df.columns else "volume"
        return int(df.iloc[-(shift + 1)][col])
    
    def i_time(self, timeframe: str = "M15", shift: int = 0) -> datetime:
        """Obtiene el timestamp de una vela específica."""
        df = getattr(self, f"df_{timeframe.lower()}", None)
        if df is None or shift < 0 or shift >= len(df):
            return datetime(1970, 1, 1)
        t = df.index[-(shift + 1)]
        if isinstance(t, pd.Timestamp):
            return t.to_pydatetime()
        return t
    
    def invalidate_cache(self, timeframe: Optional[str] = None):
        """Invalida la caché de indicadores."""
        if timeframe:
            if timeframe in self._indicadores_cache:
                self._indicadores_cache[timeframe].invalidate()
        else:
            for cache in self._indicadores_cache.values():
                cache.invalidate()


# =============================================================================
# CLASE ABSTRACTA DE ESTRATEGIA
# =============================================================================

class Estrategia(ABC):
    """
    Clase base abstracta para todas las estrategias de trading.
    
    Las estrategias deben:
    1. Definir metadatos (nombre, versión, timeframes soportados)
    2. Implementar setup() para inicialización
    3. Implementar detectar() para generar señales
    """
    
    # Metadatos (deben ser sobrescritos por subclases)
    nombre: str = "base"
    version: str = "1.0"
    timeframes: List[str] = ["M15"]  # Timeframes requeridos
    eventos: List[str] = ["candle_close"]  # Eventos que disparan evaluación
    
    # Parámetros configurables (debe ser sobrescrito)
    parametros: Dict[str, Dict[str, Any]] = {}
    
    @abstractmethod
    def setup(self, params: Dict[str, Any], activo: ActivoInfo) -> None:
        """
        Inicializa la estrategia con parámetros e información del activo.
        
        Args:
            params: Diccionario con los parámetros configurados
            activo: Información del activo a operar
        """
        pass
    
    @abstractmethod
    def detectar(self, ctx: Contexto) -> List[Señal]:
        """
        Evalúa el contexto actual y genera señales de trading.
        
        Args:
            ctx: Contexto con datos de mercado, indicadores y estado
        
        Returns:
            Lista de señales generadas (puede estar vacía)
        """
        pass
    
    def on_event(self, evento: str, ctx: Contexto) -> List[Señal]:
        """
        Maneja eventos específicos (sobrescribir si es necesario).
        
        Args:
            evento: Nombre del evento ("candle_close", "price_tick", etc.)
            ctx: Contexto actual
        
        Returns:
            Lista de señales generadas
        """
        if evento in self.eventos:
            return self.detectar(ctx)
        return []
    
    def validate_params(self, params: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Valida los parámetros de la estrategia.
        
        Args:
            params: Diccionario de parámetros a validar
        
        Returns:
            Tuple (es_valido, mensaje_error)
        """
        for param_name, config in self.parametros.items():
            if param_name not in params:
                if "default" in config:
                    continue
                return False, f"Parámetro requerido faltante: {param_name}"
            
            value = params[param_name]
            expected_type = config.get("tipo", "any")
            
            # Validar tipo
            type_map = {
                "int": int,
                "float": float,
                "str": str,
                "bool": bool
            }
            
            if expected_type != "any":
                expected_python_type = type_map.get(expected_type)
                if expected_python_type and not isinstance(value, expected_python_type):
                    return False, f"Tipo incorrecto para {param_name}: esperado {expected_type}"
            
            # Validar rangos
            if "min" in config and value < config["min"]:
                return False, f"{param_name} debe ser >= {config['min']}"
            if "max" in config and value > config["max"]:
                return False, f"{param_name} debe ser <= {config['max']}"
        
        return True, ""
    
    def get_default_params(self) -> Dict[str, Any]:
        """Obtiene los parámetros por defecto de la estrategia."""
        defaults = {}
        for param_name, config in self.parametros.items():
            defaults[param_name] = config.get("default", None)
        return defaults
    
    def get_info(self) -> Dict[str, Any]:
        """Obtiene información completa de la estrategia."""
        return {
            "nombre": self.nombre,
            "version": self.version,
            "timeframes": self.timeframes,
            "eventos": self.eventos,
            "parametros": self.parametros,
            "descripcion": getattr(self, "descripcion", "")
        }


# =============================================================================
# EXPORTACIONES PÚBLICAS
# =============================================================================

# =============================================================================
# TIPOS PARA OPCIONES BINARIAS
# =============================================================================

@dataclass
class BinarySeñal(Señal):
    """
    Señal para opciones binarias.
    Hereda de Señal y añade campos específicos de binarias.
    No usa stop_loss, take_profit, expiracion_velas (se ignoran).
    """
    # Expiración temporal exacta (en minutos desde entrada)
    expiry_minutes: int = 15
    expiry_timestamp: Optional[datetime] = None
    
    # Payout y contrato
    payout_pct: float = 0.80  # 70-95% típico
    contract_amount: float = 10.0  # USD por contrato
    contract_count: int = 1  # Número de contratos (para escalado)
    
    # Tipo de opción
    option_type: str = "CALL"  # "CALL" (direccion=1) o "PUT" (direccion=-1)
    
    def __post_init__(self):
        # Llamar __post_init__ de padre para generar id_señal
        super().__post_init__()
        
        # Mapear dirección a tipo de opción
        if self.direccion == 1:
            self.option_type = "CALL"
        elif self.direccion == -1:
            self.option_type = "PUT"
        
        # Calcular expiry_timestamp si no viene
        if self.expiry_timestamp is None and self.tiempo:
            self.expiry_timestamp = self.tiempo + timedelta(minutes=self.expiry_minutes)


@dataclass
class BinaryActivoInfo(ActivoInfo):
    """
    Información de activo para opciones binarias.
    Extiende ActivoInfo con tabla de payouts y límites de contrato.
    """
    # Tabla de payouts por horizonte temporal (minutos -> payout decimal)
    # Ej: {"1": 0.75, "5": 0.80, "15": 0.82, "30": 0.83, "60": 0.85, "EOD": 0.88}
    payout_table: Dict[str, float] = field(default_factory=dict)
    
    # Límites de contrato
    min_contract: float = 1.0
    max_contract: float = 10000.0
    min_contracts_per_trade: int = 1
    max_contracts_per_trade: int = 100
    
    # Broker específico (para payouts específicos)
    broker: str = "generic"  # "deriv", "iqoption", "pocket", "generic"
    
    def get_payout(self, expiry_minutes: int) -> float:
        """Obtiene payout para un horizonte dado, con fallback."""
        key = str(expiry_minutes)
        if key in self.payout_table:
            return self.payout_table[key]
        # Fallback: buscar el más cercano >= expiry_minutes
        candidates = []
        for k, v in self.payout_table.items():
            if k.isdigit() and int(k) >= expiry_minutes:
                candidates.append((int(k), v))
        if candidates:
            # Retornar el más cercano (mínimo key >= expiry_minutes)
            return min(candidates, key=lambda x: x[0])[1]
        # Si no hay >=, retornar el máximo disponible (EOD o el mayor)
        if self.payout_table:
            return max(self.payout_table.values())
        return 0.80  # Default


class BinaryRiskMode:
    """Modos de gestión de riesgo para binarias."""
    FIXED = "fixed"           # Monto fijo por operación
    MARTINGALE = "martingale" # Doblar tras pérdida
    ANTI_MARTINGALE = "anti_martingale"  # Aumentar tras ganancia
    KELLY = "kelly"           # Kelly fraccional basado en winrate histórico
    PERCENTAGE = "percentage" # % del capital actual


@dataclass
class BinaryRiskConfig:
    """Configuración de riesgo para binarias."""
    mode: str = BinaryRiskMode.FIXED
    
    # Fixed
    fixed_amount: float = 10.0
    
    # Martingala
    martingale_multiplier: float = 2.0
    martingale_max_steps: int = 4
    martingale_reset_on_win: bool = True
    
    # Anti-martingala
    anti_martingale_multiplier: float = 1.5
    anti_martingale_max_steps: int = 3
    
    # Kelly
    kelly_fraction: float = 0.25  # 25% de Kelly óptimo
    kelly_min_winrate: float = 0.55
    kelly_min_payout: float = 0.70
    
    # Percentage
    percentage_of_capital: float = 0.02  # 2%
    
    # Límites globales
    max_daily_loss_pct: float = 0.05  # 5% pérdida diaria máxima
    max_daily_trades: int = 20
    max_concurrent_trades: int = 1
    max_total_exposure_pct: float = 0.10  # 10% capital en riesgo simultáneo


@dataclass
class BinaryResultado:
    """Resultados de backtest binario."""
    # Configuración
    estrategia: str = ""
    simbolo: str = ""
    periodo_inicio: datetime = field(default_factory=lambda: datetime(1970, 1, 1))
    periodo_fin: datetime = field(default_factory=lambda: datetime(1970, 1, 1))
    timeframe_principal: str = "M15"
    
    # Capital
    capital_inicial: float = 0.0
    capital_final: float = 0.0
    
    # Métricas principales
    total_contratos: int = 0
    contratos_ganadores: int = 0
    contratos_perdedores: int = 0
    winrate: float = 0.0
    profit_factor: float = 0.0
    roi_pct: float = 0.0  # (ganancia_neta / total_invertido) * 100
    retorno_total_pct: float = 0.0  # (capital_final - capital_inicial) / capital_inicial * 100
    
    # Riesgo
    max_drawdown_pct: float = 0.0
    max_drawdown_abs: float = 0.0
    racha_ganadora_max: int = 0
    racha_perdedora_max: int = 0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    
    # Específicos binarias
    total_invertido: float = 0.0
    total_ganado: float = 0.0
    total_perdido: float = 0.0
    payout_promedio: float = 0.0
    
    # Detalles
    operaciones: List[Any] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    metrics_extra: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "estrategia": self.estrategia,
            "simbolo": self.simbolo,
            "periodo_inicio": self.periodo_inicio.isoformat() if self.periodo_inicio else "",
            "periodo_fin": self.periodo_fin.isoformat() if self.periodo_fin else "",
            "timeframe_principal": self.timeframe_principal,
            "total_contratos": self.total_contratos,
            "contratos_ganadores": self.contratos_ganadores,
            "contratos_perdedores": self.contratos_perdedores,
            "winrate": round(self.winrate, 2),
            "profit_factor": round(self.profit_factor, 2),
            "roi_pct": round(self.roi_pct, 2),
            "retorno_total_pct": round(self.retorno_total_pct, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 2),
            "sortino_ratio": round(self.sortino_ratio, 2),
            "racha_ganadora_max": self.racha_ganadora_max,
            "racha_perdedora_max": self.racha_perdedora_max,
            "total_invertido": round(self.total_invertido, 2),
            "total_ganado": round(self.total_ganado, 2),
            "total_perdido": round(self.total_perdido, 2),
            "payout_promedio": round(self.payout_promedio, 4),
            "metrics_extra": self.metrics_extra,
        }


# Actualizar exports
__all__ = [
    "Estrategia",
    "Contexto",
    "Señal",
    "ActivoInfo",
    "Metrica",
    "Overlay",
    "IndicadorCache",
    # Binarios
    "BinarySeñal",
    "BinaryActivoInfo",
    "BinaryRiskMode",
    "BinaryRiskConfig",
    "BinaryResultado",
]
