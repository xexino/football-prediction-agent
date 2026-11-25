import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi } from "../../hooks";
import { Card, Loading, num, pct, romeTime } from "../../ui";
import { SubNav } from "./common";

export default function Compare() {
  const { data, error } = useApi<any>("engine_compare", 300000);
  const [only, setOnly] = useState("");
  if (!data) return <Loading error={error} />;
  const rows = data.rows.filter((r: any) => !only || (only === "finished" ? r.result : only === "disagree" ? (r.disagreement ?? 0) >= 0.08 :
    only === "awaiting" ? !r.result && new Date(r.kickoff_utc).getTime() < Date.now() : !r.result && new Date(r.kickoff_utc).getTime() >= Date.now()));
  const ll = data.live_log_loss;
  return (
    <>
      <div className="topbar"><div><h1>Engine A vs Engine B</h1><div className="sub">Same fixtures, original predictions of each engine, market and actual result.</div></div></div>
      <SubNav />
      <div className="grid g3">
        {["engine_a", "engine_b", "market"].map((k) => <Card key={k} title={`Live log loss — ${k.replace("_", " ")}`}><div className="stat"><div className="v">{ll[k] ? num(ll[k].mean, 3) : "—"}</div><div className="d">n = {ll[k]?.n ?? 0} matches predicted by all three (lower is better){data.live_log_loss_all?.[k] ? ` · all ${k.replace("_", " ")} matches: ${num(data.live_log_loss_all[k].mean, 3)} (n=${data.live_log_loss_all[k].n})` : ""}</div></div></Card>)}
      </div>
      <p className="muted" style={{ fontSize: 12 }}>{data.note} The walk-forward comparison on historical matches is on the Engine B track-record page. Match pages show each engine's latest revision, so their numbers can differ from these original predictions.</p>
      <div className="filters"><select value={only} onChange={(e) => setOnly(e.target.value)}><option value="">All</option><option value="upcoming">Upcoming</option><option value="finished">With result</option><option value="awaiting">Played, result pending</option><option value="disagree">A/B disagree ≥ 8pp</option></select></div>
      <Card><div className="tablewrap"><table>
        <thead><tr><th>Kickoff</th><th>Match</th><th>Engine A 1/X/2</th><th>Engine B 1/X/2</th><th>Market</th><th className="num">Gap</th><th>Result</th><th className="num">LL A</th><th className="num">LL B</th></tr></thead>
        <tbody>{rows.map((r: any) => {
          const fmt = (p: any) => p ? `${pct(p.home, 0)} / ${pct(p.draw, 0)} / ${pct(p.away, 0)}` : "—";
          return <tr key={r.id}><td className="mono">{romeTime(r.kickoff_utc)}</td><td className="match"><Link to={`/insights/${r.id}`}>{r.home} – {r.away}</Link><small>{r.competition_name}</small></td>
            <td className="mono">{fmt(r.engine_a)}</td><td className="mono">{fmt(r.engine_b)}</td><td className="mono">{fmt(r.market)}</td>
            <td className={`num ${(r.disagreement ?? 0) >= 0.08 ? "warn" : ""}`}>{r.disagreement != null ? pct(r.disagreement, 0) : "—"}</td>
            <td className="mono">{r.score ? `${r.score} (${r.result})` : "—"}</td>
            <td className="num">{r.logloss_engine_a != null ? num(r.logloss_engine_a, 3) : "—"}</td><td className="num">{r.logloss_engine_b != null ? num(r.logloss_engine_b, 3) : "—"}</td></tr>;
        })}</tbody></table>{!rows.length && <div className="empty">No fixtures.</div>}</div></Card>
    </>
  );
}
