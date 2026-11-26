import { Link } from "react-router-dom";
import { useApi } from "../hooks";
import { matchState } from "../lib/matchState";
import { liveScoreText } from "../lib/honesty";

/** "My view": the whole lab in plain language, for someone who does not want tables and log loss. */

const rome = (iso: string) => new Date(iso).toLocaleString("en-GB", { timeZone: "Europe/Rome", weekday: "short", hour: "2-digit", minute: "2-digit" });
const romeDay = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Europe/Rome" });
const P = (x?: number) => (x === undefined || x === null ? "—" : `${Math.round(x * 100)}%`);

type X12 = { home: number; draw: number; away: number };

function pick(p: X12, home: string, away: string) {
  const [k, v] = (["home", "draw", "away"] as (keyof X12)[]).map((x) => [x, p[x]] as [keyof X12, number]).sort((a, b) => b[1] - a[1])[0];
  const who = k === "home" ? `${home} to win` : k === "away" ? `${away} to win` : "a draw";
  const strength = k === "draw" ? "a very open game" : v >= 0.6 ? "clear favourite" : v >= 0.45 ? "favourite" : "slight edge, could go any way";
  return { key: k, who, pct: v, strength };
}

function outcome(score?: string | null) {
  if (!score) return null;
  const [h, a] = score.split("-").map(Number);
  return h > a ? "home" : h < a ? "away" : "draw";
}

function StatusLight({ hd, ops }: { hd: any; ops: any }) {
  const ageH = hd ? (Date.now() - new Date(hd.computed_at).getTime()) / 3.6e6 : 99;
  const pipe = ops?.current?.state;
  const bad = pipe === "FAILED" || hd?.overall === "FAILED" || ageH > 8;
  const warn = !bad && (pipe === "DEGRADED" || hd?.overall !== "HEALTHY");
  const overdue = hd?.components?.results?.overdue || 0;
  const color = bad ? "#ef4444" : warn ? "#f59e0b" : "#22c55e";
  const text = bad ? (ageH > 8 ? `The data has not been refreshed for ${Math.round(ageH)} hours. The system will catch up automatically; nothing for you to do unless this lasts a day.`
    : "The last update failed. The previous data is still shown and the system will retry automatically.")
    : warn ? `Working. ${overdue ? `${overdue} finished match${overdue > 1 ? "es are" : " is"} still waiting for an official result (for Serie B, English lower leagues, Scotland and Japan our free result source updates 1–3 days after the match; a backup source is checked every 3 h for Serie B, League One/Two and Scotland).` : "Some data sources are slow, nothing is broken."}`
    : "Everything is working and up to date.";
  return (
    <div className="simple-card" style={{ borderLeft: `6px solid ${color}` }}>
      <div className="simple-k">Is everything working?</div>
      <div className="simple-v" style={{ color }}>{bad ? "Needs attention" : warn ? "Mostly yes" : "Yes"}</div>
      <div className="simple-t">{text} Last update: {hd ? `${Math.max(0, Math.round(ageH * 60))} min ago` : "…"}.</div>
    </div>
  );
}

/** CFO forecast (docs/council/cfo/2026-11-25-cfo-report.md): central −3.5 % per euro staked (clean closing-line
 *  value of the backtest bets), pessimistic −10 %, optimistic +3 %. */
const FORECAST = { central: -0.035, low: -0.10, high: 0.03 };

