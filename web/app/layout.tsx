import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Alfaleus — Talent Intelligence Platform",
  description: "AI-powered talent screening and interview intelligence for modern recruiters.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="antialiased" style={{ display: "flex", flexDirection: "column", minHeight: "100vh" }}>
        {/* Top nav bar */}
        <nav
          style={{
            background: "rgba(13,13,20,0.85)",
            backdropFilter: "blur(12px)",
            borderBottom: "1px solid var(--border)",
            position: "sticky",
            top: 0,
            zIndex: 50,
          }}
        >
          <div
            style={{
              maxWidth: 1200,
              margin: "0 auto",
              padding: "0 24px",
              height: 60,
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}
          >
            <a href="/" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 10 }}>
              <img
                src="/logo.png"
                alt="Alfaleus Logo"
                style={{ width: 32, height: 32, objectFit: "contain", borderRadius: 8 }}
              />
              <span
                style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: "var(--text-primary)",
                  letterSpacing: "-0.02em",
                }}
              >
                Alfaleus
              </span>
            </a>

            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
              <span
                style={{
                  fontSize: 12,
                  color: "var(--text-muted)",
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  borderRadius: 20,
                  padding: "4px 10px",
                }}
              >
                Recruiter Dashboard
              </span>
            </div>
          </div>
        </nav>

        <main style={{ flex: 1 }}>{children}</main>

        <footer
          style={{
            borderTop: "1px solid var(--border)",
            background: "rgba(13,13,20,0.5)",
            padding: "40px 24px",
            textAlign: "center",
            color: "var(--text-muted)",
            fontSize: 14,
            marginTop: 60
          }}
        >
          <div style={{ maxWidth: 1200, margin: "0 auto", display: "flex", flexDirection: "column", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 8 }}>
              <img src="/logo.png" alt="Alfaleus Logo" style={{ width: 24, height: 24, objectFit: "contain" }} />
              <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>Alfaleus Technology</span>
            </div>
            <p style={{ margin: 0 }}>Empowering the future of healthcare through AI and deep tech.</p>
            <p style={{ margin: 0, fontSize: 12, opacity: 0.6 }}>© {new Date().getFullYear()} Alfaleus Technology. All rights reserved.</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
