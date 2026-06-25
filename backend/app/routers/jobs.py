"""
Jobs router — Phase 2

Endpoints:
  POST /jobs     — Accepts raw JD text, runs Gemini analysis, stores Job, returns full record.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse
from app.services.jd_analyzer import analyze_job_description

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobResponse,
    status_code=201,
    summary="Create a job from raw JD text",
    description=(
        "Accepts a job title and raw description text. "
        "Calls Gemini 1.5 Flash to extract structured fields "
        "(required skills, experience range, role level, implicit signals), "
        "stores the result in the database, and returns the full Job record."
    ),
)
async def create_job(
    payload: JobCreate,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """
    POST /jobs

    Body:
        title       (str) — Job title
        description (str) — Raw job description text

    Returns:
        Full Job record including Gemini-extracted fields.
    """
    logger.info("Received POST /jobs for title=%r", payload.title)

    # 1. Run JD analysis via Gemini
    try:
        analysis = await analyze_job_description(payload.description)
    except HTTPException:
        raise  # Let FastAPI handle it with the correct status
    except Exception as exc:
        logger.exception("Unexpected error during JD analysis.")
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected JD analysis error: {exc}",
        )

    # 2. Build the Job ORM object
    job = Job(
        id=uuid.uuid4(),
        title=payload.title,
        description=payload.description,
        required_skills=[s.model_dump() for s in analysis.required_skills],
        preferred_skills=analysis.preferred_skills,
        experience_range=analysis.experience_range.model_dump()
        if analysis.experience_range
        else None,
        role_level=analysis.role_level,
        implicit_signals=analysis.implicit_signals,
        shortlist_threshold=0.65,
        status="active",
        created_at=datetime.now(timezone.utc),
    )

    # 3. Persist to database
    db.add(job)
    await db.flush()   # Get the id back without committing yet
    await db.refresh(job)

    logger.info("Job created successfully: id=%s", job.id)

    return JobResponse.model_validate(job)


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get a job by ID",
)
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """GET /jobs/{job_id} — Retrieve a single job record."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return JobResponse.model_validate(job)


@router.get(
    "",
    response_model=list[JobResponse],
    summary="List all jobs",
)
async def list_jobs(
    db: AsyncSession = Depends(get_db),
) -> list[JobResponse]:
    """GET /jobs — Return all jobs ordered by created_at descending."""
    result = await db.execute(
        select(Job).order_by(Job.created_at.desc())
    )
    jobs = result.scalars().all()
    return [JobResponse.model_validate(j) for j in jobs]
