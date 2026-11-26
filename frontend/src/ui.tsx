import React from "react";
import { matchState } from "./lib/matchState";

export const pct = (x: number | null | undefined, d = 1) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(d)}%`);
export const spct = (x: number | null | undefined, d = 1) =>
  x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
export const eur = (x: number | null | undefined, signed = false) =>
  x === null || x === undefined ? "—" : `${signed && x > 0 ? "+" : ""}€${x.toFixed(2)}`;
export const num = (x: number | null | undefined, d = 2) => (x === null || x === undefined ? "—" : x.toFixed(d));
export const cls = (x: number | null | undefined) => (x === null || x === undefined || x === 0 ? "" : x > 0 ? "pos" : "neg");
export const ago = (iso?: string | null) => {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return `${Math.round(s)}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  if (s < 172800) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
};
export const romeTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-GB", { timeZone: "Europe/Rome", weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : "—";

export function Card({ title, right, children, className = "" }: { title?: React.ReactNode; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`card ${className}`}>
      {title && (
        <h3>
          <span>{title}</span>
          {right}
        </h3>
      )}
      {children}
    </div>
  );
}

export function Stat({ label, value, delta, tone }: { label: string; value: React.ReactNode; delta?: React.ReactNode; tone?: string }) {
  return (
    <div className="card stat">
      <div className="l">{label}</div>
      <div className={`v ${tone || ""}`}>{value}</div>
      {delta !== undefined && <div className="d">{delta}</div>}
    </div>
  );
}

export function Decision({ d }: { d?: string | null }) {
  if (!d) return <span className="badge b-inel">NOT ELIGIBLE</span>;
  if (d === "BET") return <span className="badge b-bet">VALUE BET</span>;
  if (d === "NO_BET") return <span className="badge b-nobet">NO BET</span>;
  return <span className="badge b-inel">{d}</span>;
}

export function Status({ s }: { s: string }) {
  const map: Record<string, string> = { won: "b-won", half_won: "b-won", lost: "b-lost", half_lost: "b-lost", pending: "b-pending", void: "b-void", ok: "b-ok", success: "b-ok", error: "b-error", not_configured: "b-nc", unknown: "b-nc", running: "b-pending", skipped: "b-void", interrupted: "b-error" };
  return <span className={`badge ${map[s] || "b-nc"}`}>{s.replace("_", " ").toUpperCase()}</span>;
}

export function Quality({ q }: { q?: number | null }) {
  if (q === null || q === undefined) return <span className="muted">—</span>;
  const c = q >= 80 ? "var(--green)" : q >= 70 ? "var(--cyan)" : q >= 55 ? "var(--amber)" : "var(--red)";
  return (
    <span className="qbar" title="Data-quality score (0-100)">
      <i><b style={{ width: `${q}%`, background: c }} /></i>
      <span style={{ color: c }}>{q.toFixed(0)}</span>
    </span>
  );
}

export function ProbBar({ p }: { p?: { home: number; draw: number; away: number } | null }) {
  if (!p) return <span className="muted">—</span>;
  const seg = (v: number, c: string, t: string) => (
    <div style={{ width: `${v * 100}%`, background: c }} title={`${t} ${pct(v)}`}>{v > 0.12 ? pct(v, 0) : ""}</div>
  );
  return (
    <div className="probbar">
      {seg(p.home, "#4ea1ff", "Home")}
      {seg(p.draw, "#8b9bb0", "Draw")}
      {seg(p.away, "#f5b942", "Away")}
    </div>
  );
}

export function Form({ s }: { s?: string }) {
  if (!s) return <span className="muted">—</span>;
  return (
    <span className="form-str">
      {s.split("").map((c, i) => (
        <span key={i} className={c}>{c}</span>
      ))}
    </span>
  );
}

export function Loading({ error }: { error?: string | null }) {
  if (error) return <div className="err-box">Failed to load: {error}</div>;
  return <div className="empty">Loading…</div>;
}

export const selLabel = (market: string, sel: string, line?: number | null) => {
  if (market === "1X2") return { home: "Home win", draw: "Draw", away: "Away win" }[sel] || sel;
  if (market === "OU25") return `${sel === "over" ? "Over" : "Under"} 2.5`;
  if (market === "AH") return `AH ${sel} ${line !== null && line !== undefined ? (sel === "home" ? line : -line) > 0 ? "+" + (sel === "home" ? line : -line) : String(sel === "home" ? line : -line) : ""}`;
  return `${market} ${sel}`;
};

export const tooltipStyle = { contentStyle: { background: "#0d131a", border: "1px solid #2a3a4b", borderRadius: 7, fontFamily: "JetBrains Mono", fontSize: 11 }, labelStyle: { color: "#7d8c9b" } };

export function State({ s }: { s?: string | null }) {
  const v = s || "UNKNOWN";
  return <span className={`state s-${v}`}>{v}</span>;
}

export function Explanation({ ex }: { ex: any }) {
  if (!ex) return <div className="muted">No structured explanation stored for this prediction (created before explanations were added).</div>;
  return (
    <div>
      <p style={{ marginTop: 0 }}>{ex.summary}</p>
      <div className="grid g2">
        <div>
          <h3>Model factors (fitted parameters)</h3>
          {(ex.all_factors || []).map((f: any) => <div className="factor" key={f.factor}><span>{f.factor} <span className="muted">→ {f.on}</span></span><span>{f.effect}</span></div>)}
        </div>
        <div>
          <h3>What weakens this prediction</h3>
          {ex.weakening?.length ? <ul className="tight">{ex.weakening.map((w: string) => <li key={w}>{w}</li>)}</ul> : <div className="muted">Nothing flagged.</div>}
          <h3 style={{ marginTop: 10 }}>Missing data</h3>
          {ex.missing?.length ? <ul className="tight">{ex.missing.map((w: string) => <li key={w}>{w}</li>)}</ul> : <div className="muted">None.</div>}
          {ex.freshness && <p className="muted mono" style={{ fontSize: 11 }}>{ex.freshness}</p>}
        </div>
      </div>
      <p className="muted" style={{ fontSize: 11 }}>{ex.note}</p>
    </div>
  );
}


type Fx = { status?: string; phase?: string; score?: string | null; kickoff_utc?: string };
/** The snapshot's phase, or the fixture status where no phase is exported. */
const phaseOf = (f: Fx) => f.phase || (f.status === "finished" || f.status === "postponed" ? f.status : undefined);
/** A started match without a score that is no longer (probably) being played. One rule for every page:
 *  lib/matchState (council cycle 2026-11-26 06:50 — three helpers disagreed). */
export const awaitingResult = (f: Fx, now: number = Date.now()) =>
  !f.score && !!f.kickoff_utc && matchState(f.kickoff_utc, phaseOf(f), now) === "awaiting";
/** Status text for a fixture as of NOW in the viewer's browser (the static snapshot may be hours old). */
export const statusNow = (f: Fx, now: number = Date.now()) => {
  if (f.score) return `FT ${f.score}`;
  if (!f.kickoff_utc) return f.status || "scheduled";
  const st = matchState(f.kickoff_utc, phaseOf(f), now);
  return st === "live" ? "in play" : st === "awaiting" ? "awaiting result" : st === "postponed" ? "postponed" : (f.status || "scheduled");
};
