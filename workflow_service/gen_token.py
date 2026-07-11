import asyncio
import httpx
import time
import uuid
from jose import jwt
from app.config import settings

# Create new JWT token with long expiry
SECRET = settings.resolved_jwt_secret
USER_ID = "9cb9509c-49de-415b-a946-41f02cba0c2d"
WORKSPACE_ID = "ed991939-cf72-4fe9-9f24-2140333bf465"

payload = {
    "sub": USER_ID,
    "email": "duyanhsadg@gmail.com",
    "exp": int(time.time()) + 86400 * 30,  # 30 days
    "iat": int(time.time()),
    "type": "access",
    "jti": str(uuid.uuid4())
}
new_token = jwt.encode(payload, SECRET, algorithm="HS256")
print(f"New JWT: {new_token}")
