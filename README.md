# Alfaleus — AI-Powered Talent Screening Platform

Alfaleus is a full-stack platform that automates talent discovery and screening using semantic AI. It parses job descriptions with Gemini 1.5 Flash, scrapes candidate profiles from LinkedIn and Indeed, and scores them using sentence-transformers — returning ranked candidates with per-criterion breakdowns and red flags.

---

## Tech Stack

- **Backend**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL (async via asyncpg + SQLAlchemy)
- **ORM**: SQLAlchemy (async) + Alembic migrations
- **LLM**: Google Gemini 1.5 Flash (`google-generativeai`)
- **Embeddings**: `sentence-transformers` (`all-MiniLM-L6-v2`)
- **Scraping**: Playwright (LinkedIn), httpx + BeautifulSoup (Indeed)

---

## Project Structure

```
alfaleus/
  backend/
    app/
      main.py           # FastAPI app entry point
      database.py       # Async SQLAlchemy engine + session
      models/           # SQLAlchemy ORM models
      schemas/          # Pydantic schemas
      routers/          # FastAPI route handlers
      services/         # Business logic (JD analyzer, scorer, scraper)
    alembic/            # Database migrations
    requirements.txt
    .env.example
    Dockerfile
  .gitignore
  README.md
```

---

## Setup

### 1. Clone and install dependencies

```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Fill in all values in .env
```

### 3. Run database migrations

```bash
alembic upgrade head
```

### 4. Start the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/jobs` | Create job from raw JD text |
| POST | `/jobs/{job_id}/scrape` | Scrape candidates for a job |
| POST | `/candidates/score` | Score a single candidate |
| POST | `/candidates/score-all` | Score all candidates for a job |
| POST | `/jobs/{job_id}/run-pipeline` | Full pipeline: scrape → score → shortlist |

---

## Environment Variables

See `.env.example` for all required variables.

---

## Docker

```bash
docker build -t alfaleus-backend ./backend
docker run -p 8000:8000 --env-file backend/.env alfaleus-backend
```
