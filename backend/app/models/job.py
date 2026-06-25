"""
Job SQLAlchemy model.

Represents a job posting with structured JD analysis results stored as JSONB.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Job(Base):
    __tablename__ = "jobs"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)

    # Structured fields extracted by the JD analyzer (Gemini)
    required_skills = Column(
        JSONB,
        nullable=True,
        comment="List of {name: str, seniority: junior|mid|senior|lead|any}",
    )
    preferred_skills = Column(
        JSONB,
        nullable=True,
        comment="List of strings",
    )
    experience_range = Column(
        JSONB,
        nullable=True,
        comment="{min: int, max: int} years",
    )
    role_level = Column(
        String(20),
        nullable=True,
        comment="junior | mid | senior | lead",
    )
    implicit_signals = Column(
        JSONB,
        nullable=True,
        comment="Non-obvious requirements extracted from JD text",
    )

    # Scoring / workflow config
    shortlist_threshold = Column(Float, nullable=False, default=0.65)
    status = Column(String(20), nullable=False, default="active")

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    candidates = relationship("Candidate", back_populates="job", lazy="noload")
    scores = relationship("Score", back_populates="job", lazy="noload")

    def __repr__(self) -> str:
        return f"<Job id={self.id} title={self.title!r} status={self.status}>"
