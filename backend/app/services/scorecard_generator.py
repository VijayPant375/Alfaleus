"""
Scorecard Generator Service — Day 4, Phase 3

Generates a holistic interview scorecard by combining the candidate's profile
scores (from the Day 1/2 semantic scorer) with their interview answer scores.

Follows the exact same client initialisation and retry pattern as
question_generator.py and answer_scorer.py:
  - Module-level google-genai client (singleton)
  - Attempt 1: primary prompt
  - Attempt 2 (on JSON parse failure): stricter prompt
  - Raises HTTPException(500) if both attempts fail

Returns a dict of shape:
  {
    "overall_recommendation": "strong_yes | yes | maybe | no",
    "summary":                 str  (2-3 sentences),
    "strengths":               [str],
    "concerns":                [str],
    "interview_highlights":    [str],
    "suggested_follow_up_questions": [str],
  }
"""

import json
import logging
import os

from dotenv import load_dotenv
from fastapi import HTTPException
from google import genai

from app.models.candidate import Candidate
from app.models.interview_session import InterviewSession
from app.models.job import Job
from app.models.score import Score

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini client — same singleton pattern as question_generator.py
# ---------------------------------------------------------------------------

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not _GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

_client = genai.Client(api_key=_GEMINI_API_KEY)

_MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_PRIMARY_PROMPT = """\
You are a senior hiring manager writing a comprehensive interview scorecard.

CRITICAL RULES:
1. Your ENTIRE response must be a single, valid JSON object.
2. NO markdown code fences (no ```json or ```).
3. NO preamble, explanation, or text before or after the JSON.
4. "overall_recommendation" must be exactly one of: "strong_yes", "yes", "maybe", "no".
5. "summary" must be 2-3 sentences.
6. "strengths", "concerns", "interview_highlights", "suggested_follow_up_questions"
   must each be a JSON array of strings (at least 1 item each).

Based on the full profile and interview data below, return EXACTLY this structure:
{{
  "overall_recommendation": "strong_yes | yes | maybe | no",
  "summary": "<2-3 sentence summary>",
  "strengths": ["<strength 1>", "..."],
  "concerns": ["<concern 1>", "..."],
  "interview_highlights": ["<highlight 1>", "..."],
  "suggested_follow_up_questions": ["<question 1>", "..."]
}}

JOB CONTEXT:
- Title: {job_title}
- Role level: {role_level}
- Required skills: {required_skills}

CANDIDATE PROFILE:
- Name: {candidate_name}
- Current title: {current_title}
- Current company: {current_company}

PROFILE SCORES (0.0 – 1.0 scale):
- Technical score:  {technical_score}
- Seniority score:  {seniority_score}
- Domain score:     {domain_score}
- Profile red flags: {red_flags}

INTERVIEW ANSWER SCORES:
{answer_scores_text}

Overall interview score (0–10): {overall_interview_score}
"""

