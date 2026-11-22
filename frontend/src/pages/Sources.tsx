import { useApi } from "../hooks";
import { Card, Loading, Quality, Status, ago, pct } from "../ui";

export default function Sources() {
  const { data, error } = useApi<any>("sources", 120000);
  if (!data) return <Loading error={error} />;
  const regions = ["Europe", "Africa", "Americas", "Asia", "International"];
  return (
    <>
      <div className="topbar"><div><h1>Data Sources & Coverage</h1><div className="sub">Only legitimate, accessible sources. Missing data is reported, never invented.</div></div>
        <div className="chips"><span className="pill">{data.totals.fixtures.toLocaleString()} fixtures</span><span className="pill">{data.totals.odds_snapshots.toLocaleString()} odds snapshots</span><span className="pill">{data.totals.match_stats.toLocaleString()} stat rows</span></div></div>
      <Card title="Providers">
        <div className="tablewrap"><table>
          <thead><tr><th>Provider</th><th>Status</th><th>Provides</th><th>Last success</th><th className="num">Freshness</th><th className="num">Requests</th><th className="num">Records</th><th>Quota</th><th>Licence / access</th><th>Last error</th></tr></thead>
          <tbody>{data.providers.map((p: any) => (
            <tr key={p.key}>
              <td className="match">{p.name}<small><a href={p.base_url} target="_blank" rel="noreferrer">{p.base_url}</a></small></td>
              <td><Status s={p.configured ? p.status : "not_configured"} />{p.requires_key && !p.configured && <div className="muted" style={{ fontSize: 10 }}>API key needed</div>}</td>
              <td className="muted">{p.kind}</td><td className="mono">{ago(p.last_success_at)}</td>
              <td className="num">{p.freshness_hours === null ? "—" : `${p.freshness_hours}h`}</td>
              <td className="num">{p.requests_total}</td><td className="num">{p.records_total?.toLocaleString()}</td>
              <td className="mono" style={{ fontSize: 11 }}>{p.quota ? JSON.stringify(p.quota) : "—"}</td>
              <td className="muted" style={{ fontSize: 11, maxWidth: 260 }}>{p.license}</td>
              <td className="neg" style={{ fontSize: 11, maxWidth: 240 }}>{p.last_error ? `${ago(p.last_error_at)}: ${p.last_error.slice(0, 160)}` : ""}</td>
            </tr>))}</tbody>
        </table></div>
      </Card>
      {regions.map((r) => {
        const rows = data.coverage.filter((c: any) => c.region === r);
        if (!rows.length) return null;
        return (
          <Card key={r} title={`Competition coverage — ${r}`} right={<span className="pill">{rows.filter((c: any) => c.eligible).length}/{rows.length} eligible</span>}>
            <div className="tablewrap"><table>
              <thead><tr><th>Competition</th><th className="num">History (3y)</th><th className="num">This season</th><th className="num">Upcoming 14d</th><th className="num">With odds</th><th className="num">Odds history</th><th className="num">Stats</th><th className="num">xG</th><th>Team news</th><th>Lineups</th><th className="num">Complete</th><th>Quality</th><th>Eligible</th><th>Reasons</th></tr></thead>
              <tbody>{rows.map((c: any) => {
                const v = c.coverage || {};
                return (
                  <tr key={c.code}>
                    <td className="match">{c.name}<small>{c.code} · {Object.keys(c.coverage?.sources || {}).join(", ")}</small></td>
                    <td className="num">{v.historical_matches ?? "—"}</td><td className="num">{v.current_season_matches ?? "—"}</td>
                    <td className="num">{v.upcoming_14d ?? "—"}</td><td className="num">{v.upcoming_with_odds ?? "—"}</td>
                    <td className="num">{pct(v.odds_history_share, 0)}</td><td className="num">{pct(v.stats_share, 0)}</td><td className="num">{v.xg_current_season ?? "—"}</td>
                    <td className="muted">{v.team_news_items ? `${v.team_news_items} items` : "none"}</td><td className="muted" style={{ fontSize: 11 }}>{v.lineups ? "n/a" : "—"}</td>
                    <td className="num">{v.completeness ?? "—"}</td><td><Quality q={v.quality_score} /></td>
                    <td>{c.eligible ? <span className="badge b-ok">YES</span> : <span className="badge b-inel">NO</span>}</td>
                    <td className="muted" style={{ fontSize: 11 }}>{(v.reasons || []).join("; ")}</td>
                  </tr>);
              })}</tbody>
            </table></div>
          </Card>
        );
      })}
    </>
  );
}
