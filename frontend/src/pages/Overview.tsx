import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "../hooks";
import { Card, Decision, Loading, ProbBar, Quality, Stat, ago, cls, eur, num, pct, romeTime, selLabel, spct, tooltipStyle } from "../ui";
import { Link } from "react-router-dom";
import TodayCard from "./TodayCard";
import { sampleNote, smallSample } from "../lib/honesty";

export default function Overview() {
  const { data, error, updated } = useApi<any>("overview", 60000);
  if (!data) return <Loading error={error} />;
  const b = data.bankroll;
  const curve = [{ t: "start", bankroll: b.starting_bankroll }, ...data.pnl_curve.map((p: any) => ({ t: p.t?.slice(0, 10), bankroll: p.bankroll }))];
  const m = data.model?.metrics?.backtest;
  return (
    <>
      <div className="topbar">
        <div><h1>Overview</h1><div className="sub">Live state of the lab · auto-refresh 60s · updated {updated ? ago(updated.toISOString()) : "—"}</div></div>
        <div className="chips">
          <span className="pill"><span className={`dot ${data.scheduler_running ? "ok" : "warn"}`} />scheduler {data.scheduler_running ? "running" : "off"}</span>
          <span className="pill">last data {ago(data.last_data_update)}</span>
          <span className="pill">{data.model ? `${data.model.name} v${data.model.version}` : "no model"}</span>
        </div>
      </div>
      <TodayCard />
      <div className="grid g6" style={{ marginTop: 12 }}>
        {/* headline = equity (cash + open stakes), like My view and the chart; cash shown underneath */}
        <Stat label="Virtual bankroll" value={eur(b.equity ?? b.current_bankroll)} delta={`cash ${eur(b.current_bankroll)} + open ${eur(b.pending_exposure)} · start ${eur(b.starting_bankroll)}`} />
        <Stat label="Net P/L (settled)" value={eur(b.profit, true)} tone={cls(b.profit)} delta={`staked ${eur(b.staked)}`} />
        {/* display only: below MIN_SAMPLE settled bets a percentage is noise (1 bet showed "ROI +333 %") */}
        <Stat label="ROI" value={smallSample(b.settled) ? "—" : spct(b.roi)} tone={smallSample(b.settled) ? undefined : cls(b.roi)} delta={smallSample(b.settled) ? sampleNote(b.settled) : `CLV ${spct(b.avg_clv)}`} />
        <Stat label="Total bets" value={b.bets} delta={`${b.won}W · ${b.lost}L · ${b.void}V`} />
        <Stat label="Win rate" value={smallSample(b.settled) ? "—" : pct(b.win_rate)} delta={smallSample(b.settled) ? `profit ${eur(b.profit)} so far` : `max DD ${eur(b.max_drawdown)}`} />
        <Stat label="Pending bets" value={b.pending} delta={`${data.predictions_total} predictions stored`} />
      </div>
      <div className="grid g3" style={{ marginTop: 12 }}>
        <Card title="Bankroll (settled bets)" className="span2">
          {curve.length > 1 ? (
            <ResponsiveContainer width="100%" height={210}>
              <AreaChart data={curve}>
                <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22c55e" stopOpacity={0.35} /><stop offset="100%" stopColor="#22c55e" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid stroke="#1a2430" vertical={false} />
                <XAxis dataKey="t" stroke="#4f5e6d" fontSize={10} />
                <YAxis stroke="#4f5e6d" fontSize={10} domain={["auto", "auto"]} />
                <Tooltip {...tooltipStyle} />
                <Area isAnimationActive={false} type="stepAfter" dataKey="bankroll" stroke="#22c55e" fill="url(#g)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="empty">No settled bets yet — the curve starts at {eur(b.starting_bankroll)} and moves only when verified results settle virtual bets.</div>
          )}
        </Card>
        <Card title="Model status">
          <div className="kv">
            <span>Model</span><span className="mono">{data.model?.name} {data.model?.version}</span>
            <span>Backtest log loss</span><span className="mono">{num(m?.ensemble?.log_loss, 4)} <span className="muted">(market {num(m?.market?.log_loss, 4)})</span></span>
            <span>Backtest Brier</span><span className="mono">{num(m?.ensemble?.brier, 4)}</span>
            <span>Backtest matches</span><span className="mono">{m?.ensemble?.n ?? "—"}</span>
            <span>Backtest strategy ROI</span><span className={`mono ${cls(data.model?.metrics?.strategy?.roi)}`}>{spct(data.model?.metrics?.strategy?.roi)} ({data.model?.metrics?.strategy?.bets ?? 0} bets)</span>
            <span>Last daily cycle</span><span className="mono">{data.last_daily_run ? `${data.last_daily_run.status} · ${ago(data.last_daily_run.at)}` : "—"}</span>
          </div>
          <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>{data.model?.description}</p>
        </Card>
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <Card title="Open virtual bets (best EV first)" right={<Link to="/slip">bet slip →</Link>}>
          {data.opportunities.length === 0 ? (
            <div className="nobet-hero">No open bets right now{b.settled ? <> · {b.settled} settled → <Link to="/history">History</Link></> : null}.<br /><span>No bet is a valid decision when no price is clearly too generous.</span></div>
          ) : (
            <table><thead><tr><th>Match</th><th>Selection</th><th className="num">Odds</th><th className="num">EV</th><th>Kickoff</th></tr></thead>
              <tbody>{data.opportunities.map((o: any) => (
                <tr key={o.id}><td className="match">{o.fixture.home} – {o.fixture.away}<small>{o.fixture.competition_name}</small></td>
                  <td>{selLabel(o.market, o.selection, o.line)}</td><td className="num">{num(o.price)}</td><td className="num pos">{spct(o.ev)}</td><td className="mono">{romeTime(o.fixture.kickoff_utc)}</td></tr>))}</tbody></table>
          )}
        </Card>
        <Card title={`Upcoming (${data.upcoming_count} in 7 days · ${data.predicted_count} predicted)`} right={<Link to="/upcoming">all →</Link>}>
          <div className="tablewrap"><table><thead><tr><th>Kickoff (Rome)</th><th>Match</th><th>1X2 model</th><th>Quality</th><th>Status</th></tr></thead>
            <tbody>{data.upcoming.map((f: any) => (
              <tr key={f.id}><td className="mono">{romeTime(f.kickoff_utc)}</td><td className="match">{f.home} – {f.away}<small>{f.competition_name}</small></td>
                <td><ProbBar p={f.probs_1x2} /></td><td><Quality q={f.data_quality} /></td><td><Decision d={f.decision} /></td></tr>))}</tbody></table></div>
        </Card>
      </div>
    </>
  );
}
