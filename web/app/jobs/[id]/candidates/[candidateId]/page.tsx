"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ──────────────────────────────────────────────────────────────────────

interface Candidate {
  id: string;
  name: string | null;
  current_title: string | null;
  current_company: string | null;
  shortlisted: boolean;
  shortlist_override: boolean;
  interview_status: string;
  scorecard: Scorecard | null;
  overall_interview_score: number | null;
  answer_scores: AnswerScore[] | null;
}

interface Score {
  candidate_id: string;
  total_score: number;
  technical_score: number;
  seniority_score: number;
  domain_score: number;
  skills_breakdown: Record<string, number> | null;
  red_flags: { type: string; description: string }[] | null;
}

interface Scorecard {
  overall_recommendation: "strong_yes" | "yes" | "maybe" | "no";
  summary: string;
  strengths: string[];
  concerns: string[];
  interview_highlights: string[];
  suggested_follow_up_questions: string[];
}

interface AnswerScore {
  question_id: number;
  relevance: number;
  depth: number;
  communication: number;
  specificity?: number;
  feedback: string;
  answer_summary?: string;
  red_flag: boolean;
}

// ── UI Components ─────────────────────────────────────────────────────────────

function RecommendationBadge({ rec }: { rec: string }) {
  const map: Record<string, { label: string; color: string; bg: string }> = {
    strong_yes: { label: "Strong Yes", color: "#22c55e", bg: "rgba(34,197,94,0.12)" },
    yes: { label: "Yes", color: "#3b82f6", bg: "rgba(59,130,246,0.12)" },
    maybe: { label: "Maybe", color: "#eab308", bg: "rgba(234,179,8,0.12)" },
    no: { label: "No", color: "#ef4444", bg: "rgba(239,68,68,0.12)" },
  };
  const c = map[rec] ?? { label: rec, color: "#9898bb", bg: "rgba(152,152,187,0.12)" };
  return (
    <span
      style={{
        fontSize: 13,
        fontWeight: 700,
        color: c.color,
        background: c.bg,
        border: `1px solid ${c.color}33`,
        borderRadius: 20,
        padding: "4px 14px",
        letterSpacing: "0.03em",
      }}
    >
      {c.label}
    </span>
  );
}

function InterviewStatusBadge({ status }: { status: string }) {
  const map: Record<string, { color: string; bg: string }> = {
    not_invited: { color: "#5a5a7a", bg: "rgba(90,90,122,0.1)" },
    invited: { color: "#6c63ff", bg: "rgba(108,99,255,0.12)" },
    in_progress: { color: "#eab308", bg: "rgba(234,179,8,0.12)" },
    completed: { color: "#22c55e", bg: "rgba(34,197,94,0.12)" },
  };
  const c = map[status] ?? { color: "#9898bb", bg: "rgba(152,152,187,0.12)" };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: c.color,
        background: c.bg,
        borderRadius: 20,
        padding: "3px 10px",
        textTransform: "capitalize",
        whiteSpace: "nowrap",
      }}
    >
      {status.replace(/_/g, " ")}
    </span>
  );
}

function ShortlistBadge({ shortlisted, override }: { shortlisted: boolean; override: boolean }) {
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: shortlisted ? "#22c55e" : "#5a5a7a",
        background: shortlisted ? "rgba(34,197,94,0.12)" : "rgba(90,90,122,0.1)",
        borderRadius: 20,
        padding: "3px 10px",
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
      }}
    >
      {shortlisted ? "✓ Shortlisted" : "Not listed"}
      {override && <span style={{ fontSize: 9, opacity: 0.7 }}>OVERRIDE</span>}
    </span>
  );
}

function ScoreBar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.min(100, Math.round((value / max) * 100));
  const colour = pct >= 70 ? "#22c55e" : pct >= 45 ? "#eab308" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div
        style={{
          flex: 1,
          height: 4,
          background: "#2a2a3a",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: colour,
            borderRadius: 2,
            transition: "width 0.5s ease",
          }}
        />
      </div>
      <span style={{ fontSize: 12, color: colour, fontWeight: 600, minWidth: 32, textAlign: "right" }}>
        {(value * 100).toFixed(0)}%
      </span>
    </div>
  );
}

