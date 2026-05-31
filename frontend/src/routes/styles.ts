import type { CSSProperties } from "react";

export const authPageStyle: CSSProperties = {
  fontFamily: "system-ui, sans-serif",
  padding: "2rem",
  maxWidth: 360,
  margin: "0 auto",
};

export const formStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.75rem",
  marginTop: "1rem",
};

export const inputStyle: CSSProperties = {
  display: "block",
  width: "100%",
  padding: "0.5rem",
  marginTop: "0.25rem",
  fontSize: "1rem",
  boxSizing: "border-box",
};

export const primaryButtonStyle: CSSProperties = {
  padding: "0.5rem 1rem",
  fontSize: "1rem",
  cursor: "pointer",
};
