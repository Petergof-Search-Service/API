from collections import defaultdict

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        self._connections[user_id].discard(websocket)

    async def send(self, user_id: int, payload: dict) -> None:
        dead: set[WebSocket] = set()
        for ws in self._connections[user_id].copy():
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self._connections[user_id] -= dead


manager = ConnectionManager()
