from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.schemas import TodayResponse
from app.services.today import TodayService

router = APIRouter(prefix="/today", tags=["today"])


@router.get("", response_model=TodayResponse)
async def get_today(
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """The "Hôm nay" screen (Milestone 2.7).

    Serves decisions rather than numbers: each suggested action arrives with
    the sentence explaining what it costs to skip it.

    `state` says which of the three designs to render, including the two
    empty ones — the client never falls back to a blank table, and "hôm nay
    không có gì gấp" is a real answer, not an absence of one.
    """
    service = TodayService(db)
    return await service.get_today(current_user.id)
