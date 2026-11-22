import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis, Legend, ComposedChart, Area } from "recharts";
import { useApi } from "../hooks";
import { Card, Loading, Stat, cls, eur, num, pct, spct, tooltipStyle } from "../ui";

function PerfTable({ data, label }: { data: Record<string, any>; label: string }) {
  const rows = Object.entries(data || {});
  if (!rows.length) return <div className="empty">No data yet.</div>;
  return (
    <table><thead><tr><th>{label}</th><th className="num">Bets</th><th className="num">Settled</th><th className="num">P/L</th><th className="num">ROI</th><th className="num">Win rate</th><th className="num">Avg odds</th><th className="num">CLV</th></tr></thead>
      <tbody>{rows.map(([k, v]) => (
        <tr key={k}><td>{k}</td><td className="num">{v.bets}</td><td className="num">{v.settled ?? v.bets}</td><td className={`num ${cls(v.profit)}`}>{eur(v.profit, true)}</td>
          <td className={`num ${cls(v.roi)}`}>{spct(v.roi)}</td><td className="num">{pct(v.win_rate)}</td><td className="num">{num(v.avg_odds ?? v.avg_price)}</td><td className={`num ${cls(v.avg_clv)}`}>{spct(v.avg_clv)}</td></tr>))}</tbody></table>
  );
}

function Calib({ pts, title }: { pts: any[]; title: string }) {
  if (!pts?.length) return <div className="empty">Calibration needs evaluated predictions.</div>;
  return (
    <ResponsiveContainer width="100%" height={240}>
      <ScatterChart margin={{ top: 10, right: 10, bottom: 10, left: 0 }}>
        <CartesianGrid stroke="#1a2430" />
        <XAxis type="number" dataKey="predicted" domain={[0, 1]} stroke="#4f5e6d" fontSize={10} name="predicted" tickFormatter={(v) => pct(v, 0)} />
        <YAxis type="number" dataKey="observed" domain={[0, 1]} stroke="#4f5e6d" fontSize={10} name="observed" tickFormatter={(v) => pct(v, 0)} />
        <ZAxis type="number" dataKey="n" range={[30, 260]} />
        <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#4f5e6d" strokeDasharray="4 4" />
        <Tooltip {...tooltipStyle} formatter={(v: any) => (typeof v === "number" && v <= 1 ? pct(v) : v)} />
        <Scatter name={title} data={pts} fill="#22d3ee" />
      </ScatterChart>
    </ResponsiveContainer>
  );
}

