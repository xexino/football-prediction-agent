import { useMemo, useState } from "react";
import { useApi } from "../hooks";
import { api } from "../api";
import { Card, Decision, Explanation, Loading, ProbBar, Quality, num, pct, romeTime , awaitingResult, statusNow} from "../ui";
import { ValueTable } from "./Upcoming";

export default function Predictions() {
  const { data, error } = useApi<any>("predictions?limit=2000", 120000);
  const { data: bets } = useApi<any>("bets", 300000);
  // a bet placed from one prediction stands even when a later/earlier revision says NO BET (display only)
  const betByFixture = new Map<number, any>(((bets?.items ?? bets) || []).map((b: any) => [b.fixture?.id, b]));
  const [dec, setDec] = useState("");
  const [comp, setComp] = useState("");
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState<any>(null);
  const comps = useMemo(() => Array.from(new Set((data?.items || []).map((p: any) => p.fixture.competition_name))).sort() as string[], [data]);
  if (!data) return <Loading error={error} />;
  const rows = data.items.filter((p: any) => (!dec || p.decision === dec) && (!comp || p.fixture.competition_name === comp) &&
    (!q || `${p.fixture.home} ${p.fixture.away}`.toLowerCase().includes(q.toLowerCase())));
  const show = async (p: any) => {
    try { setDetail(await api(`predictions/${p.id}`)); } catch { setDetail({ ...p, value: null, _missing: true }); }
  };
  return (
    <>
      <div className="topbar"><div><h1>Predictions</h1><div className="sub">Every stored prediction, including NO BET decisions. Originals are immutable; revisions are separate records.</div></div>
        <span className="pill">{data.total} predictions</span></div>
      <div className="filters">
        <select value={dec} onChange={(e) => setDec(e.target.value)}><option value="">All decisions</option><option value="BET">Value bet</option><option value="NO_BET">No bet</option></select>
        <select value={comp} onChange={(e) => setComp(e.target.value)}><option value="">All competitions</option>{comps.map((c) => <option key={c}>{c}</option>)}</select>
        <input placeholder="Team…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      {detail && (
        <Card title={`Prediction #${detail.id} — ${detail.fixture.home} vs ${detail.fixture.away}`} right={<button onClick={() => setDetail(null)}>close</button>} className="detail">
          <Explanation ex={detail.inputs?.explanation} />
          <p className="expl" style={{ maxWidth: "none" }}>{detail.explanation}</p>
          {detail.probs?.CS_TOP && <p className="mono" style={{ fontSize: 12 }}>Scoreline distribution (top 6, not a certainty): {Object.entries(detail.probs.CS_TOP).map(([k, v]: any) => `${k} ${pct(v, 1)}`).join(" · ")}</p>}
          {detail.value ? <div className="tablewrap"><ValueTable rows={detail.value} /></div> : <div className="muted">Value table unavailable in static snapshot.</div>}
          {detail.revisions && <p className="muted mono" style={{ fontSize: 11 }}>Revisions: {detail.revisions.map((r: any) => `#${r.revision} ${romeTime(r.created_at)} ${r.reason || "original"}`).join(" · ")}</p>}
          <p className="muted" style={{ fontSize: 11 }}>Sources: {(detail.sources || []).join(", ")}</p>
        </Card>
      )}
      <Card>
        <div className="tablewrap">
          <table>
            <thead><tr><th>Created</th><th>Match</th><th>Kickoff</th><th>1X2 (H/D/A)</th><th className="num">xG</th><th className="num">O2.5</th><th className="num">BTTS</th><th className="num">Conf.</th><th>Quality</th><th>Decision</th><th>Result</th><th className="num">Brier</th></tr></thead>
            <tbody>
              {rows.map((p: any) => (
                <tr key={p.id} className="fixture-row" onClick={() => show(p)}>
                  <td className="mono">{romeTime(p.created_at)}{p.revision > 0 && <span className="pill" style={{ marginLeft: 4 }}>rev {p.revision}</span>}</td>
                  <td className="match">{p.fixture.home} – {p.fixture.away}<small>{p.fixture.competition_name}</small></td>
                  <td className="mono">{romeTime(p.fixture.kickoff_utc)}</td>
                  <td><ProbBar p={p.probs["1X2"]} /></td>
                  <td className="num">{num(p.exp_home_goals, 2)}–{num(p.exp_away_goals, 2)}</td>
                  <td className="num">{pct(p.probs.OU25?.over, 0)}</td><td className="num">{pct(p.probs.BTTS?.yes, 0)}</td>
                  <td className="num">{num(p.confidence, 0)}</td><td><Quality q={p.data_quality} /></td><td><Decision d={p.decision} />{(() => { const b = betByFixture.get(p.fixture?.id); return b && b.prediction_id !== p.id && p.decision !== "VALUE_BET" ? <small className="muted" style={{ display: "block" }}>bet from {p.revision > 0 ? "an earlier" : "another"} prediction stands ({String(b.status).toLowerCase()})</small> : null; })()}</td>
                  <td className="mono">{p.fixture.score || <span className={awaitingResult(p.fixture) ? "warn" : "muted"}>{statusNow(p.fixture)}</span>}</td>
                  <td className="num">{p.eval_brier !== null ? num(p.eval_brier, 3) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && <div className="empty">No predictions yet.</div>}
        </div>
      </Card>
    </>
  );
}
