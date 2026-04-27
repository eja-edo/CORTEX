# Workspace System - API Changes Documentation

## 📋 Overview

This document describes all API changes related to the new **Workspace System** feature. The workspace system allows users to organize notes and assets into separate workspaces with role-based access control.

**Key Changes:**
- All notes and assets now belong to a workspace
- New workspace management APIs (CRUD operations)
- Workspace member management APIs
- Updated note and asset APIs to support workspace_id
- Permission-based access control

---

## 🔑 Authentication

All endpoints require JWT token in Authorization header:
```
Authorization: Bearer <your_token>
```

---

## 🆕 NEW APIs: Workspace Management

### 1. List All Workspaces

Get all workspaces the current user is a member of.

**Endpoint:** `GET /api/workspaces`

**Response:** `200 OK`
```json
[
  {
    "id": "uuid-string",
    "owner_id": "uuid-string",
    "name": "My Personal Workspace",
    "is_personal": true,
    "my_role": "owner"
  },
  {
    "id": "uuid-string",
    "owner_id": "uuid-string",
    "name": "Team Project",
    "is_personal": false,
    "my_role": "editor"
  }
]
```

**Fields:**
- `id`: Workspace unique identifier
- `owner_id`: User ID of workspace owner
- `name`: Workspace name
- `is_personal`: `true` if this is auto-created personal workspace
- `my_role`: Current user's role - `"owner"`, `"editor"`, or `"viewer"`

---

### 2. Create Workspace

Create a new workspace. The creator automatically becomes the owner.

**Endpoint:** `POST /api/workspaces`

**Request Body:**
```json
{
  "name": "New Workspace"
}
```

**Validation:**
- `name`: Required, 1-255 characters

**Response:** `201 Created`
```json
{
  "id": "uuid-string",
  "owner_id": "uuid-string",
  "name": "New Workspace",
  "is_personal": false,
  "my_role": "owner"
}
```

**Error Responses:**
- `422` - Validation error (e.g., name too long)

---

### 3. Update Workspace

Update workspace name. **Only owner can update.**

**Endpoint:** `PATCH /api/workspaces/{workspace_id}`

**Request Body:**
```json
{
  "name": "Updated Workspace Name"
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid-string",
  "owner_id": "uuid-string",
  "name": "Updated Workspace Name",
  "is_personal": false,
  "my_role": "owner"
}
```

**Error Responses:**
- `403` - User is not the owner
- `404` - Workspace not found
- `422` - Validation error

---

### 4. Delete Workspace

Delete a workspace and all its notes/assets. **Only owner can delete.**

**Endpoint:** `DELETE /api/workspaces/{workspace_id}`

**Response:** `204 No Content`

**Error Responses:**
- `403` - User is not the owner
- `404` - Workspace not found

**⚠️ Warning:** This will delete all notes and assets in the workspace (CASCADE delete).

---

### 5. Add Member to Workspace

Add a user to workspace. **Only owner can add members.**

**Endpoint:** `POST /api/workspaces/{workspace_id}/members`

**Request Body:**
```json
{
  "user_id": "uuid-string",
  "role": "editor"
}
```

**Fields:**
- `user_id`: Required - User ID to add
- `role`: Required - Either `"editor"` or `"viewer"` (default: `"viewer"`)

**Response:** `201 Created`
```json
{
  "message": "Member added"
}
```

**Error Responses:**
- `400` - Invalid role
- `403` - User is not the owner
- `404` - Target user not found
- `409` - User already a member

---

### 6. Update Member Role

Change a member's role. **Only owner can update roles.**

**Endpoint:** `PATCH /api/workspaces/{workspace_id}/members/{user_id}`

**Request Body:**
```json
{
  "role": "viewer"
}
```

**Fields:**
- `role`: Required - Either `"editor"` or `"viewer"`

**Response:** `200 OK`
```json
{
  "message": "Role updated"
}
```

**Error Responses:**
- `400` - Cannot change owner role
- `403` - User is not the owner
- `404` - Member not found

---

### 7. Remove Member from Workspace

Remove a member from workspace. **Only owner can remove members. Cannot remove owner.**

