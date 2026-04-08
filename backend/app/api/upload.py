from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import Upload, UploadPart, UploadStatus, User
from app.schemas import (
    UploadAccessUrlResponse,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadListItemResponse,
    UploadListResponse,
    UploadPartConfirmRequest,
    UploadPartConfirmResponse,
    UploadPresignedResponse,
    UploadSessionResponse,
)
from app.services.multipart_upload import MinIOMultipartService, MultipartStorageError
from app.utils.logger import get_logger
from app.utils.rate_limit import InMemorySlidingWindowRateLimiter

router = APIRouter(prefix="/upload", tags=["upload"])
logger = get_logger(__name__)

rate_limiter = InMemorySlidingWindowRateLimiter(
    limit=settings.UPLOAD_RATE_LIMIT_PER_MINUTE,
    window_seconds=60,
)
storage = MinIOMultipartService()


def _enforce_rate_limit(user_id: UUID, route_key: str) -> None:
    allowed, retry_after = rate_limiter.allow(user_id=user_id, route_key=route_key)
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many upload requests. Please retry later.",
            headers={"Retry-After": str(retry_after)},
        )


def _get_upload_or_404(db: Session, upload_id: UUID, user_id: UUID) -> Upload:
    upload = db.query(Upload).filter(Upload.id == upload_id, Upload.user_id == user_id).first()
    if not upload:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload session not found")
    return upload


def _normalize_etag(etag: str) -> str:
    trimmed = etag.strip()
    return trimmed.strip('"')


def _build_completion_parts(parts: list[UploadPart]) -> list[dict]:
    completed: list[dict] = []
    for part in parts:
        etag = part.etag
        if not etag.startswith('"'):
            etag = f'"{etag}'
        if not etag.endswith('"'):
            etag = f"{etag}\""
        completed.append({"PartNumber": part.part_number, "ETag": etag})
    return completed


def _detect_media_type(upload: Upload) -> str:
    content_type = (upload.content_type or "").lower()
    if content_type.startswith("video/"):
        return "video"
    if content_type.startswith("audio/"):
        return "audio"

    filename = (upload.filename or "").lower()
    if filename.endswith((".mp4", ".mov", ".mkv", ".webm", ".avi")):
        return "video"
    if filename.endswith((".mp3", ".wav", ".ogg", ".m4a", ".aac", ".webm")):
        return "audio"

    return "unknown"


def _cleanup_stale_uploads(db: Session, user_id: UUID) -> int:
    cutoff = datetime.utcnow() - timedelta(hours=settings.UPLOAD_STALE_AFTER_HOURS)
    stale_uploads = (
        db.query(Upload)
        .filter(
            Upload.user_id == user_id,
            Upload.status.in_([UploadStatus.INITIATED, UploadStatus.UPLOADING]),
            Upload.updated_at < cutoff,
        )
        .all()
    )

    for upload in stale_uploads:
        storage.abort_multipart_upload(object_key=upload.object_key, upload_id=upload.upload_id)
        upload.status = UploadStatus.FAILED

    if stale_uploads:
        db.commit()

    return len(stale_uploads)


