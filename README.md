# Cortex Scheduling System - Backend

A FastAPI-based backend for managing student schedules with support for classroom schedules, deadlines, exams, and personal events.

For service startup instructions, see [RUN_SERVICE.md](RUN_SERVICE.md).

## Project Structure

```
cortex/
├── app/
│   ├── __init__.py              # FastAPI app initialization
│   ├── config.py                # Configuration settings
│   ├── database.py              # Database connection & session
│   ├── models.py                # SQLAlchemy ORM models
│   ├── schemas.py               # Pydantic validation schemas
│   └── api/
│       ├── __init__.py
│       └── schedules.py         # Schedule API endpoints
├── .env                         # Environment variables
├── requirements.txt             # Python dependencies
├── README.md                    # This file
└── run.py                       # Server startup script
```

## Database Design

### `schedules` Table Schema

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| id | UUID | Yes | Primary key - Schedule ID |
| user_id | Integer | Yes | User ID (for multi-user support) |
| title | String(255) | Yes | Schedule title (e.g., "Học môn Hệ thống thông tin") |
| type | Enum | Yes | Schedule type: CLASS, DEADLINE, EXAM, PERSONAL |
| start_time | DateTime | Yes | Start time |
| end_time | DateTime | Yes | End time |
| location | String(255) | No | Classroom or meeting link (Google Meet/Zoom) |
| description | Text(1000) | No | Additional notes |
| is_completed | Boolean | No | Completion status (for DEADLINE type) |
| created_at | DateTime | Yes | Creation timestamp |
| updated_at | DateTime | Yes | Last update timestamp |

## API Endpoints

### Create Schedule
```
POST /api/schedules
Content-Type: application/json

{
  "user_id": 1,
  "title": "Học môn Hệ thống thông tin",
  "type": "CLASS",
  "start_time": "2026-04-06T09:00:00",
  "end_time": "2026-04-06T11:00:00",
  "location": "Phòng 101",
  "description": "Lecture on Web Applications"
}

Response: 201 Created
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 1,
  "title": "Học môn Hệ thống thông tin",
  "type": "CLASS",
  "start_time": "2026-04-06T09:00:00",
  "end_time": "2026-04-06T11:00:00",
  "location": "Phòng 101",
  "description": "Lecture on Web Applications",
  "is_completed": false,
  "created_at": "2026-04-06T10:30:00",
  "updated_at": "2026-04-06T10:30:00"
}
```

### Get Schedules (with Date Range)
```
GET /api/schedules?start_date=2026-04-01T00:00:00&end_date=2026-04-30T23:59:59&user_id=1

Response: 200 OK
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "user_id": 1,
      "title": "Học môn Hệ thống thông tin",
      "type": "CLASS",
      "start_time": "2026-04-06T09:00:00",
      "end_time": "2026-04-06T11:00:00",
      "location": "Phòng 101",
      "description": "Lecture on Web Applications",
      "is_completed": false,
      "created_at": "2026-04-06T10:30:00",
      "updated_at": "2026-04-06T10:30:00"
    }
  ],
  "total": 1
}
```

### Get Specific Schedule
```
GET /api/schedules/{schedule_id}

Response: 200 OK
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  ...
}
```

### Update Schedule
```
PUT /api/schedules/{schedule_id}
Content-Type: application/json

{
  "title": "Updated Title",
  "is_completed": true
}

Response: 200 OK
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  ...
}
```

### Delete Schedule
```
DELETE /api/schedules/{schedule_id}

Response: 204 No Content
```

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Database

Edit `.env` file with your PostgreSQL credentials:

```
DATABASE_URL=postgresql://username:password@localhost:5432/cortex_db
```

Before running the app, create the PostgreSQL database:

```sql
CREATE DATABASE cortex_db;
```

### 3. Run the Server

```bash
python run.py
```

Or use Uvicorn directly:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

### 4. Access API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

## Schedule Types

| Type | Usage | Color Suggestion |
|------|-------|------------------|
| CLASS | Classroom/lecture schedule | Blue |
| DEADLINE | Assignment/project deadlines | Red |
| EXAM | Exam schedule | Orange |
| PERSONAL | Personal events | Green |

## Future Enhancements

- [ ] User authentication (JWT)
- [ ] Email notifications for deadlines
- [ ] Recurring schedules
- [ ] Calendar integration (Google Calendar, Outlook)
- [ ] Schedule templates
- [ ] Conflict detection
- [ ] Analytics and statistics
- [ ] Mobile app support

## Technology Stack

- **Framework**: FastAPI
- **Database**: PostgreSQL
- **ORM**: SQLAlchemy
- **Validation**: Pydantic
- **Web Server**: Uvicorn
