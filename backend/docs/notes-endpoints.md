# Notes API Quick Reference

Base path: `/api/notes`

Authentication:
- All endpoints require `Authorization: Bearer <access_token>`.
- `user_id` is derived from the access token on the server side.

## 1) Create Note

- Method: `POST /api/notes`
- Purpose: Create a new note for the authenticated user.

Request body:
```json
{
  "content": "# Todo\n- Finish backend",
  "content_type": "markdown",
  "position": { "x": 0, "y": 0 },
  "size": { "width": 200, "height": 200 },
  "style": { "color": "yellow" }
}
```

Response: `201 Created`
- Returns full note object with `id`, `version`, `created_at`, `updated_at`.

## 2) Get Notes

- Method: `GET /api/notes?render_html=false`
- Purpose: List all non-deleted notes of the authenticated user.
- Ordering: `updated_at DESC`.

Query params:
- `render_html` (optional, default `false`): when `true`, response includes sanitized `rendered_html`.

Response: `200 OK`
- Returns array of note objects.

## 3) Update Note (Optimistic Concurrency)

- Method: `PATCH /api/notes/{note_id}`
- Purpose: Partial update only for fields provided by client.
- Requires `version` in request body.

Request body example:
```json
{
  "version": 3,
  "content": "Updated markdown",
  "position": { "x": 120 }
}
```

Behavior:
- Server checks current version.
- If matched: updates fields, increments version by 1.
- If mismatch: returns `409 Conflict`.

## 4) Soft Delete Note

- Method: `DELETE /api/notes/{note_id}`
- Purpose: Mark note as deleted (`is_deleted = true`).

Response:
- `204 No Content` on success.
- `404 Not Found` if note does not exist for current user.

## 5) Batch Update Notes

- Method: `PATCH /api/notes/batch`
- Purpose: Update multiple notes in one request with per-note version check.
- Runs in one transaction.

Request body example:
```json
[
  {
    "id": "8f8af4f0-56e8-4f60-b4a9-6f1e9a0cd001",
    "version": 2,
    "updates": {
      "position": { "x": 240, "y": 160 },
      "size": { "width": 260 }
    }
  },
  {
    "id": "6a6a7e6d-1802-4f0e-a9af-8c58df59c002",
    "version": 5,
    "updates": {
      "content": "New content"
    }
  }
]
```

Response: `200 OK`
```json
{
  "success": ["..."],
  "failed": ["..."]
}
```
- `failed` includes ids with version conflict or inaccessible notes.

## Notes

- Markdown is stored as RAW text (source of truth).
- HTML is optional derived output and sanitized before returning.
- `content` max length is validated by schema.
