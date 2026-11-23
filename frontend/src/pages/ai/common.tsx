import { Link } from "react-router-dom";
import { pct } from "../../ui";

export const COV_CLASS: Record<string, string> = {
  "FULL COVERAGE": "b-ok", "PARTIAL COVERAGE": "b-pending", "FIXTURES AND RESULTS ONLY": "b-void",
  "LIVE SCORES ONLY": "b-void", "COVERAGE ONLY — NOT ENOUGH DATA FOR PREDICTIONS": "b-inel", UNAVAILABLE: "b-error",
};

export function Coverage({ s }: { s?: string }) {
  if (!s) return null;
  const short = s.startsWith("COVERAGE ONLY") ? "COVERAGE ONLY" : s;
  return <span className={`badge ${COV_CLASS[s] || "b-nc"}`} title={s}>{short}</span>;
}

export function LiveBadge({ l }: { l?: any }) {
  if (!l) return null;
  const now = liveLabel(l);
  const cls = now.startsWith("LIVE") ? "b-error" : now.startsWith("DELAYED") ? "b-inel" : "b-void";
  return <span className={`badge ${cls}`} title={`${l.provider} · snapshot ${l.at}`}>{now}{l.minute != null ? ` · ${l.minute}'` : ""}{l.score ? ` · ${l.score}` : ""}</span>;
}

export function Tri({ p, labels = ["1", "X", "2"] }: { p?: any; labels?: string[] }) {
  if (!p) return <span className="muted">—</span>;
  return (
    <div className="tri">
      {(["home", "draw", "away"] as const).map((k, i) => (
        <div key={k} className={`tri-cell ${p[k] === Math.max(p.home, p.draw, p.away) ? "tri-max" : ""}`}>
          <span>{labels[i]}</span><b>{pct(p[k], 0)}</b>
        </div>
      ))}
    </div>
  );
}

export function SubNav() {
  return (
    <div className="chips" style={{ marginBottom: 14 }}>
      <Link className="pill" to="/insights">Match Insights</Link>
      <Link className="pill" to="/compare">Engine A vs B</Link>
      <Link className="pill" to="/engine-b">Engine B track record</Link>
      <Link className="pill" to="/coverage">Global coverage & live data</Link>
    </div>
  );
}

/** Recompute a live label from its age in the viewer's browser (council LV-1): the static site may be served
 *  long after the snapshot was taken, so a stored "LIVE" must decay to DELAYED (> 3 min) and STALE (> 30 min). */
export function liveLabel(l: { label?: string; at?: string; freshness_s?: number | null } | null | undefined): string {
  if (!l || !l.at) return "UNKNOWN";
  const ageS = (Date.now() - new Date(l.at).getTime()) / 1000 + (l.freshness_s || 0);
  const mins = Math.max(0, Math.round(ageS / 60));
  let label = l.label || "UNKNOWN";
  if (ageS > 1800) label = "STALE";
  else if (label === "LIVE" && ageS > 180) label = "DELAYED";
  return `${label} · ${mins} min old`;
}
