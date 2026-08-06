import uuid
import time
from typing import AsyncGenerator

from jose import jwt
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.config import settings

JWT_SECRET = settings.resolved_jwt_secret
TEST_USER_ID = uuid.UUID("9cb9509c-49de-415b-a946-41f02cba0c2d")  # Real user from DB


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def jwt_token() -> str:
    payload = {
        "sub": str(TEST_USER_ID),
        "email": "test@test.com",
        "exp": 9999999999,
        "iat": int(time.time()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


@pytest.fixture
def auth_headers(jwt_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt_token}", "Content-Type": "application/json"}


@pytest.fixture
def valid_definition() -> dict:
    return {
        "nodes": [
            {"id": "t1", "type": "trigger.manual", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "a1", "type": "action.create_note", "position": {"x": 200, "y": 0}, "data": {}},
        ],
        "edges": [{"id": "e1", "source": "t1", "target": "a1"}],
        "variables": {},
    }
