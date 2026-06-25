"""
Semantic Scoring Service — Phase 3

Scores a Candidate against a Job using sentence-transformers (all-MiniLM-L6-v2).

Scoring breakdown:
  - technical_score  (weight 0.50): cosine similarity of each required skill vs candidate profile
  - seniority_score  (weight 0.25): cosine similarity of role level vs candidate title/summary
  - domain_score     (weight 0.25): cosine similarity of preferred skills/signals vs full profile

Red flags detected:
  - job_hopping:         >3 jobs in any 24-month window, each lasting <8 months
  - title_inflation:     senior title keywords but <5 years total inferred experience
  - skill_mismatch:      skill claimed in listed_skills but downplayed in experience_summary
  - insufficient_data:   confidence_level == "low" — all scores capped at 0.30
"""

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.score import Score

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singleton — model is loaded once on first use, not at import time
# ---------------------------------------------------------------------------

_embedding_model = None


def _get_model():
    """Return the cached SentenceTransformer instance, loading it if needed."""
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading sentence-transformers model all-MiniLM-L6-v2 ...")
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Model loaded successfully.")
    return _embedding_model


# ---------------------------------------------------------------------------
# Embedding helpers
# ---------------------------------------------------------------------------


def _embed(texts: list[str]) -> np.ndarray:
    """Encode a list of strings into unit-normalised embeddings."""
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return np.array(vecs)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity between two 1-D unit-normalised vectors.
    Result is clipped to [0.0, 1.0].
    """
    sim = float(np.dot(a, b))
    return max(0.0, min(1.0, sim))


def _best_match(query_vec: np.ndarray, candidate_vecs: np.ndarray) -> float:
    """Return the highest cosine similarity between query and any candidate vec."""
    sims = candidate_vecs @ query_vec
    return float(np.max(np.clip(sims, 0.0, 1.0)))


# ---------------------------------------------------------------------------
# Profile text builders
# ---------------------------------------------------------------------------


def _build_candidate_profile_text(candidate: Candidate) -> str:
    """Construct a single string representing the full candidate profile."""
    parts: list[str] = []
    if candidate.current_title:
        parts.append(candidate.current_title)
    if candidate.current_company:
        parts.append(f"at {candidate.current_company}")
    if candidate.listed_skills:
        parts.append("skills: " + ", ".join(candidate.listed_skills))
    if candidate.experience_summary:
        parts.append(candidate.experience_summary)
    if candidate.work_history:
        for wh in candidate.work_history:
            title = wh.get("title", "")
            company = wh.get("company", "")
            if title or company:
                parts.append(f"{title} at {company}".strip())
    return " ".join(parts) if parts else "no profile available"


def _build_skills_text(candidate: Candidate) -> str:
    """Short text focused on skills + summary for skill comparison."""
    parts: list[str] = []
    if candidate.listed_skills:
        parts.append(", ".join(candidate.listed_skills))
    if candidate.experience_summary:
        parts.append(candidate.experience_summary)
    return " ".join(parts) if parts else "no skills available"


def _build_seniority_text(candidate: Candidate) -> str:
    """Text focused on seniority signals."""
    parts: list[str] = []
    if candidate.current_title:
        parts.append(candidate.current_title)
    if candidate.experience_summary:
        parts.append(candidate.experience_summary)
    return " ".join(parts) if parts else "no seniority information"


# ---------------------------------------------------------------------------
# Scoring functions
# ---------------------------------------------------------------------------


def _score_technical(job: Job, candidate: Candidate) -> tuple[float, dict[str, float]]:
    """
    Compute technical score and per-skill breakdown.

    For each required skill in the job, encode it as:
        "experience with {skill_name} at {seniority} level"
    Then compute cosine similarity against the candidate profile.

    Returns:
        (technical_score, skills_breakdown_dict)
    """
    required_skills: list[dict] = job.required_skills or []
    if not required_skills:
        return 0.5, {}

    # Build skill query sentences
    skill_queries = [
        f"experience with {s.get('name', 'unknown')} at {s.get('seniority', 'any')} level"
        for s in required_skills
    ]

    # Candidate profile text for skill comparison
    candidate_text = _build_skills_text(candidate)

    # Encode everything in one batch
    all_texts = skill_queries + [candidate_text]
    all_vecs = _embed(all_texts)

    skill_vecs = all_vecs[: len(skill_queries)]  # shape (n_skills, dim)
    candidate_vec = all_vecs[-1]                  # shape (dim,)

    # Per-skill cosine similarity
    skills_breakdown: dict[str, float] = {}
    sims: list[float] = []
    for i, skill in enumerate(required_skills):
        skill_name = skill.get("name", f"skill_{i}")
        sim = _cosine(skill_vecs[i], candidate_vec)
        skills_breakdown[skill_name] = round(sim, 4)
        sims.append(sim)

    technical_score = float(np.mean(sims)) if sims else 0.0
    return round(technical_score, 4), skills_breakdown


def _score_seniority(job: Job, candidate: Candidate) -> float:
    """
    Compute seniority score.

    Encodes the job's role_level + seniority-related implicit signals as one
    sentence, then compares against candidate's title + summary.
    """
    role_level = job.role_level or "mid"
    seniority_signals = [
        sig for sig in (job.implicit_signals or [])
        if any(kw in sig.lower() for kw in [
            "leadership", "senior", "experience", "management", "lead", "ownership"
        ])
    ]

    job_seniority_text = f"{role_level} level engineer"
    if seniority_signals:
        job_seniority_text += ". " + ". ".join(seniority_signals)

    candidate_text = _build_seniority_text(candidate)

    vecs = _embed([job_seniority_text, candidate_text])
    return round(_cosine(vecs[0], vecs[1]), 4)


def _score_domain(job: Job, candidate: Candidate) -> float:
    """
    Compute domain score.

    Encodes job's preferred_skills + all implicit_signals as one combined sentence,
    then compares against the candidate's full profile.
    """
    preferred = ", ".join(job.preferred_skills or [])
    signals = ". ".join(job.implicit_signals or [])
    job_domain_text = " ".join(filter(None, [preferred, signals])) or "general software engineering"

    candidate_text = _build_candidate_profile_text(candidate)

    vecs = _embed([job_domain_text, candidate_text])
    return round(_cosine(vecs[0], vecs[1]), 4)


# ---------------------------------------------------------------------------
# Red flag detection
# ---------------------------------------------------------------------------


def _detect_red_flags(candidate: Candidate) -> list[dict]:
    """
    Analyse candidate data for red flags. Returns a list of
    {type: str, description: str} dicts.
    """
    flags: list[dict] = []

    # ── 1. Job hopping ──────────────────────────────────────────────────────
    work_history: list[dict] = candidate.work_history or []
    if work_history:
        # Sort jobs by some order (we can't always get start dates from scrapes,
        # so we use list order as a proxy for chronological order)
        short_stints = [
            wh for wh in work_history
            if isinstance(wh.get("duration_months"), (int, float))
            and wh["duration_months"] < 8
        ]

        # Sliding 24-month window check
        durations = [
            int(wh.get("duration_months", 0))
            for wh in work_history
            if isinstance(wh.get("duration_months"), (int, float))
        ]

        hopping_detected = False
        for i in range(len(durations)):
            window_months = 0
            window_jobs = 0
            for j in range(i, len(durations)):
                d = durations[j]
                if window_months + d <= 24:
                    if d < 8:
                        window_jobs += 1
                    window_months += d
                else:
                    break
            if window_jobs > 3:
                hopping_detected = True
                break

        if hopping_detected:
            short_companies = [
                f"{wh.get('company', '?')} ({wh.get('duration_months', '?')}mo)"
                for wh in work_history
                if isinstance(wh.get("duration_months"), (int, float))
                and wh["duration_months"] < 8
            ]
            flags.append({
                "type": "job_hopping",
                "description": (
                    f"Candidate held more than 3 jobs lasting under 8 months "
                    f"within a 24-month window. Short tenures: {', '.join(short_companies[:5])}"
                ),
            })

    # ── 2. Title inflation ───────────────────────────────────────────────────
    _SENIOR_TITLE_KEYWORDS = {
        "director", "vp", "vice president", "chief", "cto", "coo", "ceo", "head of"
    }
    title_lower = (candidate.current_title or "").lower()
    has_senior_title = any(kw in title_lower for kw in _SENIOR_TITLE_KEYWORDS)

    if has_senior_title:
        # Estimate total experience from work_history durations
        total_months = sum(
            int(wh.get("duration_months", 0))
            for wh in work_history
            if isinstance(wh.get("duration_months"), (int, float))
        )
        total_years = total_months / 12

        # Also check experience_summary for junior-sounding language
        summary_lower = (candidate.experience_summary or "").lower()
        junior_signals = ["junior", "entry level", "fresh graduate", "2 years", "1 year"]
        summary_is_junior = any(sig in summary_lower for sig in junior_signals)

        if total_years < 5 or summary_is_junior:
            flags.append({
                "type": "title_inflation",
                "description": (
                    f"Candidate holds title '{candidate.current_title}' but "
                    f"estimated total experience is {total_years:.1f} years "
                    f"(threshold: 5 years for executive/director titles)."
                ),
            })

    # ── 3. Skill level mismatch ──────────────────────────────────────────────
    _WEAK_PHRASES = [
        "familiar with", "familiarity with",
        "exposure to", "some exposure",
        "basic knowledge of", "basic understanding of",
        "introductory", "learning", "beginner",
    ]
    listed = [s.lower() for s in (candidate.listed_skills or [])]
    summary_lower = (candidate.experience_summary or "").lower()

    for skill_raw in (candidate.listed_skills or []):
        skill_lower = skill_raw.lower()
        for phrase in _WEAK_PHRASES:
            pattern = rf"{re.escape(phrase)}\s+{re.escape(skill_lower)}"
            if re.search(pattern, summary_lower):
                flags.append({
                    "type": "skill_mismatch",
                    "description": (
                        f"Skill '{skill_raw}' is listed but experience summary "
                        f"indicates weak proficiency (phrase detected: '{phrase} {skill_lower}')."
                    ),
                })
                break  # One flag per skill

    return flags


# ---------------------------------------------------------------------------
# Main scoring entry point
# ---------------------------------------------------------------------------


def score_candidate(job: Job, candidate: Candidate) -> Score:
    """
    Score a Candidate against a Job and return an unsaved Score ORM object.

    Args:
        job:       Job ORM instance (must have required_skills, role_level, etc.)
        candidate: Candidate ORM instance.

    Returns:
        Score ORM instance (NOT yet added to any session — caller must persist it).
    """
    logger.info(
        "Scoring candidate=%s against job=%s", candidate.id, job.id
    )

    # ── Low-confidence fast path ─────────────────────────────────────────────
    if candidate.confidence_level == "low":
        logger.info(
            "Candidate %s has low confidence — capping scores at 0.30.", candidate.id
        )
        return Score(
            id=uuid.uuid4(),
            candidate_id=candidate.id,
            job_id=job.id,
            total_score=0.30,
            technical_score=0.30,
            seniority_score=0.30,
            domain_score=0.30,
            skills_breakdown={},
            red_flags=[{
                "type": "insufficient_data",
                "description": (
                    "Candidate profile has low confidence — only minimal information "
                    "available (name/title only). Scores capped at 0.30."
                ),
            }],
            created_at=datetime.now(timezone.utc),
        )

    # ── Compute sub-scores ───────────────────────────────────────────────────
    technical_score, skills_breakdown = _score_technical(job, candidate)
    seniority_score = _score_seniority(job, candidate)
    domain_score = _score_domain(job, candidate)

    # ── Weighted total ───────────────────────────────────────────────────────
    total_score = round(
        0.50 * technical_score
        + 0.25 * seniority_score
        + 0.25 * domain_score,
        4,
    )

    # ── Red flags ────────────────────────────────────────────────────────────
    red_flags = _detect_red_flags(candidate)

    logger.info(
        "Score result: total=%.3f technical=%.3f seniority=%.3f domain=%.3f flags=%d",
        total_score,
        technical_score,
        seniority_score,
        domain_score,
        len(red_flags),
    )

    return Score(
        id=uuid.uuid4(),
        candidate_id=candidate.id,
        job_id=job.id,
        total_score=total_score,
        technical_score=technical_score,
        seniority_score=seniority_score,
        domain_score=domain_score,
        skills_breakdown=skills_breakdown,
        red_flags=red_flags,
        created_at=datetime.now(timezone.utc),
    )
