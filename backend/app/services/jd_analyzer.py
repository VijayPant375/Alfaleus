"""
JD Analysis Service — Phase 2

Calls Google Gemini 2.5 Flash (via the google-genai SDK) to extract structured
data from raw job description text.

Returns a JobAnalysisResult with:
  - required_skills  (list of {name, seniority})
  - preferred_skills (list of strings)
  - experience_range ({min, max} years)
  - role_level       (junior | mid | senior | lead)
  - implicit_signals (list of strings)

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

from app.schemas.job import JobAnalysisResult

load_dotenv()

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Initialise Gemini client once at module level (lazy singleton)
# ---------------------------------------------------------------------------

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not _GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

_client = genai.Client(api_key=_GEMINI_API_KEY)

# Use gemini-2.5-flash (the available Flash model on this API key)
_MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_PRIMARY_PROMPT = """\
You are a structured data extraction engine. Analyse the job description below.

CRITICAL RULES — READ CAREFULLY:
1. Your ENTIRE response must be a single, valid JSON object.
2. NO markdown code fences (no ```json or ```).
3. NO preamble, explanation, or text before or after the JSON.
4. The response must be directly parseable by Python's json.loads().

Extract and return exactly these keys:

{{
  "required_skills": [
    {{"name": "<skill name>", "seniority": "<junior|mid|senior|lead|any>"}}
  ],
  "preferred_skills": ["<skill>", "..."],
  "experience_range": {{"min": <int years>, "max": <int years>}},
  "role_level": "<junior|mid|senior|lead>",
  "implicit_signals": [
    "<non-obvious requirement extracted from context>",
    "..."
  ]
}}

For implicit_signals, capture things like:
- "startup tolerance" when text says "fast-paced" or "high ambiguity"
- "leadership readiness" when text says "stakeholder management" or "cross-functional"
- "on-call availability" when text says "24/7" or "production support"
- "autonomous work style" when text says "self-starter" or "minimal supervision"

JOB DESCRIPTION:
{description}
"""

_STRICT_PROMPT = """\
STRICT MODE. Return ONLY a raw JSON object. Zero other characters allowed.

Parse this job description and return EXACTLY this structure — nothing else:
{{
  "required_skills": [{{"name": "string", "seniority": "junior|mid|senior|lead|any"}}],
  "preferred_skills": ["string"],
  "experience_range": {{"min": 0, "max": 10}},
  "role_level": "junior|mid|senior|lead",
  "implicit_signals": ["string"]
}}

JOB DESCRIPTION:
{description}
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


# ---------------------------------------------------------------------------
# Core analysis function
# ---------------------------------------------------------------------------


async def analyze_job_description(description: str) -> JobAnalysisResult:
    """
    Extract structured fields from raw JD text using Gemini 2.5 Flash.

    Args:
        description: Raw job description text.

    Returns:
        JobAnalysisResult with all structured fields populated.

    Raises:
        HTTPException(500): If Gemini response cannot be parsed as valid JSON
                            after two attempts.
    """
    raw = ""  # Keep in scope for error reporting

    # --- Attempt 1: primary prompt ---
    try:
        prompt = _PRIMARY_PROMPT.format(description=description)
        raw = _clean_response(_call_gemini(prompt))
        data = json.loads(raw)
        logger.info("JD analysis succeeded on first attempt.")
        return JobAnalysisResult(**data)
    except json.JSONDecodeError as e:
        logger.warning(
            "First Gemini response was not valid JSON (%s) — retrying with strict prompt.",
            e,
        )
    except Exception as e:
        logger.warning("First Gemini call failed (%s) — retrying.", e)

    # --- Attempt 2: strict prompt ---
    try:
        strict_prompt = _STRICT_PROMPT.format(description=description)
        raw = _clean_response(_call_gemini(strict_prompt))
        data = json.loads(raw)
        logger.info("JD analysis succeeded on second (strict) attempt.")
        return JobAnalysisResult(**data)
    except json.JSONDecodeError as e:
        logger.error("Second Gemini response also failed JSON parse: %s", e)
        raise HTTPException(
            status_code=500,
            detail=(
                "Gemini returned invalid JSON after two attempts. "
                f"Parse error: {e}. Raw preview: {raw[:300]!r}"
            ),
        )
    except Exception as e:
        logger.error("Second Gemini call raised an exception: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"JD analysis service error: {e}",
        )
