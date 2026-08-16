from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_user_or_internal
from app.schemas import NextActionResponse
from app.services.next_action import NextActionService

router = APIRouter(prefix="/planning", tags=["planning"])


@router.get("/next-action", response_model=NextActionResponse)
async def get_next_action(
    current_user = Depends(get_current_user_or_internal),
    db: AsyncSession = Depends(get_async_db),
):
    """"What should I do next?" (Milestone 3.5).

    3.1's ranked `now_actions`/`suggestions` plus 6.8/4.4's `at_risk` list
    in one response — see `NextActionService`'s module docstring for why
    this doesn't duplicate the delivery `task.at_risk` already does through
    the Attention Gate.
    """
    service = NextActionService(db)
    return await service.get_next_action(current_user.id)
