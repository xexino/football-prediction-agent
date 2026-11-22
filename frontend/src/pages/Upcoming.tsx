import React, { useMemo, useState } from "react";
import { useApi } from "../hooks";
import { Card, Decision, Explanation, Form, Loading, ProbBar, Quality, num, pct, romeTime, selLabel, spct } from "../ui";

export function ValueTable({ rows }: { rows: any[] }) {
  return (
    <table>
      <thead><tr><th>Market</th><th>Book</th><th className="num">Odds</th><th className="num">Implied</th><th className="num">Market (no-vig)</th><th className="num">Model</th><th className="num">EV</th><th className="num">Cons. EV</th><th>Decision / reasons</th></tr></thead>
      <tbody>
        {rows.map((v) => (
          <tr key={v.id}>
            <td>{selLabel(v.market, v.selection, v.line)}</td><td className="mono">{v.bookmaker || "—"}</td>
            <td className="num">{num(v.price)}</td><td className="num">{pct(v.implied_prob)}</td><td className="num">{pct(v.market_prob)}</td>
            <td className="num">{pct(v.model_prob)}</td><td className={`num ${v.ev > 0 ? "pos" : "neg"}`}>{spct(v.ev)}</td>
            <td className={`num ${v.ev_conservative > 0 ? "pos" : "neg"}`}>{spct(v.ev_conservative)}</td>
            <td>{v.qualifies ? <span className="badge b-bet">QUALIFIES</span> : <span className="muted" style={{ fontSize: 11 }}>{(v.reject_reasons || []).join(" · ")}</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Detail({ f }: { f: any }) {
  const p = f.prediction;
  const inp = p?.inputs || {};
  const books = Object.entries(f.odds || {}) as [string, any][];
  return (
    <div className="grid g2">
      <Card title="Model output">
        {p ? (
          <div className="kv">
            <span>Expected goals</span><span className="mono">{num(p.exp_home_goals)} – {num(p.exp_away_goals)} (total {num(p.exp_total_goals)})</span>
            <span>Dixon-Coles 1X2</span><span className="mono">{pct(p.components?.dixon_coles?.home)} / {pct(p.components?.dixon_coles?.draw)} / {pct(p.components?.dixon_coles?.away)}</span>
            <span>Elo 1X2</span><span className="mono">{pct(p.components?.elo?.home)} / {pct(p.components?.elo?.draw)} / {pct(p.components?.elo?.away)}</span>
            <span>Ensemble 1X2</span><span className="mono">{pct(p.probs["1X2"].home)} / {pct(p.probs["1X2"].draw)} / {pct(p.probs["1X2"].away)}</span>
            <span>Double chance</span><span className="mono">1X {pct(p.probs.DC["1X"])} · 12 {pct(p.probs.DC["12"])} · X2 {pct(p.probs.DC["X2"])}</span>
            <span>Draw no bet</span><span className="mono">H {pct(p.probs.DNB.home)} · A {pct(p.probs.DNB.away)}</span>
            <span>Over 1.5 / 2.5 / 3.5</span><span className="mono">{pct(p.probs.OU15.over)} / {pct(p.probs.OU25.over)} / {pct(p.probs.OU35.over)}</span>
            <span>BTTS yes</span><span className="mono">{pct(p.probs.BTTS.yes)}</span>
            <span>Likely scores</span><span className="mono">{Object.entries(p.probs.CS_TOP || {}).map(([k, v]: any) => `${k} ${pct(v, 0)}`).join(" · ")}</span>
            <span>Elo ratings</span><span className="mono">{num(inp.elo?.home, 0)} vs {num(inp.elo?.away, 0)}</span>
            <span>Confidence</span><span className="mono">{num(p.confidence, 0)}/100</span>
            <span>Revision</span><span className="mono">#{p.revision}{p.revision_reason ? ` — ${p.revision_reason}` : " (original, immutable)"}</span>
            <span>Created</span><span className="mono">{romeTime(p.created_at)}</span>
          </div>
        ) : (
          <div className="empty">Not predicted: {(f.ineligible_reasons || []).join("; ")}</div>
        )}
      </Card>
      <Card title="Form & team news">
        <div className="kv">
          <span>{f.home} last 10</span><span><Form s={inp.form?.home?.string} /> <span className="muted mono">GF {inp.form?.home?.gf_avg ?? "—"} GA {inp.form?.home?.ga_avg ?? "—"}</span></span>
          <span>{f.home} at home</span><span><Form s={inp.form?.home_at_home?.string} /> <span className="muted mono">CS {inp.form?.home_at_home?.clean_sheets ?? "—"} FTS {inp.form?.home_at_home?.failed_to_score ?? "—"}</span></span>
          <span>{f.away} last 10</span><span><Form s={inp.form?.away?.string} /> <span className="muted mono">GF {inp.form?.away?.gf_avg ?? "—"} GA {inp.form?.away?.ga_avg ?? "—"}</span></span>
          <span>{f.away} away</span><span><Form s={inp.form?.away_away?.string} /> <span className="muted mono">CS {inp.form?.away_away?.clean_sheets ?? "—"} FTS {inp.form?.away_away?.failed_to_score ?? "—"}</span></span>
          <span>League table</span><span className="mono">{f.table?.home || f.table?.away ? `${f.home} ${f.table?.home ? `#${f.table.home.position} (${f.table.home.points} pts)` : "—"} · ${f.away} ${f.table?.away ? `#${f.table.away.position} (${f.table.away.points} pts)` : "—"} — football-data.org ${f.table?.home?.as_of || f.table?.away?.as_of || ""}` : "not available for this competition"}</span>
          <span>Sample (in competition)</span><span className="mono">{inp.n_matches?.home ?? "—"} / {inp.n_matches?.away ?? "—"} matches</span>
          <span>Team news</span><span className="warn">{f.team_news.length ? f.team_news.map((n: any) => `${n.team}: ${n.player} ${n.type} (${n.certainty})`).join("; ") : f.team_news_status}</span>
        </div>
        {p && <><h3 style={{ marginTop: 14 }}>Data-quality breakdown</h3><div className="chips">{Object.entries(p.quality_breakdown).map(([k, v]: any) => <span key={k} className="pill">{k.replace(/_/g, " ")} {v}</span>)}</div></>}
      </Card>
      <Card title="Bookmaker odds (latest pre-match snapshot per book)" className="span2">
        {books.length ? (
          <div className="tablewrap"><table>
            <thead><tr><th>Book</th><th className="num">1</th><th className="num">X</th><th className="num">2</th><th className="num">Margin</th><th className="num">O2.5</th><th className="num">U2.5</th><th className="num">AH line</th><th className="num">AH H</th><th className="num">AH A</th><th>Retrieved</th><th>Source</th></tr></thead>
            <tbody>{books.map(([b, o]) => (
              <tr key={b} style={o.suspect ? { background: "#24141a" } : undefined}><td>{o.label}{o.suspect && <div className="neg" style={{ fontSize: 10 }}>⚠ {o.flags.join("; ")}</div>}</td><td className="num">{num(o.home)}</td><td className="num">{num(o.draw)}</td><td className="num">{num(o.away)}</td>
                <td className="num">{pct(o.overround_1x2)}</td><td className="num">{num(o.over25)}</td><td className="num">{num(o.under25)}</td>
                <td className="num">{o.ah_line ?? "—"}</td><td className="num">{num(o.ah_home)}</td><td className="num">{num(o.ah_away)}</td>
                <td className="mono">{romeTime(o.retrieved_at)}</td><td><a href={o.source_url} target="_blank" rel="noreferrer">{o.source}</a></td></tr>))}</tbody>
          </table></div>
        ) : <div className="empty">No odds available from connected providers for this match.</div>}
      </Card>
      {p && <Card title="Why the model thinks this" className="span2"><Explanation ex={inp.explanation} /></Card>}
      {f.value && <Card title="Value assessment" className="span2"><div className="tablewrap"><ValueTable rows={f.value} /></div><p className="expl">{p?.explanation}</p></Card>}
    </div>
  );
}

export default function Upcoming() {
  const { data, error } = useApi<any>("upcoming?days=14", 120000);
  const [comp, setComp] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [day, setDay] = useState("");
  const [team, setTeam] = useState("");
  const comps = useMemo(() => Array.from(new Set((data?.fixtures || []).map((f: any) => f.competition_name))).sort() as string[], [data]);
  if (!data) return <Loading error={error} />;
  const days = Array.from(new Set(data.fixtures.map((f: any) => f.kickoff_rome?.slice(0, 10)))).sort() as string[];
  const rows = data.fixtures.filter((f: any) => (!comp || f.competition_name === comp) &&
    (!day || f.kickoff_rome?.startsWith(day)) && (!team || `${f.home} ${f.away}`.toLowerCase().includes(team.toLowerCase())) &&
    (!status || (status === "predicted" ? f.prediction : status === "bet" ? f.prediction?.decision === "BET" : !f.prediction)));
  return (
    <>
      <div className="topbar"><div><h1>Upcoming Matches</h1><div className="sub">{data.data_mode} · times in Europe/Rome · click a row for full analysis</div></div></div>
      <div className="filters">
        <select value={comp} onChange={(e) => setComp(e.target.value)}><option value="">All competitions ({data.fixtures.length})</option>{comps.map((c) => <option key={c}>{c}</option>)}</select>
        <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option><option value="predicted">Predicted</option><option value="bet">Value bets</option><option value="ineligible">Not eligible</option></select>
        <select value={day} onChange={(e) => setDay(e.target.value)}><option value="">All dates</option>{days.map((d) => <option key={d}>{d}</option>)}</select>
        <input placeholder="Team…" value={team} onChange={(e) => setTeam(e.target.value)} />
      </div>
      <Card>
        <div className="tablewrap" style={{ maxHeight: "none" }}>
          <table>
            <thead><tr><th>Kickoff</th><th>Match</th><th>Form (H / A)</th><th className="num">Odds 1 / X / 2</th><th>Model 1X2</th><th className="num">xG</th><th>Quality</th><th>Best value</th><th>Status</th></tr></thead>
            <tbody>
              {rows.map((f: any) => {
                const p = f.prediction;
                const ref = f.odds?.B365 || f.odds?.Avg || f.odds?.PS || Object.values(f.odds || {})[0];
                const best = f.best_value;
                const oddsErr = f.odds_suspect || (f.data_error_markets || []).length > 0;
                return (
                  <React.Fragment key={f.id}>
                    <tr className="fixture-row" onClick={() => setOpen(open === f.id ? null : f.id)}>
                      <td className="mono">{romeTime(f.kickoff_utc)}</td>
                      <td className="match">{f.home} – {f.away}<small>{f.competition_name}{f.status !== "scheduled" ? ` · ${f.status.toUpperCase()}` : ""}</small></td>
                      <td><Form s={p?.inputs?.form?.home?.string?.slice(-5)} /><br /><Form s={p?.inputs?.form?.away?.string?.slice(-5)} /></td>
                      <td className="num">{ref ? `${num(ref.home)} / ${num(ref.draw)} / ${num(ref.away)}` : "—"}</td>
                      <td><ProbBar p={p?.probs?.["1X2"]} /></td>
                      <td className="num">{p ? `${num(p.exp_home_goals, 1)}–${num(p.exp_away_goals, 1)}` : "—"}</td>
                      <td><Quality q={p?.data_quality} /></td>
                      <td className="mono">{best ? <span className={best.qualifies ? "pos" : "muted"}>{selLabel(best.market, best.selection, best.line)} {spct(best.ev_conservative)}</span> : "—"}
                        {oddsErr && <div><span className="badge b-err" title="Some bookmaker prices look corrupt; those markets were excluded">⚠ ODDS ERROR</span></div>}</td>
                      <td>{p ? <Decision d={p.decision} /> : new Date(f.kickoff_utc) <= new Date() ? <span className="badge b-pending">STARTED · AWAITING RESULT</span>
                        : <span className="badge b-inel" title={(f.ineligible_reasons || []).join("; ")}>{f.coverage_label === "DATA COVERAGE ONLY — PREDICTIONS NOT ENABLED" ? "COVERAGE ONLY" : "INSUFFICIENT DATA"}</span>}</td>
                    </tr>
                    {open === f.id && <tr className="detail"><td colSpan={9}><Detail f={f} /></td></tr>}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty">No fixtures match the filter.</div>}
        </div>
      </Card>
    </>
  );
}
