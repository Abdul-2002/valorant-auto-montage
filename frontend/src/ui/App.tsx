import { useEffect, useState } from "react";

import { LogsView } from "./LogsView";
import { Studio } from "./Studio";

type Tab = "studio" | "logs";

function tabFromPath(): Tab {
  return window.location.pathname.startsWith("/logs") ? "logs" : "studio";
}

export function App() {
  const [tab, setTab] = useState<Tab>(tabFromPath);

  useEffect(() => {
    const onPop = () => setTab(tabFromPath());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function choose(next: Tab): void {
    window.history.pushState({}, "", next === "logs" ? "/logs" : "/");
    setTab(next);
  }

  return (
    <div style={page}>
      <header style={header}>
        <div>
          <div style={title}>Valorant Montage Bot</div>
          <div style={subtitle}>Videos, song, montage, YouTube</div>
        </div>
        <nav style={nav}>
          <button type="button" style={tab === "studio" ? tabOn : tabOff} onClick={() => choose("studio")}>
            Create
          </button>
          <button type="button" style={tab === "logs" ? tabOn : tabOff} onClick={() => choose("logs")}>
            Logs
          </button>
          <a style={link} href="http://localhost:8000/docs" target="_blank" rel="noreferrer">
            API docs
          </a>
        </nav>
      </header>
      {tab === "logs" ? <LogsView /> : <Studio />}
    </div>
  );
}

const page: React.CSSProperties = {
  fontFamily: "ui-sans-serif, system-ui, Segoe UI, Roboto, sans-serif",
  background: "#0b0f17",
  color: "#e7edf7",
  minHeight: "100vh",
  padding: 16,
};
const header: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  gap: 12,
  marginBottom: 16,
  flexWrap: "wrap",
};
const title: React.CSSProperties = { fontSize: 20, fontWeight: 800 };
const subtitle: React.CSSProperties = { fontSize: 12, opacity: 0.7 };
const nav: React.CSSProperties = { display: "flex", gap: 8, alignItems: "center" };
const tabOff: React.CSSProperties = {
  background: "#121a29",
  border: "1px solid #22304b",
  color: "#e7edf7",
  padding: "8px 12px",
  borderRadius: 10,
  cursor: "pointer",
};
const tabOn: React.CSSProperties = { ...tabOff, background: "#1e2a44" };
const link: React.CSSProperties = { color: "#8dd3ff", textDecoration: "none", fontSize: 13, marginLeft: 8 };
