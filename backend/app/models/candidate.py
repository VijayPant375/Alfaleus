"""
Candidate SQLAlchemy model.

Represents a scraped or manually added candidate linked to a specific job posting.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False,
    )
    job_id = Column(
        UUID(as_uuid=True),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Profile fields — nullable because scrapers may return partial data
    name = Column(String(255), nullable=True)
    current_title = Column(String(255), nullable=True)
    current_company = Column(String(255), nullable=True)
    listed_skills = Column(
        JSONB,
        nullable=True,
        comment="List of skill strings",
    )
    experience_summary = Column(Text, nullable=True)
    work_history = Column(
        JSONB,
        nullable=True,
        comment="List of {title, company, duration_months}",
    )

    # Provenance
    source = Column(String(50), nullable=False, comment="linkedin | indeed | manual")
    profile_url = Column(String(1024), nullable=True)

    # Quality / workflow state
    confidence_level = Column(
        String(10),
        nullable=False,
        default="low",
        comment="high | medium | low",
    )
    shortlisted = Column(Boolean, nullable=False, default=False)
    shortlist_override = Column(Boolean, nullable=False, default=False)
    interview_status = Column(
        String(20),
        nullable=False,
        default="not_invited",
        comment="not_invited | invited | in_progress | completed",
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    job = relationship("Job", back_populates="candidates")
    scores = relationship("Score", back_populates="candidate", lazy="noload")

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} name={self.name!r} job_id={self.job_id}>"
