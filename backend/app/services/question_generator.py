"""
Question Generation Service — Day 3

Calls Google Gemini 2.5 Flash (via the google-genai SDK) to generate
exactly 5 interview questions tailored to both the job and candidate.

Returns a list of question dicts of the shape:
  [
    {
      "id": 1,
      "type": "technical|behavioural|situational",
      "question": "string",
      "time_limit_seconds": int
    }
  ]

Behaviour:
  - Returns ONLY parsed JSON — never raw text
  - Retries once with a stricter prompt on JSON parse failure
  - Raises HTTPException(500) if both attempts fail
"""

import json
import logging
import os

from dotenv import load_dotenv
from fastapi import HTTPException
from google import genai

from app.models.job import Job
from app.models.candidate import Candidate

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Initialise Gemini client once at module level (lazy singleton)
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
You are an expert technical interviewer. Generate exactly 5 interview questions \
for the candidate and job described below.

CRITICAL RULES — READ CAREFULLY:
1. Your ENTIRE response must be a single, valid JSON array.
2. NO markdown code fences (no ```json or ```).
3. NO preamble, explanation, or text before or after the JSON array.
4. The response must be directly parseable by Python's json.loads().
5. The array must contain EXACTLY 5 objects — no more, no less.

Question type distribution (must include at least one of each):
- "technical"    — tests hard skills and domain knowledge
- "behavioural"  — tests past behaviour and soft skills (STAR format)
- "situational"  — tests hypothetical / problem-solving thinking

For each question, set "time_limit_seconds" based on complexity:
- Simple recall or definition questions: 60–90 seconds
- Applied or behavioural questions: 120–180 seconds
- Complex situational or system-design questions: 180–300 seconds

Return EXACTLY this array structure:
[
  {{
    "id": 1,
    "type": "technical|behavioural|situational",
    "question": "<the full interview question>",
    "time_limit_seconds": <int>
  }},
  ...
]

JOB CONTEXT:
- Role level: {role_level}
- Required skills: {required_skills}
- Implicit signals: {implicit_signals}

CANDIDATE CONTEXT:
- Current title: {current_title}
- Listed skills: {listed_skills}
- Experience summary: {experience_summary}
"""

_STRICT_PROMPT = """\
STRICT MODE. Return ONLY a raw JSON array. Zero other characters allowed.

Generate exactly 5 interview questions. Each must have: id (1–5), \
type (technical|behavioural|situational), question (string), \
time_limit_seconds (int between 60 and 300).

Must include at least 1 technical, 1 behavioural, 1 situational question.

[
  {{"id": 1, "type": "technical", "question": "...", "time_limit_seconds": 120}},
  {{"id": 2, "type": "behavioural", "question": "...", "time_limit_seconds": 150}},
  {{"id": 3, "type": "situational", "question": "...", "time_limit_seconds": 180}},
  {{"id": 4, "type": "technical", "question": "...", "time_limit_seconds": 120}},
  {{"id": 5, "type": "behavioural", "question": "...", "time_limit_seconds": 150}}
]

JOB CONTEXT:
- Role level: {role_level}
- Required skills: {required_skills}
- Implicit signals: {implicit_signals}

CANDIDATE CONTEXT:
- Current title: {current_title}
- Listed skills: {listed_skills}
- Experience summary: {experience_summary}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _build_prompt_vars(job: Job, candidate: Candidate) -> dict:
    """Extract prompt interpolation values from ORM objects."""
    required_skills = job.required_skills or []
    # Flatten to readable strings for the prompt
    if required_skills and isinstance(required_skills[0], dict):
        skills_str = ", ".join(
            f"{s.get('name', '')} ({s.get('seniority', 'any')})"
            for s in required_skills
        )
    else:
        skills_str = ", ".join(str(s) for s in required_skills)

    implicit_signals = job.implicit_signals or []
    signals_str = ", ".join(str(s) for s in implicit_signals) if implicit_signals else "none"

    listed_skills = candidate.listed_skills or []
    candidate_skills_str = (
        ", ".join(str(s) for s in listed_skills) if listed_skills else "not specified"
    )

    return {
        "role_level": job.role_level or "not specified",
        "required_skills": skills_str or "not specified",
        "implicit_signals": signals_str,
        "current_title": candidate.current_title or "not specified",
        "listed_skills": candidate_skills_str,
        "experience_summary": candidate.experience_summary or "not provided",
    }


def _validate_questions(data: list) -> list:
    """Validate that the parsed list has exactly 5 properly shaped questions."""
    if not isinstance(data, list) or len(data) != 5:
        raise ValueError(f"Expected list of 5 questions, got {type(data).__name__} of length {len(data) if isinstance(data, list) else '?'}")

    valid_types = {"technical", "behavioural", "situational"}
    type_counts = {"technical": 0, "behavioural": 0, "situational": 0}

    for i, q in enumerate(data, 1):
        if not isinstance(q, dict):
            raise ValueError(f"Question {i} is not a dict")
        if q.get("type") not in valid_types:
            raise ValueError(f"Question {i} has invalid type: {q.get('type')!r}")
        if not isinstance(q.get("question"), str) or not q["question"].strip():
            raise ValueError(f"Question {i} has empty or missing question text")
        if not isinstance(q.get("time_limit_seconds"), int):
            raise ValueError(f"Question {i} has non-integer time_limit_seconds")
        type_counts[q["type"]] += 1

    for qtype, count in type_counts.items():
        if count < 1:
            raise ValueError(f"Must have at least 1 {qtype} question, got 0")

    return data


# ---------------------------------------------------------------------------
# Core generation function
# ---------------------------------------------------------------------------


async def generate_questions(job: Job, candidate: Candidate) -> list[dict]:
    """
    Generate 5 tailored interview questions for a given job and candidate.

    Args:
        job: The Job ORM object (must have required_skills, role_level, implicit_signals).
        candidate: The Candidate ORM object (must have current_title, listed_skills,
                   experience_summary).

    Returns:
        A list of exactly 5 question dicts.

    Raises:
        HTTPException(500): If Gemini response cannot be parsed as valid JSON
                            after two attempts.
    """
    raw = ""
    prompt_vars = _build_prompt_vars(job, candidate)

    # --- Attempt 1: primary prompt ---
    try:
        prompt = _PRIMARY_PROMPT.format(**prompt_vars)
        raw = _clean_response(_call_gemini(prompt))
        data = json.loads(raw)
        questions = _validate_questions(data)
        logger.info("Question generation succeeded on first attempt.")
        return questions
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "First Gemini response was not valid (%s) — retrying with strict prompt.",
            e,
        )
    except Exception as e:
        logger.warning("First Gemini call failed (%s) — retrying.", e)

    # --- Attempt 2: strict prompt ---
    try:
        strict_prompt = _STRICT_PROMPT.format(**prompt_vars)
        raw = _clean_response(_call_gemini(strict_prompt))
        data = json.loads(raw)
        questions = _validate_questions(data)
        logger.info("Question generation succeeded on second (strict) attempt.")
        return questions
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Second Gemini response also failed: %s", e)
        raise HTTPException(
            status_code=500,
            detail=(
                "Gemini returned invalid questions after two attempts. "
                f"Error: {e}. Raw preview: {raw[:300]!r}"
            ),
        )
    except Exception as e:
        logger.error("Second Gemini call raised an exception: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Question generation service error: {e}",
        )