**Endpoint:** `DELETE /api/workspaces/{workspace_id}/members/{user_id}`

**Response:** `204 No Content`

**Error Responses:**
- `400` - Cannot remove workspace owner
- `403` - User is not the owner
- `404` - Member not found

---

## 🔄 CHANGED APIs: Notes

### Important Changes

**BREAKING CHANGE:** All note operations now require `workspace_id`.

#### Note Schema Changes

**NoteCreate** (Request Body for creating notes):
```json
{
  "workspace_id": "uuid-string",  // ⭐ NEW: REQUIRED
  "content": "# Note content",
  "content_type": "markdown",
  "parent_note_id": "uuid-string or null",
  "position": {"x": 0, "y": 0},
  "size": {"width": 200, "height": 200},
  "style": {"color": "yellow"}
}
```

**NoteResponse** (Response from note endpoints):
```json
{
  "id": "uuid-string",
  "user_id": "uuid-string",
  "workspace_id": "uuid-string or null",  // ⭐ NEW FIELD
  "parent_note_id": "uuid-string or null",
  "content": "# Note content",
  "content_type": "markdown",
  "position": {"x": 0, "y": 0},
  "size": {"width": 200, "height": 200},
  "style": {"color": "yellow"},
  "version": 1,
  "is_deleted": false,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00",
  "rendered_html": "<h1>Note content</h1>"
}
```

---

### 1. Create Note (UPDATED)

**Endpoint:** `POST /api/notes`

**Request Body:** (workspace_id is now REQUIRED)
```json
{
  "workspace_id": "uuid-string",
  "content": "# My Note",
  "content_type": "markdown",
  "parent_note_id": null,
  "position": {"x": 0, "y": 0},
  "size": {"width": 200, "height": 200},
  "style": {"color": "yellow"}
}
```

**Response:** `201 Created`
```json
{
  "id": "uuid-string",
  "user_id": "uuid-string",
  "workspace_id": "uuid-string",
  "content": "# My Note",
  "content_type": "markdown",
  "position": {"x": 0, "y": 0},
  "size": {"width": 200, "height": 200},
  "style": {"color": "yellow"},
  "version": 1,
  "is_deleted": false,
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00",
  "rendered_html": "<h1>My Note</h1>"
}
```

**Error Responses:**
- `403` - User doesn't have editor access to workspace
- `404` - Workspace not found or user not a member
- `422` - Validation error (missing workspace_id, invalid content, etc.)

---

### 2. List User Notes (EXISTING - No Change)

**Endpoint:** `GET /api/notes`

Returns all notes across all workspaces for the current user.

**Response:** `200 OK`
```json
[
  {
    "id": "uuid-string",
    "workspace_id": "workspace-uuid-1",
    "content": "...",
    // ... other fields
  },
  {
    "id": "uuid-string",
    "workspace_id": "workspace-uuid-2",
    "content": "...",
    // ... other fields
  }
]
```

---

### 3. List Workspace Notes (⭐ NEW)

Get all notes in a specific workspace.

**Endpoint:** `GET /api/notes/workspaces/{workspace_id}`

**Response:** `200 OK`
```json
[
  {
    "id": "uuid-string",
    "user_id": "uuid-string",
    "workspace_id": "workspace-uuid",
    "content": "# Note 1",
    "content_type": "markdown",
    "position": {"x": 0, "y": 0},
    "size": {"width": 200, "height": 200},
    "style": {"color": "yellow"},
    "version": 1,
    "is_deleted": false,
    "created_at": "2024-01-01T00:00:00",
    "updated_at": "2024-01-01T00:00:00"
  }
]
```

**Error Responses:**
- `403` - User is not a member of this workspace

---

### 4. Update Note (EXISTING - No Change)

**Endpoint:** `PATCH /api/notes/{note_id}`

Uses version-based optimistic locking.

**Request Body:**
```json
{
  "version": 1,
  "content": "# Updated content"
}
```

**Response:** `200 OK` - Updated NoteResponse

**Error Responses:**
- `404` - Note not found
- `409` - Version conflict (note was updated by another request)

