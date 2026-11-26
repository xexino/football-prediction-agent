import { useApi } from "../hooks";
import { Card, Loading, Status, eur, num, pct, romeTime, selLabel, spct } from "../ui";
import { legacyStake } from "../lib/honesty";

export default function BetSlip() {
  const { data, error } = useApi<any>("bets?status=pending", 60000);
  const { data: meta } = useApi<any>("meta", 600000);
  if (!data) return <Loading error={error} />;
  const items = data.items.filter((b: any) => b.status === "pending");
  const stake = items.reduce((a: number, b: any) => a + b.stake, 0);
  const ret = items.reduce((a: number, b: any) => a + b.potential_return, 0);
  return (
    <>
      <div className="topbar"><div><h1>Virtual Bet Slip</h1><div className="sub">{data.disclaimer} Bets are recorded before kickoff and can never be edited.</div></div>
        <div className="chips"><span className="pill">{items.length} open</span><span className="pill">staked {eur(stake)}</span><span className="pill">potential return {eur(ret)}</span></div></div>
      {items.length === 0 ? (
        <div className="nobet-hero">NO OPEN BETS — no sufficiently reliable value opportunity identified (or all bets settled).</div>
      ) : (
        <div className="grid g3">
          {items.map((b: any) => (
            <Card key={b.id} title={<>#{b.id} · {b.fixture.competition_name}</>} right={<Status s={b.status} />}>
              <div className="match" style={{ fontSize: 15 }}>{b.fixture.home} – {b.fixture.away}</div>
              <div className="muted mono" style={{ marginBottom: 10 }}>kickoff {romeTime(b.fixture.kickoff_utc)}</div>
              <div className="kv">
                <span>Selection</span><span><b>{selLabel(b.market, b.selection, b.line)}</b></span>
                <span>Odds</span><span className="mono">{num(b.price)} <span className="muted">({b.bookmaker_label})</span></span>
                <span>Stake</span><span className="mono">{eur(b.stake)}{legacyStake(b.created_at) && <small className="muted"> old €1 rule</small>}</span>
                <span>Potential return</span><span className="mono">{eur(b.potential_return)}</span>
                <span>Model probability (at placement)</span><span className="mono">{pct(b.model_prob)}</span>
                <span>Expected value</span><span className="mono pos">{spct(b.ev)}</span>
                <span>Placed</span><span className="mono">{romeTime(b.created_at)}</span>
              </div>
            </Card>
          ))}
        </div>
      )}
      {meta && (
        <Card title="Risk & settlement rules" className="" >
          <div className="grid g2">
            <div className="kv">{Object.entries(meta.risk_rules).map(([k, v]: any) => <><span key={k}>{k.replace(/_/g, " ")}</span><span className="mono">{String(v)}</span></>)}</div>
            <div className="kv">{Object.entries(meta.value_rules).map(([k, v]: any) => <><span key={k}>{k.replace(/_/g, " ")}</span><span className="mono">{Array.isArray(v) ? v.join(", ") : String(v)}</span></>)}</div>
          </div>
          {Object.entries(meta.settlement_rules).map(([k, v]: any) => <p key={k} className="expl" style={{ maxWidth: "none" }}><b>{k}:</b> {v}</p>)}
        </Card>
      )}
    </>
  );
}
