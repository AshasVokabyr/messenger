import uuid

from fastapi import Depends, WebSocket
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.utils import decode_access_token
from app.db import get_db
from app.models.user import User


async def get_ws_current_user(
    ws: WebSocket,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    token = ws.query_params.get("token")
    if not token:
        await ws.close(code=1008)
        return None
    payload = decode_access_token(token)
    if payload is None:
        await ws.close(code=1008)
        return None
    user_id_str = payload.get("sub")
    if user_id_str is None:
        await ws.close(code=1008)
        return None
    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError:
        await ws.close(code=1008)
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        await ws.close(code=1008)
        return None
    return user
