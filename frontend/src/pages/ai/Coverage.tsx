import { useState } from "react";
import { useApi } from "../../hooks";
import { Card, Loading, ago, pct } from "../../ui";
import { Coverage as Cov, SubNav } from "./common";

export default function CoveragePage() {
  const { data, error } = useApi<any>("coverage_matrix", 300000);
  const [region, setRegion] = useState("");
  const [status, setStatus] = useState("");
  if (!data) return <Loading error={error} />;
  const comps = data.competitions.filter((c: any) => (!region || c.region === region) && (!status || c.status === status));
  const regions = Array.from(new Set(data.competitions.map((c: any) => c.region))) as string[];
  return (
    <>
      <div className="topbar"><div><h1>Global coverage & live data</h1><div className="sub">What we can genuinely cover, per competition. Missing data is shown as missing.</div></div><span className="pill">{data.live_snapshots_24h} live snapshots (24h)</span></div>
      <SubNav />
      <Card title="Live data providers (priority order)">
        <table><thead><tr><th>Provider</th><th>Configured</th><th>Score</th><th>Minute</th><th>Events</th><th>Statistics</th><th>Lineups</th><th>What it really gives</th><th>Last success</th></tr></thead>
          <tbody>{data.live_providers.map((p: any) => <tr key={p.name}><td className="mono">{p.name}</td><td>{p.configured ? <span className="badge b-ok">YES</span> : <span className="badge b-inel">AWAITING KEY</span>}</td>
            {["score", "minute", "events", "statistics", "lineups"].map((k) => <td key={k}>{p.capabilities[k] ? "✓" : "—"}</td>)}<td className="muted" style={{ fontSize: 11 }}>{p.capabilities.label}</td><td className="mono">{ago(p.last_success)}</td></tr>)}</tbody></table>
        <p className="muted" style={{ fontSize: 11 }}>Live mode is genuinely available only from providers that supply the match minute. On the football-data.org free plan scores are delayed and carry no minute, events or statistics, so they are labelled DELAYED, or STALE when old, and produce no live prediction.</p>
      </Card>
      <div className="filters">
        <select value={region} onChange={(e) => setRegion(e.target.value)}><option value="">All regions</option>{regions.map((r) => <option key={r}>{r}</option>)}</select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{data.statuses.map((s: string) => <option key={s}>{s}</option>)}</select>
      </div>
      <Card title={`Competition coverage (${comps.length})`}>
        <div className="tablewrap"><table><thead><tr><th>Competition</th><th>Region</th><th>Status</th><th className="num">History (3y)</th><th className="num">Upcoming 14d</th><th className="num">Odds</th><th className="num">Stats</th><th>Live</th><th>Sources</th></tr></thead>
          <tbody>{comps.map((c: any) => <tr key={c.code}><td className="match">{c.name}<small>{c.country} · {c.code}</small></td><td>{c.region}</td><td><Cov s={c.status} /></td><td className="num">{c.history}</td><td className="num">{c.upcoming}</td><td className="num">{pct(c.odds, 0)}</td><td className="num">{pct(c.stats, 0)}</td><td className="muted" style={{ fontSize: 11 }}>{c.live}</td><td className="mono" style={{ fontSize: 11 }}>{c.sources.join(", ") || "—"}</td></tr>)}</tbody></table></div>
      </Card>
    </>
  );
}
