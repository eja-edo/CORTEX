# Database Migrations (Alembic)

This project now uses Alembic to manage schema changes.
Automatic schema creation at app startup has been removed.

## Files

- alembic.ini
- alembic/env.py
- alembic/versions/20260413_0001_initial_schema.py
- alembic/versions/20260413_0002_knowledge_phase1.py
- alembic/versions/20260413_0003_phase2_ingest_search.py

## Quick Start

Run from backend directory:

```powershell
Set-Location e:/Cortex/backend
```

### 1) Fresh database

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic upgrade head
```

### 2) Existing database already at latest schema

If your DB was previously created by SQLAlchemy `create_all` and already has all current tables:

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic stamp 20260413_0003
```

### 3) Existing database at old schema (before knowledge phase 1)

If DB has only old core tables and not phase-1 tables:

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic stamp 20260413_0001
e:/Cortex/backend/venv/Scripts/python.exe -m alembic upgrade head
```

### 4) Existing database already at phase 1

If the DB is already at `20260413_0002`, just run:

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic upgrade head
```

## Useful Commands

Show migration history:

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic history
```

Show current DB revision:

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic current
```

Generate new migration (for future changes):

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic revision -m "describe_change"
```

Autogenerate migration from model diff:

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic revision --autogenerate -m "describe_change"
```

## Deployment Rule

Before starting API service in each environment:

```powershell
e:/Cortex/backend/venv/Scripts/python.exe -m alembic upgrade head
```

This guarantees schema is upgraded once and avoids runtime table-create checks.
