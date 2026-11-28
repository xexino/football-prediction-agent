import { useParams, Link } from "react-router-dom";
import { useApi } from "../../hooks";
import { Card, Loading, num, pct, romeTime, Status, statusNow } from "../../ui";
import { Coverage, SubNav, Tri, liveLabel } from "./common";

const SECTION_TITLES: Record<string, string> = {
  assessment: "Overall assessment", goals: "Goals", corners: "Corners", corners_note: "Corners — model reliability",
  cards: "Cards", form: "Recent form", head_to_head: "Head to head", confidence: "Confidence",
};

function Matrix({ m }: { m: number[][] }) {
  const max = Math.max(...m.flat());
  return (
    <div className="tablewrap"><table className="cs-matrix">
      <thead><tr><th>H \ A</th>{m[0].map((_, j) => <th key={j} className="num">{j}</th>)}</tr></thead>
      <tbody>{m.map((row, i) => <tr key={i}><th>{i}</th>{row.map((v, j) => (
        <td key={j} className="num" style={{ background: `rgba(34,197,94,${(v / max) * 0.55})` }} title={`${i}-${j}: ${pct(v, 1)}`}>{v >= 0.005 ? pct(v, 1) : ""}</td>))}</tr>)}</tbody>
    </table></div>
  );
}

function MarketRows({ mk }: { mk: any }) {
  const rows: [string, string][] = [];
  const add = (label: string, v?: number) => v !== undefined && rows.push([label, pct(v, 1)]);
  add("Double chance 1X", mk.DC?.["1X"]); add("Double chance X2", mk.DC?.["X2"]); add("Double chance 12", mk.DC?.["12"]);
  add("Both teams to score — yes", mk.BTTS?.yes);
  for (const l of ["05", "15", "25", "35", "45"]) add(`Over ${l[0]}.${l[1]} goals`, mk[`OU${l}`]?.over);
  add("Home clean sheet", mk.CLEAN_SHEET?.home); add("Away clean sheet", mk.CLEAN_SHEET?.away);
  add("Home scores first", mk.FIRST_TO_SCORE?.home); add("Away scores first", mk.FIRST_TO_SCORE?.away); add("No goals", mk.FIRST_TO_SCORE?.none);
  for (const [key, name] of [["CORNERS", "corners"], ["YELLOWS", "yellow cards"], ["SOT", "shots on target"], ["SHOTS", "shots"], ["FOULS", "fouls"]]) {
    const c = mk[key];
    if (!c) continue;
    rows.push([`Expected ${name} (home–away · total)`, `${num(c.expected.home, 1)}–${num(c.expected.away, 1)} · ${num(c.expected.total, 1)} (80%: ${c.interval_80[0]}–${c.interval_80[1]})`]);
    Object.entries(c).filter(([k]) => k.startsWith("OU")).forEach(([k, v]: any) => add(`Over ${k.slice(2)} ${name}`, v.over));
    Object.entries(c).filter(([k]) => k.includes("_OU")).forEach(([k, v]: any) => add(`${k.startsWith("home") ? "Home" : "Away"} over ${k.split("_OU")[1]} ${name}`, v.over));
  }
  add("Red card in match (league base rate)", mk.RED?.any_red_card);
  return <table><tbody>{rows.map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{v}</td></tr>)}</tbody></table>;
}

