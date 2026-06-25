"""
Score SQLAlchemy model.

Stores the result of semantic scoring for a candidate against a specific job.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Score(Base):
    __tablename__ = "scores"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    candidate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Aggregate scores — all floats in [0.0, 1.0]
    total_score = Column(Float, nullable=False)
    technical_score = Column(Float, nullable=False)
    seniority_score = Column(Float, nullable=False)
    domain_score = Column(Float, nullable=False)

    # Per-skill breakdown and detected red flags
    skills_breakdown = Column(
        JSONB,
        nullable=True,
        comment="Dict of skill_name -> cosine_similarity float",
    )
    red_flags = Column(
        JSONB,
        nullable=True,
        comment="List of {type: str, description: str}",
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    candidate = relationship("Candidate", back_populates="scores")
    job = relationship("Job", back_populates="scores")

    def __repr__(self) -> str:
        return (
            f"<Score id={self.id} candidate_id={self.candidate_id} "
            f"total={self.total_score:.3f}>"
        )
