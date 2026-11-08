"""
Loader de configuración de activos desde JSON.
Traduce archivos de configuración a dataclass ActivoInfo.
"""
import json
import logging
import os
from datetime import timezone
from typing import List, Optional
from kernel.contrato import ActivoInfo

logger = logging.getLogger(__name__)


def cargar_activo(simbolo: str, activos_dir: str = "activos") -> ActivoInfo:
    """
    Carga un ActivoInfo desde activos/{simbolo}.json.
    
    Args:
        simbolo: Símbolo del activo (ej. "EURUSD")
        activos_dir: Directorio donde están los JSON
        
    Returns:
        Instancia de ActivoInfo configurada
        
    Raises:
        ValueError: Si el archivo no existe o faltan campos requeridos
    """
    path = os.path.join(activos_dir, f"{simbolo.lower()}.json")
    
    if not os.path.exists(path):
        raise ValueError(f"No existe configuración para activo '{simbolo}' en {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Validar campo crítico 'point'
    punto = data.get("point")
    if punto is None:
        raise ValueError(f"Campo 'point' faltante en {path} - requerido para cálculo de pips")

    # Decisión de diseño explícita:
    # tick_size default = punto si no viene especificado
    # Esto asume que el mínimo movimiento cotizable es igual al punto base
    # En casos especiales (índices, crypto) puede diferir y debe especificarse en JSON
    tick_size = data.get("tick_size", punto)
    
    return ActivoInfo(
        simbolo=data.get("simbolo", simbolo.upper()),
        punto=punto,
        tick_size=tick_size,
        contract_size=data.get("contract_size", 100000),
        session_open=data.get("session_open", "00:00"),
        session_close=data.get("session_close", "23:59"),
        timezone=timezone.utc,  # Default UTC, se puede extender para TZ-aware
    )


def listar_activos_disponibles(activos_dir: str = "activos") -> List[str]:
    """
    Lista todos los activos disponibles en el directorio de configuración.
    
    Returns:
        Lista de símbolos en mayúsculas (sin extensión .json)
    """
    if not os.path.isdir(activos_dir):
        return []
    
    return [
        f.replace(".json", "").upper()
        for f in os.listdir(activos_dir)
        if f.endswith(".json") and not f.lower().endswith("_binary.json")
    ]


def validar_configuracion_activo(path: str) -> bool:
    """
    Valida que un archivo JSON de activo tenga la estructura correcta.
    Útil para validación pre-startup.
    
    Returns:
        True si es válido, False si hay errores (logueados internamente)
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        required_fields = ["simbolo", "point"]
        for field in required_fields:
            if field not in data:
                logger.error(f"Campo requerido '{field}' faltante en {path}")
                return False
        
        if not isinstance(data["point"], (int, float)) or data["point"] <= 0:
            logger.error(f"Campo 'point' debe ser numérico positivo en {path}")
            return False
            
        return True
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON inválido en {path}: {e}")
        return False
    except Exception as e:
        logger.error(f"Error leyendo {path}: {e}")
        return False
