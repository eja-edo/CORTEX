# Run Service Guide

## Prerequisites

- Windows PowerShell
- Backend virtual environment at `backend/venv`
- Database credentials configured in `backend/.env`

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
