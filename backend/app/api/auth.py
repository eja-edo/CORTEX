from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import User, RefreshToken
from app.schemas import (
    UserCreate,
    UserResponse,
    Token,
    RefreshTokenRequest,
    MessageResponse,
    LoginRequest,
)
from app.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
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

    # **Đăng ký không tạo container nào nữa.**
    #
    # Trước đây mỗi tài khoản mới đẻ một workspace "cá nhân". Kết quả đo
    # được ngày 2026-08-24: 95 tài khoản, 94 trong đó do integration test
    # sinh ra, mỗi cái kèm một workspace rỗng không ai mở. Đó chính là lỗi
    # P4 mà DESIGN 3.4 lấy làm ví dụ, và là lý do dự án cá nhân được **tạo
    # lười** — lần đầu người dùng thật sự cần một chỗ để đặt việc, không
    # phải lúc họ điền xong form đăng ký.
    #
    # `ProjectService.get_or_create_personal` lo phần còn lại, ở đúng thời
    # điểm có ngữ cảnh.
    db.commit()
    db.refresh(user)
    return user


@router.post("/login", response_model=Token)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    """Validate credentials and issue an access/refresh token pair."""
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

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
