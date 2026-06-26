import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.candidate import Candidate
from app.models.interview_session import InterviewSession
from app.models.job import Job
from app.services.question_generator import generate_questions

load_dotenv()

logger = logging.getLogger(__name__)

_SUPABASE_URL = os.getenv("SUPABASE_URL", "")
_SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
_STORAGE_BUCKET = "interviews"

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


# ---------------------------------------------------------------------------
# Phase 3 — Chunked Video Upload
# ---------------------------------------------------------------------------


class ChunkUploadResponse(BaseModel):
    chunk_index: int
    received: bool


class FinalizeAnswerRequest(BaseModel):
    question_id: int
    total_chunks: int


class FinalizeAnswerResponse(BaseModel):
    question_id: int
    video_url: str
    answers_submitted: int


async def _upload_chunk_to_supabase(
    path: str,
    data: bytes,
    content_type: str = "video/webm",
) -> None:
    """Upload a single raw chunk to Supabase Storage via the REST API."""
    if not _SUPABASE_URL or not _SUPABASE_KEY:
        raise HTTPException(
            status_code=500,
            detail="Supabase credentials are not configured on the server.",
        )

    url = f"{_SUPABASE_URL}/storage/v1/object/{_STORAGE_BUCKET}/{path}"
    headers = {
        "Authorization": f"Bearer {_SUPABASE_KEY}",
        "Content-Type": content_type,
        "x-upsert": "true",  # overwrite if re-uploaded
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, content=data, headers=headers)

    if response.status_code not in (200, 201):
        logger.error(
            "Supabase Storage upload failed (%s): %s",
            response.status_code,
            response.text[:300],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Supabase Storage upload failed: {response.status_code}",
        )


@router.post(
    "/{token}/upload-chunk",
    response_model=ChunkUploadResponse,
    summary="Upload a single video chunk to Supabase Storage",
)
async def upload_chunk(
    token: str,
    question_id: int = Form(...),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    video_chunk: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> ChunkUploadResponse:
    """
    POST /interview/{token}/upload-chunk

    Accepts a single video chunk (multipart/form-data) and uploads it directly
    to Supabase Storage at:
      interviews/{candidate_id}/{question_id}/chunk_{chunk_index}.webm

    Uses httpx to call the Supabase Storage REST API — no additional SDK needed.
    """
    # Look up candidate by token
    query = select(Candidate).where(Candidate.interview_token == token)
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")

    # Read chunk bytes
    chunk_data = await video_chunk.read()

    # Upload to Supabase Storage
    storage_path = f"{candidate.id}/{question_id}/chunk_{chunk_index}.webm"
    await _upload_chunk_to_supabase(storage_path, chunk_data)

    logger.info(
        "Uploaded chunk %d/%d for question %d (candidate %s)",
        chunk_index + 1,
        total_chunks,
        question_id,
        candidate.id,
    )

    return ChunkUploadResponse(chunk_index=chunk_index, received=True)


@router.post(
    "/{token}/finalize-answer",
    response_model=FinalizeAnswerResponse,
    summary="Finalize a recorded answer and store the video URL",
)
async def finalize_answer(
    token: str,
    body: FinalizeAnswerRequest,
    db: AsyncSession = Depends(get_db),
) -> FinalizeAnswerResponse:
    """
    POST /interview/{token}/finalize-answer

    Called after all chunks for a question have been uploaded. Constructs the
    public URL for chunk_0 (Day 4 will handle merging) and appends the answer
    record to the InterviewSession.answers JSONB column.
    """
    # Look up candidate by token
    query = select(Candidate).where(Candidate.interview_token == token)
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")

    # Fetch the InterviewSession for this candidate + job (bug fix: must filter by both)
    session_query = select(InterviewSession).where(
        InterviewSession.candidate_id == candidate.id,
        InterviewSession.job_id == candidate.job_id,
    )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="No interview session found for this candidate. Call /questions first.",
        )

    # Construct placeholder video URL (Day 4 will handle chunk merging)
    video_url = (
        f"{_SUPABASE_URL}/storage/v1/object/public/{_STORAGE_BUCKET}/"
        f"{candidate.id}/{body.question_id}/chunk_0.webm"
    )

    # Append answer to session (overwrite if same question_id to allow retries)
    current_answers: list = list(session.answers or [])
    current_answers = [a for a in current_answers if a.get("question_id") != body.question_id]
    current_answers.append(
        {
            "question_id": body.question_id,
            "transcript": None,
            "video_url": video_url,
        }
    )

    # Reassign to trigger SQLAlchemy dirty-tracking on JSONB column
    session.answers = current_answers
    await db.commit()

    logger.info(
        "Finalized answer for question %d (candidate %s) — %d answers total",
        body.question_id,
        candidate.id,
        len(current_answers),
    )

    return FinalizeAnswerResponse(
        question_id=body.question_id,
        video_url=video_url,
        answers_submitted=len(current_answers),
    )


# ---------------------------------------------------------------------------
# Phase 1 — Whisper Transcription
# ---------------------------------------------------------------------------


class TranscribeRequest(BaseModel):
    question_id: int


class TranscribeResponse(BaseModel):
    question_id: int
    transcript: str


@router.post(
    "/{token}/transcribe",
    response_model=TranscribeResponse,
    summary="Transcribe a recorded answer using Whisper",
)
async def transcribe_answer_endpoint(
    token: str,
    body: TranscribeRequest,
    db: AsyncSession = Depends(get_db),
) -> TranscribeResponse:
    """
    POST /interview/{token}/transcribe

    Downloads the uploaded video for the given question_id and runs Whisper
    speech-to-text on it. Updates the transcript field in session.answers and
    persists. Idempotent — calling again will overwrite the previous transcript.
    """
    from app.services.transcriber import transcribe_answer as _transcribe  # noqa: PLC0415

    # 1. Look up candidate by token
    query = select(Candidate).where(Candidate.interview_token == token)
    result = await db.execute(query)
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")

    # 2. Fetch interview session by candidate_id + job_id
    session_query = select(InterviewSession).where(
        InterviewSession.candidate_id == candidate.id,
        InterviewSession.job_id == candidate.job_id,
    )
    session_result = await db.execute(session_query)
    session = session_result.scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=404,
            detail="No interview session found. Call /questions first.",
        )

    # 3. Locate the answer for the requested question_id
    current_answers: list = list(session.answers or [])
    matching = [
        a for a in current_answers if a.get("question_id") == body.question_id
    ]
    if not matching:
        raise HTTPException(
            status_code=400,
            detail=f"No answer found for question_id={body.question_id}. Upload video first.",
        )

    answer = matching[0]
    video_url: str = answer.get("video_url", "")

    # 4. Transcribe via Whisper (runs in thread pool — never blocks the event loop)
    transcript = await _transcribe(
        video_url=video_url,
        candidate_id=str(candidate.id),
        question_id=body.question_id,
    )

    # 5. Reassign answers list (SQLAlchemy requires full reassignment to detect JSONB changes)
    updated_answers = [
        (
            {**a, "transcript": transcript}
            if a.get("question_id") == body.question_id
            else a
        )
        for a in current_answers
    ]
    session.answers = updated_answers
    await db.commit()

    logger.info(
        "Transcribed question %d for candidate %s (%d chars)",
        body.question_id,
        candidate.id,
        len(transcript),
    )

    return TranscribeResponse(question_id=body.question_id, transcript=transcript)
