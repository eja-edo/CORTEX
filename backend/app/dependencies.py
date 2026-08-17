from uuid import UUID
from typing import Union

from fastapi import Depends, HTTPException, status, Header, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security import oauth2_scheme, decode_token
from app.config import settings


class InternalUser:
    """Represents a user authenticated via internal API key."""
    def __init__(self, id: UUID, email: str | None = None):
        self.id = id
        self.email = email
        self.is_active = True


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if not payload:
        raise credentials_exception

    if payload.get("type") != "access":
        raise credentials_exception

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_exception

    try:
        parsed_user_id = UUID(user_id)
    except ValueError:
        raise credentials_exception

    user = db.query(User).filter(User.id == parsed_user_id).first()
    if not user:
        raise credentials_exception

    return user


def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


def get_current_user_or_internal(
    request: Request,
    x_internal_api_key: str | None = Header(None, alias="X-Internal-API-Key"),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
    db: Session = Depends(get_db),
) -> Union[User, InternalUser]:
    """
    Accept EITHER:
    1. Internal service auth: X-Internal-API-Key + X-User-ID
    2. JWT token auth
    
    This allows both internal services and user sessions to access the same endpoints.
    """
    # Try internal auth first
    if x_internal_api_key:
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
    
    # Fall back to JWT auth
    # Extract token from Authorization header manually
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (JWT token or internal API key)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if not payload:
        raise credentials_exception

    if payload.get("type") != "access":
        raise credentials_exception

    user_id = payload.get("sub")
    if not user_id:
        raise credentials_exception

    try:
        parsed_user_id = UUID(user_id)
    except ValueError:
        raise credentials_exception

    user = db.query(User).filter(User.id == parsed_user_id).first()
    if not user:
        raise credentials_exception
    
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return user


def require_internal_service(
    x_internal_api_key: str | None = Header(None, alias="X-Internal-API-Key"),
) -> bool:
    """Service-to-service auth with **no user identity attached**.

    Distinct from `get_current_user_or_internal`, which takes `X-User-ID`
    and acts as that person. Some internal endpoints must not work that
    way: channel redemption (M1) decides *which* account to link from the
    one-time code alone, so accepting a caller-supplied user id would let
    the key holder attach any chat account to anybody — exactly the attack
    the code exists to prevent.

    Use this wherever the endpoint derives the subject from its own
    payload rather than from the caller.
    """
    if not settings.INTERNAL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="INTERNAL_API_KEY not configured in backend",
        )
    if not x_internal_api_key or x_internal_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid internal API key")
    return True
