# Upload -> Asset Flow (Backend + Frontend)

Tai lieu nay mo ta luong hoat dong sau khi upload thanh cong, cach frontend cap nhat thong tin asset, va cac API asset can dung (`list`, `get`, `update`, `delete`).

## 1) Tong quan luong

1. Frontend upload multipart qua nhom API `/api/upload/*`.
2. Frontend goi `POST /api/upload/complete`.
3. Backend tu dong tao (hoac lay lai) `asset` tu `upload`.
4. Backend enqueue STT/OCR jobs (bat dong bo).
5. Backend tra response `UploadCompleteResponse` cho frontend voi `asset_id`.
6. Frontend dung `asset_id` de goi `GET /api/assets/{asset_id}` lay full asset detail.
7. Frontend cap nhat state/UI ngay lap tuc theo asset vua tao.

Luu y: API create asset (`POST /api/assets`) khong can dung trong flow nay vi asset da duoc tao tu dong khi complete upload.

---

## 2) Backend hien tai tra ve gi sau upload complete

Endpoint: `POST /api/upload/complete`

Schema response hien tai:

```json
{
  "upload_id": "uuid",
  "asset_id": "uuid",
  "object_key": "videos/...",
  "status": "completed"
}
```

Response nay da du de frontend lien ket den asset, nhung chua bao gom full asset object.

### Khuyen nghi frontend

Ngay sau khi nhan `asset_id`, frontend goi tiep:

- `GET /api/assets/{asset_id}`

De lay day du thong tin asset (`title`, `type`, `status`, `metadata`, `created_at`, ...), roi merge vao state.

---

## 3) Frontend update state de "co asset ngay"

### 3.1. Luong cap nhat de xuat

1. Upload complete -> nhan `asset_id`.
2. Set tam state recording:
   - `uploadState = "uploaded"`
   - `uploadedAssetId = asset_id`
3. Goi `GET /api/assets/{asset_id}`.
4. Neu thanh cong: cap nhat store asset list/detail ngay.
5. Neu loi: van giu `uploadedAssetId` de retry fetch sau.

### 3.2. Vi du pseudo code

```ts
const complete = await requestWithAuth<UploadCompleteResponse>("/upload/complete", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ upload_id: uploadId }),
});

updateRecording(recordingId, rec => ({
  ...rec,
  uploadState: "uploaded",
  uploadProgress: 100,
  uploadedObjectKey: complete.object_key,
  uploadedAssetId: complete.asset_id,
}));

try {
  const asset = await requestWithAuth<AssetResponse>(`/assets/${complete.asset_id}`);
  upsertAssetInStore(asset); // cap nhat UI list/detail ngay
} catch (e) {
  // co the retry nen khong can fail ca flow upload
}
```

---

## 4) Asset APIs can dung

Tat ca API ben duoi deu theo prefix: `/api/assets`.

## 4.1) List assets

- Method: `GET /api/assets`
- Query:
  - `status` (optional)
  - `limit` (default 50)
  - `offset` (default 0)
- Response: `list[AssetResponse]`

Vi du:

```http
GET /api/assets?status=completed&limit=20&offset=0
Authorization: Bearer <token>
```

## 4.2) Get asset detail

- Method: `GET /api/assets/{asset_id}`
- Response: `AssetResponse`

Dung endpoint nay ngay sau upload complete de lay full thong tin asset.

## 4.3) Update asset

- Method: `PATCH /api/assets/{asset_id}`
- Body (`AssetUpdate`):
  - `title` (optional)
  - `description` (optional)
  - `status` (optional)
  - `metadata` (optional, merge vao metadata hien co)
- Response: `AssetResponse`

Vi du:

```json
{
  "title": "Meeting 2026-04-18",
  "description": "Ban ghi man hinh",
  "metadata": {
    "lang": ["en", "vi"],
    "source": "upload"
  }
}
```

## 4.4) Delete asset (soft delete)

- Method: `DELETE /api/assets/{asset_id}`
- Response: `204 No Content`
- Hanh vi:
  - Dat `deleted_at`
  - Dat `status = ARCHIVED`

Frontend sau khi delete nen:
- Xoa item khoi local list, hoac
- Reload list tu `GET /api/assets`

---

## 5) Data contract cho frontend

## 5.1. UploadCompleteResponse

```ts
type UploadCompleteResponse = {
  upload_id: string;
  asset_id: string;
  object_key: string;
  status: "initiated" | "uploading" | "completed" | "failed";
};
```

## 5.2. AssetResponse (rut gon)

```ts
type AssetResponse = {
  id: string;
  user_id: string;
  workspace_id: string | null;
  type: string;
  status: string;
  title: string | null;
  description: string | null;
  source_upload_id: string | null;
  source_object_key: string;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};
```

---

## 6) Best practice de UI muot

1. Optimistic update recording ngay sau `/upload/complete`.
2. Fetch asset detail ngay sau do (khong chan render).
3. Co retry nhe cho `GET /assets/{id}` neu backend vua commit xong.
4. Dinh ky refresh list asset khi man hinh list dang mo.
5. Khi update/delete asset, cap nhat local state truoc, sau do sync backend.

---

## 7) Mapping voi code hien tai

- Upload complete backend: `backend/app/api/upload.py`
- Upload response schema: `backend/app/schemas.py` (`UploadCompleteResponse`)
- Asset APIs backend: `backend/app/api/assets.py`
- Frontend upload flow: `frontend/src/components/RecordPanel.tsx`
- Frontend local recording state: `frontend/src/components/recordingTypes.ts`

Tai lieu nay phu hop voi state code hien tai: asset duoc tao tu dong khi upload complete, frontend can dung `asset_id` de lay full asset object.
