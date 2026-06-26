"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div style={{
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      alignItems: "center",
      justifyContent: "center",
      background: "var(--bg-primary)",
      color: "var(--text-primary)",
      gap: 16,
      padding: 24,
      textAlign: "center",
    }}>
      <div style={{ fontSize: 40 }}>⚠</div>
      <h2 style={{ fontSize: 22, fontWeight: 700, margin: 0 }}>Something went wrong</h2>
      <p style={{ color: "var(--text-secondary)", maxWidth: 420, margin: 0, fontSize: 14 }}>
        {error.message || "An unexpected error occurred. Please try again."}
      </p>
      <button
        onClick={reset}
        style={{
          marginTop: 8,
          padding: "10px 24px",
          background: "var(--accent)",
          color: "#fff",
          border: "none",
          borderRadius: 8,
          fontSize: 14,
          fontWeight: 600,
          cursor: "pointer",
        }}
      >
        Try again
      </button>
    </div>
  );
}
