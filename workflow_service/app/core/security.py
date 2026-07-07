from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from app.config import settings
from dataclasses import dataclass

security = HTTPBearer()


@dataclass
class CurrentUser:
    user_id: str
    email: str


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CurrentUser:
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            settings.resolved_jwt_secret,
            algorithms=[settings.jwt_algorithm]
        )
        user_id: str = payload.get("sub")
        email: str = payload.get("email", "")

        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing user_id"
            )

        return CurrentUser(user_id=user_id, email=email)

    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}"
        )
