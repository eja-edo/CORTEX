"""
Internal authentication dependencies for service-to-service communication.

These endpoints are NOT exposed in Swagger docs (include_in_schema=False).
"""

from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models import User


class InternalUser:
    """Represents a user identified by X-User-ID in an internal request."""
    def __init__(self, id: UUID, email: str | None = None):
        self.id = id
        self.email = email


def verify_internal_key(x_internal_api_key: str = Header(..., alias="X-Internal-API-Key")):
    """Verify that the request comes from an authorized internal service."""
    if not settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="INTERNAL_API_KEY not configured in backend",
        )

    if x_internal_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid internal API key",
        )


def get_internal_user(
    _: None = Depends(verify_internal_key),
    x_user_id: str = Header(..., alias="X-User-ID"),
    db: Session = Depends(get_db),
) -> InternalUser:
    """Extract and validate the user from X-User-ID header."""
    try:
        user_uuid = UUID(x_user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-User-ID format")

    user = db.query(User).filter(User.id == user_uuid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return InternalUser(id=user.id, email=user.email)