_STRICT_PROMPT = """\
STRICT MODE. Return ONLY a raw JSON object. Zero other characters allowed.

Generate a hiring scorecard. Required fields:
- "overall_recommendation": one of "strong_yes", "yes", "maybe", "no"
- "summary": 2-3 sentence string
- "strengths": array of strings
- "concerns": array of strings
- "interview_highlights": array of strings
- "suggested_follow_up_questions": array of strings

Example format:
{{
  "overall_recommendation": "yes",
  "summary": "The candidate demonstrated solid technical knowledge with room to grow.",
  "strengths": ["Strong Python skills", "Good communication"],
  "concerns": ["Limited leadership experience"],
  "interview_highlights": ["Excellent answer on system design"],
  "suggested_follow_up_questions": ["How do you handle cross-team conflict?"]
}}

JOB: {job_title} ({role_level})
Required skills: {required_skills}

CANDIDATE: {candidate_name} — {current_title} at {current_company}
Technical: {technical_score}, Seniority: {seniority_score}, Domain: {domain_score}
Red flags: {red_flags}

INTERVIEW SCORES:
{answer_scores_text}
Overall interview score: {overall_interview_score}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_RECOMMENDATIONS = {"strong_yes", "yes", "maybe", "no"}


def _clean_response(text: str) -> str:
    """Strip any accidental markdown fences or surrounding whitespace."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if lines and lines[-1].strip() == "```" else lines[1:]
        text = "\n".join(inner).strip()
    return text


def _call_gemini(prompt: str) -> str:
    """Send a prompt to Gemini and return the raw text response."""
    response = _client.models.generate_content(
        model=_MODEL,
        contents=prompt,
    )
    return response.text


def _format_answer_scores(answer_scores: list) -> str:
    """Format the per-answer scores list into a readable prompt block."""
    if not answer_scores:
        return "  (no answer scores available)"
    lines = []
    for s in answer_scores:
        qid = s.get("question_id", "?")
        rel = s.get("relevance", 0)
        dep = s.get("depth", 0)
        com = s.get("communication", 0)
        fb = s.get("feedback", "")
        rf = "⚑ RED FLAG" if s.get("red_flag") else ""
        lines.append(
            f"  Q{qid}: relevance={rel}/10  depth={dep}/10  communication={com}/10  "
            f"{rf}\n       Feedback: {fb}"
        )
    return "\n".join(lines)


def _build_prompt_vars(
    job: Job,
    candidate: Candidate,
    session: InterviewSession,
    profile_score: Score,
) -> dict:
    """Extract all prompt interpolation values from ORM objects."""
    required_skills = job.required_skills or []
    if required_skills and isinstance(required_skills[0], dict):
        skills_str = ", ".join(
            f"{s.get('name', '')} ({s.get('seniority', 'any')})"
            for s in required_skills
        )
    else:
        skills_str = ", ".join(str(s) for s in required_skills)

    red_flags = profile_score.red_flags or []
    if red_flags and isinstance(red_flags[0], dict):
        red_flags_str = "; ".join(
            f"{f.get('type', '')}: {f.get('description', '')}"
            for f in red_flags
        ) or "none"
    else:
        red_flags_str = ", ".join(str(f) for f in red_flags) or "none"

    answer_scores = session.answer_scores or []

    return {
        "job_title": job.title or "not specified",
        "role_level": job.role_level or "not specified",
        "required_skills": skills_str or "not specified",
        "candidate_name": candidate.name or "Unknown",
        "current_title": candidate.current_title or "not specified",
        "current_company": candidate.current_company or "not specified",
        "technical_score": f"{profile_score.technical_score:.3f}",
        "seniority_score": f"{profile_score.seniority_score:.3f}",
        "domain_score": f"{profile_score.domain_score:.3f}",
        "red_flags": red_flags_str,
        "answer_scores_text": _format_answer_scores(answer_scores),
        "overall_interview_score": f"{session.overall_interview_score:.2f}" if session.overall_interview_score is not None else "N/A",
    }


def _validate_scorecard(data: dict) -> dict:
    """Validate that all required fields exist with correct types."""
    if data.get("overall_recommendation") not in _VALID_RECOMMENDATIONS:
        raise ValueError(
            f"'overall_recommendation' must be one of {_VALID_RECOMMENDATIONS}, "
            f"got {data.get('overall_recommendation')!r}"
        )

    if not isinstance(data.get("summary"), str) or not data["summary"].strip():
        raise ValueError("'summary' must be a non-empty string")

    array_fields = (
        "strengths",
        "concerns",
        "interview_highlights",
        "suggested_follow_up_questions",
    )
    for field in array_fields:
        if not isinstance(data.get(field), list):
            raise ValueError(f"'{field}' must be a JSON array")

    return data


# ---------------------------------------------------------------------------
# Core generation function
# ---------------------------------------------------------------------------


async def generate_scorecard(
    job: Job,
    candidate: Candidate,
    session: InterviewSession,
    profile_score: Score,
) -> dict:
    """
    Generate a holistic interview scorecard using Gemini.

    Args:
        job:           The Job ORM object.
        candidate:     The Candidate ORM object.
        session:       The InterviewSession (must have answer_scores populated).
        profile_score: The Score ORM object from the semantic scorer.

    Returns:
        A validated scorecard dict.

    Raises:
        HTTPException(500): If Gemini fails to return valid JSON after two attempts.
    """
    raw = ""
    prompt_vars = _build_prompt_vars(job, candidate, session, profile_score)

    # --- Attempt 1: primary prompt ---
    try:
        prompt = _PRIMARY_PROMPT.format(**prompt_vars)
        raw = _clean_response(_call_gemini(prompt))
        data = json.loads(raw)
        validated = _validate_scorecard(data)
        logger.info(
            "Scorecard generation succeeded on first attempt for candidate %s.",
            candidate.id,
        )
        return validated
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "First scorecard attempt failed for candidate %s (%s) — retrying with strict prompt.",
            candidate.id,
            e,
        )
    except Exception as e:
        logger.warning(
            "First Gemini call failed for scorecard (candidate %s): %s — retrying.",
            candidate.id,
            e,
        )

    # --- Attempt 2: strict prompt ---
    try:
        strict_prompt = _STRICT_PROMPT.format(**prompt_vars)
        raw = _clean_response(_call_gemini(strict_prompt))
        data = json.loads(raw)
        validated = _validate_scorecard(data)
        logger.info(
            "Scorecard generation succeeded on second (strict) attempt for candidate %s.",
            candidate.id,
        )
        return validated
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(
            "Second scorecard attempt also failed for candidate %s: %s",
            candidate.id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"Scorecard generation failed after two attempts for candidate {candidate.id}. "
                f"Error: {e}. Raw preview: {raw[:300]!r}"
            ),
        )
    except Exception as e:
        logger.error(
            "Second Gemini call raised exception for scorecard (candidate %s): %s",
            candidate.id,
            e,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Scorecard generation service error for candidate {candidate.id}: {e}",
        )
