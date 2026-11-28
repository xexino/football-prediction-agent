import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useApi } from "../../hooks";
import { Card, Loading, Stat, Status, cls, eur, num, pct, romeTime, spct, tooltipStyle } from "../../ui";
import { SubNav } from "./common";
import { sampleNote, smallSample } from "../../lib/honesty";

function Perf({ data, label }: { data: Record<string, any>; label: string }) {
  const rows = Object.entries(data || {});
  if (!rows.length) return <div className="empty">No bets yet.</div>;
  return <table><thead><tr><th>{label}</th><th className="num">Bets</th><th className="num">Settled</th><th className="num">P/L</th><th className="num">ROI</th><th className="num">Win rate</th><th className="num">CLV</th></tr></thead>
    <tbody>{rows.map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{v.bets}</td><td className="num">{v.settled}</td><td className={`num ${cls(v.profit)}`}>{eur(v.profit, true)}</td><td className={`num ${smallSample(v.settled) ? "" : cls(v.roi)}`}>{smallSample(v.settled) ? "—" : spct(v.roi)}</td><td className="num">{smallSample(v.settled) ? "—" : pct(v.win_rate)}</td><td className="num">{spct(v.avg_clv)}</td></tr>)}</tbody></table>;
}

export default function EngineB() {
  const { data, error } = useApi<any>("engine_b/performance", 300000);
  if (!data) return <Loading error={error} />;
  const o = data.overall, v = data.validation;
  const hist = data.bankroll.history.map((h: any) => ({ t: h.t?.slice(5, 16).replace("T", " "), balance: h.balance })).filter((h: any, i: number, a: any[]) => i === a.length - 1 || a[i + 1].t !== h.t);
  const m1 = v?.metrics_1x2 || {};
  return (
    <>
      <div className="topbar"><div><h1>Engine B — track record</h1><div className="sub">{data.disclaimer}</div></div></div>
      <SubNav />
      <div className="grid g6">
        <Stat label="Engine B bankroll" value={eur((data.bankroll.current ?? 0) + (data.bankroll.open ?? 0))}
              delta={`cash ${eur(data.bankroll.current)} + open ${eur(data.bankroll.open ?? 0)} · capital ${eur(data.bankroll.capital ?? data.bankroll.start)}`} />
        <Stat label="P/L (settled)" value={eur(o.profit, true)} tone={cls(o.profit)} delta={`staked ${eur(o.staked)}`} />
        <Stat label="ROI" value={smallSample(o.settled) ? "—" : spct(o.roi)} tone={smallSample(o.settled) ? undefined : cls(o.roi)} delta={smallSample(o.settled) ? sampleNote(o.settled) : `n = ${o.settled}`} />
        <Stat label="Selections" value={o.bets} delta={`${o.pending} pending`} />
        <Stat label="Win rate" value={smallSample(o.settled) ? "—" : pct(o.win_rate)} delta={`n = ${o.settled}`} />
        <Stat label="Predictions" value={data.predictions_total} delta="pre-match, immutable" />
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <Card title="Bankroll (Engine B ledger)">{hist.length > 1 ? <ResponsiveContainer width="100%" height={200}><AreaChart data={hist}><CartesianGrid stroke="#1a2430" vertical={false} /><XAxis dataKey="t" stroke="#4f5e6d" fontSize={10} /><YAxis stroke="#4f5e6d" fontSize={10} domain={["auto", "auto"]} /><Tooltip {...tooltipStyle} /><Area isAnimationActive={false} type="stepAfter" dataKey="balance" stroke="#a78bfa" fill="#a78bfa22" /></AreaChart></ResponsiveContainer> : <div className="empty">€500 starting balance (raised from €100 on 25 Nov 2026); the curve moves as selections are placed and settled.</div>}</Card>
        <Card title="Live prediction accuracy (settled fixtures)">
          {Object.keys(data.prediction_metrics).length ? <table><tbody>{Object.entries(data.prediction_metrics).map(([k, x]: any) => <tr key={k}><td>{k.replace(/_/g, " ")}</td><td className="num">{/(correct|_in_|in_80|hit|rate)/.test(k) ? pct(x.mean, 1) : num(x.mean, 3)}</td><td className="num muted">n={x.n}</td></tr>)}</tbody></table>
            : <div className="empty">No settled fixtures yet — metrics appear as results arrive.</div>}
        </Card>
      </div>
      {v && <Card title={`Walk-forward validation — ${v.model} · ${v.start.slice(0, 10)} → ${v.end.slice(0, 10)} · same matches for every model`}>
        <div className="grid g2">
          <div><h3>1X2 (lower log loss/Brier is better)</h3><table><thead><tr><th>Model</th><th className="num">n</th><th className="num">Log loss</th><th className="num">Brier</th><th className="num">Acc.</th><th className="num">ECE</th></tr></thead>
            <tbody>{Object.entries(m1).filter(([, x]) => x).map(([k, x]: any) => <tr key={k}><td>{k.replace("_", " ")}</td><td className="num">{x.n}</td><td className="num">{num(x.log_loss, 4)}</td><td className="num">{num(x.brier, 4)}</td><td className="num">{pct(x.accuracy)}</td><td className="num">{num(x.ece, 4)}</td></tr>)}</tbody></table></div>
          <div><h3>Goal & count markets</h3><table><tbody>
            {Object.entries(v.ou25 || {}).map(([k, x]: any) => x && <tr key={"ou" + k}><td>Over/Under 2.5 — {k.replace("_", " ")}</td><td className="num">LL {num(x.log_loss, 4)}</td><td className="num muted">n={x.n}</td></tr>)}
            {Object.entries(v.btts || {}).map(([k, x]: any) => x && <tr key={"bt" + k}><td>BTTS — {k.replace("_", " ")}</td><td className="num">LL {num(x.log_loss, 4)}</td><td className="num muted">n={x.n}</td></tr>)}
            {Object.entries(v.counts || {}).map(([k, x]: any) => <tr key={k}><td>{k}: abs. error vs league-mean baseline · 80% interval hit</td><td className="num">{num(x.abs_err, 3)} vs {num(x.baseline_abs_err, 3)} · {pct(x.in_80, 0)}</td><td className="num muted">n={x.n}</td></tr>)}
          </tbody></table></div>
        </div>
        <h3 style={{ marginTop: 10 }}>Simulated strategy (Engine B rules, historical)</h3>
        <Perf data={{ "All markets": v.strategy_engine_b, ...Object.fromEntries(Object.entries(v.strategy_engine_b_by_market || {}).map(([k, x]) => [k, x])) }} label="Segment" />
        <p className="muted" style={{ fontSize: 11 }}>95% ROI intervals: {Object.entries(v.strategy_engine_b_by_market || {}).map(([k, x]: any) => `${k} ${x.roi_95ci ? `${spct(x.roi_95ci[0])}…${spct(x.roi_95ci[1])}` : "n/a"}`).join(" · ")}. Engine B 1X2 selections are disabled because this interval was entirely negative. {v.note}</p>
      </Card>}
      <div className="grid g2">
        <Card title="By market"><Perf data={data.by_market} label="Market" /></Card>
        <Card title="By competition / mode / model"><Perf data={data.by_competition} label="Competition" /><div style={{ height: 8 }} /><Perf data={data.by_mode} label="Mode" /><div style={{ height: 8 }} /><Perf data={data.by_model} label="Model" /></Card>
      </div>
      <Card title="Engine B ledger (all selections, including losers)">
        {data.ledger.length ? <div className="tablewrap"><table><thead><tr><th>Placed</th><th>Match</th><th>Selection</th><th className="num">Odds</th><th className="num">EV</th><th>Status</th><th className="num">P/L</th><th>Reason</th></tr></thead>
          <tbody>{data.ledger.map((b: any) => <tr key={b.id}><td className="mono">{romeTime(b.created_at)}</td><td className="match">{b.match}<small>{b.competition}</small></td><td>{b.market} {b.selection}</td><td className="num">{num(b.price)}</td><td className="num">{spct(b.ev)}</td><td><Status s={b.status} /></td><td className={`num ${cls(b.profit)}`}>{b.profit == null ? "—" : eur(b.profit, true)}</td><td className="muted" style={{ fontSize: 11 }}>{b.reason}</td></tr>)}</tbody></table></div>
          : <div className="nobet-hero">NO SELECTIONS YET — Engine B only bets when its rules are met.</div>}
      </Card>
      <Card title="Model versions">{data.models.map((m: any) => <p key={m.version} style={{ fontSize: 12 }}><b className="mono">{m.name} {m.version}</b> — {m.description}</p>)}</Card>
    </>
  );
}