function MiniScore({ val }: { val: number | null | undefined }) {
  if (val == null) return <span style={{ color: "var(--text-muted)", fontSize: 14 }}>—</span>;
  const pct = Math.max(0, Math.min(100, (val / 10) * 100));
  const color = val >= 7 ? "var(--green)" : val >= 4.5 ? "var(--yellow)" : "var(--red)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, width: 48 }}>
      <span style={{ color: "var(--text-primary)", fontSize: 14 }}>{val.toFixed(1)}</span>
      <div style={{ height: 3, background: "var(--border)", borderRadius: 2, width: "100%", overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function CandidateDetailPage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.id as string;
  const candidateId = params.candidateId as string;

  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [score, setScore] = useState<Score | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [candRes, scoreRes] = await Promise.all([
        fetch(`${API}/candidates/${candidateId}`),
        fetch(`${API}/candidates/${candidateId}/score`),
      ]);
      if (!candRes.ok) throw new Error(`Candidate fetch: HTTP ${candRes.status}`);
      
      const candData = await candRes.json();
      setCandidate(candData);

      if (scoreRes.ok) {
        setScore(await scoreRes.json());
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [candidateId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "80px 0" }}>
        <div style={{ width: 36, height: 36, borderRadius: "50%", border: "3px solid #2a2a3a", borderTopColor: "#6c63ff", animation: "spin 0.8s linear infinite" }} />
        <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
      </div>
    );
  }

  if (error || !candidate) {
    return (
      <div style={{ maxWidth: 1280, margin: "0 auto", padding: "40px 24px" }}>
        <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 12, padding: 20, color: "#fca5a5", fontSize: 14 }}>
          ⚠ {error || "Candidate not found"}
        </div>
      </div>
    );
  }

  const sc = candidate.scorecard;

  return (
    <div style={{ maxWidth: 800, margin: "0 auto", padding: "40px 24px" }}>
      {/* Header */}
      <button
        onClick={() => router.push(`/jobs/${jobId}`)}
        style={{ background: "none", border: "none", color: "#9898bb", cursor: "pointer", fontSize: 13, padding: 0, marginBottom: 24, display: "flex", alignItems: "center", gap: 6 }}
      >
        ← Back to Pipeline
      </button>

      <div style={{ marginBottom: 32, background: "#13131a", border: "1px solid #2a2a3a", borderRadius: 16, padding: 24 }}>
        <h1 style={{ fontSize: 28, fontWeight: 700, color: "#f0f0ff", margin: "0 0 8px" }}>
          {candidate.name ?? "Unknown Candidate"}
        </h1>
        <div style={{ fontSize: 15, color: "#9898bb", marginBottom: 16 }}>
          {candidate.current_title ?? "—"} at {candidate.current_company ?? "—"}
        </div>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <InterviewStatusBadge status={candidate.interview_status} />
          <ShortlistBadge shortlisted={candidate.shortlisted} override={candidate.shortlist_override} />
        </div>
      </div>

      {/* Profile Score Section */}
      {score && (
        <section style={{ marginBottom: 32, background: "#13131a", border: "1px solid #2a2a3a", borderRadius: 16, padding: 24 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: "#f0f0ff", margin: "0 0 20px" }}>Profile Score</h2>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
            <div>
              <div style={{ fontSize: 13, color: "#9898bb", marginBottom: 8 }}>Overall Score</div>
              <ScoreBar value={score.total_score} />
            </div>
            <div>
              <div style={{ fontSize: 13, color: "#9898bb", marginBottom: 8 }}>Technical Score</div>
              <ScoreBar value={score.technical_score} />
            </div>
            <div>
              <div style={{ fontSize: 13, color: "#9898bb", marginBottom: 8 }}>Seniority Score</div>
              <ScoreBar value={score.seniority_score} />
            </div>
            <div>
              <div style={{ fontSize: 13, color: "#9898bb", marginBottom: 8 }}>Domain Score</div>
              <ScoreBar value={score.domain_score} />
            </div>
          </div>
          
          <div style={{ marginTop: 20, paddingTop: 20, borderTop: "1px solid #2a2a3a" }}>
            <h3 style={{ fontSize: 13, color: "#9898bb", margin: "0 0 12px", textTransform: "uppercase", letterSpacing: "0.05em" }}>Red Flags</h3>
            {score.red_flags && score.red_flags.length > 0 ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {score.red_flags.map((flag, i) => (
                  <div key={i} style={{ color: "#ef4444", fontSize: 14 }}>
                    ⚠ {flag.type}: {flag.description}
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ color: "#22c55e", fontSize: 14 }}>✓ No red flags detected</div>
            )}
          </div>
        </section>
      )}

      {/* Skills Breakdown Section */}
      {score?.skills_breakdown && Object.keys(score.skills_breakdown).length > 0 && (
        <section style={{ marginBottom: 32, background: "#13131a", border: "1px solid #2a2a3a", borderRadius: 16, padding: 24 }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, color: "#f0f0ff", margin: "0 0 20px" }}>Skills Breakdown</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {Object.entries(score.skills_breakdown)
              .sort(([, a], [, b]) => b - a)
              .map(([skill, val]) => (
                <div key={skill} style={{ display: "grid", gridTemplateColumns: "150px 1fr", alignItems: "center", gap: 16 }}>
                  <div style={{ fontSize: 14, color: "#d0d0f0", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {skill}
                  </div>
                  <ScoreBar value={val} />
                </div>
              ))}
          </div>
        </section>
      )}

      {/* Interview Section */}
      {candidate.interview_status === "completed" && candidate.answer_scores && (
        <section style={{ marginBottom: 32, background: "#13131a", border: "1px solid #2a2a3a", borderRadius: 16, padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "#f0f0ff", margin: 0 }}>Interview Scores</h2>
            {candidate.overall_interview_score != null && (
              <div style={{ fontSize: 16, fontWeight: 700, color: "#6c63ff" }}>
                Overall: {candidate.overall_interview_score.toFixed(1)} / 10
              </div>
            )}
          </div>
          
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #2a2a3a" }}>
                  {["Q#", "Relevance", "Depth", "Communication", "Specificity", "Red Flag", "Feedback"].map((h) => (
                    <th key={h} style={{ padding: "12px 16px", textAlign: "left", fontSize: 11, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", whiteSpace: "nowrap" }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {candidate.answer_scores.map((ans) => (
                  <tr key={ans.question_id} style={{ borderBottom: "1px solid #1e1e2a" }}>
                    <td style={{ padding: "12px 16px", color: "var(--text-primary)", fontSize: 14 }}>{ans.question_id}</td>
                    <td style={{ padding: "12px 16px" }}><MiniScore val={ans.relevance} /></td>
                    <td style={{ padding: "12px 16px" }}><MiniScore val={ans.depth} /></td>
                    <td style={{ padding: "12px 16px" }}><MiniScore val={ans.communication} /></td>
                    <td style={{ padding: "12px 16px" }}><MiniScore val={ans.specificity} /></td>
                    <td style={{ padding: "12px 16px", color: ans.red_flag ? "var(--red)" : "var(--text-muted)", fontSize: 14 }}>
                      {ans.red_flag ? "⚑" : "—"}
                    </td>
                    <td style={{ padding: "16px", minWidth: 280 }}>
                      <div style={{ marginBottom: 12, fontStyle: "italic", color: "var(--text-muted)", fontSize: 13 }}>
                        {ans.feedback}
                      </div>
                      <div style={{ paddingLeft: 12, borderLeft: "2px solid var(--border)", color: "var(--text-secondary)", fontSize: 13, lineHeight: 1.5 }}>
                        {ans.answer_summary || ans.feedback}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Scorecard Section */}
      {sc && (
        <section style={{ marginBottom: 32, background: "#13131a", border: "1px solid #2a2a3a", borderRadius: 16, padding: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: "#f0f0ff", margin: 0 }}>Scorecard Summary</h2>
            <RecommendationBadge rec={sc.overall_recommendation} />
          </div>
          
          <div style={{ marginBottom: 20 }}>
            <p style={{ fontSize: 15, color: "#d0d0f0", lineHeight: 1.65, margin: 0 }}>{sc.summary}</p>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginBottom: 24 }}>
            <div>
              <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", marginBottom: 12 }}>Strengths</h3>
              <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
                {sc.strengths.map((s, i) => (
                  <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>
                    <span style={{ color: "#22c55e", marginRight: 4 }}>✓</span> {s}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", marginBottom: 12 }}>Concerns</h3>
              <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
                {sc.concerns.map((c, i) => (
                  <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>
                    <span style={{ color: "#ef4444", marginRight: 4 }}>⚠</span> {c}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div style={{ marginBottom: 24 }}>
            <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", marginBottom: 12 }}>Interview Highlights</h3>
            <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
              {sc.interview_highlights.map((h, i) => (
                <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>
                  <span style={{ color: "#6c63ff", marginRight: 4 }}>★</span> {h}
                </li>
              ))}
            </ul>
          </div>

          <div>
            <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", marginBottom: 12 }}>Suggested Follow-up Questions</h3>
            <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 8 }}>
              {sc.suggested_follow_up_questions.map((q, i) => (
                <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>{q}</li>
              ))}
            </ol>
          </div>
        </section>
      )}
    </div>
  );
}
