import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, NavLink, Route, Routes } from "react-router-dom";
import "./styles.css";
import { useApi } from "./hooks";
import { ago } from "./ui";
import Overview from "./pages/Overview";
import Upcoming from "./pages/Upcoming";
import Predictions from "./pages/Predictions";
import BetSlip from "./pages/BetSlip";
import History from "./pages/History";
import Analytics from "./pages/Analytics";
import Sources from "./pages/Sources";
import System from "./pages/System";

const NAV = [
  ["/", "◎", "Overview"], ["/upcoming", "▤", "Upcoming"], ["/predictions", "∑", "Predictions"],
  ["/slip", "▣", "Virtual Bet Slip"], ["/history", "≡", "Results & History"], ["/analytics", "▲", "Analytics"],
  ["/sources", "⇅", "Data Sources"], ["/system", "♥", "System Health"],
];

const STATE_CLASS: Record<string, string> = { HEALTHY: "ok", WARNING: "warn", STALE: "warn", FAILED: "err", UNKNOWN: "" };

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

function Shell() {
  const { data: h } = useApi<any>("health", 30000);
  const { data: hd } = useApi<any>("health_detail", 120000);
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
        </nav>
        <div className="sim-banner"><b>SIMULATION ONLY.</b> Virtual €100 bankroll. No real-money bets, no bookmaker accounts, no transactions.</div>
        <div className="sim-banner">
          <span className={`dot ${h?.status === "ok" ? "ok" : h ? "err" : ""}`} /> backend {h?.status || "…"}<br />
          <span className={`dot ${h?.scheduler_running ? "ok" : "warn"}`} /> scheduler {h ? (h.scheduler_running ? "running" : "off / static snapshot") : "…"}<br />
          <span className={`dot ${STATE_CLASS[hd?.overall] ?? ""}`} /> health {hd?.overall ?? "…"}<br />
          <span className="muted">data as of {hd ? ago(hd.computed_at) : "—"}</span>
        </div>
      </aside>
      <main className="main">
        <FreshnessBanner hd={hd} />
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/upcoming" element={<Upcoming />} />
          <Route path="/predictions" element={<Predictions />} />
          <Route path="/slip" element={<BetSlip />} />
          <Route path="/history" element={<History />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/sources" element={<Sources />} />
          <Route path="/system" element={<System />} />
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
