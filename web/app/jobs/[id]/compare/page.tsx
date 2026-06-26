"use client";

import { useEffect, useState } from "react";
import { useParams, useSearchParams, useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ── Types ───────────────────────────────────────────────────────────────────

interface Score {
  candidate_id: string;
  total_score: number;
  technical_score: number;
  seniority_score: number;
  domain_score: number;
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

interface Candidate {
  id: string;
  name: string | null;
  current_title: string | null;
  current_company: string | null;
  shortlisted: boolean;
  interview_status: string;
  overall_interview_score: number | null;
  scorecard: Scorecard | null;
  score?: Score;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

function RecommendationBadge({ rec }: { rec: string }) {
  const map: Record<string, { label: string; color: string; bg: string }> = {
    strong_yes: { label: "Strong Yes ✦", color: "#22c55e", bg: "rgba(34,197,94,0.15)" },
    yes: { label: "Yes", color: "#3b82f6", bg: "rgba(59,130,246,0.15)" },
    maybe: { label: "Maybe", color: "#eab308", bg: "rgba(234,179,8,0.15)" },
    no: { label: "No", color: "#ef4444", bg: "rgba(239,68,68,0.15)" },
  };
  const c = map[rec] ?? { label: rec, color: "#9898bb", bg: "rgba(152,152,187,0.1)" };
  return (
    <span
      style={{
        display: "inline-block",
        fontSize: 13,
        fontWeight: 700,
        color: c.color,
        background: c.bg,
        border: `1px solid ${c.color}44`,
        borderRadius: 20,
        padding: "4px 14px",
      }}
    >
      {c.label}
    </span>
  );
}

function ScoreCell({ label, value, scale = 1 }: { label: string; value?: number; scale?: number }) {
  if (value == null) {
    return (
      <div style={{ padding: "12px 0" }}>
        <div style={{ fontSize: 11, color: "#5a5a7a", marginBottom: 4 }}>{label}</div>
        <div style={{ fontSize: 18, fontWeight: 700, color: "#5a5a7a" }}>—</div>
      </div>
    );
  }
  const normalised = value / scale;
  const pct = Math.min(100, Math.round(normalised * 100));
  const colour = pct >= 70 ? "#22c55e" : pct >= 45 ? "#eab308" : "#ef4444";
  const displayed = scale === 10 ? value.toFixed(1) : `${pct}%`;

  return (
    <div style={{ padding: "12px 0" }}>
      <div style={{ fontSize: 11, color: "#5a5a7a", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.06em" }}>
        {label}
      </div>
      <div style={{ fontSize: 24, fontWeight: 700, color: colour, marginBottom: 6 }}>
        {displayed}
      </div>
      <div style={{ height: 4, background: "#2a2a3a", borderRadius: 2, overflow: "hidden" }}>
        <div
          style={{
            width: `${pct}%`,
            height: "100%",
            background: colour,
            borderRadius: 2,
            transition: "width 0.6s ease",
          }}
        />
      </div>
    </div>
  );
}

function BulletList({ items, color }: { items: string[] | null | undefined; color: string }) {
  if (!items || items.length === 0)
    return <p style={{ fontSize: 13, color: "#5a5a7a", margin: 0 }}>—</p>;
  return (
    <ul style={{ margin: 0, paddingLeft: 16, display: "flex", flexDirection: "column", gap: 5 }}>
      {items.map((item, i) => (
        <li key={i} style={{ fontSize: 13, color: "#d0d0f0", lineHeight: 1.5 }}>
          <span style={{ color, marginRight: 4 }}>•</span>{item}
        </li>
      ))}
    </ul>
  );
}

function RedFlagsCell({ flags }: { flags: { type: string; description: string }[] | null | undefined }) {
  if (!flags || flags.length === 0)
    return <span style={{ fontSize: 13, color: "#22c55e" }}>None ✓</span>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {flags.map((f, i) => (
        <div key={i} style={{ fontSize: 12, color: "#ef4444" }}>
          ⚠ {f.type}: {f.description}
        </div>
      ))}
    </div>
  );
}

function SectionHeader({ title }: { title: string }) {
  return (
    <div
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: "#5a5a7a",
        textTransform: "uppercase",
        letterSpacing: "0.1em",
        padding: "14px 0 10px",
        borderTop: "1px solid #2a2a3a",
        marginTop: 4,
      }}
    >
      {title}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ComparePage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const jobId = params.id as string;

  const rawIds = searchParams.get("candidates") ?? "";
  const candidateIds = rawIds.split(",").filter(Boolean).slice(0, 3);

  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (candidateIds.length === 0) {
      setError("No candidate IDs provided.");
      setLoading(false);
      return;
    }

    (async () => {
      try {
        // Fetch each candidate
        const candResults = await Promise.all(
          candidateIds.map((id) =>
            fetch(`${API}/candidates/${id}`).then((r) => {
              if (!r.ok) throw new Error(`Candidate ${id}: HTTP ${r.status}`);
              return r.json();
            })
          )
        );

        // Try to get their scores (non-blocking)
        const scoreResults = await Promise.allSettled(
          candidateIds.map((id) =>
            fetch(`${API}/candidates/${id}/score`).then((r) =>
              r.ok ? r.json() : null
            )
          )
        );

        // Merge score data
        const enriched: Candidate[] = candResults.map((c, i) => {
          const scoreResult = scoreResults[i];
          const scoreData = scoreResult.status === "fulfilled" ? scoreResult.value : null;
          return { ...c, score: scoreData };
        });

        setCandidates(enriched);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load candidates.");
      } finally {
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rawIds]);

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 300 }}>
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
    );
  }

  if (error) {
    return (
      <div style={{ maxWidth: 700, margin: "40px auto", padding: "0 24px" }}>
        <div style={{ background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 12, padding: 20, color: "#fca5a5" }}>
          ⚠ {error}
        </div>
      </div>
    );
  }

  const colWidth = Math.floor(100 / candidates.length);

  return (
    <div style={{ maxWidth: 1280, margin: "0 auto", padding: "40px 24px" }}>
      {/* Back link */}
      <button
        id="back-to-pipeline"
        onClick={() => router.push(`/jobs/${jobId}`)}
        style={{
          background: "none",
          border: "none",
          color: "#9898bb",
          cursor: "pointer",
          fontSize: 13,
          padding: 0,
          marginBottom: 28,
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        ← Back to Pipeline
      </button>

      <h1 style={{ fontSize: 28, fontWeight: 700, color: "#f0f0ff", margin: "0 0 8px", letterSpacing: "-0.02em" }}>
        Candidate Comparison
      </h1>
      <p style={{ margin: "0 0 32px", color: "#9898bb", fontSize: 14 }}>
        Comparing {candidates.length} candidate{candidates.length !== 1 ? "s" : ""} side-by-side.
      </p>

      <div
        style={{
          background: "#13131a",
          border: "1px solid #2a2a3a",
          borderRadius: 20,
          overflow: "hidden",
        }}
      >
        {/* Sticky header row */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: `180px repeat(${candidates.length}, 1fr)`,
            borderBottom: "1px solid #2a2a3a",
          }}
        >
          {/* Label column header */}
          <div style={{ padding: "20px 24px" }} />

          {/* Candidate headers */}
          {candidates.map((c) => (
            <div
              key={c.id}
              style={{
                padding: "20px 24px",
                borderLeft: "1px solid #2a2a3a",
              }}
            >
              <div style={{ fontSize: 16, fontWeight: 700, color: "#f0f0ff", marginBottom: 4 }}>
                {c.name ?? "Unknown"}
              </div>
              <div style={{ fontSize: 13, color: "#9898bb", marginBottom: 4 }}>
                {c.current_title ?? "—"}
              </div>
              <div style={{ fontSize: 12, color: "#5a5a7a", marginBottom: 10 }}>
                {c.current_company ?? "—"}
              </div>
              {c.scorecard && (
                <RecommendationBadge rec={c.scorecard.overall_recommendation} />
              )}
            </div>
          ))}
        </div>

        {/* Rows */}
        {[
          {
            section: "Profile Scores",
            rows: [
              { label: "Overall Score", render: (c: Candidate) => <ScoreCell label="" value={c.score?.total_score} /> },
              { label: "Technical", render: (c: Candidate) => <ScoreCell label="" value={c.score?.technical_score} /> },
              { label: "Seniority", render: (c: Candidate) => <ScoreCell label="" value={c.score?.seniority_score} /> },
              { label: "Domain", render: (c: Candidate) => <ScoreCell label="" value={c.score?.domain_score} /> },
              { label: "Red Flags", render: (c: Candidate) => <RedFlagsCell flags={c.score?.red_flags} /> },
            ],
          },
          {
            section: "Interview",
            rows: [
              {
                label: "Interview Score",
                render: (c: Candidate) => (
                  <ScoreCell label="" value={c.overall_interview_score ?? undefined} scale={10} />
                ),
              },
              {
                label: "Recommendation",
                render: (c: Candidate) =>
                  c.scorecard ? (
                    <RecommendationBadge rec={c.scorecard.overall_recommendation} />
                  ) : (
                    <span style={{ fontSize: 13, color: "#5a5a7a" }}>—</span>
                  ),
              },
              {
                label: "Strengths",
                render: (c: Candidate) => <BulletList items={c.scorecard?.strengths} color="#22c55e" />,
              },
              {
                label: "Concerns",
                render: (c: Candidate) => <BulletList items={c.scorecard?.concerns} color="#ef4444" />,
              },
            ],
          },
        ].map((group) => (
          <div key={group.section}>
            {/* Section divider */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: `180px repeat(${candidates.length}, 1fr)`,
              }}
            >
              <div
                style={{
                  padding: "10px 24px",
                  fontSize: 11,
                  fontWeight: 700,
                  color: "#5a5a7a",
                  textTransform: "uppercase",
                  letterSpacing: "0.1em",
                  background: "#0f0f16",
                  borderTop: "1px solid #2a2a3a",
                  gridColumn: `1 / ${candidates.length + 2}`,
                }}
              >
                {group.section}
              </div>
            </div>

            {group.rows.map((row) => (
              <div
                key={row.label}
                style={{
                  display: "grid",
                  gridTemplateColumns: `180px repeat(${candidates.length}, 1fr)`,
                  borderTop: "1px solid #1e1e2a",
                }}
              >
                {/* Row label */}
                <div
                  style={{
                    padding: "14px 24px",
                    fontSize: 13,
                    fontWeight: 500,
                    color: "#9898bb",
                    display: "flex",
                    alignItems: "flex-start",
                    paddingTop: 16,
                  }}
                >
                  {row.label}
                </div>

                {/* Candidate values */}
                {candidates.map((c) => (
                  <div
                    key={c.id}
                    style={{
                      padding: "14px 24px",
                      borderLeft: "1px solid #1e1e2a",
                    }}
                  >
                    {row.render(c)}
                  </div>
                ))}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
