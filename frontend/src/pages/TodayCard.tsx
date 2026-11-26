import { Link } from "react-router-dom";
import { useApi } from "../hooks";
import { Card, pct, num, statusNow } from "../ui";
import { keepOnToday } from "../lib/honesty";

const romeDay = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: "Europe/Rome" });

/** Every match kicking off today (Rome time), with both engines' probabilities, expected goals and the most likely
 *  scores. Each row opens the full match page (score matrix, all markets, AI analyst report). */
export default function TodayCard() {
  const { data } = useApi<any>("insights", 120000);
  if (!data) return null;
  const today = romeDay(new Date());
  const items = data.items
    .filter((i: any) => keepOnToday(romeDay(new Date(i.kickoff_utc)) === today, i.kickoff_utc, i.score, i.phase || i.status) && (i.engine_a || i.engine_b))
    .sort((a: any, b: any) => a.kickoff_utc.localeCompare(b.kickoff_utc));
  return (
    <Card title={`Today's matches (${items.length} predicted)`} right={<Link to="/insights">all matches →</Link>}>
      {!items.length ? <div className="empty">No predicted matches today.</div> :
        <div style={{ overflowX: "auto" }}><table>
          <thead><tr><th>Kickoff</th><th>Match</th><th className="num">1</th><th className="num">X</th><th className="num">2</th><th className="num">xG</th><th>Most likely scores</th><th>Over 2.5 · BTTS</th></tr></thead>
          <tbody>{items.map((i: any) => {
            const p = i.engine_a || i.engine_b?.x12;
            const b = i.engine_b;
            return (
              <tr key={i.id}>
                <td className="mono">{i.kickoff_rome?.slice(11)}{new Date(i.kickoff_utc).getTime() < Date.now() ? <small className={i.score ? "" : "warn"}> · {statusNow(i)}</small> : null}</td>
                <td className="match"><Link to={`/insights/${i.id}`}>{i.home} – {i.away}</Link><small>{i.competition_name}</small></td>
                <td className="num">{!i.engine_a && <span className="pill" title="Engine A does not cover this competition; Engine B probabilities shown">B</span>} {pct(p?.home, 0)}</td><td className="num">{pct(p?.draw, 0)}</td><td className="num">{pct(p?.away, 0)}</td>
                <td className="num">{b ? `${num(b.xg.home, 1)}–${num(b.xg.away, 1)}` : "—"}</td>
                <td className="mono">{b ? Object.entries(b.top_scores).slice(0, 3).map(([s, v]: any) => `${s} (${pct(v, 0)})`).join(" · ") : "—"}</td>
                <td className="mono">{b ? `${pct(b.over25, 0)} · ${pct(b.btts, 0)}` : "—"}</td>
              </tr>);
          })}</tbody>
        </table></div>}
      <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>1 / X / 2 = Engine A probabilities; rows marked B use Engine B because Engine A does not cover that competition. xG and scores = Engine B model. Probabilities, not certainties. Simulation only.</p>
    </Card>
  );
}
