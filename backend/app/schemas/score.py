"""
Score Pydantic schemas.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class RedFlag(BaseModel):
    type: str
    description: str


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class ScoreResponse(BaseModel):
    id: UUID
    candidate_id: UUID
    job_id: UUID
    total_score: float
    technical_score: float
    seniority_score: float
    domain_score: float
    skills_breakdown: Optional[Dict[str, float]] = None
    red_flags: Optional[List[Dict[str, Any]]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScoredCandidateResponse(BaseModel):
    """Candidate + their latest score, used in score-all responses."""

    candidate: "CandidateResponse"
    score: ScoreResponse


# Avoid circular imports
from app.schemas.candidate import CandidateResponse  # noqa: E402
ScoredCandidateResponse.model_rebuild()
