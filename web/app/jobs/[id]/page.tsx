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
}

interface CandidateWithScore extends Candidate {
  score?: Score;
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
  feedback: string;
  red_flag: boolean;
}

// ── Small utility components ───────────────────────────────────────────────────

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
      {override && (
        <span style={{ fontSize: 9, opacity: 0.7 }}>OVERRIDE</span>
      )}
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

// ── Scorecard Modal ─────────────────────────────────────────────────────────────

function ScorecardModal({
  candidate,
  onClose,
}: {
  candidate: CandidateWithScore;
  onClose: () => void;
}) {
  const sc = candidate.scorecard;
  if (!sc) return null;

  return (
    <div
      id="scorecard-modal-overlay"
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.75)",
        backdropFilter: "blur(6px)",
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        id="scorecard-modal"
        style={{
          background: "#13131a",
          border: "1px solid #2a2a3a",
          borderRadius: 20,
          width: "100%",
          maxWidth: 680,
          maxHeight: "85vh",
          overflowY: "auto",
          padding: 32,
          position: "relative",
          animation: "slideUp 0.25s ease",
        }}
      >
        <style>{`
          @keyframes slideUp {
            from { opacity: 0; transform: translateY(20px); }
            to   { opacity: 1; transform: translateY(0); }
          }
        `}</style>

        {/* Close */}
        <button
          id="scorecard-modal-close"
          onClick={onClose}
          style={{
            position: "absolute",
            top: 20,
            right: 20,
            background: "#2a2a3a",
            border: "none",
            color: "#9898bb",
            width: 32,
            height: 32,
            borderRadius: 8,
            cursor: "pointer",
            fontSize: 16,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          ✕
        </button>

        {/* Header */}
        <div style={{ marginBottom: 24 }}>
          <p style={{ fontSize: 13, color: "#9898bb", margin: "0 0 6px" }}>Scorecard for</p>
          <h2 style={{ fontSize: 22, fontWeight: 700, color: "#f0f0ff", margin: "0 0 12px" }}>
            {candidate.name ?? "Unknown Candidate"}
          </h2>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <RecommendationBadge rec={sc.overall_recommendation} />
            {candidate.overall_interview_score != null && (
              <span style={{ fontSize: 13, color: "#9898bb" }}>
                Interview score:{" "}
                <strong style={{ color: "#f0f0ff" }}>
                  {candidate.overall_interview_score.toFixed(1)}/10
                </strong>
              </span>
            )}
          </div>
        </div>

        <div style={{ height: 1, background: "#2a2a3a", marginBottom: 24 }} />

        {/* Summary */}
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 10px" }}>
            Summary
          </h3>
          <p style={{ fontSize: 15, color: "#d0d0f0", lineHeight: 1.65, margin: 0 }}>{sc.summary}</p>
        </section>

        {/* Strengths */}
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 10px" }}>
            Strengths
          </h3>
          <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
            {sc.strengths.map((s, i) => (
              <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>
                <span style={{ color: "#22c55e", marginRight: 4 }}>✓</span> {s}
              </li>
            ))}
          </ul>
        </section>

        {/* Concerns */}
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 10px" }}>
            Concerns
          </h3>
          <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
            {sc.concerns.map((c, i) => (
              <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>
                <span style={{ color: "#ef4444", marginRight: 4 }}>⚠</span> {c}
              </li>
            ))}
          </ul>
        </section>

        {/* Interview highlights */}
        <section style={{ marginBottom: 24 }}>
          <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 10px" }}>
            Interview Highlights
          </h3>
          <ul style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 6 }}>
            {sc.interview_highlights.map((h, i) => (
              <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>
                <span style={{ color: "#6c63ff", marginRight: 4 }}>★</span> {h}
              </li>
            ))}
          </ul>
        </section>

        {/* Follow-up questions */}
        <section>
          <h3 style={{ fontSize: 13, fontWeight: 600, color: "#9898bb", textTransform: "uppercase", letterSpacing: "0.08em", margin: "0 0 10px" }}>
            Suggested Follow-up Questions
          </h3>
          <ol style={{ margin: 0, paddingLeft: 20, display: "flex", flexDirection: "column", gap: 8 }}>
            {sc.suggested_follow_up_questions.map((q, i) => (
              <li key={i} style={{ fontSize: 14, color: "#d0d0f0", lineHeight: 1.5 }}>
                {q}
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function JobPipelinePage() {
  const params = useParams();
  const router = useRouter();
  const jobId = params.id as string;

  const [candidates, setCandidates] = useState<CandidateWithScore[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [scorecardCandidate, setScorecardCandidate] = useState<CandidateWithScore | null>(null);
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [jobRes, candRes] = await Promise.all([
        fetch(`${API}/jobs/${jobId}`),
        fetch(`${API}/candidates?job_id=${jobId}`),
      ]);
      if (!jobRes.ok) throw new Error(`Job fetch: HTTP ${jobRes.status}`);
      if (!candRes.ok) throw new Error(`Candidates fetch: HTTP ${candRes.status}`);

      const job = await jobRes.json();
      const cands: Candidate[] = await candRes.json();
      setJobTitle(job.title);

      // Fetch profile scores concurrently — non-blocking
      const scoreResults = await Promise.allSettled(
        cands.map((c) =>
          fetch(`${API}/candidates/${c.id}/score`).then((r) =>
            r.ok ? r.json() : null
          )
        )
      );

      const scoreMap: Record<string, Score> = {};
      scoreResults.forEach((result, i) => {
        if (result.status === "fulfilled" && result.value) {
          scoreMap[cands[i].id] = result.value;
        }
      });

      const enriched: CandidateWithScore[] = cands.map((c) => ({
        ...c,
        score: scoreMap[c.id],
      }));

      // Sort by total_score descending
      enriched.sort((a, b) => (b.score?.total_score ?? 0) - (a.score?.total_score ?? 0));
      setCandidates(enriched);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  useEffect(() => {
    fetchData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const handleOverride = async (candidate: CandidateWithScore) => {
    setLoadingAction(`override-${candidate.id}`);
    try {
      const res = await fetch(`${API}/candidates/${candidate.id}/override`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shortlisted: !candidate.shortlisted }),
      });
      if (!res.ok) throw new Error("Override failed");
      await fetchData();
    } catch {
      alert("Failed to override shortlist.");
    } finally {
      setLoadingAction(null);
    }
  };

  const handleInvite = async (candidate: CandidateWithScore) => {
    setLoadingAction(`invite-${candidate.id}`);
    try {
      const res = await fetch(`${API}/candidates/${candidate.id}/invite`, {
        method: "POST",
      });
      if (!res.ok) throw new Error("Invite failed");
      await fetchData();
    } catch {
      alert("Failed to invite candidate.");
    } finally {
      setLoadingAction(null);
    }
  };

  const toggleSelect = (id: string) => {
    if (!selected.has(id) && selected.size >= 4) {
      alert("You can compare up to 4 candidates at a time");
      return;
    }
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else if (next.size < 4) next.add(id);
      return next;
    });
  };

  const handleCompare = () => {
    const ids = [...selected].join(",");
    router.push(`/jobs/${jobId}/compare?candidates=${ids}`);
  };

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto", padding: "40px 24px" }}>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <button
          onClick={() => router.push("/")}
          style={{
            background: "none",
            border: "none",
            color: "#9898bb",
            cursor: "pointer",
            fontSize: 13,
            padding: 0,
            marginBottom: 16,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          ← Back to Jobs
        </button>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}>
          <div>
            <h1 style={{ fontSize: 28, fontWeight: 700, color: "#f0f0ff", margin: 0, letterSpacing: "-0.02em" }}>
              {jobTitle || "Loading…"}
            </h1>
            <p style={{ margin: "4px 0 0", color: "#9898bb", fontSize: 14 }}>
              {candidates.length} candidate{candidates.length !== 1 ? "s" : ""} • Sorted by score
            </p>
          </div>

          {selected.size >= 2 && (
            <button
              id="compare-btn"
              onClick={handleCompare}
              style={{
                background: "linear-gradient(135deg, #6c63ff 0%, #5a52e0 100%)",
                border: "none",
                color: "#fff",
                borderRadius: 10,
                padding: "10px 20px",
                cursor: "pointer",
                fontSize: 14,
                fontWeight: 600,
                display: "flex",
                alignItems: "center",
                gap: 8,
                transition: "opacity 0.2s",
              }}
            >
              ⇄ Compare {selected.size} Candidates
            </button>
          )}
        </div>
      </div>

      {loading && (
        <div style={{ display: "flex", justifyContent: "center", padding: "80px 0" }}>
          <div
            style={{
              width: 36,
              height: 36,
              borderRadius: "50%",
              border: "3px solid #2a2a3a",
              borderTopColor: "#6c63ff",
              animation: "spin 0.8s linear infinite",
            }}
          />
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {error && (
        <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 12, padding: 20, color: "#fca5a5", fontSize: 14 }}>
          ⚠ {error}
        </div>
      )}

      {!loading && !error && candidates.length === 0 && (
        <div style={{ textAlign: "center", padding: "80px 0", color: "#5a5a7a" }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>👥</div>
          <p>No candidates found for this job.</p>
        </div>
      )}

      {/* Candidates table */}
      {!loading && !error && candidates.length > 0 && (
        <div
          style={{
            background: "#13131a",
            border: "1px solid #2a2a3a",
            borderRadius: 16,
            overflow: "hidden",
          }}
        >
          {/* Compare hint */}
          {selected.size > 0 && selected.size < 2 && (
            <div style={{ padding: "10px 20px", background: "rgba(108,99,255,0.08)", borderBottom: "1px solid rgba(108,99,255,0.2)", fontSize: 13, color: "#a09af0" }}>
              Select {2 - selected.size} more candidate{2 - selected.size !== 1 ? "s" : ""} to enable comparison.
            </div>
          )}

          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #2a2a3a" }}>
                  {["", "#", "Name", "Title", "Company", "Score", "Shortlisted", "Interview", "Actions"].map((h) => (
                    <th
                      key={h}
                      style={{
                        padding: "12px 16px",
                        textAlign: "left",
                        fontSize: 11,
                        fontWeight: 600,
                        color: "#9898bb",
                        textTransform: "uppercase",
                        letterSpacing: "0.06em",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {candidates.map((c, idx) => (
                  <tr
                    key={c.id}
                    id={`candidate-row-${c.id}`}
                    style={{
                      borderBottom: idx < candidates.length - 1 ? "1px solid #1e1e2a" : "none",
                      background: selected.has(c.id) ? "rgba(108,99,255,0.06)" : "transparent",
                      transition: "background 0.15s",
                    }}
                    onMouseEnter={(e) => {
                      if (!selected.has(c.id))
                        (e.currentTarget as HTMLTableRowElement).style.background = "#16161f";
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLTableRowElement).style.background = selected.has(c.id) ? "rgba(108,99,255,0.06)" : "transparent";
                    }}
                  >
                    {/* Checkbox */}
                    <td style={{ padding: "14px 16px" }}>
                      <input
                        type="checkbox"
                        id={`select-${c.id}`}
                        checked={selected.has(c.id)}
                        onChange={() => toggleSelect(c.id)}
                        disabled={!selected.has(c.id) && selected.size >= 4}
                        style={{ cursor: "pointer", accentColor: "#6c63ff" }}
                      />
                    </td>

                    {/* Rank */}
                    <td style={{ padding: "14px 16px" }}>
                      <span
                        style={{
                          fontSize: 13,
                          fontWeight: 700,
                          color: idx === 0 ? "#eab308" : idx === 1 ? "#9898bb" : idx === 2 ? "#b45309" : "#5a5a7a",
                        }}
                      >
                        {idx + 1}
                      </span>
                    </td>

                    {/* Name */}
                    <td style={{ padding: "14px 16px" }}>
                      <Link href={`/jobs/${jobId}/candidates/${c.id}`} style={{ textDecoration: "none" }}>
                        <div style={{ fontSize: 14, fontWeight: 600, color: "#f0f0ff" }}>
                          {c.name ?? "—"}
                        </div>
                      </Link>
                    </td>

                    {/* Title */}
                    <td style={{ padding: "14px 16px" }}>
                      <div style={{ fontSize: 13, color: "#9898bb" }}>{c.current_title ?? "—"}</div>
                    </td>

                    {/* Company */}
                    <td style={{ padding: "14px 16px" }}>
                      <div style={{ fontSize: 13, color: "#9898bb" }}>{c.current_company ?? "—"}</div>
                    </td>

                    {/* Score */}
                    <td style={{ padding: "14px 16px", minWidth: 120 }}>
                      {c.score ? (
                        <div>
                          <ScoreBar value={c.score.total_score} />
                        </div>
                      ) : (
                        <span style={{ fontSize: 12, color: "#5a5a7a" }}>—</span>
                      )}
                    </td>

                    {/* Shortlisted */}
                    <td style={{ padding: "14px 16px" }}>
                      <ShortlistBadge shortlisted={c.shortlisted} override={c.shortlist_override} />
                    </td>

                    {/* Interview status */}
                    <td style={{ padding: "14px 16px" }}>
                      <InterviewStatusBadge status={c.interview_status} />
                    </td>

                    {/* Actions */}
                    <td style={{ padding: "14px 16px" }}>
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <button
                          id={`override-btn-${c.id}`}
                          onClick={() => handleOverride(c)}
                          disabled={loadingAction === `override-${c.id}`}
                          style={{
                            fontSize: 12,
                            fontWeight: 500,
                            color: c.shortlisted ? "#ef4444" : "#22c55e",
                            background: c.shortlisted ? "rgba(239,68,68,0.08)" : "rgba(34,197,94,0.08)",
                            border: `1px solid ${c.shortlisted ? "rgba(239,68,68,0.3)" : "rgba(34,197,94,0.3)"}`,
                            borderRadius: 8,
                            padding: "5px 10px",
                            cursor: "pointer",
                            transition: "opacity 0.2s",
                            opacity: loadingAction === `override-${c.id}` ? 0.5 : 1,
                            whiteSpace: "nowrap",
                          }}
                        >
                          {loadingAction === `override-${c.id}` ? "…" : c.shortlisted ? "Remove" : "Shortlist"}
                        </button>

                        {c.interview_status === "not_invited" && (
                          <button
                            id={`invite-btn-${c.id}`}
                            onClick={() => handleInvite(c)}
                            disabled={loadingAction === `invite-${c.id}`}
                            style={{
                              fontSize: 12,
                              fontWeight: 500,
                              color: "#eab308",
                              background: "rgba(234,179,8,0.08)",
                              border: "1px solid rgba(234,179,8,0.3)",
                              borderRadius: 8,
                              padding: "5px 10px",
                              cursor: "pointer",
                              transition: "opacity 0.2s",
                              opacity: loadingAction === `invite-${c.id}` ? 0.5 : 1,
                              whiteSpace: "nowrap",
                            }}
                          >
                            {loadingAction === `invite-${c.id}` ? "…" : "Invite"}
                          </button>
                        )}

                        {c.interview_status === "completed" && c.scorecard && (
                          <button
                            id={`scorecard-btn-${c.id}`}
                            onClick={() => setScorecardCandidate(c)}
                            style={{
                              fontSize: 12,
                              fontWeight: 500,
                              color: "#6c63ff",
                              background: "rgba(108,99,255,0.08)",
                              border: "1px solid rgba(108,99,255,0.3)",
                              borderRadius: 8,
                              padding: "5px 10px",
                              cursor: "pointer",
                              whiteSpace: "nowrap",
                            }}
                          >
                            View Scorecard
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Scorecard Modal */}
      {scorecardCandidate && (
        <ScorecardModal
          candidate={scorecardCandidate}
          onClose={() => setScorecardCandidate(null)}
        />
      )}
    </div>
  );
}