export default function Analytics() {
  const { data, error } = useApi<any>("analytics", 300000);
  if (!data) return <Loading error={error} />;
  const L = data.live, B = data.backtest;
  const curve = [{ t: "start", bankroll: L.starting_bankroll, cum: 0 }, ...L.pnl_curve.map((p: any) => ({ t: p.t.slice(0, 10), bankroll: p.bankroll, cum: p.cum_profit }))];
  const metricRows = B ? Object.entries(B.metrics).filter(([, v]) => v).map(([k, v]: any) => ({ model: k, ...v })) : [];
  const btCurve = (B?.cumulative_pnl || []).map((v: number, i: number) => ({ i, pnl: v }));
  const blend = B?.market_blend_scan?.second_half ? Object.entries(B.market_blend_scan.second_half).map(([w, ll]: any) => ({ w, test: ll, train: B.market_blend_scan.first_half[w] })) : [];
  return (
    <>
      <div className="topbar"><div><h1>Analytics</h1><div className="sub">Live simulated performance + walk-forward backtest ({B ? `${B.start.slice(0, 10)} → ${B.end.slice(0, 10)}` : "not run yet"})</div></div></div>
      <div className="grid g6">
        <Stat label="Bankroll" value={eur(L.current_bankroll)} delta={`equity ${eur(L.equity)}`} />
        <Stat label="Net P/L" value={eur(L.profit, true)} tone={cls(L.profit)} />
        <Stat label="ROI" value={spct(L.roi)} tone={cls(L.roi)} />
        <Stat label="Win rate" value={pct(L.win_rate)} delta={`${L.settled} settled`} />
        <Stat label="Max drawdown" value={eur(L.max_drawdown)} />
        <Stat label="Live Brier / log loss" value={num(L.prediction_metrics.brier, 3)} delta={`log loss ${num(L.prediction_metrics.log_loss, 3)} · n=${L.prediction_metrics.evaluated}`} />
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <Card title="Bankroll history & cumulative P/L (live)">
          {curve.length > 1 ? (
            <ResponsiveContainer width="100%" height={240}><ComposedChart data={curve}><CartesianGrid stroke="#1a2430" vertical={false} /><XAxis dataKey="t" stroke="#4f5e6d" fontSize={10} /><YAxis yAxisId="a" stroke="#4f5e6d" fontSize={10} domain={["auto", "auto"]} /><YAxis yAxisId="b" orientation="right" stroke="#4f5e6d" fontSize={10} /><Tooltip {...tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} /><Area yAxisId="a" type="stepAfter" dataKey="bankroll" stroke="#22c55e" fill="#22c55e22" /><Line yAxisId="b" type="stepAfter" dataKey="cum" stroke="#4ea1ff" dot={false} name="cumulative P/L" /></ComposedChart></ResponsiveContainer>
          ) : <div className="empty">No settled bets yet. Live performance appears as verified results settle bets.</div>}
        </Card>
        <Card title="Live calibration (original predictions, 1X2)"><Calib pts={L.prediction_metrics.calibration} title="live" /></Card>
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <Card title="Live performance by competition"><div className="tablewrap"><PerfTable data={L.by_competition} label="Competition" /></div></Card>
        <Card title="Live performance by market / odds range / model">
          <PerfTable data={L.by_market} label="Market" /><div style={{ height: 10 }} /><PerfTable data={L.by_odds_range} label="Odds" /><div style={{ height: 10 }} /><PerfTable data={L.by_model} label="Model" />
        </Card>
      </div>
      {B && (
        <>
          <h2 style={{ fontSize: 14, margin: "22px 0 10px" }}>Walk-forward backtest — {B.model} · {B.metrics.ensemble?.n} matches · refit every {B.step_days} days</h2>
          <div className="grid g3">
            <Card title="Model comparison (lower is better)" className="span2">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={metricRows}><CartesianGrid stroke="#1a2430" vertical={false} /><XAxis dataKey="model" stroke="#4f5e6d" fontSize={10} /><YAxis stroke="#4f5e6d" fontSize={10} domain={[0.9, "auto"]} /><Tooltip {...tooltipStyle} /><Bar dataKey="log_loss" fill="#4ea1ff" name="log loss" /></BarChart>
              </ResponsiveContainer>
              <table><thead><tr><th>Model</th><th className="num">n</th><th className="num">Log loss</th><th className="num">Brier</th><th className="num">Accuracy</th></tr></thead>
                <tbody>{metricRows.map((r: any) => <tr key={r.model}><td>{r.model}</td><td className="num">{r.n}</td><td className="num">{num(r.log_loss, 4)}</td><td className="num">{num(r.brier, 4)}</td><td className="num">{pct(r.accuracy)}</td></tr>)}</tbody></table>
            </Card>
            <Card title="Backtest calibration (ensemble)"><Calib pts={B.calibration.ensemble} title="ensemble" /></Card>
          </div>
          <div className="grid g3" style={{ marginTop: 12 }}>
            <Card title="Simulated strategy (backtest, 1u flat)">
              <div className="kv">
                <span>Bets</span><span className="mono">{B.strategy.bets}</span><span>Profit</span><span className={`mono ${cls(B.strategy.profit)}`}>{num(B.strategy.profit)}u</span>
                <span>ROI</span><span className={`mono ${cls(B.strategy.roi)}`}>{spct(B.strategy.roi)}</span><span>Win rate</span><span className="mono">{pct(B.strategy.win_rate)}</span>
                <span>Max drawdown</span><span className="mono">{num(B.strategy.max_drawdown)}u</span><span>Avg CLV</span><span className="mono">{spct(B.strategy.avg_clv)}</span>
              </div>
              <p className="muted" style={{ fontSize: 11 }}>{B.note}</p>
            </Card>
            <Card title="Backtest cumulative P/L (units)" className="span2">
              {btCurve.length ? <ResponsiveContainer width="100%" height={200}><LineChart data={btCurve}><CartesianGrid stroke="#1a2430" vertical={false} /><XAxis dataKey="i" hide /><YAxis stroke="#4f5e6d" fontSize={10} /><ReferenceLine y={0} stroke="#4f5e6d" /><Tooltip {...tooltipStyle} /><Line dataKey="pnl" stroke="#f5b942" dot={false} strokeWidth={2} /></LineChart></ResponsiveContainer> : <div className="empty">The rules selected no bets in the backtest period.</div>}
            </Card>
          </div>
          <div className="grid g2" style={{ marginTop: 12 }}>
            <Card title="Backtest strategy by market & odds"><PerfTable data={B.strategy_by_market} label="Market" /><div style={{ height: 10 }} /><PerfTable data={B.strategy_by_odds} label="Odds" /></Card>
            <Card title="Backtest strategy by competition"><div className="tablewrap"><PerfTable data={B.strategy_by_competition} label="Competition" /></div></Card>
          </div>
          {blend.length > 0 && (
            <Card title="How much does the model add to the market? (log loss of w·model + (1−w)·market)">
              <ResponsiveContainer width="100%" height={200}><LineChart data={blend}><CartesianGrid stroke="#1a2430" /><XAxis dataKey="w" stroke="#4f5e6d" fontSize={10} /><YAxis stroke="#4f5e6d" fontSize={10} domain={["auto", "auto"]} /><Tooltip {...tooltipStyle} /><Legend wrapperStyle={{ fontSize: 11 }} /><Line dataKey="train" stroke="#4ea1ff" name="first half (fit)" /><Line dataKey="test" stroke="#22c55e" name="second half (check)" /></LineChart></ResponsiveContainer>
              <p className="muted" style={{ fontSize: 11 }}>{B.market_blend_scan.note} Optimal w on first half: {B.market_blend_scan.optimal_w_first_half}. The value engine's market-shrink weight is set from this, not from betting profit.</p>
            </Card>
          )}
        </>
      )}
      <Card title="Model versions">
        <table><thead><tr><th>Model</th><th>Created</th><th>Parameters</th></tr></thead>
          <tbody>{data.models.map((m: any) => <tr key={m.id}><td className="mono">{m.name} {m.version}</td><td className="mono">{m.created_at?.slice(0, 16)}</td><td className="muted mono" style={{ fontSize: 11 }}>{JSON.stringify(m.params)}</td></tr>)}</tbody></table>
      </Card>
    </>
  );
}
