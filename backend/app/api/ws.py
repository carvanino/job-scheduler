"""
WebSocket connection manager.
Broadcasts job status changes and stats updates to all connected UI clients.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from app.logger import get_logger

log = get_logger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        log.info("ws.connected", total=len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            try:
                self._connections.remove(ws)
            except ValueError:
                pass
        log.info("ws.disconnected", total=len(self._connections))

    async def broadcast(self, event_type: str, data: dict[str, Any]) -> None:
        message = json.dumps({"type": event_type, "data": data})
        dead: list[WebSocket] = []
        async with self._lock:
            connections = list(self._connections)
        for ws in connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


ws_manager = WebSocketManager()
