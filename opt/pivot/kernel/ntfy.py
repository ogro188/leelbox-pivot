# -*- coding: utf-8 -*-
"""Utilidades ntfy: config por activo, envío de mensajes y prueba de conexión."""
import json
import logging
import os
import requests
from datetime import datetime
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

DEFAULT_SERVER = "https://ntfy.sh"


def alertas_live_habilitadas() -> bool:
    """True solo si las alertas de mercado en vivo están habilitadas explícitamente.

    Default OFF: el sistema puede estar en prueba/replay sin spamear ntfy.
    Habilitar con PIVOT_ALERTAS_LIVE=1 (o true/yes/on).
    """
    raw = (os.getenv("PIVOT_ALERTAS_LIVE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def cargar_config_activo(simbolo: str) -> Dict[str, str]:
    """Config ntfy del activo: prioriza activos/{simbolo}.json -> data/ntfy_config.json."""
    ntfy: Dict[str, str] = {}
    path_json = f"activos/{simbolo.lower()}.json"
    if os.path.exists(path_json):
        try:
            with open(path_json, "r", encoding="utf-8") as f:
                data = json.load(f)
            ntfy = data.get("ntfy") or {}
        except Exception as e:
            logger.error(f"Error leyendo config ntfy de {path_json}: {e}")
            ntfy = {}
    if not ntfy.get("topic"):
        try:
            with open("data/ntfy_config.json", "r", encoding="utf-8") as f:
                g = json.load(f)
            ntfy = {"topic": g.get("topic", ""), "server": g.get("server", DEFAULT_SERVER)}
        except FileNotFoundError:
            ntfy = {}
        except Exception as e:
            logger.error(f"Error leyendo data/ntfy_config.json: {e}")
            ntfy = {}
    if not ntfy.get("server"):
        ntfy["server"] = DEFAULT_SERVER
    return ntfy


def guardar_config_activo(simbolo: str, topic: str, server: str) -> None:
    """Persiste la config ntfy del activo en activos/{simbolo}.json."""
    path_json = f"activos/{simbolo.lower()}.json"
    data: Dict = {}
    if os.path.exists(path_json):
        try:
            with open(path_json, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"JSON corrupto en {path_json}, se reescribe solo con ntfy: {e}")
            data = {}
    data["ntfy"] = {"topic": topic, "server": server or DEFAULT_SERVER}
    with open(path_json, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def enviar(
    simbolo: str,
    text: str,
    config: Dict[str, str] | None = None,
    *,
    forzar: bool = False,
    titulo: str = "",
    prioridad: str = "default",
    tags: str = "bell",
) -> Tuple[bool, str]:
    """Envía un mensaje ntfy para el activo. Devuelve (ok, detalle).

    forzar=True salta el gate de alertas live (solo para el endpoint de test
    de conectividad). El replay/backtest nunca debe pasar forzar=True.
    """
    if not forzar and not alertas_live_habilitadas():
        return False, "Alertas live deshabilitadas (PIVOT_ALERTAS_LIVE)"
    cfg = config or cargar_config_activo(simbolo)
    topic = cfg.get("topic", "")
    if not topic:
        return False, "Sin topic ntfy configurado"
    server = cfg.get("server", DEFAULT_SERVER).rstrip("/")
    url = f"{server}/{topic}"
    monitor = os.environ.get("LEELBOX_MONITOR_URL",
                             "http://10.0.0.34:8080").rstrip("/")
    from urllib.parse import quote
    headers = {
        "Title": quote(titulo or "%s - PIVOT" % simbolo, safe=" ·"),
        "Priority": prioridad,
        "Tags": quote(tags, safe=","),
        "Click": monitor,
        "Actions": "action=view, Abrir monitor, %s" % monitor,
        "Markdown": "yes",
        "Content-Type": "text/markdown; charset=utf-8",
    }
    try:
        # Autenticacion: config (user/password) o entorno (NTFY_USER/NTFY_PASS,
        # cargado desde /etc/pivot-ntfy.env). Sin credenciales el ntfy responde 403.
        auth = None
        u = cfg.get("user") or os.getenv("NTFY_USER")
        p = cfg.get("password") or os.getenv("NTFY_PASS")
        if u and p:
            auth = (u, p)
        resp = requests.post(url, data=(text or "").encode("utf-8"),
                             headers=headers, timeout=5, auth=auth)
        if resp.status_code in (200, 201):
            return True, f"OK (HTTP {resp.status_code})"
        return False, f"HTTP {resp.status_code}"
    except Exception as e:
        return False, str(e)


def mensaje_prueba(simbolo: str) -> str:
    return (
        "### 🛠️ Conexión de prueba\n"
        f"**Activo:** {simbolo}\n"
        f"**Hora:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "\nSi lees esto, las alertas del trading te van a llegar bien."
    )
