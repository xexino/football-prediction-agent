import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../../hooks";
import { Loading, num, pct, romeTime } from "../../ui";
import { Coverage, LiveBadge, SubNav, Tri } from "./common";
import { matchState } from "../../lib/matchState";

const TABS = [["upcoming", "Upcoming"], ["live", "Live"], ["finished", "Recent results"], ["all", "All"]] as const;

export default function Insights() {
  const { data, error } = useApi<any>("insights", 120000);
  const [tab, setTab] = useState<string>("upcoming");
  const [q, setQ] = useState("");
  const [comp, setComp] = useState("");
  const [region, setRegion] = useState("");
  const [day, setDay] = useState("");
  const [onlyPred, setOnlyPred] = useState(true);
  const items = data?.items || [];
  const comps = useMemo(() => Array.from(new Set(items.map((i: any) => i.competition_name))).sort() as string[], [items]);
  const regions = useMemo(() => Array.from(new Set(items.map((i: any) => i.region))).sort() as string[], [items]);
  const days = useMemo(() => Array.from(new Set(items.map((i: any) => i.kickoff_rome?.slice(0, 10)))).sort() as string[], [items]);
  if (!data) return <Loading error={error} />;
  // phase as of NOW (the snapshot's phase is frozen at export time)
  // one rule for every page (lib/matchState); a score means finished
  const phaseNow = (i: any) => {
    if (i.score) return "finished";
    const st = matchState(i.kickoff_utc, i.phase);
    return st === "awaiting" ? "awaiting_result" : st;
  };
  const rows = items.map((i: any) => ({ ...i, phase: phaseNow(i) })).filter((i: any) =>
    (tab === "all" || i.phase === tab || (tab === "finished" && i.phase === "awaiting_result")) &&
    (!comp || i.competition_name === comp) && (!region || i.region === region) && (!day || i.kickoff_rome?.startsWith(day)) &&
    (!onlyPred || i.engine_b || i.phase === "live") &&
    (!q || `${i.home} ${i.away} ${i.competition_name}`.toLowerCase().includes(q.toLowerCase())));
  const liveCount = items.filter((i: any) => phaseNow(i) === "live").length;
  return (
    <>
      <div className="topbar"><div><h1>AI Match Insights</h1><div className="sub">Engine B — independent statistical engine with an evidence-based match analyst. Times Europe/Rome.</div></div>
        <span className="pill">{items.filter((i: any) => i.engine_b).length} analysed · {liveCount} live</span></div>
      <SubNav />
      <div className="filters">
        {TABS.map(([k, l]) => <button key={k} onClick={() => setTab(k)} style={tab === k ? { borderColor: "var(--green)", color: "var(--green)" } : undefined}>{l}{k === "live" && liveCount ? ` (${liveCount})` : ""}</button>)}
        <select value={region} onChange={(e) => setRegion(e.target.value)}><option value="">All regions</option>{regions.map((r) => <option key={r}>{r}</option>)}</select>
        <select value={comp} onChange={(e) => setComp(e.target.value)}><option value="">All competitions</option>{comps.map((c) => <option key={c}>{c}</option>)}</select>
        <select value={day} onChange={(e) => setDay(e.target.value)}><option value="">All dates</option>{days.map((d) => <option key={d}>{d}</option>)}</select>
        <input placeholder="Team or competition…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="muted" style={{ display: "flex", gap: 6, alignItems: "center" }}><input type="checkbox" checked={onlyPred} onChange={(e) => setOnlyPred(e.target.checked)} />analysed only</label>
      </div>
      {rows.length === 0 && <div className="empty">{tab === "live" ? "No live matches right now from the connected providers. Free-plan scores are delayed; full live mode needs API_FOOTBALL_KEY." : "No fixtures match the filters."}</div>}
      <div className="grid g3">
        {rows.slice(0, 120).map((i: any) => {
          const b = i.engine_b;
          return (
            <Link key={i.id} to={`/insights/${i.id}`} className="card ai-card">
              <div className="ai-head"><span className="muted" style={{ fontSize: 11 }}>{i.competition_name} · {romeTime(i.kickoff_utc)}</span><span className="chips"><LiveBadge l={i.phase === "live" ? i.live : null} /><Coverage s={i.coverage_status} />{i.cross_league_low_confidence && <span className="pill warn" title="Engine B: cross-league rating, low confidence">low conf.</span>}</span></div>
              <div className="ai-teams">{i.home} <span className="muted">vs</span> {i.away}{i.score ? <span className="mono" style={{ marginLeft: 8 }}>{i.score}</span> : i.phase === "awaiting_result" ? <span className="warn" style={{ marginLeft: 8, fontSize: 11 }}>awaiting result</span> : null}</div>
              {b ? (
                <>
                  <Tri p={b.x12} />
                  <div className="ai-stats mono">
                    <span>xG {num(b.xg.home, 2)}–{num(b.xg.away, 2)}</span><span>BTTS {pct(b.btts, 0)}</span><span>O2.5 {pct(b.over25, 0)}</span>
                    {b.corners && <span>Corners {num(b.corners.total, 1)}</span>}{b.cards && <span>Cards {num(b.cards.total, 1)}</span>}
                  </div>
                  <div className="muted mono" style={{ fontSize: 11 }}>Likely: {Object.entries(b.top_scores).map(([k, v]: any) => `${k} ${pct(v, 0)}`).join(" · ")}</div>
                  <div className="ai-foot"><span className="mono" style={{ fontSize: 11 }}>conf {num(b.confidence, 0)} · quality {num(b.data_quality, 0)}</span>
                    {i.engine_a && <span className="muted" style={{ fontSize: 11 }}>A: {pct(i.engine_a.home, 0)}/{pct(i.engine_a.draw, 0)}/{pct(i.engine_a.away, 0)}</span>}
                    {i.has_selection && <span className="badge b-bet">B SELECTION</span>}</div>
                </>
              ) : <div className="muted" style={{ fontSize: 12 }}>No Engine B prediction: {i.coverage_status === "UNAVAILABLE" || i.coverage_status?.startsWith("COVERAGE ONLY") ? "not enough data for predictions" : "insufficient team history"}.</div>}
            </Link>
          );
        })}
      </div>
    </>
  );
}
