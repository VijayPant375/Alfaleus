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
from sqlalchemy import select, func

from app.database import get_db
from app.models.job import Job
from app.schemas.job import JobCreate, JobResponse, PipelineResponse
from app.services.jd_analyzer import analyze_job_description
from app.services.scraper import run_scrapers
from app.schemas.scraper import ScrapeRequest, ScrapeResponse
from app.models.candidate import Candidate
from app.routers.candidates import score_all_candidates, ScoreAllRequest

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
        select(Job, func.count(Candidate.id).label("candidate_count"))
        .outerjoin(Candidate, Job.id == Candidate.job_id)
        .group_by(Job.id)
        .order_by(Job.created_at.desc())
    )
    rows = result.all()
    jobs = []
    for job, count in rows:
        job.candidate_count = count
        jobs.append(JobResponse.model_validate(job))
    return jobs


@router.post(
    "/{job_id}/scrape",
    response_model=ScrapeResponse,
    summary="Scrape candidates for a job",
)
async def scrape_candidates(
    job_id: uuid.UUID,
    payload: ScrapeRequest,
    db: AsyncSession = Depends(get_db),
) -> ScrapeResponse:
    """POST /jobs/{job_id}/scrape — Scrapes LinkedIn and Indeed for candidates."""
    logger.info("Received POST /jobs/%s/scrape", job_id)
    
    # Verify job exists
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
        
    title_to_search = payload.title or job.title
    location_to_search = payload.location
    
    # Run scrapers
    scraped_candidates = await run_scrapers(title_to_search, location_to_search)
    
    # Deduplicate by (name, company) internally in scraped data
    seen_combinations = set()
    unique_scraped = []
    
    linkedin_count = 0
    indeed_count = 0
    
    for c_data in scraped_candidates:
        name = c_data.get("name", "").strip().lower()
        company = (c_data.get("current_company") or "").strip().lower()
        key = (name, company)
        
        if key not in seen_combinations:
            seen_combinations.add(key)
            unique_scraped.append(c_data)
            if c_data.get("source") == "linkedin":
                linkedin_count += 1
            else:
                indeed_count += 1
                
    # Insert unique candidates to database
    total_added = 0
    for c_data in unique_scraped:
        # Check if candidate already exists in the DB for this job
        name = c_data.get("name", "")
        company = c_data.get("current_company")
        
        existing = None
        if name:
            query = select(Candidate).where(
                Candidate.job_id == job_id,
                Candidate.name == name
            )
            existing_candidates = await db.execute(query)
            for ec in existing_candidates.scalars().all():
                if ec.current_company == company:
                    existing = ec
                    break
        
        if not existing:
            new_candidate = Candidate(
                id=uuid.uuid4(),
                job_id=job_id,
                **c_data,
                shortlisted=False,
                shortlist_override=False,
                interview_status="not_invited",
                created_at=datetime.now(timezone.utc),
            )
            db.add(new_candidate)
            total_added += 1
            
    await db.flush()
    
    return ScrapeResponse(
        job_id=job_id,
        linkedin_count=linkedin_count,
        indeed_count=indeed_count,
        total_added=total_added,
        warnings=["Playwright fallback active" if linkedin_count > 0 and unique_scraped[0].get("profile_url", "").endswith("-mock") else ""]
    )


@router.post(
    "/{job_id}/run-pipeline",
    response_model=PipelineResponse,
    summary="Run full end-to-end pipeline",
    description=(
        "Triggers the full pipeline for a job:\n"
        "1. Scrape candidates (LinkedIn/Indeed)\n"
        "2. Score all candidates using semantic embeddings\n"
        "3. Apply shortlisting logic\n"
        "Returns a summary of the pipeline execution."
    ),
)
async def run_pipeline(
    job_id: uuid.UUID,
    payload: ScrapeRequest,
    db: AsyncSession = Depends(get_db),
) -> PipelineResponse:
    """POST /jobs/{job_id}/run-pipeline"""
    logger.info("Starting pipeline for job_id=%s", job_id)
    
    # 1. Scrape candidates
    scrape_resp = await scrape_candidates(job_id=job_id, payload=payload, db=db)
    
    # 2. Score candidates
    score_req = ScoreAllRequest(job_id=job_id)
    score_resp = await score_all_candidates(payload=score_req, db=db)
    
    logger.info("Pipeline completed for job_id=%s. Scraped=%d, Scored=%d, Shortlisted=%d",
                job_id, scrape_resp.total_added, score_resp.total_scored, score_resp.total_shortlisted)
                
    return PipelineResponse(
        job_id=job_id,
        candidates_scraped=scrape_resp.total_added,
        candidates_scored=score_resp.total_scored,
        shortlisted_count=score_resp.total_shortlisted,
        warnings=scrape_resp.warnings
    )


# ---------------------------------------------------------------------------
# POST /jobs/{job_id}/send-invites
# ---------------------------------------------------------------------------

from pydantic import BaseModel
from app.services.email_service import send_interview_invite

class SendInvitesResponse(BaseModel):
    invited_count: int
    failed_count: int

@router.post(
    "/{job_id}/send-invites",
    response_model=SendInvitesResponse,
    summary="Send interview invites to shortlisted candidates",
)
async def send_invites(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> SendInvitesResponse:
    """POST /jobs/{job_id}/send-invites"""
    logger.info("Received POST /jobs/%s/send-invites", job_id)
    
    # Verify job
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
        
    # Fetch shortlisted, not_invited candidates
    candidates_res = await db.execute(
        select(Candidate).where(
            Candidate.job_id == job_id,
            Candidate.shortlisted == True,
            Candidate.interview_status == "not_invited"
        )
    )
    candidates = candidates_res.scalars().all()
    
    invited_count = 0
    failed_count = 0
    
    for candidate in candidates:
        candidate.interview_token = uuid.uuid4().hex
        candidate.interview_token_created_at = datetime.now(timezone.utc)
        
        success = await send_interview_invite(candidate, job)
        if success:
            candidate.interview_status = "invited"
            invited_count += 1
        else:
            failed_count += 1
            
    await db.commit()
    
    return SendInvitesResponse(
        invited_count=invited_count,
        failed_count=failed_count
    )