export default function InsightDetail() {
  const { id } = useParams();
  const { data, error } = useApi<any>(`insights/${id}`, 60000);
  if (!data && error && /404/.test(String(error)))
    return <div className="empty">Match not found — it may be outside the current snapshot. <Link to="/insights">Back to Match Insights</Link></div>;
  if (!data) return <Loading error={error} />;
  const f = data.fixture, p = data.prediction, rep = p?.report;
  const lastLive = data.live[data.live.length - 1];
  return (
    <>
      <div className="topbar"><div><h1>{f.home} vs {f.away}</h1><div className="sub">{f.competition_name} · {romeTime(f.kickoff_utc)} · {statusNow(f)}</div></div>
        <div className="chips"><Coverage s={f.coverage_status} />{data.model && <span className="pill">{data.model.name} {data.model.version}</span>}</div></div>
      <SubNav />
      {!p ? <div className="empty">Engine B has not produced a prediction for this fixture: not enough reliable data. Coverage status: {f.coverage_status}.</div> : (
        <>
          <div className="grid g3">
            <Card title="Engine B — match outcome" className="span2">
              <Tri p={p.markets["1X2"]} labels={[f.home, "Draw", f.away]} />
              <div className="ai-stats mono" style={{ marginTop: 10 }}>
                <span>xG {num(p.markets.EXPECTED_GOALS.home, 2)} – {num(p.markets.EXPECTED_GOALS.away, 2)} (total {num(p.markets.EXPECTED_GOALS.total, 2)})</span>
                <span>confidence {num(p.confidence, 0)}/100</span>{p.cross_league_low_confidence && <span className="warn" title="Engine B compares ratings from different leagues here, and at least one team may lack domestic-league history in its data. Treat this prediction as low confidence.">cross-league rating · low confidence</span>}<span>data quality {num(p.data_quality, 0)}/100</span>
              </div>
              <p className="muted" style={{ fontSize: 11 }}>Predicted {romeTime(p.created_at)} · revision {p.revision} · training data up to {romeTime(p.data_cutoff)}. Probabilities, not certainties.</p>
            </Card>
            <Card title="Engine A vs Engine B vs market">
              <table><thead><tr><th>Source</th><th className="num">1</th><th className="num">X</th><th className="num">2</th></tr></thead><tbody>
                {[["Engine B", p.markets["1X2"]], [`Engine A${data.engine_a?.model ? ` (${data.engine_a.model.replace("fil-ensemble ", "v")})` : ""}`, data.engine_a?.x12], ["Market (no-vig)", data.market]].map(([n, v]: any) => (
                  <tr key={n}><td>{n}</td>{v ? ["home", "draw", "away"].map((k) => <td key={k} className="num">{pct(v[k], 0)}</td>) : <td colSpan={3} className="muted">not available</td>}</tr>))}
              </tbody></table>
              {rep?.comparison?.engine_a_gap != null && <p className="muted" style={{ fontSize: 11 }}>Largest A/B gap {pct(rep.comparison.engine_a_gap, 0)}; B/market gap {rep.comparison.market_gap != null ? pct(rep.comparison.market_gap, 0) : "—"}.</p>}
            </Card>
          </div>
          <Card title="AI Match Analyst">
            {Object.entries(rep.sections).map(([k, v]: any) => <p key={k} style={{ margin: "6px 0" }}><b>{SECTION_TITLES[k] || k}.</b> {v}</p>)}
            <div className="grid g3" style={{ marginTop: 8 }}>
              <div><h3>Supports the prediction</h3>{rep.supporting.length ? <ul className="tight">{rep.supporting.map((x: string) => <li key={x}>{x}</li>)}</ul> : <div className="muted">—</div>}</div>
              <div><h3>Could make it wrong</h3>{rep.contradicting.length ? <ul className="tight">{rep.contradicting.map((x: string) => <li key={x}>{x}</li>)}</ul> : <div className="muted">—</div>}</div>
              <div><h3>Missing or unreliable information</h3><ul className="tight">{rep.missing.map((x: string) => <li key={x}>{x}</li>)}</ul></div>
            </div>
            <p className="muted" style={{ fontSize: 11 }}>Generated by {rep.generator}. Every statement comes from stored data or model output; nothing is assumed about injuries or lineups.</p>
          </Card>
          <div className="grid g2">
            <Card title="Correct-score probability matrix (home rows × away columns)"><Matrix m={p.score_matrix} /></Card>
            <Card title="All Engine B markets"><MarketRows mk={p.markets} />
              {Object.keys(p.unavailable || {}).length > 0 && <><h3 style={{ marginTop: 10 }}>Not available</h3><ul className="tight">{Object.entries(p.unavailable).map(([k, v]: any) => <li key={k}>{k.replace(/_/g, " ")}: {v}</li>)}</ul></>}
            </Card>
          </div>
        </>
      )}
      <div className="grid g2">
        <Card title="Live match" right={lastLive && <span className="muted mono" style={{ fontSize: 11 }}>{lastLive.provider} · {liveLabel(lastLive)}</span>}>
          {!data.live.length ? <div className="empty">No live data received for this match. Free-plan football-data.org scores are delayed; full live mode (minute, events, statistics) requires API_FOOTBALL_KEY.</div> : (
            <>
              <div className="ai-teams mono">{lastLive.score ?? "–"} {lastLive.minute != null ? `· ${lastLive.minute}' (${lastLive.minute_source})` : "· minute not supplied"} · <span className={liveLabel(lastLive).startsWith("LIVE") ? "neg" : "warn"}>{liveLabel(lastLive)}</span></div>
              {Object.keys(lastLive.stats || {}).length ? <table><tbody>{Object.entries(lastLive.stats).map(([k, v]: any) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{v.home}</td><td className="num">{v.away}</td></tr>)}</tbody></table>
                : <p className="muted" style={{ fontSize: 12 }}>The provider supplied no live statistics — none are shown.</p>}
              {lastLive.probs && <p className="mono" style={{ fontSize: 12 }}>Live: 1 {pct(lastLive.probs["1X2"].home, 0)} · X {pct(lastLive.probs["1X2"].draw, 0)} · 2 {pct(lastLive.probs["1X2"].away, 0)} — {lastLive.probs.assumptions}</p>}
              <h3>Snapshots ({data.live.length})</h3>
              <div className="tablewrap" style={{ maxHeight: 220 }}><table><tbody>{data.live.slice().reverse().map((l: any, i: number) => <tr key={i}><td className="mono">{romeTime(l.at)}</td><td>{l.label}</td><td className="mono">{l.minute ?? "—"}'</td><td className="mono">{l.score ?? "—"}</td><td className="mono">{l.probs ? `${pct(l.probs["1X2"].home, 0)}/${pct(l.probs["1X2"].draw, 0)}/${pct(l.probs["1X2"].away, 0)}` : "no live prediction"}</td></tr>)}</tbody></table></div>
              {data.events.length > 0 && <><h3>Events</h3><ul className="tight">{data.events.map((e: any, i: number) => <li key={i}>{e.minute}' {e.type} ({e.side}) {e.player || ""} {e.detail || ""}</li>)}</ul></>}
            </>
          )}
        </Card>
        <Card title="Prediction history & selections">
          <table><thead><tr><th>Rev</th><th>Created</th><th>1X2</th><th className="num">xG</th><th>Evaluation</th></tr></thead><tbody>
            {data.history.map((h: any) => <tr key={h.id}><td>{h.revision}</td><td className="mono">{romeTime(h.created_at)}</td><td className="mono">{pct(h.x12.home, 0)}/{pct(h.x12.draw, 0)}/{pct(h.x12.away, 0)}</td>
              <td className="num">{num(h.xg.home, 1)}–{num(h.xg.away, 1)}</td><td className="mono" style={{ fontSize: 11 }}>{h.evaluation ? `log loss ${num(h.evaluation.logloss_1x2, 3)} · ${h.evaluation.correct_1x2 ? "favourite won" : "favourite lost"}` : "pending result"}</td></tr>)}
          </tbody></table>
          <h3 style={{ marginTop: 10 }}>Engine B virtual selections</h3>
          {data.selections.length ? <table><tbody>{data.selections.map((b: any, i: number) => <tr key={i}><td>{b.market} {b.selection}</td><td className="num">{num(b.price)}</td><td><Status s={b.status} /></td><td className="muted" style={{ fontSize: 11 }}>{b.reason}</td></tr>)}</tbody></table>
            : <div className="nobet-hero">NO BET — Engine B found no selection meeting its rules for this match.</div>}
          <p style={{ marginTop: 10 }}><Link to="/insights">← all matches</Link></p>
        </Card>
      </div>
    </>
  );
}
