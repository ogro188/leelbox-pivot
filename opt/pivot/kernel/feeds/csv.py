# -*- coding: utf-8 -*-
"""
Kernel de PIVOT - Feed de datos CSV para backtesting.
Permite cargar datos históricos desde archivos CSV y generar velas para el motor de backtest.
"""
import logging
import pandas as pd
from datetime import datetime, timezone
from typing import Iterator, Optional, Dict, List, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class CSVFeed:
    """
    Feed de datos que carga velas históricas desde archivos CSV.
    
    Formato esperado del CSV:
    - Columnas requeridas: timestamp, open, high, low, close, volume (o tick_volume)
    - Timestamp en formato ISO o Unix timestamp
    - Timeframe inferido del nombre del archivo o parámetro explícito
    
    Ejemplo de uso:
        feed = CSVFeed("data/eurusd_m15.csv", timeframe="M15")
        for vela in feed.iter_barras():
            print(vela)
    """
    
    TIMEFRAME_MAP = {
        "M1": 60,
        "M3": 180,
        "M5": 300,
        "M15": 900,
        "M30": 1800,
        "H1": 3600,
        "H4": 14400,
        "D1": 86400,
        "W1": 604800,
        "MN1": 2592000,
    }
    
    def __init__(
        self,
        path: str,
        timeframe: str = "M15",
        symbol: str = "EURUSD",
        tz: timezone = timezone.utc,
        column_map: Optional[Dict[str, str]] = None,
        fecha_inicio: Optional[datetime] = None,
        fecha_fin: Optional[datetime] = None,
    ):
        """
        Inicializa el feed CSV.
        
        Args:
            path: Ruta al archivo CSV
            timeframe: Timeframe de los datos ("M15", "H1", etc.)
            symbol: Símbolo del activo
            tz: Timezone para convertir timestamps
            column_map: Mapeo personalizado de columnas (ej: {"time": "timestamp", "o": "open"})
            fecha_inicio: Filtrar datos desde esta fecha (opcional)
            fecha_fin: Filtrar datos hasta esta fecha (opcional)
        """
        self.path = Path(path)
        self.timeframe = timeframe
        self.symbol = symbol
        self.tz = tz
        self.column_map = column_map or {}
        self.fecha_inicio = fecha_inicio
        self.fecha_fin = fecha_fin
        
        if not self.path.exists():
            raise FileNotFoundError(f"CSV no encontrado: {self.path}")
        
        # Cargar datos
        self.df = self._cargar_csv()
        self.idx = 0
        
    def _precalcular_indicadores(self, df: pd.DataFrame) -> pd.DataFrame:
        """Precalcula indicadores técnicos una sola vez al cargar el CSV."""
        if df.empty or len(df) < 50:
            return df
        
        # True Range
        tr1 = df['high'] - df['low']
        tr2 = abs(df['high'] - df['close'].shift(1))
        tr3 = abs(df['low'] - df['close'].shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        df['atr8'] = tr.ewm(span=8, adjust=False).mean()
        df['atr14'] = tr.ewm(span=14, adjust=False).mean()
        df['atr30'] = tr.ewm(span=30, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        # RSI 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi14'] = 100 - (100 / (1 + rs))
        
        return df
    
    def _cargar_csv(self) -> pd.DataFrame:
        """Carga y valida el CSV."""
        # Leer CSV
        df = pd.read_csv(self.path)
        
        # Normalizar nombres de columnas
        default_map = {
            "time": "timestamp",
            "date": "timestamp",
            "datetime": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
            "tick_v": "tick_volume",
        }
        
        # Aplicar mapeo personalizado + default
        combined_map = {**default_map, **self.column_map}
        df = df.rename(columns=combined_map)
        
        # Validar columnas requeridas
        required_cols = ["timestamp", "open", "high", "low", "close"]
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            raise ValueError(f"Columnas faltantes en CSV: {missing}")
        
        # Convertir timestamp a datetime
        # Nota: en pandas >= 3.0 las columnas de texto usan dtype "str" (StringDtype),
        # no "object". Se detecta por tipo numérico en lugar del dtype exacto.
        if pd.api.types.is_numeric_dtype(df["timestamp"]):
            # Unix timestamp
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
        else:
            # Intentar parsear ISO format
            try:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            except Exception as e:
                # Asumir Unix timestamp en segundos
                logger.warning(f"Parse ISO falló, reintentando como Unix seconds: {e}")
                df["timestamp"] = pd.to_datetime(df["timestamp"].astype(float), unit="s", utc=True)
        
        # Convertir a timezone especificada
        df["timestamp"] = df["timestamp"].dt.tz_convert(self.tz)
        
        # Setear timestamp como índice
        df = df.set_index("timestamp")
        
        # Asegurar columnas estándar
        if "volume" not in df.columns and "tick_volume" in df.columns:
            df["volume"] = df["tick_volume"]
        elif "volume" not in df.columns:
            df["volume"] = 0
            
        # Ordenar por tiempo
        df = df.sort_index()
        
        # Eliminar duplicados
        df = df[~df.index.duplicated(keep="first")]
        
        # Aplicar filtro de fechas si se especificó
        if self.fecha_inicio is not None:
            # Asegurar timezone-aware
            if self.fecha_inicio.tzinfo is None:
                fecha_inicio = self.fecha_inicio.replace(tzinfo=self.tz)
            else:
                fecha_inicio = self.fecha_inicio.astimezone(self.tz)
            df = df[df.index >= fecha_inicio]
        
        if self.fecha_fin is not None:
            if self.fecha_fin.tzinfo is None:
                fecha_fin = self.fecha_fin.replace(tzinfo=self.tz)
            else:
                fecha_fin = self.fecha_fin.astimezone(self.tz)
            df = df[df.index <= fecha_fin]
        
        # Precalcular indicadores una sola vez
        df = self._precalcular_indicadores(df)
        
        return df
    
    def __len__(self) -> int:
        """Número de velas disponibles."""
        return len(self.df)
    
    def reset(self):
        """Reinicia el feed al inicio."""
        self.idx = 0
    
    def iter_barras(self) -> Iterator[Dict[str, Any]]:
        """
        Itera sobre todas las velas del feed.
        
        Yields:
            Diccionario con: timestamp, open, high, low, close, volume, timeframe, symbol
        """
        self.reset()
        for idx, row in self.df.iterrows():
            yield {
                "timestamp": idx.to_pydatetime(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0)),
                "timeframe": self.timeframe,
                "symbol": self.symbol,
            }
            self.idx += 1
    
    def get_bars(self, n: int = 100) -> pd.DataFrame:
        """
        Obtiene las últimas n velas hasta la posición actual.
        
        Args:
            n: Número de velas a retornar
            
        Returns:
            DataFrame con las últimas n velas
        """
        if self.idx == 0:
            return pd.DataFrame()
        
        start_idx = max(0, self.idx - n)
        return self.df.iloc[start_idx:self.idx].copy()
    
    def current_bar(self) -> Optional[Dict[str, Any]]:
        """Retorna la vela actual (en la posición del iterator)."""
        if self.idx == 0 or self.idx > len(self.df):
            return None
        
        row = self.df.iloc[self.idx - 1]
        return {
            "timestamp": self.df.index[self.idx - 1].to_pydatetime(),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
            "timeframe": self.timeframe,
            "symbol": self.symbol,
        }
    
    def skip_to(self, timestamp: datetime) -> int:
        """
        Salta a una posición específica en el tiempo.
        
        Args:
            timestamp: Timestamp objetivo
            
        Returns:
            Nuevo índice de posición
        """
        # Buscar el índice más cercano
        try:
            self.idx = self.df.index.get_indexer([method], method="ffill")[0] if method else self.df.index.get_loc(timestamp)
        except Exception:
            # Si no encuentra, buscar el más cercano
            diffs = (self.df.index - timestamp).abs()
            self.idx = diffs.argmin()
        
        return self.idx
    
    def has_more(self) -> bool:
        """Verifica si hay más velas por procesar."""
        return self.idx < len(self.df)
    
    @property
    def start_date(self) -> datetime:
        """Fecha de inicio de los datos."""
        return self.df.index[0].to_pydatetime()
    
    @property
    def end_date(self) -> datetime:
        """Fecha de fin de los datos."""
        return self.df.index[-1].to_pydatetime()
    
    @property
    def total_bars(self) -> int:
        """Número total de velas."""
        return len(self.df)
    
    def resamplear_ohlc(self, timeframe_destino: str) -> pd.DataFrame:
        """
        Deriva OHLC de timeframe mayor desde el dataframe base (resampling).
        Ej: M15 -> H1, H4, D1
        
        Args:
            timeframe_destino: Timeframe destino ("H1", "H4", "D1")
            
        Returns:
            DataFrame con velas OHLC resampleadas
        """
        reglas = {
            "M1": "1min", "M3": "3min", "M5": "5min", "M15": "15min", 
            "M30": "30min", "H1": "1h", "H4": "4h", "D1": "1D", "W1": "1W"
        }
        
        if timeframe_destino not in reglas:
            raise ValueError(f"No se puede resamplear a {timeframe_destino}")
        
        regla = reglas[timeframe_destino]
        
        # Resamplear OHLCV
        agg = self.df.resample(regla).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna(subset=["open"])
        
        return agg


class MultiTimeframeFeed:
    """
    Gestiona múltiples feeds CSV para diferentes timeframes.
    Sincroniza los datos para que todos los timeframes estén alineados temporalmente.
    """
    
    def __init__(self, symbol: str, base_tz: timezone = timezone.utc):
        """
        Inicializa el feed multi-timeframe.
        
        Args:
            symbol: Símbolo del activo
            base_tz: Timezone base
        """
        self.symbol = symbol
        self.tz = base_tz
        self.feeds: Dict[str, CSVFeed] = {}
        
    def add_feed(self, timeframe: str, path: str):
        """
        Agrega un feed para un timeframe específico.
        
        Args:
            timeframe: Timeframe ("M15", "H1", etc.)
            path: Ruta al CSV
        """
        self.feeds[timeframe] = CSVFeed(
            path=path,
            timeframe=timeframe,
            symbol=self.symbol,
            tz=self.tz,
        )
    
    def get_feed(self, timeframe: str) -> Optional[CSVFeed]:
        """Obtiene el feed para un timeframe específico."""
        return self.feeds.get(timeframe)
    
    def iter_synchronized(self) -> Iterator[Dict[str, pd.DataFrame]]:
        """
        Itera sincronizando todos los timeframes.
        En cada paso, retorna los DataFrames actualizados de cada timeframe.
        
        Yields:
            Diccionario {timeframe: DataFrame_con_datos_hasta_ahora}
        """
        if not self.feeds:
            return
        
        # Obtener el feed con menor cantidad de barras como referencia
        min_feed_name = min(self.feeds.keys(), key=lambda tf: len(self.feeds[tf]))
        ref_feed = self.feeds[min_feed_name]
        
        # Iterar sobre el feed de referencia
        for bar in ref_feed.iter_barras():
            current_time = bar["timestamp"]
            
            result = {}
            for tf, feed in self.feeds.items():
                # Actualizar cada feed hasta el tiempo actual
                while feed.has_more():
                    current_bar = feed.current_bar()
                    if current_bar and current_bar["timestamp"] <= current_time:
                        next(feed.iter_barras())  # Avanzar
                    else:
                        break
                
                # Retornar datos hasta ahora
                result[tf] = feed.get_bars(n=500)  # Últimas 500 velas
            
            yield result
    
    def reset(self):
        """Reinicia todos los feeds."""
        for feed in self.feeds.values():
            feed.reset()
    
    def tiene_datos(self, timeframe: str) -> bool:
        """Verifica si hay datos disponibles para un timeframe específico."""
        return timeframe in self.feeds and len(self.feeds[timeframe]) > 0


def load_csv_feed(
    path: str,
    timeframe: str = "M15",
    symbol: str = "EURUSD",
    tz: str = "UTC",
) -> CSVFeed:
    """
    Función helper para cargar un feed CSV rápidamente.
    
    Args:
        path: Ruta al archivo CSV
        timeframe: Timeframe
        symbol: Símbolo
        tz: Timezone string (ej: "UTC", "Europe/London")
    
    Returns:
        Instancia de CSVFeed configurada
    """
    from zoneinfo import ZoneInfo
    timezone_obj = ZoneInfo(tz) if tz != "UTC" else timezone.utc
    return CSVFeed(path=path, timeframe=timeframe, symbol=symbol, tz=timezone_obj)