function ForecastVsReality({ ov }: { ov: any }) {
  if (!ov) return null;
  const b = ov.bankroll;
  const staked = b.staked || 0, actual = b.profit || 0;
  const exp = staked * FORECAST.central, lo = staked * FORECAST.low, hi = staked * FORECAST.high;
  const verdict = !b.settled ? "no settled bets yet"
    : actual > hi ? "better than the optimistic forecast (probably luck so far)"
    : actual < lo ? "worse than the pessimistic forecast"
    : actual >= exp ? "within the forecast range, above the central estimate" : "within the forecast range, below the central estimate";
  const eur = (x: number) => `${x < 0 ? "−" : "+"}€${Math.abs(x).toFixed(2)}`;
  return (
    <div className="simple-card" style={{ marginTop: 12 }}>
      <div className="simple-k">Forecast vs reality (settled bets only)</div>
      <div className="simple-t" style={{ marginTop: 6 }}>
        {b.settled ? <>{b.settled} settled bet{b.settled === 1 ? "" : "s"}, €{staked.toFixed(0)} staked. <b>Actual result {eur(actual)}</b> ·
        forecast {eur(exp)} (range {eur(lo)} to {eur(hi)}) → <b>{verdict}</b>.</>
          : <>No settled bets yet. The forecast per €10 bet is {eur(10 * FORECAST.central)} (range {eur(10 * FORECAST.low)} to {eur(10 * FORECAST.high)}); the comparison starts with the first settled bet.</>}
        {b.avg_clv != null && <> Average closing-line value {(b.avg_clv * 100).toFixed(1)}% (positive = we bet at better prices than the market's final price; the best early sign of a real edge).</>}
        {" "}A few dozen bets are mostly luck; the comparison becomes meaningful after ~150 bets for closing-line value and many hundreds for profit.
      </div>
    </div>
  );
}

export default function Simple() {
  const { data: ins } = useApi<any>("insights", 120000);
  const { data: cmp } = useApi<any>("engine_compare", 300000);
  const { data: hd } = useApi<any>("health_detail", 120000);
  const { data: ops } = useApi<any>("ops_status", 120000);
  const { data: ov } = useApi<any>("overview", 300000);

  const today = romeDay(new Date());
  const todays = (ins?.items || []).filter((i: any) => romeDay(new Date(i.kickoff_utc)) === today && (i.engine_a || i.engine_b))
    .sort((a: any, b: any) => a.kickoff_utc.localeCompare(b.kickoff_utc));

  // track record on finished matches the model predicted before kickoff (original prediction)
  // Engine A only (the main model); matches only Engine B covers (e.g. Champions League) are counted separately
  const doneAll = (cmp?.rows || []).filter((r: any) => r.result && (r.engine_a || r.engine_b));
  const done = doneAll.filter((r: any) => r.engine_a);
  const bOnly = doneAll.filter((r: any) => !r.engine_a);
  const bOnlyRight = bOnly.filter((r: any) => pick(r.engine_b, "", "").key === r.result).length;
  const ours = done.filter((r: any) => pick(r.engine_a, "", "").key === r.result).length;
  const mk = done.filter((r: any) => r.market);
  const mkRight = mk.filter((r: any) => pick(r.market, "", "").key === r.result).length;
  const oursOnMk = mk.filter((r: any) => pick(r.engine_a, "", "").key === r.result).length;
  const recent = doneAll.slice(0, 12);

  return (
    <>
      <div className="topbar"><div><h1>My view</h1><div className="sub">The lab in plain words. Everything is a simulation — no real money.</div></div>
        <div className="chips"><Link className="pill" to="/overview">detailed dashboard →</Link></div></div>

      <div className="simple-grid">
        <StatusLight hd={hd} ops={ops} />
        <div className="simple-card">
          <div className="simple-k">How good is the model?</div>
          <div className="simple-v">{done.length ? `${Math.round((ours / done.length) * 100)}% right` : "too early"}</div>
          <div className="simple-t">
            {done.length ? <>On the last {done.length} finished matches, the result the model thought most likely happened {ours} times.
              {mk.length ? <> On the {mk.length} of them with betting-market prices: model {oursOnMk}/{mk.length}, market {mkRight}/{mk.length}.</> : null}
              {bOnly.length ? <> Matches only our second engine (Engine B) covers, such as the Champions League: {bOnlyRight}/{bOnly.length}.</> : null}
              {" "}Guessing blindly is right about 1 time in 3. A few dozen games prove little: over thousands of past matches the betting market is still slightly more accurate than our model, so treat the market as the benchmark and ours as a second opinion.</>
              : "Results are still coming in; this fills up as matches are played."}
          </div>
        </div>
        <div className="simple-card">
          <div className="simple-k">Virtual money</div>
          <div className="simple-v">{ov ? `€${(ov.bankroll.equity ?? ov.bankroll.current_bankroll).toFixed(2)}` : "…"}</div>
          <div className="simple-t">Virtual capital €{ov ? ov.bankroll.starting_bankroll.toFixed(0) : "…"}. {ov ? `€${ov.bankroll.current_bankroll.toFixed(2)} free + €${(ov.bankroll.pending_exposure ?? 0).toFixed(2)} on ${ov.bankroll.pending} bet${ov.bankroll.pending === 1 ? "" : "s"} waiting for a result${ov.bankroll.pending && (ov.bankroll.pending_exposure ?? 0) < 10 * ov.bankroll.pending ? " (placed at €1 each, before the €10 rule)" : ""}.` : ""} The model "bets" a flat €10 only when the price is clearly too generous; most days the right answer is no bet.</div>
        </div>
      </div>

      <ForecastVsReality ov={ov} />

      <h2 className="simple-h">Today's games ({todays.length})</h2>
      {!todays.length && <div className="empty">No predicted games today.</div>}
      <div className="simple-list simple-2col">
        {todays.map((i: any) => {
          const p = i.engine_a || i.engine_b?.x12;
          const pk = pick(p, i.home, i.away);
          const res = outcome(i.score);
          const top = i.engine_b ? Object.keys(i.engine_b.top_scores)[0] : null;
          const goals = i.engine_b ? (i.engine_b.over25 >= 0.5 ? `3 or more goals more likely (${P(i.engine_b.over25)})` : `2 goals or fewer more likely (${P(1 - i.engine_b.over25)})`) : null;
          const st = matchState(i.kickoff_utc, i.phase);
          return (
            <Link key={i.id} to={`/insights/${i.id}`} className="simple-match">
              <div className="simple-when">{rome(i.kickoff_utc)} · {i.competition_name}</div>
              <div className="simple-teams">{i.home} <span>vs</span> {i.away}</div>
              <div className="simple-pick">{i.engine_a ? "Model says" : <>Engine B says <span className="pill" title="Our main model does not cover this competition">B</span></>}: <b>{pk.who}</b> ({P(pk.pct)}) — {pk.strength}</div>
              <div className="simple-bar">
                <span style={{ width: P(p.home), background: "#22c55e" }} title={`${i.home} ${P(p.home)}`} />
                <span style={{ width: P(p.draw), background: "#64748b" }} title={`draw ${P(p.draw)}`} />
                <span style={{ width: P(p.away), background: "#3b82f6" }} title={`${i.away} ${P(p.away)}`} />
              </div>
              <div className="simple-small">{i.home} {P(p.home)} · draw {P(p.draw)} · {i.away} {P(p.away)}{top ? ` · most likely score ${top}` : ""}{goals ? ` · ${goals}` : ""}</div>
              {i.market && (() => { const mk = pick(i.market, i.home, i.away); return (
                <div className="simple-small">Bookmakers: <b>{mk.who}</b> ({P(mk.pct)}) — {i.home} {P(i.market.home)} · draw {P(i.market.draw)} · {i.away} {P(i.market.away)}{mk.key === pk.key ? " · model and bookmakers agree" : " · model and bookmakers disagree"}</div>); })()}
              <div className="simple-result">
                {res ? <>Final score {i.score} — {res === pk.key ? <b className="pos">the model was right ✓</b> : <b className="neg">the model was wrong ✗</b>}</>
                  : st === "live" ? <span className="warn">Playing now{i.live?.score ? <> — <span className="muted">{liveScoreText(i.live.score, Math.max(0, Math.round((Date.now() - new Date(i.live.at).getTime()) / 60000)))}</span></> : " (or just finished)"}</span>
                  : st === "awaiting" ? <span className="warn">Finished — waiting for the official result{i.live?.score ? <> (last live score {i.live.score})</> : null}</span>
                  : st === "postponed" ? <span className="muted">Postponed / not played</span> : <span className="muted">Not started yet</span>}
              </div>
            </Link>
          );
        })}
      </div>

      <h2 className="simple-h">Recent results</h2>
      <div className="simple-list">
        {recent.map((r: any) => {
          const p = r.engine_a || r.engine_b;  // B-only rows are marked below
          const pk = pick(p, r.home, r.away);
          return (
            <Link key={r.id} to={`/insights/${r.id}`} className="simple-match simple-row">
              <span className="simple-when">{rome(r.kickoff_utc)}</span>
              <span className="simple-teams-s">{r.home} {r.score} {r.away}</span>
              <span>{r.engine_a ? "model" : "Engine B"}: {pk.who} ({P(pk.pct)})</span>
              <b className={pk.key === r.result ? "pos" : "neg"}>{pk.key === r.result ? "✓ right" : "✗ wrong"}</b>
            </Link>);
        })}
      </div>
      <p className="muted" style={{ fontSize: 11 }}>"Right" means the outcome the model rated most likely happened. A 45% favourite loses more often than it wins, so single games say little; the percentage over many games is what matters.</p>
    </>
  );
}