---

### 5. Delete Note (EXISTING - No Change)

**Endpoint:** `DELETE /api/notes/{note_id}`

Soft deletes the note and all its children.

**Response:** `200 OK`
```json
{
  "message": "Note deleted"
}
```

---

## 🔄 CHANGED APIs: Assets

### Important Changes

**BREAKING CHANGE:** All asset operations now support `workspace_id`.

#### Asset Schema Changes

**AssetCreate** (Request Body):
```json
{
  "workspace_id": "uuid-string",  // ⭐ NEW: REQUIRED
  "type": "video",
  "title": "My Asset",
  "description": "Optional description",
  "source_upload_id": "uuid-string or null",
  "source_object_key": "path/to/file.mp4"
}
```

**AssetResponse** (Response):
```json
{
  "id": "uuid-string",
  "user_id": "uuid-string",
  "workspace_id": "uuid-string or null",  // ⭐ NEW FIELD
  "type": "video",
  "status": "processing",
  "title": "My Asset",
  "description": null,
  "source_upload_id": "uuid-string",
  "source_object_key": "path/to/file.mp4",
  "duration_ms": 60000,
  "frame_rate": 30.0,
  "width": 1920,
  "height": 1080,
  "size_bytes": 1048576,
  "checksum_sha256": "hash...",
  "metadata": {},
  "created_at": "2024-01-01T00:00:00",
  "updated_at": "2024-01-01T00:00:00"
}
```

---

### 1. List Workspace Assets (⭐ NEW)

Get all assets in a specific workspace.

**Endpoint:** `GET /api/assets/workspaces/{workspace_id}`

**Response:** `200 OK`
```json
[
  {
    "id": "uuid-string",
    "workspace_id": "workspace-uuid",
    "type": "video",
    "title": "Meeting Recording",
    "status": "completed",
    // ... other asset fields
  }
]
```

**Error Responses:**
- `403` - User is not a member of this workspace

---

### 2. Upload Asset (UPDATED)

Upload init now accepts optional `workspace_id`.

**Endpoint:** `POST /api/uploads/init`

**Request Body:**
```json
{
  "filename": "video.mp4",
  "content_type": "video/mp4",
  "total_parts": 10,
  "total_size": 10485760,
  "workspace_id": "uuid-string"  // ⭐ NEW: Optional
}
```

If `workspace_id` is provided, the created asset will be associated with that workspace.

---

## 🔐 Permission System

### Workspace Roles

| Role | Can View | Can Edit | Can Delete | Can Manage Members |
|------|----------|----------|------------|-------------------|
| `owner` | ✅ | ✅ | ✅ | ✅ |
| `editor` | ✅ | ✅ | ❌ | ❌ |
| `viewer` | ✅ | ❌ | ❌ | ❌ |

### Permission Checks

**Creating Notes:**
- User must be a workspace member
- User must have `editor` or `owner` role
- Returns `403` if permission denied

**Creating Assets:**
- User must be a workspace member
- User must have `editor` or `owner` role
- Returns `403` if permission denied

**Viewing Notes/Assets:**
- User must be a workspace member (any role)
- Returns `403` if not a member

**Workspace Management:**
- Only `owner` can update/delete workspace
- Only `owner` can add/update/remove members

---

## 📦 Migration Guide for Frontend

### Step 1: Update Note Creation Flow

**Before:**
```typescript
// Old code
const note = await createNote({
  content: "# My Note",
  content_type: "markdown"
});
```

**After:**
```typescript
// New code - MUST specify workspace_id
const note = await createNote({
  workspace_id: currentWorkspaceId,  // ⭐ REQUIRED
  content: "# My Note",
  content_type: "markdown"
});
```

---

### Step 2: Update Asset Creation Flow

**Before:**
```typescript
// Old code
const asset = await createAsset({
  type: "video",
  source_object_key: "path/to/file.mp4"
});
```

**After:**
```typescript
// New code - MUST specify workspace_id
const asset = await createAsset({
  workspace_id: currentWorkspaceId,  // ⭐ REQUIRED
  type: "video",
  source_object_key: "path/to/file.mp4"
});
```

