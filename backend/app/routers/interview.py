import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interview", tags=["interview"])

class InterviewStatusResponse(BaseModel):
    candidate_name: Optional[str]
    job_title: str
    interview_status: str

class StartInterviewResponse(BaseModel):
    interview_status: str
    message: str

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
    query = select(Candidate, Job).join(Job, Candidate.job_id == Job.id).where(Candidate.interview_token == token)
    result = await db.execute(query)
    row = result.first()
    
    if not row:
        raise HTTPException(status_code=404, detail="Invalid or expired interview token")
        
    candidate, job = row
    
    return InterviewStatusResponse(
        candidate_name=candidate.name,
        job_title=job.title,
        interview_status=candidate.interview_status
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
            message=f"Interview already {candidate.interview_status.replace('_', ' ')}"
        )
        
    candidate.interview_status = "in_progress"
    await db.commit()
    
    return StartInterviewResponse(
        interview_status=candidate.interview_status,
        message="Interview started successfully"
    )
