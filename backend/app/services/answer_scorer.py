"""
Answer Scorer Service — Day 4, Phase 2

Scores a single interview answer against the job requirements using Google Gemini.

Follows the exact same client initialisation and retry pattern as question_generator.py:
  - Module-level google-genai client (singleton)
  - Attempt 1: primary prompt
  - Attempt 2 (on JSON parse failure): stricter prompt
  - Raises HTTPException(500) if both attempts fail

Returns a dict of shape:
  {
    "question_id": int,
    "relevance":      float (0-10),
    "depth":          float (0-10),
    "communication":  float (0-10),
    "specificity":    float (0-10),
    "feedback":       str,
    "red_flag":       bool,
  }
"""

import json
import logging
import os

from dotenv import load_dotenv
from fastapi import HTTPException
from google import genai

from app.models.job import Job

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
You are an expert technical interviewer evaluating a candidate's answer.

CRITICAL RULES:
1. Return only a valid JSON object. Do not include markdown, backticks, or any text outside the JSON object.
2. NO markdown code fences (no ```json or ```).
3. NO preamble, explanation, or text before or after the JSON.
4. All float fields must be numbers between 0 and 10 (inclusive).
5. "red_flag" must be a boolean (true or false).

Rate the candidate's answer on the following dimensions:
- "relevance":     Did the answer address the question? (0-10)
- "depth":         Did the answer demonstrate deep knowledge or insight? (0-10)
- "communication": Was the answer clear, structured, and articulate? (0-10)
- "specificity":   How specific and concrete the candidate's answer was — use of real examples, named technologies, measurable outcomes, or precise details rather than vague generalisations (0-10)
- "feedback":      One concise sentence of constructive feedback.
- "answer_summary": 2-3 sentences: a narrative summary of what the candidate actually said in their answer, written in third person (e.g. "The candidate explained X and gave an example of Y. They demonstrated Z.").
- "red_flag":      true if the answer reveals a serious concern (e.g. dishonesty, severe
                   knowledge gap, inappropriate content), false otherwise.

Return EXACTLY this JSON structure:
{{
  "relevance": <float>,
  "depth": <float>,
  "communication": <float>,
  "specificity": <float>,
  "feedback": "<one sentence>",
  "answer_summary": "<2-3 sentence narrative summary>",
  "red_flag": <bool>
}}

JOB CONTEXT:
- Title: {job_title}
- Required skills: {required_skills}
- Role level: {role_level}

INTERVIEW QUESTION:
{question_text}

CANDIDATE'S ANSWER (transcript):
{transcript}
"""

_STRICT_PROMPT = """\
STRICT MODE. Return only a valid JSON object. Do not include markdown, backticks, or any text outside the JSON object. Zero other characters allowed.

Score this interview answer. All fields required:
- "relevance": float 0-10
- "depth": float 0-10
- "communication": float 0-10
- "specificity": float 0-10
- "feedback": string (one sentence)
- "answer_summary": string (2-3 sentence narrative summary of what the candidate said, in third person)
- "red_flag": boolean

Example format:
{{"relevance": 7.5, "depth": 6.0, "communication": 8.0, "specificity": 8.0, "feedback": "Good structure but lacked specific examples.", "answer_summary": "The candidate explained the core concept clearly. They provided a brief example from their past experience.", "red_flag": false}}

JOB CONTEXT:
- Title: {job_title}
- Required skills: {required_skills}
- Role level: {role_level}

INTERVIEW QUESTION:
{question_text}

