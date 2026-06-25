import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.candidate import Candidate
from app.models.interview_session import InterviewSession
from app.models.job import Job
from app.services.question_generator import generate_questions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interview", tags=["interview"])


class InterviewStatusResponse(BaseModel):
    candidate_name: Optional[str]
    job_title: str
    interview_status: str


class StartInterviewResponse(BaseModel):
    interview_status: str
    message: str


class QuestionResponse(BaseModel):
    id: int
    type: str
    question: str
    time_limit_seconds: int


@router.get(
    "/{token}",
    response_model=InterviewStatusResponse,
    summary="Get interview status by token",
)
async def get_interview_status(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> InterviewStatusResponse:
    """GET /interview/{token}"""
    query = (
        select(Candidate, Job)
        .join(Job, Candidate.job_id == Job.id)
        .where(Candidate.interview_token == token)
    )
    result = await db.execute(query)
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")

    candidate, job = row

    return InterviewStatusResponse(
        candidate_name=candidate.name,
        job_title=job.title,
        interview_status=candidate.interview_status,
    )


@router.post(
    "/{token}/start",
    response_model=StartInterviewResponse,
    summary="Start an interview session",
)
async def start_interview(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> StartInterviewResponse:
    """POST /interview/{token}/start"""
    query = select(Candidate).where(Candidate.interview_token == token)
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")

    if candidate.interview_status in ("in_progress", "completed"):
        return StartInterviewResponse(
            interview_status=candidate.interview_status,
            message=f"Interview already {candidate.interview_status.replace('_', ' ')}",
        )

    candidate.interview_status = "in_progress"
    await db.commit()

    return StartInterviewResponse(
        interview_status=candidate.interview_status,
        message="Interview started successfully",
    )


@router.post(
    "/{token}/questions",
    response_model=List[QuestionResponse],
    summary="Generate (or retrieve cached) interview questions for candidate",
)
async def get_interview_questions(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> List[QuestionResponse]:
    """
    POST /interview/{token}/questions

    Idempotent — if an InterviewSession already exists for this candidate+job,
    returns the stored questions without calling Gemini again.

    If no session exists, generates 5 questions via Gemini, creates the session
    record with started_at, persists, and returns the questions.
    """
    # Look up candidate + job by token
    query = (
        select(Candidate, Job)
        .join(Job, Candidate.job_id == Job.id)
        .where(Candidate.interview_token == token)
    )
    result = await db.execute(query)
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")

    candidate, job = row

    # Guard: interview must be in progress
    if candidate.interview_status != "in_progress":
        raise HTTPException(
            status_code=400,
            detail="Interview must be started before fetching questions",
        )

    # --- Idempotency check: return cached questions if session exists ---
    session_query = select(InterviewSession).where(
        InterviewSession.candidate_id == candidate.id,
        InterviewSession.job_id == job.id,
    )
    session_result = await db.execute(session_query)
    existing_session = session_result.scalar_one_or_none()

    if existing_session:
        logger.info(
            "Returning cached questions for candidate %s (session %s)",
            candidate.id,
            existing_session.id,
        )
        return [QuestionResponse(**q) for q in existing_session.questions]

    # --- No session yet: generate questions and persist ---
    questions = await generate_questions(job, candidate)

    session = InterviewSession(
        candidate_id=candidate.id,
        job_id=job.id,
        questions=questions,
        answers=[],
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    await db.commit()

    logger.info(
        "Created InterviewSession %s for candidate %s", session.id, candidate.id
    )
    return [QuestionResponse(**q) for q in questions]

