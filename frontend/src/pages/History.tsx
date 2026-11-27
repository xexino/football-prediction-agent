import { useMemo, useState } from "react";
import { useApi } from "../hooks";
import { Card, Loading, Status, cls, eur, num, romeTime, selLabel, spct } from "../ui";
import { statusNow } from "../ui";
import { legacyStake } from "../lib/honesty";
import { fixAhReason } from "../lib/honesty";

export default function History() {
  const { data, error } = useApi<any>("bets", 120000);
  const { data: meta } = useApi<any>("meta", 600000);
  const [f, setF] = useState({ comp: "", market: "", status: "", team: "", from: "", to: "", model: "" });
  const comps = useMemo(() => Array.from(new Set((data?.items || []).map((b: any) => b.fixture.competition_name))).sort() as string[], [data]);
  if (!data) return <Loading error={error} />;
  const rows = data.items.filter((b: any) =>
    (!f.comp || b.fixture.competition_name === f.comp) && (!f.market || b.market === f.market) &&
    (!f.status || (f.status === "settled" ? b.status !== "pending" : b.status === f.status)) &&
    (!f.team || `${b.fixture.home} ${b.fixture.away}`.toLowerCase().includes(f.team.toLowerCase())) &&
    (!f.from || b.fixture.kickoff_utc >= f.from) && (!f.to || b.fixture.kickoff_utc.slice(0, 10) <= f.to) &&
    (!f.model || String(b.model_version_id) === f.model));
  const settled = rows.filter((b: any) => b.status !== "pending");
  const pl = settled.reduce((a: number, b: any) => a + (b.profit || 0), 0);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });
  return (
    <>
      <div className="topbar"><div><h1>Results & History</h1><div className="sub">All simulated bets, pending and settled, with settlement evidence.</div></div>
        <div className="chips"><span className="pill">{rows.length} bets</span><span className="pill">{settled.length} settled</span><span className={`pill ${cls(pl)}`}>P/L {eur(pl, true)}</span></div></div>
      <div className="filters">
        <input type="date" value={f.from} onChange={set("from")} title="from" /><input type="date" value={f.to} onChange={set("to")} title="to" />
        <select value={f.comp} onChange={set("comp")}><option value="">All competitions</option>{comps.map((c) => <option key={c}>{c}</option>)}</select>
        <select value={f.market} onChange={set("market")}><option value="">All markets</option><option>1X2</option><option>OU25</option><option>AH</option></select>
        <select value={f.status} onChange={set("status")}><option value="">All results</option><option value="pending">Pending</option><option value="settled">Settled</option><option value="won">Won</option><option value="lost">Lost</option><option value="void">Void</option></select>
        <select value={f.model} onChange={set("model")}><option value="">All models</option>{(meta?.models || []).map((m: any) => <option key={m.id} value={m.id}>{m.label}</option>)}</select>
        <input placeholder="Team…" value={f.team} onChange={set("team")} />
      </div>
      <Card>
        <div className="tablewrap">
          <table>
            <thead><tr><th>#</th><th>Placed</th><th>Match</th><th>Selection</th><th className="num">Odds</th><th className="num">Stake</th><th className="num">EV</th><th>Status</th><th>Score</th><th className="num">P/L</th><th className="num">Close</th><th className="num">CLV</th><th className="num">Bankroll before → after</th><th className="num">DQ</th><th>Reason / settlement</th></tr></thead>
            <tbody>{rows.map((b: any) => (
              <tr key={b.id}>
                <td className="mono">{b.id}</td><td className="mono">{romeTime(b.created_at)}</td>
                <td className="match">{b.fixture.home} – {b.fixture.away}<small>{b.fixture.competition_name} · {romeTime(b.fixture.kickoff_utc)}</small></td>
                <td>{selLabel(b.market, b.selection, b.line)}</td><td className="num">{num(b.price)}</td><td className="num">{eur(b.stake)}{legacyStake(b.created_at) && <small className="muted"> old €1 rule</small>}</td>
                <td className="num">{spct(b.ev)}</td><td><Status s={b.status} /></td><td className="mono">{b.fixture.score || "—"}</td>
                <td className={`num ${cls(b.profit)}`}>{b.profit === null ? "—" : eur(b.profit, true)}</td>
                <td className="num">{num(b.closing_price)}</td><td className={`num ${cls(b.clv)}`}>{spct(b.clv)}</td>
                <td className="num">{legacyStake(b.created_at)
                  ? <span className="muted" title={`Placed under the old €100 bankroll: ${eur(b.bankroll_before)} → ${eur(b.bankroll_after_settlement ?? b.bankroll_after_stake)} (the €400 top-up to €500 came later, 25 Nov 21:21 UTC)`}>legacy (€100 bankroll)</span>
                  : <>{eur(b.bankroll_before)} → {eur(b.bankroll_after_settlement ?? b.bankroll_after_stake)}</>}</td>
                <td className="num">{num(b.data_quality, 0)}</td>
                <td className="muted" style={{ fontSize: 11 }}>{b.reason && <div>{fixAhReason(b.reason, b.market, b.selection, b.line)}</div>}{b.settlement ? `${b.settlement.source}: ${b.settlement.rule}` : b.fixture.result_conflict ? "RESULT CONFLICT — held pending" : new Date(b.fixture.kickoff_utc).getTime() > Date.now() ? "scheduled — not played yet" : statusNow({ kickoff_utc: b.fixture.kickoff_utc, status: b.fixture.status }) === "in play" ? "in play" : "awaiting verified result"}</td>
              </tr>))}</tbody>
          </table>
          {rows.length === 0 && <div className="empty">No bets match the filters.</div>}
        </div>
      </Card>
    </>
  );
}
