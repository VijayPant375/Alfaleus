"""
Candidates router — Phase 3

Endpoints:
  POST /candidates/score          — Score a single new candidate against a job
  POST /candidates/score-all      — Score all existing candidates for a job
  GET  /candidates/{candidate_id} — Retrieve a single candidate record
  GET  /candidates                — List all candidates for a job (query param: job_id)
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.candidate import Candidate
from app.models.interview_session import InterviewSession
from app.models.job import Job
from app.models.score import Score
from app.schemas.candidate import CandidateCreate, CandidateResponse
from app.schemas.score import ScoreResponse
from app.services.scorer import score_candidate
from app.services.email_service import send_interview_invite

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/candidates", tags=["candidates"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_job_or_404(job_id: uuid.UUID, db: AsyncSession) -> Job:
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")
    return job


async def _get_candidate_or_404(candidate_id: uuid.UUID, db: AsyncSession) -> Candidate:
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found.")
    return candidate


async def _fetch_session(candidate: Candidate, db: AsyncSession):
    """Fetch the InterviewSession for a candidate, or None if not found."""
    result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.candidate_id == candidate.id,
            InterviewSession.job_id == candidate.job_id,
        )
    )
    return result.scalar_one_or_none()


def _build_candidate_response(candidate: Candidate, session=None, score=None) -> CandidateResponse:
    """Build a CandidateResponse, merging in interview session data if available."""
    data = CandidateResponse.model_validate(candidate)
    if session:
        data.scorecard = session.scorecard
        data.overall_interview_score = session.overall_interview_score
        data.answer_scores = session.answer_scores
    if score:
        from app.schemas.score import ScoreResponse
        data.score = ScoreResponse.model_validate(score)
    return data


def _infer_confidence(candidate_data: CandidateCreate) -> str:
    """
    Infer confidence level from available data if not explicitly provided.
    high   — name + title + company + skills all present
    medium — name + title present, company or skills missing
    low    — only name or only title present
    """
    has_name = bool(candidate_data.name)
    has_title = bool(candidate_data.current_title)
    has_company = bool(candidate_data.current_company)
    has_skills = bool(candidate_data.listed_skills)

    if has_name and has_title and has_company and has_skills:
        return "high"
    elif has_name and has_title:
        return "medium"
    else:
        return "low"


async def _apply_shortlisting(
    candidate: Candidate, score: Score, job: Job, db: AsyncSession
) -> None:
    """
    Apply shortlisting logic in-place:
    - If shortlist_override is True → shortlisted stays as-is (override wins)
    - Otherwise shortlisted = (total_score >= job.shortlist_threshold)
    """
    if not candidate.shortlist_override:
        candidate.shortlisted = score.total_score >= job.shortlist_threshold
    # If shortlist_override is True, the human decision is preserved — no change


# ---------------------------------------------------------------------------
# POST /candidates/score
# ---------------------------------------------------------------------------


class ScoreRequest(CandidateCreate):
    """Extend CandidateCreate with nothing extra — score endpoint uses the same shape."""
    pass


from pydantic import BaseModel


class SingleScoreResponse(BaseModel):
    candidate: CandidateResponse
    score: ScoreResponse

    model_config = {"from_attributes": True}


@router.post(
    "/score",
    response_model=SingleScoreResponse,
    status_code=201,
    summary="Score a single candidate against a job",
    description=(
        "Creates a new candidate record, scores it against the specified job using "
        "semantic embeddings, applies shortlisting logic, stores the score, "
        "and returns both the candidate and their score."
    ),
)
async def score_single_candidate(
    payload: CandidateCreate,
    db: AsyncSession = Depends(get_db),
) -> SingleScoreResponse:
    """POST /candidates/score"""
    logger.info("POST /candidates/score — job_id=%s", payload.job_id)

    # 1. Validate job exists
    job = await _get_job_or_404(payload.job_id, db)

    # 2. Determine confidence level
    confidence = payload.confidence_level or _infer_confidence(payload)

    # 3. Create candidate record
    candidate = Candidate(
        id=uuid.uuid4(),
        job_id=payload.job_id,
        name=payload.name,
        current_title=payload.current_title,
        current_company=payload.current_company,
        listed_skills=payload.listed_skills,
        experience_summary=payload.experience_summary,
        work_history=payload.work_history,
        source=payload.source,
        profile_url=payload.profile_url,
        confidence_level=confidence,
        shortlisted=False,
        shortlist_override=payload.shortlist_override if hasattr(payload, "shortlist_override") else False,
        interview_status="not_invited",
        created_at=datetime.now(timezone.utc),
    )
    db.add(candidate)
    await db.flush()

    # 4. Run scorer (sync — CPU-bound, but fast enough for single candidate)
    score = score_candidate(job, candidate)
    db.add(score)
    await db.flush()

    # 5. Apply shortlisting
    await _apply_shortlisting(candidate, score, job, db)
    await db.flush()
    await db.refresh(candidate)
    await db.refresh(score)
    await db.commit()

    return SingleScoreResponse(
        candidate=CandidateResponse.model_validate(candidate),
        score=ScoreResponse.model_validate(score),
    )


# ---------------------------------------------------------------------------
# POST /candidates/score-all
# ---------------------------------------------------------------------------


class ScoreAllRequest(BaseModel):
    job_id: uuid.UUID


class ScoredCandidateSummary(BaseModel):
    candidate: CandidateResponse
    score: ScoreResponse

    model_config = {"from_attributes": True}


class ScoreAllResponse(BaseModel):
    job_id: uuid.UUID
    total_scored: int
    total_shortlisted: int
    results: list[ScoredCandidateSummary]


@router.post(
    "/score-all",
    response_model=ScoreAllResponse,
    summary="Score all candidates for a job",
    description=(
        "Fetches all candidates linked to the given job, runs semantic scoring "
        "on each, stores/updates their scores, applies shortlisting, and returns "
        "the full list sorted by total_score descending."
    ),
)
async def score_all_candidates(
    payload: ScoreAllRequest,
    db: AsyncSession = Depends(get_db),
) -> ScoreAllResponse:
    """POST /candidates/score-all"""
    logger.info("POST /candidates/score-all — job_id=%s", payload.job_id)

    # 1. Validate job
    job = await _get_job_or_404(payload.job_id, db)

    # 2. Fetch all candidates for this job
    result = await db.execute(
        select(Candidate).where(Candidate.job_id == payload.job_id)
    )
    candidates = result.scalars().all()

    if not candidates:
        return ScoreAllResponse(
            job_id=payload.job_id,
            total_scored=0,
            total_shortlisted=0,
            results=[],
        )

    logger.info("Scoring %d candidates for job %s", len(candidates), payload.job_id)

    results: list[ScoredCandidateSummary] = []

    for candidate in candidates:
        # Delete any existing score for this candidate+job to avoid duplicates
        existing = await db.execute(
            select(Score).where(
                Score.candidate_id == candidate.id,
                Score.job_id == job.id,
            )
        )
        for old_score in existing.scalars().all():
            await db.delete(old_score)

        # Score
        score = score_candidate(job, candidate)
        db.add(score)
        await db.flush()

        # Apply shortlisting
        await _apply_shortlisting(candidate, score, job, db)
        await db.flush()
        await db.refresh(candidate)
        await db.refresh(score)

        results.append(
            ScoredCandidateSummary(
                candidate=CandidateResponse.model_validate(candidate),
                score=ScoreResponse.model_validate(score),
            )
        )

    # Sort by total_score descending
    results.sort(key=lambda r: r.score.total_score, reverse=True)

    total_shortlisted = sum(1 for r in results if r.candidate.shortlisted)

    return ScoreAllResponse(
        job_id=payload.job_id,
        total_scored=len(results),
        total_shortlisted=total_shortlisted,
        results=results,
    )


# ---------------------------------------------------------------------------
# GET /candidates
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[CandidateResponse],
    summary="List candidates for a job",
)
async def list_candidates(
    job_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> list[CandidateResponse]:
    from sqlalchemy.orm import outerjoin
    result = await db.execute(
        select(Candidate, InterviewSession, Score)
        .outerjoin(
            InterviewSession,
            (InterviewSession.candidate_id == Candidate.id) &
            (InterviewSession.job_id == Candidate.job_id)
        )
        .outerjoin(
            Score,
            (Score.candidate_id == Candidate.id) &
            (Score.job_id == Candidate.job_id)
        )
        .where(Candidate.job_id == job_id)
        .order_by(Candidate.created_at.desc())
    )
    rows = result.all()
    return [_build_candidate_response(candidate, session, score) for candidate, session, score in rows]


# ---------------------------------------------------------------------------
# GET /candidates/{candidate_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{candidate_id}",
    response_model=CandidateResponse,
    summary="Get a single candidate",
)
async def get_candidate(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> CandidateResponse:
    """GET /candidates/{candidate_id}"""
    candidate = await _get_candidate_or_404(candidate_id, db)
    session = await _fetch_session(candidate, db)
    score_result = await db.execute(
        select(Score).where(Score.candidate_id == candidate_id).order_by(Score.created_at.desc()).limit(1)
    )
    score = score_result.scalar_one_or_none()
    return _build_candidate_response(candidate, session, score)


# ---------------------------------------------------------------------------
# PATCH /candidates/{candidate_id}/override
# ---------------------------------------------------------------------------

class ShortlistOverrideRequest(BaseModel):
    shortlisted: bool


@router.patch(
    "/{candidate_id}/override",
    response_model=CandidateResponse,
    summary="Manual Shortlist Override",
    description="Manually override the shortlist status of a candidate. This prevents future score-all runs from changing it.",
)
async def override_shortlist(
    candidate_id: uuid.UUID,
    payload: ShortlistOverrideRequest,
    db: AsyncSession = Depends(get_db),
) -> CandidateResponse:
    """PATCH /candidates/{candidate_id}/override"""
    candidate = await _get_candidate_or_404(candidate_id, db)
    
    candidate.shortlist_override = True
    candidate.shortlisted = payload.shortlisted
    
    await db.commit()
    await db.refresh(candidate)
    session = await _fetch_session(candidate, db)
    return _build_candidate_response(candidate, session)


# ---------------------------------------------------------------------------
# GET /candidates/{candidate_id}/score
# ---------------------------------------------------------------------------

@router.get(
    "/{candidate_id}/score",
    response_model=ScoreResponse,
    summary="Get candidate score",
)
async def get_candidate_score(
    candidate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> ScoreResponse:
    result = await db.execute(
        select(Score)
        .where(Score.candidate_id == candidate_id)
        .order_by(Score.created_at.desc())
        .limit(1)
    )
    score = result.scalar_one_or_none()
    if not score:
        raise HTTPException(status_code=404, detail="No score found for this candidate.")
    return ScoreResponse.model_validate(score)


# ---------------------------------------------------------------------------
# POST /candidates/{candidate_id}/invite
# ---------------------------------------------------------------------------

@router.post(
    "/{candidate_id}/invite",
    summary="Invite a candidate",
)
async def invite_candidate(
    candidate_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    candidate = await _get_candidate_or_404(candidate_id, db)
    job = await _get_job_or_404(candidate.job_id, db)

    if candidate.interview_status in ("in_progress", "completed"):
        raise HTTPException(
            status_code=400,
            detail="Candidate has already started or completed their interview."
        )

    token = uuid.uuid4().hex
    candidate.interview_token = token
    candidate.interview_token_created_at = datetime.now(timezone.utc)
    candidate.interview_status = "invited"

    success = await send_interview_invite(candidate, job)
    await db.commit()

    if not success:
        response.status_code = 207
        return {"invited": True, "email_sent": False, "token": token}
    return {"invited": True, "email_sent": True, "token": token}
