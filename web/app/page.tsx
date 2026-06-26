"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Job {
  id: string;
  title: string;
  status: string;
  role_level: string;
  created_at: string;
  required_skills: { name: string; seniority: string }[];
}

function StatusBadge({ status }: { status: string }) {
  const colours: Record<string, string> = {
    active: "#22c55e",
    closed: "#6b7280",
    draft: "#eab308",
  };
  const bg: Record<string, string> = {
    active: "rgba(34,197,94,0.12)",
    closed: "rgba(107,114,128,0.12)",
    draft: "rgba(234,179,8,0.12)",
  };
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        color: colours[status] ?? "#9898bb",
        background: bg[status] ?? "rgba(152,152,187,0.12)",
        borderRadius: 20,
        padding: "3px 10px",
        textTransform: "uppercase",
        letterSpacing: "0.06em",
      }}
    >
      {status}
    </span>
  );
}

function SkillPill({ name }: { name: string }) {
  return (
    <span
      style={{
        fontSize: 11,
        color: "#9898bb",
        background: "#1a1a2e",
        border: "1px solid #2a2a3a",
        borderRadius: 4,
        padding: "2px 7px",
      }}
    >
      {name}
    </span>
  );
}

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const router = useRouter();

  useEffect(() => {
    fetch(`${API}/jobs`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(setJobs)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", padding: "40px 24px" }}>
      {/* Header */}
      <div style={{ marginBottom: 40 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <div
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#22c55e",
              boxShadow: "0 0 8px #22c55e",
            }}
          />
          <span style={{ fontSize: 12, color: "#9898bb", textTransform: "uppercase", letterSpacing: "0.1em" }}>
            Live
          </span>
        </div>
        <h1
          style={{
            fontSize: 36,
            fontWeight: 700,
            color: "#f0f0ff",
            margin: 0,
            letterSpacing: "-0.03em",
            lineHeight: 1.1,
          }}
        >
          Active Job Pipelines
        </h1>
        <p style={{ marginTop: 8, color: "#9898bb", fontSize: 15 }}>
          Select a job to view and manage the candidate pipeline.
        </p>
      </div>

      {/* State: loading */}
      {loading && (
        <div
          style={{
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            height: 200,
            flexDirection: "column",
            gap: 16,
          }}
        >
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: "50%",
              border: "3px solid #2a2a3a",
              borderTopColor: "#6c63ff",
              animation: "spin 0.8s linear infinite",
            }}
          />
          <span style={{ color: "#9898bb", fontSize: 14 }}>Loading jobs…</span>
          <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
      )}

      {/* State: error */}
      {error && (
        <div
          style={{
            background: "rgba(239,68,68,0.08)",
            border: "1px solid rgba(239,68,68,0.3)",
            borderRadius: 12,
            padding: 20,
            color: "#fca5a5",
            fontSize: 14,
          }}
        >
          ⚠ Failed to load jobs: {error}. Make sure the backend is running at{" "}
          <code style={{ color: "#f87171" }}>{API}</code>.
        </div>
      )}

      {/* State: empty */}
      {!loading && !error && jobs.length === 0 && (
        <div
          style={{
            textAlign: "center",
            padding: "80px 0",
            color: "#5a5a7a",
          }}
        >
          <div style={{ fontSize: 40, marginBottom: 16 }}>📋</div>
          <p style={{ fontSize: 16 }}>No jobs found. Create one via the API first.</p>
        </div>
      )}

      {/* Job cards grid */}
      {!loading && !error && jobs.length > 0 && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))",
            gap: 20,
          }}
        >
          {jobs.map((job) => (
            <button
              key={job.id}
              id={`job-card-${job.id}`}
              onClick={() => router.push(`/jobs/${job.id}`)}
              style={{
                background: "#13131a",
                border: "1px solid #2a2a3a",
                borderRadius: 16,
                padding: 24,
                textAlign: "left",
                cursor: "pointer",
                transition: "all 0.2s ease",
                width: "100%",
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#6c63ff";
                (e.currentTarget as HTMLButtonElement).style.background = "#16161f";
                (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-2px)";
                (e.currentTarget as HTMLButtonElement).style.boxShadow =
                  "0 8px 32px rgba(108,99,255,0.12)";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.borderColor = "#2a2a3a";
                (e.currentTarget as HTMLButtonElement).style.background = "#13131a";
                (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
                (e.currentTarget as HTMLButtonElement).style.boxShadow = "none";
              }}
            >
              {/* Top row */}
              <div
                style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}
              >
                <div
                  style={{
                    width: 42,
                    height: 42,
                    borderRadius: 10,
                    background: "linear-gradient(135deg, rgba(108,99,255,0.25) 0%, rgba(59,130,246,0.25) 100%)",
                    border: "1px solid rgba(108,99,255,0.3)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontSize: 18,
                  }}
                >
                  💼
                </div>
                <StatusBadge status={job.status} />
              </div>

              {/* Title */}
              <h2
                style={{
                  fontSize: 18,
                  fontWeight: 600,
                  color: "#f0f0ff",
                  margin: "0 0 4px",
                  letterSpacing: "-0.01em",
                }}
              >
                {job.title}
              </h2>

              {/* Role level */}
              <p style={{ fontSize: 13, color: "#9898bb", margin: "0 0 16px" }}>
                {job.role_level ?? "Unknown level"} •{" "}
                {new Date(job.created_at).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}
              </p>

              {/* Skills */}
              {job.required_skills && job.required_skills.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 16 }}>
                  {job.required_skills.slice(0, 4).map((s) => (
                    <SkillPill key={s.name} name={s.name} />
                  ))}
                  {job.required_skills.length > 4 && (
                    <SkillPill name={`+${job.required_skills.length - 4} more`} />
                  )}
                </div>
              )}

              {/* CTA */}
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "flex-end",
                  color: "#6c63ff",
                  fontSize: 13,
                  fontWeight: 500,
                  gap: 4,
                }}
              >
                View Pipeline →
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
