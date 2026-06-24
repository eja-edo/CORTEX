# PHASE 1 — FOUNDATION
## Temporal Setup + Database Schema + Service Skeleton

> **Thời gian**: Tuần 1–2 (10 ngày làm việc)  
> **Mục tiêu**: Có một `workflow_service` chạy được, Temporal kết nối được, schema DB sẵn sàng  
> **Output cuối phase**: `docker-compose up` khởi động được toàn bộ stack bao gồm Temporal

---

## 1. Tổng quan công việc Phase 1

```
Tuần 1                          Tuần 2
─────────────────────────────── ───────────────────────────────
Day 1-2: Docker + Temporal      Day 6-7: PostgreSQL migrations
Day 3-4: workflow_service init  Day 8-9: DB models + Alembic
Day 5:   Verify connectivity    Day 10: Smoke test toàn stack
```

---

## 2. Docker Compose — Thêm Temporal vào infrastructure

### 2.1 Các service cần thêm vào `docker-compose.yml`

Temporal yêu cầu **4 containers** tối thiểu:

```
temporal-postgresql   ← DB riêng cho Temporal (KHÔNG dùng chung DB của Cortex)
temporal              ← Temporal Server (gRPC port 7233)
temporal-ui           ← Web UI để xem workflow history (port 8080)
workflow_service      ← FastAPI service mới của chúng ta (port 8001)
```

### 2.2 Nội dung thêm vào `docker-compose.yml`

```yaml
# Thêm vào file docker-compose.yml hiện tại của Cortex

services:
  # --- TEMPORAL STACK ---
  temporal-postgresql:
    image: postgres:13
    container_name: temporal-postgresql
    environment:
      POSTGRES_USER: temporal
      POSTGRES_PASSWORD: temporal
      POSTGRES_DB: temporal
    volumes:
      - temporal-postgres-data:/var/lib/postgresql/data
    networks:
      - cortex-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U temporal"]
      interval: 5s
      timeout: 5s
      retries: 5

  temporal:
    image: temporalio/auto-setup:1.24
    container_name: temporal
    depends_on:
      temporal-postgresql:
        condition: service_healthy
    environment:
      - DB=postgresql
      - DB_PORT=5432
      - POSTGRES_USER=temporal
      - POSTGRES_PWD=temporal
      - POSTGRES_SEEDS=temporal-postgresql
      - DYNAMIC_CONFIG_FILE_PATH=config/dynamicconfig/development-sql.yaml
    ports:
      - "7233:7233"
    volumes:
      - ./infrastructure/temporal/dynamicconfig:/etc/temporal/config/dynamicconfig
    networks:
      - cortex-network

  temporal-ui:
    image: temporalio/ui:2.26
    container_name: temporal-ui
    depends_on:
      - temporal
    environment:
      - TEMPORAL_ADDRESS=temporal:7233
      - TEMPORAL_CORS_ORIGINS=http://localhost:3000
    ports:
      - "8080:8080"
    networks:
      - cortex-network

  # --- WORKFLOW SERVICE ---
  workflow_service:
    build:
      context: ./workflow_service
      dockerfile: Dockerfile
    container_name: workflow_service
    depends_on:
      - temporal
      - cortex-postgres   # tên service PostgreSQL hiện tại của Cortex
      - redis
    environment:
      - DATABASE_URL=postgresql+asyncpg://cortex:cortex@cortex-postgres:5432/cortex
      - TEMPORAL_HOST=temporal:7233
      - CORTEX_BACKEND_URL=http://backend:8000
      - CORTEX_INTERNAL_API_KEY=${INTERNAL_API_KEY}
      - REDIS_URL=redis://redis:6379
    ports:
      - "8001:8001"
    networks:
      - cortex-network

volumes:
  temporal-postgres-data:
```

> **Lưu ý**: `cortex-postgres`, `redis`, `cortex-network` phải khớp với tên đang dùng trong docker-compose.yml hiện tại. Kiểm tra file gốc trước khi copy.

### 2.3 Tạo file dynamic config cho Temporal

Tạo thư mục và file:

```
infrastructure/
└── temporal/
    └── dynamicconfig/
        └── development-sql.yaml
```

Nội dung `development-sql.yaml`:

```yaml
# File này cần thiết để Temporal server khởi động đúng
# Không cần chỉnh sửa gì thêm cho development
limit.maxIDLength:
  - value: 255
    constraints: {}
frontend.enableClientVersionCheck:
  - value: false
    constraints: {}
```

---

## 3. Khởi tạo `workflow_service` — Cấu trúc thư mục

Tạo thư mục mới ở root của project (cùng cấp với `backend/`, `frontend/`):