CANDIDATE'S ANSWER:
{transcript}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean_response(text: str) -> str:
    """Strip any accidental markdown fences or surrounding whitespace."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        inner = lines[1:-1] if (len(lines) > 1 and lines[-1].strip() == "```") else lines[1:]
        text = "\n".join(inner).strip()
    return text


def _call_gemini(prompt: str) -> str:
    """Send a prompt to Gemini and return the raw text response."""
    response = _client.models.generate_content(
        model=_MODEL,
        contents=prompt,
    )
    return response.text


def _build_prompt_vars(question: dict, transcript: str, job: Job) -> dict:
    """Extract prompt interpolation values from ORM objects and question dict."""
    required_skills = job.required_skills or []
    if required_skills and isinstance(required_skills[0], dict):
        skills_str = ", ".join(
            f"{s.get('name', '')} ({s.get('seniority', 'any')})"
            for s in required_skills
        )
    else:
        skills_str = ", ".join(str(s) for s in required_skills)

    return {
        "job_title": job.title or "not specified",
        "required_skills": skills_str or "not specified",
        "role_level": job.role_level or "not specified",
        "question_text": question.get("question", ""),
        "transcript": transcript or "(no transcript provided)",
    }


def _validate_score(data: dict) -> dict:
    """Validate that the parsed dict has all required fields with correct types."""
    required_float_fields = ("relevance", "depth", "communication")
    for field in required_float_fields:
        if field not in data:
            raise ValueError(f"Missing required field: '{field}'")
        val = data[field]
        if not isinstance(val, (int, float)):
            raise ValueError(f"Field '{field}' must be a number, got {type(val).__name__}")
        if not (0 <= float(val) <= 10):
            raise ValueError(f"Field '{field}' must be between 0 and 10, got {val}")
        data[field] = float(val)

    if "specificity" not in data:
        data["specificity"] = 5.0
    else:
        val = data["specificity"]
        if not isinstance(val, (int, float)):
            raise ValueError(f"Field 'specificity' must be a number, got {type(val).__name__}")
        if not (0 <= float(val) <= 10):
            raise ValueError(f"Field 'specificity' must be between 0 and 10, got {val}")
        data["specificity"] = float(val)

    if "feedback" not in data or not isinstance(data["feedback"], str):
        raise ValueError("Field 'feedback' must be a non-empty string")

    if "answer_summary" not in data or not isinstance(data["answer_summary"], str) or not data["answer_summary"].strip():
        data["answer_summary"] = data.get("feedback", "")

    if "red_flag" not in data or not isinstance(data["red_flag"], bool):
        raise ValueError("Field 'red_flag' must be a boolean")

    return data


# ---------------------------------------------------------------------------
# Core scoring function
# ---------------------------------------------------------------------------


async def score_answer(question: dict, transcript: str, job: Job) -> dict:
    """
    Score a single interview answer using Gemini.

    Args:
        question:   Question dict with at minimum "id" and "question" keys.
        transcript: The candidate's spoken answer (from Whisper transcription).
        job:        The Job ORM object for context.

    Returns:
        A dict with keys: question_id, relevance, depth, communication, feedback, red_flag.

    Raises:
        HTTPException(500): If Gemini fails to return valid JSON after two attempts.
    """
    raw = ""
    prompt_vars = _build_prompt_vars(question, transcript, job)

    # --- Attempt 1: primary prompt ---
    try:
        prompt = _PRIMARY_PROMPT.format(**prompt_vars)
        raw = _clean_response(_call_gemini(prompt))
        data = json.loads(raw)
        validated = _validate_score(data)
        logger.info("Answer scoring succeeded on first attempt for question_id=%s.", question.get("id"))
        return {"question_id": question["id"], **validated}
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "First scoring attempt failed for question_id=%s (%s) — retrying with strict prompt.",
            question.get("id"),
            e,
        )
    except Exception as e:
        logger.warning("First Gemini call failed for question_id=%s (%s) — retrying.", question.get("id"), e)

    # --- Attempt 2: strict prompt ---
    try:
        strict_prompt = _STRICT_PROMPT.format(**prompt_vars)
        raw = _clean_response(_call_gemini(strict_prompt))
        data = json.loads(raw)
        validated = _validate_score(data)
        logger.info("Answer scoring succeeded on second (strict) attempt for question_id=%s.", question.get("id"))
        return {"question_id": question["id"], **validated}
    except (json.JSONDecodeError, ValueError) as e:
        logger.error("Second scoring attempt also failed for question_id=%s: %s", question.get("id"), e)
        raise HTTPException(
            status_code=500,
            detail=(
                f"Answer scoring failed after two attempts for question_id={question.get('id')}. "
                f"Error: {e}. Raw preview: {raw[:300]!r}"
            ),
        )
    except Exception as e:
        logger.error("Second Gemini call raised exception for question_id=%s: %s", question.get("id"), e)
        raise HTTPException(
            status_code=500,
            detail=f"Answer scoring service error for question_id={question.get('id')}: {e}",
        )