@router.post("/init", response_model=UploadInitResponse, status_code=status.HTTP_201_CREATED)
def init_upload(
    payload: UploadInitRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(current_user.id, "init")
    _cleanup_stale_uploads(db, current_user.id)

    if payload.total_parts > settings.MULTIPART_MAX_PARTS:
        raise HTTPException(status_code=400, detail="total_parts exceeds allowed multipart limit")

    if payload.total_size > settings.UPLOAD_MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds upload size limit")

    if (payload.total_parts == 0 and payload.total_size > 0) or (payload.total_parts > 0 and payload.total_size == 0):
        raise HTTPException(
            status_code=400,
            detail="total_parts and total_size must both be provided or both be 0 for live mode",
        )

    if payload.total_parts > 0 and payload.total_size > 0:
        max_parts_for_size = ceil(payload.total_size / settings.MULTIPART_MIN_PART_SIZE_BYTES)
        if payload.total_parts > max_parts_for_size:
            raise HTTPException(
                status_code=400,
                detail="total_parts is inconsistent with minimum part size constraints",
            )

    object_key = storage.build_object_key(user_id=current_user.id, filename=payload.filename)

    try:
        multipart_upload_id = storage.create_multipart_upload(
            object_key=object_key,
            content_type=payload.content_type,
        )
    except MultipartStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    upload = Upload(
        user_id=current_user.id,
        status=UploadStatus.INITIATED,
        object_key=object_key,
        upload_id=multipart_upload_id,
        total_parts=payload.total_parts,
        total_size=payload.total_size,
        filename=payload.filename,
        content_type=payload.content_type,
    )

    db.add(upload)
    db.commit()
    db.refresh(upload)

    return UploadInitResponse(
        upload_id=upload.id,
        object_key=upload.object_key,
        total_parts=upload.total_parts,
        expires_in_seconds=settings.PRESIGNED_URL_EXPIRE_SECONDS,
    )


@router.get("/presigned", response_model=UploadPresignedResponse)
def get_presigned_url(
    upload_id: UUID = Query(...),
    part_number: int = Query(..., ge=1),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(current_user.id, "presigned")

    upload = _get_upload_or_404(db, upload_id, current_user.id)

    if upload.status == UploadStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Upload session is already completed")

    if upload.status == UploadStatus.FAILED:
        raise HTTPException(status_code=409, detail="Upload session has failed")

    if part_number < 1:
        raise HTTPException(status_code=400, detail="part_number is out of range")

    if upload.total_parts > 0 and part_number > upload.total_parts:
        raise HTTPException(status_code=400, detail="part_number is out of range")

    if upload.total_parts == 0 and part_number > settings.MULTIPART_MAX_PARTS:
        raise HTTPException(status_code=400, detail="part_number exceeds allowed multipart limit")

    try:
        url = storage.presign_upload_part(
            object_key=upload.object_key,
            upload_id=upload.upload_id,
            part_number=part_number,
            expires_seconds=max(60, min(settings.PRESIGNED_URL_EXPIRE_SECONDS, 300)),
        )
    except MultipartStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if upload.status == UploadStatus.INITIATED:
        upload.status = UploadStatus.UPLOADING
        db.commit()

    return UploadPresignedResponse(
        upload_id=upload.id,
        part_number=part_number,
        url=url,
        expires_in_seconds=max(60, min(settings.PRESIGNED_URL_EXPIRE_SECONDS, 300)),
    )


@router.post("/part/confirm", response_model=UploadPartConfirmResponse)
def confirm_upload_part(
    payload: UploadPartConfirmRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(current_user.id, "confirm")

    upload = _get_upload_or_404(db, payload.upload_id, current_user.id)

    if upload.status in [UploadStatus.COMPLETED, UploadStatus.FAILED]:
        raise HTTPException(status_code=409, detail="Upload session is not active")

    if payload.part_number < 1:
        raise HTTPException(status_code=400, detail="part_number is out of range")

    if upload.total_parts > 0 and payload.part_number > upload.total_parts:
        raise HTTPException(status_code=400, detail="part_number is out of range")

    if (not payload.is_last_part) and payload.size < settings.MULTIPART_MIN_PART_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Part size is below minimum allowed size")

    normalized_etag = _normalize_etag(payload.etag)

    part = (
        db.query(UploadPart)
        .filter(
            UploadPart.upload_record_id == upload.id,
            UploadPart.part_number == payload.part_number,
        )
        .first()
    )

    part_status = "confirmed"
    if part:
        part.etag = normalized_etag
        part.size = payload.size
        part_status = "overwritten"
    else:
        part = UploadPart(
            upload_record_id=upload.id,
            part_number=payload.part_number,
            etag=normalized_etag,
            size=payload.size,
        )
        db.add(part)

    if upload.status == UploadStatus.INITIATED:
        upload.status = UploadStatus.UPLOADING

    db.commit()

    return UploadPartConfirmResponse(
        upload_id=upload.id,
        part_number=payload.part_number,
        status=part_status,
    )


@router.post("/complete", response_model=UploadCompleteResponse)
def complete_upload(
    payload: UploadCompleteRequest,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(current_user.id, "complete")

    upload = _get_upload_or_404(db, payload.upload_id, current_user.id)

    if upload.status == UploadStatus.COMPLETED:
        return UploadCompleteResponse(
            upload_id=upload.id,
            object_key=upload.object_key,
            status=upload.status,
        )

    if upload.status == UploadStatus.FAILED:
        raise HTTPException(status_code=409, detail="Upload session has failed")

    parts = (
        db.query(UploadPart)
        .filter(UploadPart.upload_record_id == upload.id)
        .order_by(UploadPart.part_number.asc())
        .all()
    )

    if not parts:
        raise HTTPException(status_code=400, detail="No uploaded parts found")

    expected_total_parts = upload.total_parts
    if expected_total_parts == 0:
        if payload.total_parts is not None:
            expected_total_parts = payload.total_parts
        else:
            expected_total_parts = parts[-1].part_number

    if expected_total_parts > settings.MULTIPART_MAX_PARTS:
        raise HTTPException(status_code=400, detail="total_parts exceeds allowed multipart limit")

    if len(parts) != expected_total_parts:
        raise HTTPException(status_code=400, detail="Missing parts; cannot complete upload")

    expected = list(range(1, expected_total_parts + 1))
    actual = [p.part_number for p in parts]
    if actual != expected:
        raise HTTPException(status_code=400, detail="Part numbers are not contiguous")

    final_total_size = upload.total_size if upload.total_size > 0 else sum(p.size for p in parts)
    if payload.total_size is not None:
        final_total_size = payload.total_size

    if final_total_size > settings.UPLOAD_MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds upload size limit")

    completion_parts = _build_completion_parts(parts)

    try:
        storage.complete_multipart_upload(
            object_key=upload.object_key,
            upload_id=upload.upload_id,
            parts=completion_parts,
        )
    except MultipartStorageError as exc:
        upload.status = UploadStatus.FAILED
        db.commit()
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    upload.status = UploadStatus.COMPLETED
    upload.total_parts = expected_total_parts
    upload.total_size = final_total_size
    upload.completed_at = datetime.utcnow()
    db.commit()

    return UploadCompleteResponse(
        upload_id=upload.id,
        object_key=upload.object_key,
        status=upload.status,
    )


@router.get("/{upload_id:uuid}", response_model=UploadSessionResponse)
def get_upload_session(
    upload_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    upload = _get_upload_or_404(db, upload_id, current_user.id)
    parts = (
        db.query(UploadPart.part_number)
        .filter(UploadPart.upload_record_id == upload.id)
        .order_by(UploadPart.part_number.asc())
        .all()
    )

    return UploadSessionResponse(
        id=upload.id,
        status=upload.status,
        object_key=upload.object_key,
        total_parts=upload.total_parts,
        total_size=upload.total_size,
        uploaded_parts=[p.part_number for p in parts],
        created_at=upload.created_at,
        updated_at=upload.updated_at,
        completed_at=upload.completed_at,
    )


@router.get("/list", response_model=UploadListResponse)
def list_user_uploads(
    media_type: str | None = Query(default=None, pattern="^(video|audio)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Upload)
        .filter(Upload.user_id == current_user.id, Upload.status == UploadStatus.COMPLETED)
        .order_by(Upload.completed_at.desc(), Upload.created_at.desc())
    )

    uploads = query.all()
    if media_type:
        uploads = [upload for upload in uploads if _detect_media_type(upload) == media_type]

    total = len(uploads)
    paged = uploads[offset : offset + limit]

    return UploadListResponse(
        items=[
            UploadListItemResponse(
                id=upload.id,
                object_key=upload.object_key,
                filename=upload.filename,
                content_type=upload.content_type,
                media_type=_detect_media_type(upload),
                total_size=upload.total_size,
                created_at=upload.created_at,
                completed_at=upload.completed_at,
            )
            for upload in paged
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/access", response_model=UploadAccessUrlResponse)
def get_upload_access_url(
    upload_id: UUID = Query(...),
    disposition: str = Query(default="inline", pattern="^(inline|attachment)$"),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(current_user.id, "access")
    upload = _get_upload_or_404(db, upload_id, current_user.id)

    if upload.status != UploadStatus.COMPLETED:
        raise HTTPException(status_code=409, detail="Upload session is not completed")

    expires_in = max(60, min(settings.PRESIGNED_URL_EXPIRE_SECONDS, 900))

    try:
        url = storage.presign_get_object(
            object_key=upload.object_key,
            expires_seconds=expires_in,
            disposition=disposition,
        )
    except MultipartStorageError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return UploadAccessUrlResponse(
        upload_id=upload.id,
        object_key=upload.object_key,
        url=url,
        expires_in_seconds=expires_in,
    )

@router.post("/cleanup-stale", status_code=status.HTTP_204_NO_CONTENT)
def cleanup_stale_uploads(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    _enforce_rate_limit(current_user.id, "cleanup")
    _cleanup_stale_uploads(db, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
