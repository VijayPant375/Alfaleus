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

import json
from google import genai

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not _GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

_client = genai.Client(api_key=_GEMINI_API_KEY)
_MODEL = "gemini-2.5-flash"

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

    from datetime import timedelta
    TOKEN_EXPIRY_DAYS = 7

    if (
        candidate.interview_token_created_at is not None
        and candidate.interview_status not in ("in_progress", "completed")
    ):
        age = datetime.now(timezone.utc) - candidate.interview_token_created_at
        if age > timedelta(days=TOKEN_EXPIRY_DAYS):
            raise HTTPException(
                status_code=410,
                detail="This interview link has expired. Please contact the recruiter for a new invitation.",
            )

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


# ---------------------------------------------------------------------------
# Phase 2 — Answer Scoring
# ---------------------------------------------------------------------------


class ScoreAnswersResponse(BaseModel):
    scores: list
    overall_interview_score: float


@router.post(
    "/{token}/score-answers",
    response_model=ScoreAnswersResponse,
    summary="Score all transcribed answers for an interview session",
)
async def score_answers(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> ScoreAnswersResponse:
    """
    POST /interview/{token}/score-answers

    Iterates over all answers that have a non-empty transcript, calls Gemini
    to score each on relevance/depth/communication, stores the results in
    session.answer_scores, and computes an overall interview score.

    Must be called after /transcribe has been run for each answer.
    """
    from app.services.answer_scorer import score_answer as _score_answer  # noqa: PLC0415

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

    # 3. Fetch the Job record
    job_query = select(Job).where(Job.id == candidate.job_id)
    job_result = await db.execute(job_query)
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {candidate.job_id} not found.")

    # 4. Filter answers to only those with a non-empty transcript
    all_answers: list = list(session.answers or [])
    answered = [
        a for a in all_answers
        if isinstance(a.get("transcript"), str) and a["transcript"].strip()
    ]

    if not answered:
        raise HTTPException(
            status_code=400,
            detail="No transcribed answers found. Run /transcribe for each answer first.",
        )

    # 5. Build a quick lookup of questions by id
    questions_by_id: dict = {q["id"]: q for q in (session.questions or [])}

    # 6. Score each answered question
    import asyncio

    async def _score_one(answer: dict) -> dict | None:
        qid = answer["question_id"]
        question = questions_by_id.get(qid)
        if not question:
            logger.warning("No question found for question_id=%s — skipping.", qid)
            return None
        return await _score_answer(question, answer["transcript"], job)

    scored_raw = await asyncio.gather(*[_score_one(a) for a in answered])
    scored = [s for s in scored_raw if s is not None]

    if not scored:
        raise HTTPException(
            status_code=400,
            detail="Could not match any answers to questions.",
        )

    # 7. Compute overall_interview_score: mean of per-answer sub-score means
    per_answer_means = [
        (s["relevance"] + s["depth"] + s["communication"]) / 3.0
        for s in scored
    ]
    overall = sum(per_answer_means) / len(per_answer_means)

    # 8. Reassign JSONB columns (full replacement required for SQLAlchemy dirty-tracking)
    session.answer_scores = scored
    session.overall_interview_score = overall
    await db.commit()

    logger.info(
        "Scored %d answers for candidate %s — overall_interview_score=%.2f",
        len(scored),
        candidate.id,
        overall,
    )

    return ScoreAnswersResponse(scores=scored, overall_interview_score=overall)


# ---------------------------------------------------------------------------
# Phase 3 — Scorecard Generation
# ---------------------------------------------------------------------------


@router.post(
    "/{token}/generate-scorecard",
    summary="Generate a holistic interview scorecard using Gemini",
)
async def generate_scorecard_endpoint(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    POST /interview/{token}/generate-scorecard

    Synthesises profile scores and interview answer scores into a structured
    Gemini-generated scorecard. Sets session.completed_at and marks the
    candidate's interview_status as 'completed'.

    Prerequisites:
      - /score-answers must have been called first (session.answer_scores must be populated)
    """
    from app.models.score import Score  # noqa: PLC0415
    from app.services.scorecard_generator import generate_scorecard as _generate  # noqa: PLC0415

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

    # 3. Guard: answer scores must exist before generating a scorecard
    if not session.answer_scores:
        raise HTTPException(
            status_code=400,
            detail="Score answers before generating scorecard",
        )

    # 4. Fetch the profile Score record
    score_query = select(Score).where(
        Score.candidate_id == candidate.id,
        Score.job_id == candidate.job_id,
    )
    score_result = await db.execute(score_query)
    profile_score = score_result.scalar_one_or_none()

    if not profile_score:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No profile score found for candidate {candidate.id}. "
                "Run /candidates/score first."
            ),
        )

    # 5. Fetch the Job record
    job_query = select(Job).where(Job.id == candidate.job_id)
    job_result = await db.execute(job_query)
    job = job_result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {candidate.job_id} not found.")

    # 6. Generate the scorecard via Gemini (2-attempt retry inside the service)
    scorecard = await _generate(job, candidate, session, profile_score)

    # 7. Persist scorecard, mark session complete, update candidate status
    session.scorecard = scorecard  # full reassignment for JSONB dirty-tracking
    session.completed_at = datetime.now(timezone.utc)
    candidate.interview_status = "completed"
    await db.commit()

    logger.info(
        "Scorecard generated for candidate %s — recommendation=%s",
        candidate.id,
        scorecard.get("overall_recommendation"),
    )

    return scorecard


# ---------------------------------------------------------------------------
# Phase 1 — Candidate Comparison (Gap 5)
# ---------------------------------------------------------------------------

class CompareRequest(BaseModel):
    job_id: int
    candidate_ids: List[int]

class RankingItem(BaseModel):
    rank: int
    candidate_id: int
    candidate_name: str
    justification: str

class CompareResponse(BaseModel):
    ranking: List[RankingItem]
    comparison_summary: str

_COMPARE_PROMPT = """\
You are an expert technical recruiter comparing candidates for a job.

CRITICAL RULES:
1. Return only a valid JSON object. Do not include markdown, backticks, or any text outside the JSON object.
2. NO markdown code fences (no ```json or ```).
3. NO preamble, explanation, or text before or after the JSON.

You are comparing the following candidates:
{candidates_context}

Return EXACTLY this JSON structure:
{{
  "ranking": [
    {{
      "rank": <int, 1 being best>,
      "candidate_id": <int>,
      "candidate_name": "<string>",
      "justification": "<plain-English sentence explaining why this candidate is ranked here>"
    }}
  ],
  "comparison_summary": "<2-3 sentence overall summary of the candidate pool>"
}}
"""

def _clean_response(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if (len(lines) > 1 and lines[-1].strip() == "```") else lines[1:]
        text = "\n".join(inner).strip()
    return text

@router.post(
    "/compare",
    response_model=CompareResponse,
    summary="Compare and rank multiple candidates via Gemini",
)
async def compare_candidates(
    body: CompareRequest,
    db: AsyncSession = Depends(get_db),
) -> CompareResponse:
    if not (2 <= len(body.candidate_ids) <= 3):
        raise HTTPException(status_code=422, detail="Must provide exactly 2 or 3 candidate_ids")

    import asyncio
    from app.models.score import Score

    async def _fetch_candidate_data(cid: int):
        c_res = await db.execute(select(Candidate).where(Candidate.id == cid))
        c = c_res.scalar_one_or_none()
        s_res = await db.execute(select(Score).where(Score.candidate_id == cid, Score.job_id == body.job_id))
        s = s_res.scalar_one_or_none()
        is_res = await db.execute(select(InterviewSession).where(InterviewSession.candidate_id == cid, InterviewSession.job_id == body.job_id))
        i_session = is_res.scalar_one_or_none()
        return c, s, i_session

    results = await asyncio.gather(*[_fetch_candidate_data(cid) for cid in body.candidate_ids])

    candidates_context = ""
    for cid, (cand, score, session) in zip(body.candidate_ids, results):
        if not cand:
            continue
        ctx = f"Candidate ID: {cid}\n"
        ctx += f"Name: {cand.name or 'N/A'}, Title: {cand.current_title or 'N/A'}, Company: {cand.current_company or 'N/A'}\n"
        if score:
            ctx += f"Profile Scores -> Total: {score.total_score}, Tech: {score.technical_score}, Seniority: {score.seniority_score}, Domain: {score.domain_score}\n"
        if session:
            if session.overall_interview_score is not None:
                ctx += f"Overall Interview Score: {session.overall_interview_score}\n"
            if session.scorecard:
                sc = session.scorecard
                ctx += f"Recommendation: {sc.get('overall_recommendation', 'N/A')}\n"
                ctx += f"Summary: {sc.get('summary', 'N/A')}\n"
            if session.answer_scores:
                ctx += "Answer Summaries:\n"
                for ans in session.answer_scores:
                    ctx += f" - Q{ans.get('question_id')}: {ans.get('answer_summary', 'N/A')}\n"
        ctx += "\n"
        candidates_context += ctx

    if not candidates_context.strip():
        raise HTTPException(status_code=400, detail="No valid candidates found.")

    prompt = _COMPARE_PROMPT.format(candidates_context=candidates_context)

    try:
        raw = _clean_response(_client.models.generate_content(model=_MODEL, contents=prompt).text)
        data = json.loads(raw)
        return CompareResponse(**data)
    except Exception as e:
        logger.warning("First comparison attempt failed: %s. Retrying.", e)

    try:
        raw = _clean_response(_client.models.generate_content(model=_MODEL, contents=prompt).text)
        data = json.loads(raw)
        return CompareResponse(**data)
    except Exception as e:
        logger.error("Second comparison attempt failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to generate comparison from AI.")
