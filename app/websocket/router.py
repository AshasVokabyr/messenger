from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from app.auth.dependencies import get_current_user
from app.models.user import User
from app.websocket.manager import manager

router = APIRouter()


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, user: User = Depends(get_current_user)):
    await manager.connect(user.id, ws)
    try:
        while True:
            data = await ws.receive_json()
            await manager.send_to_user(user.id, {"echo": data})
    except WebSocketDisconnect:
        manager.disconnect(user.id, ws)
