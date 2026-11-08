"""
Servidor WebSocket para comunicación en tiempo real con el frontend
"""
import asyncio
import json
import logging
from typing import Dict, List, Any, Optional
from fastapi import WebSocket, WebSocketDisconnect
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class ConnectionManager:
    """Gestiona conexiones WebSocket múltiples"""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.subscriptions: Dict[str, List[WebSocket]] = {}  # asset -> connections
        
    async def connect(self, websocket: WebSocket) -> bool:
        """Acepta conexión WebSocket"""
        try:
            await websocket.accept()
            self.active_connections.append(websocket)
            logger.info(f"Cliente WebSocket conectado. Total: {len(self.active_connections)}")
            return True
        except Exception as e:
            logger.error(f"Error al aceptar conexión: {e}")
            return False
    
    def disconnect(self, websocket: WebSocket):
        """Elimina conexión cerrada"""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        # Limpiar suscripciones
        for asset in list(self.subscriptions.keys()):
            if websocket in self.subscriptions[asset]:
                self.subscriptions[asset].remove(websocket)
            if not self.subscriptions[asset]:
                del self.subscriptions[asset]
        logger.info(f"Cliente WebSocket desconectado. Total: {len(self.active_connections)}")
    
    def subscribe(self, asset: str, websocket: WebSocket):
        """Suscribe conexión a un activo específico"""
        if asset not in self.subscriptions:
            self.subscriptions[asset] = []
        if websocket not in self.subscriptions[asset]:
            self.subscriptions[asset].append(websocket)
        logger.debug(f"Cliente suscrito a {asset}. Suscriptores: {len(self.subscriptions[asset])}")
    
    def unsubscribe(self, asset: str, websocket: WebSocket):
        """Desuscribe conexión de un activo"""
        if asset in self.subscriptions and websocket in self.subscriptions[asset]:
            self.subscriptions[asset].remove(websocket)
            if not self.subscriptions[asset]:
                del self.subscriptions[asset]
    
    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """Envía mensaje a un cliente específico"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Error enviando mensaje: {e}")
            self.disconnect(websocket)
    
    async def broadcast(self, message: dict):
        """Envía mensaje a todos los clientes conectados"""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")
                disconnected.append(connection)
        
        # Limpiar conexiones desconectadas
        for conn in disconnected:
            self.disconnect(conn)
    
    async def broadcast_to_asset(self, asset: str, message: dict):
        """Envía mensaje solo a suscriptores de un activo"""
        if asset not in self.subscriptions:
            return
        
        disconnected = []
        for connection in self.subscriptions[asset]:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error enviando a suscriptores de {asset}: {e}")
                disconnected.append(connection)
        
        # Limpiar conexiones desconectadas
        for conn in disconnected:
            self.disconnect(conn)
            if conn in self.active_connections:
                self.active_connections.remove(conn)
    
    async def send_signal(self, signal: dict):
        """Envía señal de trading a todos los clientes"""
        message = {
            "type": "signal",
            "data": signal,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.broadcast(message)
        logger.info(f"Señal broadcast: {signal.get('tipo', 'UNKNOWN')} en {signal.get('simbolo', 'N/A')}")
    
    async def send_tick(self, asset: str, price: float, bid: float = None, ask: float = None):
        """Envía tick de precio actualizado"""
        message = {
            "type": "tick",
            "asset": asset,
            "price": price,
            "bid": bid or price,
            "ask": ask or price,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.broadcast_to_asset(asset, message)
    
    async def send_console_log(self, log_entry: dict):
        """Envía log de consola a todos los clientes"""
        message = {
            "type": "consola",
            "data": log_entry,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        await self.broadcast(message)

# Instancia global del manager
manager = ConnectionManager()

async def websocket_endpoint(websocket: WebSocket, asset: Optional[str] = None):
    """Endpoint WebSocket principal"""
    if await manager.connect(websocket):
        if asset:
            manager.subscribe(asset, websocket)
            await websocket.send_json({
                "type": "connected",
                "asset": asset,
                "message": f"Suscrito a {asset}"
            })
        else:
            await websocket.send_json({
                "type": "connected",
                "message": "Conectado al servidor PIVOT"
            })
        
        try:
            while True:
                # Escuchar mensajes del cliente (suscripciones, comandos)
                data = await websocket.receive_text()
                try:
                    message = json.loads(data)
                    msg_type = message.get("type")
                    
                    if msg_type == "subscribe":
                        asset_name = message.get("asset")
                        if asset_name:
                            manager.subscribe(asset_name, websocket)
                            await websocket.send_json({
                                "type": "subscribed",
                                "asset": asset_name
                            })
                    
                    elif msg_type == "unsubscribe":
                        asset_name = message.get("asset")
                        if asset_name:
                            manager.unsubscribe(asset_name, websocket)
                    
                    elif msg_type == "ping":
                        await websocket.send_json({"type": "pong"})
                        
                except json.JSONDecodeError:
                    logger.warning(f"Mensaje JSON inválido: {data}")
                    
        except WebSocketDisconnect:
            manager.disconnect(websocket)
            logger.info("Cliente WebSocket desconectado")
        except Exception as e:
            logger.error(f"Error en WebSocket: {e}")
            manager.disconnect(websocket)
