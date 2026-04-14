from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Asset, IngestJob, IngestJobStatus


class IngestJobService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_job(self, job_id: UUID, user_id: UUID) -> IngestJob | None:
        return self.db.query(IngestJob).filter(
            IngestJob.id == job_id,
            IngestJob.user_id == user_id,
        ).first()

    def get_jobs_by_asset(self, asset_id: UUID, user_id: UUID) -> list[IngestJob]:
        return self.db.query(IngestJob).join(
            Asset,
            Asset.id == IngestJob.asset_id,
        ).filter(
            IngestJob.asset_id == asset_id,
            IngestJob.user_id == user_id,
            Asset.deleted_at.is_(None),
        ).order_by(IngestJob.created_at.desc()).all()

    def cancel_job(self, job_id: UUID, user_id: UUID) -> IngestJob | None:
        job = self.get_job(job_id=job_id, user_id=user_id)
        if job is None:
            return None

        if job.status in (IngestJobStatus.SUCCESS, IngestJobStatus.FAILED, IngestJobStatus.DEAD):
            return job

        job.status = IngestJobStatus.CANCELED
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job
