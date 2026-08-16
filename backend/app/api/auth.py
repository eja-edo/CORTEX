from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import User, RefreshToken, AuthorizationCode, Workspace, WorkspaceMember, WorkspaceRole
from app.schemas import (
    UserCreate,
    UserResponse,
    Token,
    RefreshTokenRequest,
    MessageResponse,
    AuthorizeRequest,
    AuthorizeResponse,
    TokenExchangeRequest,
)
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_authorization_code,
    hash_authorization_code,
    verify_pkce,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _generate_token_pair(user: User, db: Session) -> Token:
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)

    access_token = create_access_token(subject=str(user.id), expires_delta=access_token_expires)
    refresh_token = create_refresh_token(subject=str(user.id), expires_delta=refresh_token_expires)

    refresh_payload = decode_token(refresh_token)
    if not refresh_payload:
        raise HTTPException(status_code=500, detail="Unable to generate refresh token")

    jti = refresh_payload.get("jti")
    exp = refresh_payload.get("exp")
    if not jti or not exp:
        raise HTTPException(status_code=500, detail="Invalid refresh token payload")

    refresh_token_row = RefreshToken(
        user_id=user.id,
        jti=UUID(jti),
        expires_at=datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None),
    )
    db.add(refresh_token_row)
    db.commit()

    return Token(access_token=access_token, refresh_token=refresh_token, token_type="bearer")


def _validate_refresh_token_or_401(refresh_token: str, db: Session) -> tuple[RefreshToken, User]:
    payload = decode_token(refresh_token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    sub = payload.get("sub")
    jti = payload.get("jti")
    if not sub or not jti:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token payload",
        )

    try:
        user_id = UUID(sub)
        token_jti = UUID(jti)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token",
        )

    token_row = db.query(RefreshToken).filter(RefreshToken.jti == token_jti).first()
    if not token_row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token not found")

    if token_row.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked")

    if token_row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is not active")

    return token_row, user


def _validate_redirect_uri_or_400(redirect_uri: str) -> None:
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid redirect_uri")


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register_user(user_input: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    existing_user = db.query(User).filter(User.email == user_input.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=user_input.email,
        full_name=user_input.full_name,
        hashed_password=get_password_hash(user_input.password),
        is_active=True,
    )
    db.add(user)
    db.flush()

    workspace = Workspace(
        owner_id=user.id,
        name=f"{user.email}'s Workspace",
        is_personal=True,
    )
    db.add(workspace)
    db.flush()

    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WorkspaceRole.OWNER,
    )
    db.add(member)

    db.commit()
    db.refresh(user)
    return user


@router.post("/authorize", response_model=AuthorizeResponse)
def authorize_with_pkce(payload: AuthorizeRequest, db: Session = Depends(get_db)):
    """Validate credentials and issue an authorization code bound to PKCE challenge."""
    _validate_redirect_uri_or_400(payload.redirect_uri)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    pkce_method = payload.code_challenge_method.upper()

    auth_code = generate_authorization_code()
    auth_code_row = AuthorizationCode(
        user_id=user.id,
        code_hash=hash_authorization_code(auth_code),
        client_id=payload.client_id,
        redirect_uri=payload.redirect_uri,
        code_challenge=payload.code_challenge,
        code_challenge_method=pkce_method,
        expires_at=datetime.utcnow() + timedelta(minutes=10),
    )

    db.add(auth_code_row)
    db.commit()

    return {
        "code": auth_code,
        "expires_in": 600,
        "state": payload.state,
    }


@router.post("/token", response_model=Token)
def exchange_code_for_token(payload: TokenExchangeRequest, db: Session = Depends(get_db)):
    """Exchange authorization code + code_verifier (PKCE) for access/refresh token pair."""
    _validate_redirect_uri_or_400(payload.redirect_uri)

    code_hash = hash_authorization_code(payload.code)
    auth_code_row = db.query(AuthorizationCode).filter(
        AuthorizationCode.code_hash == code_hash
    ).first()

    if not auth_code_row:
        raise HTTPException(status_code=401, detail="Invalid authorization code")

    if auth_code_row.used_at is not None:
        raise HTTPException(status_code=401, detail="Authorization code already used")

    if auth_code_row.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Authorization code expired")

    if auth_code_row.client_id != payload.client_id:
        raise HTTPException(status_code=401, detail="Client mismatch")

    if auth_code_row.redirect_uri != payload.redirect_uri:
        raise HTTPException(status_code=401, detail="Redirect URI mismatch")

    if not verify_pkce(
        code_verifier=payload.code_verifier,
        code_challenge=auth_code_row.code_challenge,
        method=auth_code_row.code_challenge_method,
    ):
        raise HTTPException(status_code=401, detail="Invalid PKCE verifier")

    user = db.query(User).filter(User.id == auth_code_row.user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User is not active")

    auth_code_row.used_at = datetime.utcnow()
    db.add(auth_code_row)
    db.commit()

    return _generate_token_pair(user, db)


@router.post("/refresh", response_model=Token)
def refresh_access_token(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Rotate refresh token and issue a new access/refresh token pair"""
    token_row, user = _validate_refresh_token_or_401(payload.refresh_token, db)

    token_row.revoked_at = datetime.utcnow()
    db.add(token_row)
    db.commit()

    return _generate_token_pair(user, db)


@router.post("/logout", response_model=MessageResponse)
def logout(payload: RefreshTokenRequest, db: Session = Depends(get_db)):
    """Logout by revoking the provided refresh token"""
    token_row, _ = _validate_refresh_token_or_401(payload.refresh_token, db)

    token_row.revoked_at = datetime.utcnow()
    db.add(token_row)
    db.commit()

    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_active_user)):
    """Get current authenticated user"""
    return current_user
