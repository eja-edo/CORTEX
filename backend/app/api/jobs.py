from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_active_user
from app.models import User
from app.schemas import IngestJobResponse, MessageResponse
from app.services.ingest_jobs import IngestJobService

router = APIRouter(tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=IngestJobResponse)
def get_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = IngestJobService(db)
    job = service.get_job(job_id=job_id, user_id=current_user.id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.get("/assets/{asset_id}/jobs", response_model=list[IngestJobResponse])
def get_jobs_by_asset(
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = IngestJobService(db)
    return service.get_jobs_by_asset(asset_id=asset_id, user_id=current_user.id)


@router.post("/jobs/{job_id}/cancel", response_model=IngestJobResponse)
def cancel_job(
    job_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    service = IngestJobService(db)
    job = service.cancel_job(job_id=job_id, user_id=current_user.id)
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job