```
workflow_service/
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/           ← Chứa migration files
├── app/
│   ├── __init__.py
│   ├── main.py             ← FastAPI app entry point
│   ├── config.py           ← Settings (đọc từ env vars)
│   ├── database.py         ← Async SQLAlchemy engine + session
│   ├── models/             ← SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── workflow.py
│   │   └── execution.py
│   ├── schemas/            ← Pydantic schemas (request/response)
│   │   ├── __init__.py
│   │   ├── workflow.py
│   │   └── execution.py
│   ├── api/                ← FastAPI routers
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── workflows.py
│   │       └── executions.py
│   ├── temporal/           ← Temporal integration
│   │   ├── __init__.py
│   │   ├── client.py       ← Temporal client singleton
│   │   └── worker.py       ← Worker startup
│   └── core/
│       ├── __init__.py
│       └── security.py     ← Auth middleware (verify JWT từ Cortex)
└── tests/
    └── __init__.py
```

---

## 4. Nội dung các file skeleton

### 4.1 `requirements.txt`

```txt
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy[asyncio]==2.0.35
asyncpg==0.29.0
alembic==1.13.0
pydantic==2.9.0
pydantic-settings==2.5.0
temporalio==1.7.0
httpx==0.27.0
redis==5.1.0
python-jose[cryptography]==3.3.0
python-multipart==0.0.9
```

### 4.2 `app/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database (dùng chung PostgreSQL với Cortex, schema riêng)
    database_url: str = "postgresql+asyncpg://cortex:cortex@localhost:5432/cortex"
    
    # Temporal
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "cortex-workflow-queue"
    
    # Cortex backend (để gọi internal API)
    cortex_backend_url: str = "http://localhost:8000"
    cortex_internal_api_key: str = ""
    
    # Redis (dùng chung với Cortex)
    redis_url: str = "redis://localhost:6379"
    
    # Security
    jwt_secret_key: str = ""        # Phải giống hệt với Cortex backend
    jwt_algorithm: str = "HS256"
    
    # Service
    service_port: int = 8001
    debug: bool = False

    class Config:
        env_file = ".env"

settings = Settings()
```

### 4.3 `app/database.py`

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

class Base(DeclarativeBase):
    pass

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 4.4 `app/main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api.v1 import workflows, executions

app = FastAPI(
    title="Cortex Workflow Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Cortex frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["workflows"])
app.include_router(executions.router, prefix="/api/v1/executions", tags=["executions"])

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "workflow_service"}

@app.on_event("startup")
async def startup_event():
    # Sẽ thêm Temporal worker startup ở Phase 3
    pass
```

### 4.5 `Dockerfile`

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
```

---

## 5. Database Schema — PostgreSQL Migrations

Workflow Runtime sẽ dùng **schema riêng** `workflow` trong cùng PostgreSQL database của Cortex. Điều này giúp tránh xung đột với các table hiện tại.

### 5.1 Cấu hình Alembic để dùng schema riêng

Trong `alembic/env.py`, thêm:

```python
from app.models.workflow import *
from app.models.execution import *
from app.database import Base

# Toàn bộ models của workflow_service sẽ nằm trong schema "workflow"
```

### 5.2 SQLAlchemy Models

**`app/models/workflow.py`**

```python
from sqlalchemy import Column, String, Text, Boolean, Integer, DateTime, JSON, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum
from app.database import Base

class WorkflowStatus(enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"

class TriggerType(enum.Enum):
    INTERNAL_EVENT = "internal_event"   # Cortex internal events
    WEBHOOK = "webhook"                  # External HTTP webhook
    SCHEDULE = "schedule"               # Cron-based
    MANUAL = "manual"                   # User triggers manually

class WorkflowDefinition(Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)  # FK tới User của Cortex
    workspace_id = Column(UUID(as_uuid=True), nullable=True, index=True)  # Optional workspace scope
    
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    
    status = Column(Enum(WorkflowStatus), nullable=False, default=WorkflowStatus.DRAFT)
    version = Column(Integer, nullable=False, default=1)
    
    # Định nghĩa trigger
    trigger_type = Column(Enum(TriggerType), nullable=False)
    trigger_config = Column(JSON, nullable=False, default=dict)
    # Ví dụ trigger_config:
    # { "event": "note.created", "filters": { "workspace_id": "xxx" } }
    # { "cron": "0 9 * * MON", "timezone": "Asia/Ho_Chi_Minh" }
    # { "webhook_id": "uuid" }

    # Định nghĩa các steps (nodes + edges từ React Flow)
    definition = Column(JSON, nullable=False, default=dict)
    # Ví dụ definition:
    # { "nodes": [...], "edges": [...], "variables": {} }
    
    # Webhook secret (chỉ dùng khi trigger_type = WEBHOOK)
    webhook_secret = Column(String(255), nullable=True)
    
    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

class WorkflowTriggerWebhook(Base):
    """
    Bảng riêng để lưu thông tin webhook endpoint cho mỗi workflow.
    Mỗi workflow có trigger_type=WEBHOOK sẽ có 1 row ở đây.
    """
    __tablename__ = "workflow_trigger_webhooks"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=False)
    webhook_path = Column(String(255), nullable=False, unique=True)
    # URL sẽ là: POST /api/v1/webhooks/{webhook_path}
    secret_hash = Column(String(255), nullable=False)  # bcrypt hash của secret
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
```

