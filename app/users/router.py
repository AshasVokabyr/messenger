from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.user import User
from app.users.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/by-login/{login}", response_model=UserResponse)
async def get_user_by_login(login: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.login == login))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse(id=user.id, login=user.login)


@router.get("/search", response_model=list[UserResponse])
async def search_users(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    safe_q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    result = await db.execute(
        select(User)
        .where(User.login.ilike(f"%{safe_q}%", escape="\\"))
        .order_by(User.login)
        .limit(limit)
    )
    users = result.scalars().all()
    return [UserResponse(id=u.id, login=u.login) for u in users]
