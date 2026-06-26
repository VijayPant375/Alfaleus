"""
Candidate Pydantic schemas.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class WorkHistoryEntry(BaseModel):
    title: str
    company: str
    duration_months: int = Field(..., ge=0)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class CandidateCreate(BaseModel):
    job_id: UUID
    name: Optional[str] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    listed_skills: Optional[List[str]] = None
    experience_summary: Optional[str] = None
    work_history: Optional[List[Dict[str, Any]]] = None
    source: str = Field(..., description="linkedin | indeed | manual")
    profile_url: Optional[str] = None
    confidence_level: str = Field(
        "low", description="high | medium | low"
    )
    shortlist_override: bool = Field(
        False,
        description="If True, manual shortlist decision overrides score-based logic",
    )


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class CandidateResponse(BaseModel):
    id: UUID
    job_id: UUID
    name: Optional[str] = None
    current_title: Optional[str] = None
    current_company: Optional[str] = None
    listed_skills: Optional[List[str]] = None
    experience_summary: Optional[str] = None
    work_history: Optional[List[Dict[str, Any]]] = None
    source: str
    profile_url: Optional[str] = None
    confidence_level: str
    shortlisted: bool
    shortlist_override: bool
    interview_status: str
    interview_token: Optional[str] = None
    created_at: datetime

    # Interview session fields — populated when interview is completed
    scorecard: Optional[Dict[str, Any]] = None
    overall_interview_score: Optional[float] = None
    answer_scores: Optional[List[Dict[str, Any]]] = None

    model_config = {"from_attributes": True}
