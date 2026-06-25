"""
Job Pydantic schemas.

Handles request validation, JD analysis result typing, and API response shapes.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class RequiredSkill(BaseModel):
    name: str
    seniority: str = Field(
        ..., description="one of: junior, mid, senior, lead, any"
    )


class ExperienceRange(BaseModel):
    min: Optional[int] = Field(default=0, ge=0)
    max: Optional[int] = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# JD Analysis Result (from Gemini)
# ---------------------------------------------------------------------------


class JobAnalysisResult(BaseModel):
    required_skills: List[RequiredSkill] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience_range: Optional[ExperienceRange] = None
    role_level: str = Field(
        ..., description="one of: junior, mid, senior, lead"
    )
    implicit_signals: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class JobCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=10)


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    id: UUID
    title: str
    description: str
    required_skills: Optional[List[Dict[str, Any]]] = None
    preferred_skills: Optional[List[str]] = None
    experience_range: Optional[Dict[str, Any]] = None
    role_level: Optional[str] = None
    implicit_signals: Optional[List[str]] = None
    shortlist_threshold: float
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
