import type { CSSProperties } from "react";

export const stack: CSSProperties = { display: "flex", flexDirection: "column", gap: 12 };
export const panel: CSSProperties = {
  background: "#0f1624",
  border: "1px solid #22304b",
  borderRadius: 12,
  padding: 16,
  display: "flex",
  flexDirection: "column",
  gap: 10,
};
export const heading: CSSProperties = { margin: 0, fontSize: 16 };
export const hint: CSSProperties = { margin: 0, fontSize: 13, opacity: 0.8 };
export const row: CSSProperties = { display: "flex", gap: 12, flexWrap: "wrap" };
export const label: CSSProperties = { display: "flex", flexDirection: "column", gap: 6, fontSize: 12, flex: 1 };
export const field: CSSProperties = {
  background: "#121a29",
  border: "1px solid #22304b",
  color: "#e7edf7",
  padding: "8px 10px",
  borderRadius: 10,
};
export const area: CSSProperties = { ...field, minHeight: 72, resize: "vertical" };
export const button: CSSProperties = {
  background: "#1e2a44",
  border: "1px solid #2b3a5c",
  color: "#e7edf7",
  padding: "9px 12px",
  borderRadius: 10,
  cursor: "pointer",
  width: "fit-content",
};
export const checkRow: CSSProperties = { display: "flex", gap: 8, alignItems: "center", fontSize: 13 };
export const link: CSSProperties = { color: "#8dd3ff" };
export const errorText: CSSProperties = { margin: 0, color: "#ffb4b4", fontSize: 13 };
