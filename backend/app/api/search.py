from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import User
from app.schemas import SearchResponse
from app.services.search import SearchService

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    types: str = Query(default="notes,segments", description="Comma-separated: notes,segments"),
    semantic: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    requested_types = [part.strip().lower() for part in types.split(",") if part.strip()]
    if not requested_types:
        requested_types = ["notes", "segments"]

    allowed = {"notes", "segments"}
    filtered_types = [item for item in requested_types if item in allowed]
    if not filtered_types:
        filtered_types = ["notes", "segments"]

    service = SearchService(db)
    items = service.search(
        user_id=current_user.id,
        query=q,
        types=filtered_types,
        limit=limit,
        semantic=semantic,
    )

    return SearchResponse(
        query=q,
        semantic=semantic,
        items=items,
        total=len(items),
    )
