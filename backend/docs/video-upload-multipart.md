# Secure Multipart Video Upload (MinIO)

This module implements direct-to-storage multipart upload where backend controls access but never proxies video bytes.

## Endpoints

- `POST /api/upload/init`
- `GET /api/upload/presigned?upload_id=<uuid>&part_number=<n>`
- `POST /api/upload/part/confirm`
- `POST /api/upload/complete`
- `GET /api/upload/{upload_id}`
- `POST /api/upload/cleanup-stale`

## Request/Response Examples

### 1) Init

Request:

```json
{
  "filename": "lecture-2026-04-08.webm",
  "content_type": "video/webm",
  "total_parts": 42,
  "total_size": 274877906
}
```

Response:

```json
{
  "upload_id": "6b1b5c2f-6e41-4f4f-9f98-6af7c6f070f8",
  "object_key": "videos/<user-id>/2026/04/08/<uuid>.webm",
  "total_parts": 42,
  "expires_in_seconds": 180
}
```

### 2) Get presigned URL for part

`GET /api/upload/presigned?upload_id=<uuid>&part_number=1`

Response:

```json
{
  "upload_id": "6b1b5c2f-6e41-4f4f-9f98-6af7c6f070f8",
  "part_number": 1,
  "url": "http://minio/...",
  "expires_in_seconds": 180
}
```

### 3) Confirm uploaded part metadata

Request:

```json
{
  "upload_id": "6b1b5c2f-6e41-4f4f-9f98-6af7c6f070f8",
  "part_number": 1,
  "etag": "\"3a0f7...\"",
  "size": 8388608
}
```

### 4) Complete

Request:

```json
{
  "upload_id": "6b1b5c2f-6e41-4f4f-9f98-6af7c6f070f8"
}
```

## Frontend Reference (MediaRecorder + chunk upload)

```javascript
const MIN_PART = 5 * 1024 * 1024;

async function uploadRecordedVideo(blob, token) {
  // Split blob into >=5MB chunks except the last chunk.
  const chunks = [];
  let offset = 0;
  while (offset < blob.size) {
    const end = Math.min(offset + MIN_PART, blob.size);
    chunks.push(blob.slice(offset, end, blob.type || "video/webm"));
    offset = end;
  }

  const initRes = await fetch("/api/upload/init", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      filename: `recording-${Date.now()}.webm`,
      content_type: blob.type || "video/webm",
      total_parts: chunks.length,
      total_size: blob.size,
    }),
  });
  if (!initRes.ok) throw new Error("init failed");
  const session = await initRes.json();

  // Parallel upload parts with bounded concurrency.
  const concurrency = 4;
  const workers = Array.from({ length: concurrency }, (_, idx) => idx);

  let nextPart = 0;
  const confirmPart = async (partNumber, etag, size) => {
    const res = await fetch("/api/upload/part/confirm", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        upload_id: session.upload_id,
        part_number: partNumber,
        etag,
        size,
      }),
    });
    if (!res.ok) throw new Error(`confirm failed: part ${partNumber}`);
  };

  await Promise.all(
    workers.map(async () => {
      while (nextPart < chunks.length) {
        const myIndex = nextPart++;
        const partNumber = myIndex + 1;
        const chunk = chunks[myIndex];

        const urlRes = await fetch(
          `/api/upload/presigned?upload_id=${session.upload_id}&part_number=${partNumber}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        if (!urlRes.ok) throw new Error(`presigned failed: part ${partNumber}`);

        const { url } = await urlRes.json();
        const putRes = await fetch(url, {
          method: "PUT",
          headers: { "Content-Type": "application/octet-stream" },
          body: chunk,
        });
        if (!putRes.ok) throw new Error(`upload failed: part ${partNumber}`);

        const etag = putRes.headers.get("ETag");
        if (!etag) throw new Error(`missing ETag: part ${partNumber}`);

        await confirmPart(partNumber, etag, chunk.size);
      }
    })
  );

  const completeRes = await fetch("/api/upload/complete", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ upload_id: session.upload_id }),
  });

  if (!completeRes.ok) throw new Error("complete failed");
  return completeRes.json();
}
```

## Important Notes

- Backend validates ownership for every upload endpoint.
- Presigned URLs are short-lived and re-requestable when expired.
- Duplicate part confirms are idempotent and overwrite metadata safely.
- Stale uploads are marked failed and aborted after timeout.
- For horizontal scaling, replace in-memory rate limiter with Redis.