---

### Step 3: Add Workspace Selection UI

Users need to select a workspace before creating notes/assets.

**Recommended Flow:**
1. Fetch user's workspaces: `GET /api/workspaces`
2. Display workspace list/dropdown
3. Store selected `workspace_id` in app state
4. Use selected workspace_id when creating notes/assets

**Example:**
```typescript
// Fetch workspaces on app load
const workspaces = await fetchWorkspaces();

// Set default workspace (prefer personal workspace)
const defaultWorkspace = workspaces.find(ws => ws.is_personal) || workspaces[0];
setCurrentWorkspace(defaultWorkspace);

// Use when creating notes
const createNoteInCurrentWorkspace = async (content: string) => {
  return await createNote({
    workspace_id: currentWorkspace.id,
    content
  });
};
```

---

### Step 4: Update Note Listing

**Option A: Show all notes (existing behavior)**
```typescript
// Get all notes across all workspaces
const allNotes = await fetchNotes();
```

**Option B: Filter by workspace (new)**
```typescript
// Get notes in specific workspace
const workspaceNotes = await fetchWorkspaceNotes(workspaceId);
```

---

### Step 5: Handle Workspace Permissions

When creating notes/assets, handle permission errors:

```typescript
try {
  const note = await createNote({
    workspace_id: workspaceId,
    content
  });
} catch (error) {
  if (error.status === 403) {
    // User doesn't have permission to create notes in this workspace
    showError("You don't have permission to create notes in this workspace");
  } else if (error.status === 404) {
    // Workspace not found or user not a member
    showError("Workspace not accessible");
  }
}
```

---

## 🗄️ Database Migration (Completed)

✅ All existing users have personal workspaces created  
✅ All existing notes assigned to user's personal workspace  
✅ All existing assets assigned to user's personal workspace  
✅ `workspace_id` is now NOT NULL on notes and assets tables  

**No action needed** - migration already completed on backend.

---

## 🧪 Testing Your Integration

### Test Checklist:

1. ✅ Fetch user's workspaces
2. ✅ Create a new workspace
3. ✅ Select a workspace
4. ✅ Create a note in selected workspace
5. ✅ List notes in workspace
6. ✅ List all user notes
7. ✅ Create an asset in workspace
8. ✅ List assets in workspace
9. ✅ Handle permission errors (403)
10. ✅ Update workspace name (owner only)
11. ✅ Delete workspace (owner only)

---

## 📚 API Base URLs

| Environment | Base URL |
|-------------|----------|
| Development | `http://localhost:8000/api` |
| Staging | (TBD) |
| Production | (TBD) |

---

## 🆘 Support

For questions or issues:
- Check backend logs for detailed error messages
- Review this documentation for expected request/response formats
- Test endpoints using tools like Postman or curl

---

## 📝 Summary of Changes

| Endpoint | Method | Change |
|----------|--------|--------|
| `/api/workspaces` | GET | ⭐ NEW - List workspaces |
| `/api/workspaces` | POST | ⭐ NEW - Create workspace |
| `/api/workspaces/{id}` | PATCH | ⭐ NEW - Update workspace |
| `/api/workspaces/{id}` | DELETE | ⭐ NEW - Delete workspace |
| `/api/workspaces/{id}/members` | POST | ⭐ NEW - Add member |
| `/api/workspaces/{id}/members/{uid}` | PATCH | ⭐ NEW - Update member role |
| `/api/workspaces/{id}/members/{uid}` | DELETE | ⭐ NEW - Remove member |
| `/api/notes` | POST | 🔄 CHANGED - workspace_id now required |
| `/api/notes` | GET | ✅ No change - returns all notes |
| `/api/notes/workspaces/{id}` | GET | ⭐ NEW - List workspace notes |
| `/api/assets/workspaces/{id}` | GET | ⭐ NEW - List workspace assets |
| `/api/uploads/init` | POST | 🔄 CHANGED - workspace_id optional |

---

**Last Updated:** 2026-04-27  
**Version:** 1.0  
**Status:** ✅ Production Ready
