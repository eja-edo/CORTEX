# Run Service Guide

## Prerequisites

- Windows PowerShell
- Backend virtual environment at `backend/venv`
- Database credentials configured in `backend/.env`

## 0) Start Infrastructure (Postgres, MinIO, Redis, MongoDB)

From the repository root:

```powershell
Set-Location e:/Cortex/infrastructure
docker compose up -d db pgadmin minio-cortex minio-cortex-init redis mongo
```

If backend runs on host machine, use in `backend/.env`:

```env
REDIS_URL=redis://localhost:6379/0
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=cortex
```

If backend is containerized in the same Docker network, use:

```env
REDIS_URL=redis://redis:6379/0
MONGODB_URL=mongodb://mongo:27017
MONGODB_DB_NAME=cortex
```

## 1) Update Database Schema

From the repository root:

```powershell
Set-Location e:/Cortex/backend
e:/Cortex/backend/venv/Scripts/python.exe -m alembic upgrade head
```

## 2) Start the Backend Service

From the repository root:

```powershell
Set-Location e:/Cortex/backend
e:/Cortex/backend/venv/Scripts/python.exe -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## 3) Verify

- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Notes

- Run `alembic upgrade head` whenever schema changes are pulled.
- If the virtual environment does not exist yet, create it first and install `backend/requirements.txt`.
