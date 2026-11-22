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

function Shell() {
  const { data: h } = useApi<any>("health", 30000);
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
          <span className="muted">checked {h ? ago(h.time_utc) : "—"}</span>
        </div>
      </aside>
      <main className="main">
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