**`app/models/execution.py`**

```python
from sqlalchemy import Column, String, Text, Integer, DateTime, JSON, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum
from app.database import Base

class ExecutionStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"      # Đang chờ (human approval, delay, etc.)
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

class WorkflowInstance(Base):
    """
    Mỗi lần workflow chạy tạo ra một instance.
    Temporal Run ID được lưu ở đây để có thể query history.
    """
    __tablename__ = "workflow_instances"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_definitions.id"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), nullable=False, index=True)
    
    status = Column(Enum(ExecutionStatus), nullable=False, default=ExecutionStatus.PENDING)
    
    # Temporal identifiers (để query Temporal history)
    temporal_workflow_id = Column(String(255), nullable=True)  # Format: cortex-wf-{instance_id}
    temporal_run_id = Column(String(255), nullable=True)
    
    # Trigger context — dữ liệu trigger gửi vào workflow
    trigger_data = Column(JSON, nullable=True)
    # Ví dụ: { "event": "note.created", "note_id": "xxx", "user_id": "yyy" }
    
    # Output cuối cùng của workflow
    output = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

class WorkflowStepExecution(Base):
    """
    Log thực thi của từng step trong một instance.
    """
    __tablename__ = "workflow_step_executions"
    __table_args__ = {"schema": "workflow"}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id = Column(UUID(as_uuid=True), ForeignKey("workflow.workflow_instances.id"), nullable=False, index=True)
    
    node_id = Column(String(255), nullable=False)    # ID của node trong React Flow definition
    node_type = Column(String(100), nullable=False)  # Ví dụ: "action.create_note", "action.send_notification"
    
    status = Column(Enum(ExecutionStatus), nullable=False)
    input_data = Column(JSON, nullable=True)    # Input vào step này
    output_data = Column(JSON, nullable=True)   # Output của step này
    error_message = Column(Text, nullable=True)
    
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

### 5.3 Tạo migration đầu tiên

```bash
# Chạy trong thư mục workflow_service/
cd workflow_service

# Khởi tạo schema "workflow" trong PostgreSQL trước
# (chạy SQL thủ công hoặc thêm vào migration)

# Tạo migration
alembic revision --autogenerate -m "create_workflow_tables"

# Apply migration
alembic upgrade head
```

Trong file migration được tạo ra, thêm ở đầu để tạo schema:

```python
def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS workflow")
    # ... rest of autogenerated code
```

---

## 6. Temporal Client Setup

**`app/temporal/client.py`**

```python
from temporalio.client import Client
from app.config import settings
import asyncio

_client: Client | None = None

async def get_temporal_client() -> Client:
    """
    Singleton Temporal client.
    Gọi hàm này ở bất cứ đâu cần tương tác với Temporal.
    """
    global _client
    if _client is None:
        _client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
    return _client

async def close_temporal_client():
    global _client
    if _client is not None:
        await _client.close()
        _client = None
```

---

## 7. Verification Checklist — Cuối Phase 1

Trước khi chuyển sang Phase 2, xác nhận tất cả các điểm sau:

### Infrastructure

- [ ] `docker-compose up` khởi động không có error
- [ ] Temporal UI accessible tại `http://localhost:8080`
- [ ] `workflow_service` health check trả về 200: `curl http://localhost:8001/health`
- [ ] `workflow_service` có thể connect đến Temporal: kiểm tra log không có connection error
- [ ] PostgreSQL có schema `workflow` với các tables: `workflow_definitions`, `workflow_instances`, `workflow_step_executions`, `workflow_trigger_webhooks`

### Code

- [ ] Alembic migration chạy thành công (`alembic upgrade head`)
- [ ] FastAPI docs accessible tại `http://localhost:8001/docs`
- [ ] Không có import error khi start service

### Connectivity

- [ ] `workflow_service` có thể gọi được `http://backend:8000/health` (Cortex backend)
- [ ] `workflow_service` có thể connect Redis
- [ ] Temporal server log không có error

---

## 8. Troubleshooting thường gặp

**Temporal không start được:**
- Kiểm tra `temporal-postgresql` đã healthy chưa trước khi `temporal` start
- Xem log: `docker logs temporal`

**Schema `workflow` không tạo được:**
- Đảm bảo PostgreSQL user có quyền CREATE SCHEMA
- Chạy thủ công: `psql -U cortex -d cortex -c "CREATE SCHEMA IF NOT EXISTS workflow;"`

**workflow_service không connect được Cortex PostgreSQL:**
- Kiểm tra tên service PostgreSQL trong docker-compose.yml của Cortex (có thể là `db`, `postgres`, hoặc khác)
- Đảm bảo `cortex-network` được khai báo đúng

**Temporal UI hiện "Unable to connect":**
- Temporal server cần ~30 giây để fully initialize
- Kiểm tra `TEMPORAL_ADDRESS` trong temporal-ui environment
