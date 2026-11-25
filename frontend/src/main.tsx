import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import "./styles.css";
import { useApi } from "./hooks";
import { ago } from "./ui";
import Overview from "./pages/Overview";
import Simple from "./pages/Simple";
import Upcoming from "./pages/Upcoming";
import Predictions from "./pages/Predictions";
import BetSlip from "./pages/BetSlip";
import History from "./pages/History";
import Analytics from "./pages/Analytics";
import Sources from "./pages/Sources";
import System from "./pages/System";
import Insights from "./pages/ai/Insights";
import InsightDetail from "./pages/ai/InsightDetail";
import Compare from "./pages/ai/Compare";
import EngineB from "./pages/ai/EngineB";
import CoveragePage from "./pages/ai/Coverage";

const NAV = [
  ["/", "☺", "My view"], ["/overview", "◎", "Overview"], ["/upcoming", "▤", "Upcoming"], ["/predictions", "∑", "Predictions"],
  ["/slip", "▣", "Virtual Bet Slip"], ["/history", "≡", "Results & History"], ["/analytics", "▲", "Analytics"],
  ["/sources", "⇅", "Data Sources"], ["/system", "♥", "System Health"],
];
const NAV_AI = [["/insights", "✦", "Match Insights"], ["/compare", "⇄", "Engine A vs B"], ["/engine-b", "◆", "Engine B record"], ["/coverage", "⊕", "Global coverage"]];

const STATE_CLASS: Record<string, string> = { HEALTHY: "ok", DEGRADED: "warn", WARNING: "warn", STALE: "warn", FAILED: "err", UNKNOWN: "" };

function FreshnessBanner({ hd }: { hd: any }) {
  if (!hd) return null;
  const ageH = (Date.now() - new Date(hd.computed_at).getTime()) / 3.6e6;
  const stale = ageH > 8;
  const bad = hd.overall === "FAILED" || hd.overall === "STALE";
  if (!stale && !bad) return null;
  return (
    <div className={`banner ${bad || stale ? "banner-warn" : ""}`}>
      {stale && <b>STALE SNAPSHOT — </b>}
      {stale ? `data last refreshed ${ageH.toFixed(0)}h ago (expected every 3h). Figures below may be out of date. ` : ""}
      {bad && <>System health: <b>{hd.overall}</b>. See <a href="#/system">System Health</a>.</>}
    </div>
  );
}

/** Pipeline status of the Autopilot run that published this snapshot (data/ops_status.json). */
function useOpenIncidents() {
  const [inc, setInc] = React.useState<any[]>([]);
  React.useEffect(() => {
    let alive = true;
    const load = () => fetch("https://api.github.com/repos/xexino/football-prediction-agent/issues?labels=autopilot-incident&state=open")
      .then((r) => (r.ok ? r.json() : [])).then((j) => alive && setInc(Array.isArray(j) ? j : [])).catch(() => {});
    load();
    const t = setInterval(load, 600000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return inc;
}

function OpsBanner({ ops }: { ops: any }) {
  const incidents = useOpenIncidents();
  const cur = ops?.current;
  if (incidents.length && (!cur || cur.state === "HEALTHY")) return (
    <div className="banner banner-warn"><b>Open incident</b> — the watchdog reports a problem the last run could not see:{" "}
      {incidents.map((i: any) => <a key={i.number} href={i.html_url} target="_blank" rel="noreferrer">#{i.number} {i.title.replace("Autopilot incident: ", "")}</a>)} · <a href="#/system">System Health</a></div>
  );
  if (!cur || cur.state === "HEALTHY") return null;
  const failed = cur.state === "FAILED";
  return (
    <div className={`banner ${failed ? "banner-err" : "banner-warn"}`}>
      <b>Pipeline {cur.state}</b>
      {cur.failure_stage ? <> — the last run failed at the <b>{cur.failure_stage}</b> stage</> : cur.job_status === "partial" ? <> — the last run completed only partly</> : null}
      {cur.dashboard_data === "previous_snapshot" && <>; the data below is the <b>previous</b> snapshot</>}
      {ops.consecutive_failures > 1 && <> ({ops.consecutive_failures} failed runs in a row)</>}.{" "}
      {cur.run_url && <a href={cur.run_url} target="_blank" rel="noreferrer">Run log</a>} · <a href="#/system">System Health</a>
    </div>
  );
}

function Shell() {
  const { data: h } = useApi<any>("health", 30000);
  const { data: hd } = useApi<any>("health_detail", 120000);
  const { data: ops } = useApi<any>("ops_status", 120000);
  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <div className="logo">FI</div>
          <div><b>Football Intelligence Lab</b><span>research · prediction · simulation</span></div>
        </div>
        <nav className="nav">
          {NAV.map(([to, ico, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              <span className="ico">{ico}</span>{label}
            </NavLink>
          ))}
          <div className="nav-sec">AI MATCH INSIGHTS</div>
          {NAV_AI.map(([to, ico, label]) => (
            <NavLink key={to} to={to}><span className="ico">{ico}</span>{label}</NavLink>
          ))}
        </nav>
        <div className="sim-banner"><b>SIMULATION ONLY.</b> Virtual €500 bankroll, €10 flat stakes. No real-money bets, no bookmaker accounts, no transactions.</div>
        <div className="sim-banner">
          <span className={`dot ${h?.status === "ok" ? "ok" : h ? "err" : ""}`} /> backend {h?.status || "…"}<br />
          <span className={`dot ${h?.scheduler_running ? "ok" : "warn"}`} /> scheduler {h ? (h.scheduler_running ? "running" : "off / static snapshot") : "…"}<br />
          <span className={`dot ${STATE_CLASS[hd?.overall] ?? ""}`} /> health {hd?.overall ?? "…"}<br />
          <span className="muted">snapshot published {hd ? ago(hd.computed_at) : "—"}</span>
        </div>
      </aside>
      <main className="main">
        <div className="mobile-disclaimer"><b>SIMULATION ONLY.</b> Virtual €500 bankroll · no real money · health {hd?.overall ?? "…"} · data {hd ? ago(hd.computed_at) : "—"}</div>
        <OpsBanner ops={ops} />
        <FreshnessBanner hd={hd} />
        <Routes>
          <Route path="/" element={<Simple />} />
          <Route path="/overview" element={<Overview />} />
          <Route path="/upcoming" element={<Upcoming />} />
          <Route path="/predictions" element={<Predictions />} />
          <Route path="/slip" element={<BetSlip />} />
          <Route path="/history" element={<History />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/system" element={<System />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/insights/:id" element={<InsightDetail />} />
          <Route path="/compare" element={<Compare />} />
          <Route path="/engine-b" element={<EngineB />} />
          <Route path="/coverage" element={<CoveragePage />} />
        </Routes>
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter><Shell /></HashRouter>
  </React.StrictMode>
);
