# Alfaleus

## Project Overview

Alfaleus is a full-stack AI hiring platform designed to automate and streamline the talent screening process. A recruiter posts a job description, and the system automatically scrapes candidate profiles from platforms like LinkedIn and Indeed. Each candidate is semantically scored against the job requirements, and shortlisted candidates receive an email containing a link for an async video interview.

During the interview phase, candidates record their answers using a dedicated Android application. The app handles chunked video uploads and includes resume-on-failure logic to ensure reliable data transmission. Once uploaded, the backend transcribes the video answers using a self-hosted Whisper model and evaluates them using Gemini. This generates a structured scorecard for each candidate.

The final output is presented to the recruiter via a web dashboard. The dashboard features a ranked pipeline view, side-by-side candidate comparisons, and AI-generated justifications for the rankings, enabling data-driven hiring decisions.

## Architecture Diagram

```text
Recruiter
   │
   ▼ (Creates Job)
Backend API
   │
   ├─► Scraper (LinkedIn/Indeed / Mock Fallback) ◄── Candidates Data
   │
   ├─► Semantic Scorer (sentence-transformers)
   │
   ▼
Shortlisted Candidates
   │
   ▼ (Email sent via Resend with deep link)
Candidate
   │
   ▼ (Opens Mobile App)
Mobile App (Android / Expo) ──► Storage (Chunked Video Upload to Supabase)
   │
   ▼ (Video chunks complete)
Backend API
   │
   ├─► Transcription (Whisper)
   │
   ├─► Scoring (Gemini)
   │
   ▼
Recruiter Dashboard
   │
   ▼
Ranked Pipeline & AI Comparison
```

## Tech Stack

| Area | Technology |
|---|---|
| **Backend** | FastAPI (Python) on Railway |
| **Database** | PostgreSQL on Railway, SQLAlchemy async + asyncpg, Alembic migrations |
| **LLM** | Google Gemini 2.5 Flash via `google-genai` SDK |
| **Embeddings** | `sentence-transformers` (`all-MiniLM-L6-v2`) |
| **Transcription** | Whisper (base model, CPU, self-hosted) |
| **Storage** | Supabase Storage (video chunks) |
| **Email** | Resend |
| **Web frontend** | Next.js 14 App Router, TypeScript, Tailwind CSS, deployed on Vercel |
| **Mobile** | Expo SDK 56 with expo-router, Android APK via EAS Build |
| **Scraping** | Playwright (LinkedIn) + httpx + BeautifulSoup (Indeed), mock fallback when blocked |

## Features

* **JD analysis**: Gemini parses job descriptions into structured signals (required skills, preferred skills, experience range, role level, implicit signals).
* **Scraping with mock fallback**: Scrapes candidates from LinkedIn and Indeed (up to 5 pages per source), falling back to mock data if blocked.
* **Semantic scoring**: `sentence-transformers` scores each candidate semantically, generating a technical score, seniority score, domain score, combined total score, and identifying red flags.
* **Async video interviews**: Shortlisted candidates receive an email with a deep link (`alfaleus://interview/{token}`) that expires after 7 days.
* **Think timer**: 30-second think timer per question prior to recording.
* **Chunked upload with retry and resume**: 2MB chunks with 3-attempt retry per chunk and resume-on-failure if the app is closed mid-interview.
* **Review screen**: Allows candidates to review answers before final submission.
* **Whisper transcription**: Self-hosted Whisper transcribes video answers.
* **Gemini answer scoring with answer summaries**: Evaluates relevance, depth, communication, and feedback.
* **Scorecard generation**: Full AI-generated scorecard for each interview.
* **Recruiter pipeline dashboard**: Pipeline view with sortable scores and candidate detail with per-answer breakdown.
* **Candidate comparison with AI ranking**: Side-by-side comparison with expandable answer summaries and Gemini-generated ranked justification.

## Project Structure

```text
├── backend/       # FastAPI application, database models, AI services, and scrapers
├── mobile/        # Expo React Native Android application for candidate interviews
├── web/           # Next.js 14 recruiter dashboard
└── scripts/       # Utility scripts for database seeding or one-off tasks
```

## Getting Started

### Prerequisites

* Python 3.11+
* Node 18+
* Expo CLI
* EAS CLI
* Railway CLI

### Environment Variables

Key environment variables required for backend and web:

* `DATABASE_URL`
* `GEMINI_API_KEY`
* `SUPABASE_URL`
* `SUPABASE_KEY`
* `RESEND_API_KEY`
* `CORS_ALLOWED_ORIGINS`
* `NEXT_PUBLIC_API_URL`

### Running the Backend Locally

```bash
cd backend
uvicorn app.main:app --reload
```

### Running the Web Frontend Locally

```bash
cd web
npm run dev
```

### Running the Mobile App Locally

```bash
cd mobile
npx expo start
```

## Deployment

**Railway (Backend + Database):** Deploy using the Railway CLI (`railway up`). Alembic migrations run automatically on start.

**Vercel (Web):** Deploy using the Vercel CLI (`vercel --prod`).

**EAS Build (Android APK):** Build the Android APK using EAS CLI (`eas build --platform android --profile preview`).

## API Overview

| Area | Method | Path | Description |
|---|---|---|---|
| **Jobs** | GET | `/jobs` | List all jobs |
| | POST | `/jobs` | Create a new job |
| | GET | `/jobs/{id}` | Get details of a specific job |
| **Candidates** | GET | `/candidates` | List candidates associated with a job |
| | GET | `/candidates/{id}` | Get candidate details and scores |
| | POST | `/candidates/scrape` | Trigger profile scraping for a job |
| **Interview** | GET | `/interview/{token}` | Get interview session details by token |
| | POST | `/interview/upload-chunk` | Upload a video chunk for a question |
| | POST | `/interview/submit` | Finalize interview and trigger scoring pipeline |
| | POST | `/interview/compare` | Compare multiple candidates for a job |

## AI Pipeline

The AI pipeline is composed of three main components: Gemini, `sentence-transformers`, and Whisper. Gemini first parses the job description into structured requirements. Then, `sentence-transformers` generates embeddings for both the job requirements and the scraped candidate profiles, matching them to produce a semantic score. During the interview phase, candidates' video answers are transcribed locally using Whisper (CPU). Finally, the transcriptions are passed back to Gemini, which scores the answers for depth and relevance, summarizes them, and generates a ranked justification for candidate comparison on the recruiter dashboard.

## Known Limitations

* LinkedIn scraping may be blocked without proxies (mock fallback activates when blocked).
* Whisper runs on CPU, which can result in slow processing on cold start.
* Gemini free tier rate limits may affect concurrent candidate scoring.
* There is no authentication layer on the recruiter dashboard.
