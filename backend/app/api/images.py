from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database_async import get_async_db
from app.dependencies import get_current_active_user
from app.models import NoteImage, User
from app.services.multipart_upload import MinIOMultipartService, MultipartStorageError
from app.utils.logger import get_logger

router = APIRouter(prefix="/notes/{note_id}/images", tags=["note-images"])
logger = get_logger(__name__)

storage = MinIOMultipartService()
IMAGE_URL_EXPIRE_SECONDS = 604800  # 7 days


def _image_response(img: NoteImage) -> dict:
    return {
        "id": str(img.id),
        "note_id": str(img.note_id),
        "object_key": img.object_key,
        "original_filename": img.original_filename,
        "content_type": img.content_type,
        "file_size": img.file_size,
        "url": storage.presign_get_object(img.object_key, IMAGE_URL_EXPIRE_SECONDS, disposition="inline"),
        "created_at": img.created_at.isoformat(),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_note_image(
    note_id: UUID,
    file: UploadFile,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only image files are allowed",
        )

    data = await file.read()
    object_key = storage.build_image_key(current_user.id, file.filename)

    try:
        storage.put_object(object_key, data, file.content_type)
    except MultipartStorageError as exc:
        logger.exception("Failed to upload image to storage")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image upload failed",
        ) from exc

    img = NoteImage(
        note_id=note_id,
        user_id=current_user.id,
        object_key=object_key,
        original_filename=file.filename,
        content_type=file.content_type,
        file_size=len(data),
    )
    db.add(img)
    await db.commit()
    await db.refresh(img)

    logger.info(f"✅ Image uploaded: note={note_id} key={object_key} size={len(data)}")
    return _image_response(img)


@router.get("")
async def list_note_images(
    note_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    stmt = (
        select(NoteImage)
        .where(NoteImage.note_id == note_id, NoteImage.user_id == current_user.id)
        .order_by(NoteImage.created_at.desc())
    )
    result = await db.execute(stmt)
    images = result.scalars().all()
    return [_image_response(img) for img in images]


@router.delete("/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note_image(
    note_id: UUID,
    image_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    stmt = select(NoteImage).where(
        NoteImage.id == image_id,
        NoteImage.note_id == note_id,
        NoteImage.user_id == current_user.id,
    )
    result = await db.execute(stmt)
    img = result.scalar_one_or_none()

    if not img:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    try:
        storage.delete_object(img.object_key)
    except MultipartStorageError:
        logger.warning(f"Failed to delete object from storage: {img.object_key}")

    await db.delete(img)
    await db.commit()
    logger.info(f"🗑️ Image deleted: note={note_id} image={image_id}")
    return None
