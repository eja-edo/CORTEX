"""
Internal authentication dependencies for service-to-service communication.

These endpoints are NOT exposed in Swagger docs (include_in_schema=False).
"""

from uuid import UUID
from typing import Union

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User


class InternalUser:
    """Represents a user identified by X-User-ID in an internal request."""
    def __init__(self, id: UUID, email: str | None = None):
        self.id = id
        self.email = email
        self.is_active = True  # Internal users are always active


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


def get_user_or_internal(
    x_internal_api_key: str | None = Header(None, alias="X-Internal-API-Key"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    db: Session = Depends(get_db),
) -> Union[User, InternalUser, None]:
    """
    Try internal auth first (X-Internal-API-Key + X-User-ID).
    Returns InternalUser if successful, None otherwise (caller should try JWT).
    """
    # Check if internal API key is provided
    if x_internal_api_key:
        # Verify internal key
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
        
        # Internal API key is valid, now get user from X-User-ID
        if not x_user_id:
            raise HTTPException(
                status_code=400,
                detail="X-User-ID header required with internal API key",
            )
        
        try:
            user_uuid = UUID(x_user_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid X-User-ID format")
        
        user = db.query(User).filter(User.id == user_uuid).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        return InternalUser(id=user.id, email=user.email)
    
    # No internal auth provided
    return None


def get_current_user_or_internal(
    internal_user: Union[InternalUser, None] = Depends(get_user_or_internal),
    db: Session = Depends(get_db),
) -> Union[User, InternalUser]:
    """
    Accept EITHER internal auth OR JWT auth.
    Returns User or InternalUser.
    Must be used with additional JWT dependency injection.
    """
    if internal_user:
        return internal_user
    
    # If no internal user, fall through to JWT auth
    # This will be handled by combining with get_current_active_user
    from app.dependencies import get_current_active_user as jwt_auth
    # Can't call jwt_auth directly here, so we raise 401
    raise HTTPException(
        status_code=401,
        detail="Authentication required (JWT or internal API key)",
    )
