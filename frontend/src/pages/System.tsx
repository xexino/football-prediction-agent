import { useApi } from "../hooks";
import { Card, Loading, State, Status, ago, romeTime } from "../ui";
import { GithubRunsCard, PipelineCard } from "./OpsPanels";

export default function System() {
  const { data, error } = useApi<any>("system", 30000);
  const { data: reports } = useApi<any>("reports", 300000);
  const { data: hd } = useApi<any>("health_detail", 60000);
  if (!data) return <Loading error={error} />;
  const last = data.recent_runs.find((r: any) => r.status === "success");
  const errs = data.recent_runs.filter((r: any) => r.status === "error").length;
  return (
    <>
      <div className="topbar"><div><h1>System Health</h1><div className="sub">Scheduler, jobs, database and recent errors · refresh 30s</div></div></div>
      <div className="grid g2"><PipelineCard /><GithubRunsCard /></div>
      {!hd ? <Card title="Overall health"><div className="empty">Loading health…</div></Card> :
      <Card title={<>Overall health <State s={hd?.overall} /></>} right={<span className="muted mono">computed {ago(hd?.computed_at)}</span>}>
        <div className="grid g4">
          {hd && Object.entries(hd.components).map(([k, c]: any) => (
            <div key={k} className="card" style={{ padding: 10 }}>
              <div className="l" style={{ display: "flex", justifyContent: "space-between", gap: 6 }}><span className="muted" style={{ textTransform: "uppercase", fontSize: 11, letterSpacing: ".7px" }}>{k.replace("_", " ")}</span><State s={c.state} /></div>
              <div className="mono" style={{ fontSize: 11, marginTop: 6 }}>
                {c.last ? <>last OK {ago(c.last)}</> : c.state === "UNKNOWN" ? "no record yet" : ""}
                {c.job && <> · {c.job} {c.status}</>}
                {c.upcoming_7d !== undefined && <> {c.upcoming_7d} upcoming (7d)</>}
                {c.failed_steps?.length ? <div className="neg">failed: {c.failed_steps.join(", ")}</div> : null}
                {c.problems?.length ? <div className="neg">{c.problems.join("; ")}</div> : null}
              </div>
              {c.detail && <div className="muted" style={{ fontSize: 10.5, marginTop: 4 }}>{c.detail}</div>}
            </div>
          ))}
        </div>
        <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>
          {hd && Object.entries(hd.states).map(([k, v]: any) => `${k}: ${v}`).join(" · ")}. Health is judged on the age of the last <i>successful</i> work, not on whether a job exited. Times are shown in Rome time; the Autopilot schedule runs in UTC.
        </p>
      </Card>}
      <Card title="Providers">
        <table><thead><tr><th>Provider</th><th>State</th><th>Last success</th><th>Circuit breaker</th><th>Last error</th></tr></thead>
          <tbody>{hd && Object.entries(hd.providers).map(([k, p]: any) => <tr key={k}><td className="mono">{k}</td><td><State s={p.state} />{!p.configured && <span className="muted"> no API key</span>}</td><td className="mono">{ago(p.last_success)}</td>
            <td className="mono" style={{ fontSize: 11 }}>{p.circuit?.open_until ? <span className="neg">OPEN until {romeTime(p.circuit.open_until)}</span> : `closed${p.circuit?.failures ? ` (${p.circuit.failures} recent failures)` : ""}`}</td>
            <td className="neg" style={{ fontSize: 11 }}>{p.error_kind && <b>{p.error_kind.replace(/_/g, " ")}: </b>}{p.last_error || ""}</td></tr>)}</tbody></table>
      </Card>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <Card title="Scheduled jobs (Europe/Rome)">
          {data.jobs.length ? <table><thead><tr><th>Job</th><th>Schedule</th><th>Last success</th><th>Next run</th></tr></thead>
            <tbody>{data.jobs.map((j: any) => <tr key={j.job}><td className="match">{j.job}<small>{j.description}</small></td><td className="mono" style={{ fontSize: 11 }}>{j.trigger}</td><td className="mono">{ago(j.last_success)}</td><td className="mono">{romeTime(j.next_run)}</td></tr>)}</tbody></table>
            : <div className="empty">Scheduler not running in this process (static snapshot, or FIL_SCHEDULER=0). Jobs may be driven externally (GitHub Actions / cron).</div>}
        </Card>
        <Card title="Database">
          <div className="kv"><span>Path</span><span className="mono">{data.database.path}</span>
            {Object.entries(data.database.counts).map(([k, v]: any) => <><span key={k}>{k.replace(/_/g, " ")}</span><span className="mono">{v.toLocaleString()}</span></>)}
            <span>Backups</span><span className="mono">{data.database.backups.map((b: any) => b.file).slice(-3).join(", ") || "none yet"}</span></div>
        </Card>
      </div>
      <Card title="Recent job runs">
        <div className="tablewrap"><table><thead><tr><th>#</th><th>Job</th><th>Status</th><th>Started</th><th className="num">Duration</th><th>Summary / error</th></tr></thead>
          <tbody>{data.recent_runs.map((r: any) => <tr key={r.id}><td className="mono">{r.id}</td><td>{r.job}</td><td><Status s={r.status} /></td><td className="mono">{romeTime(r.started_at)}</td><td className="num">{r.duration_s ?? "—"}s</td>
            <td style={{ fontSize: 11 }}>
              {r.summary?.steps && <div className="chips" style={{ marginBottom: 4 }}>{Object.entries(r.summary.steps).map(([k, v]: any) => <span key={k} className={`badge ${v.status === "success" ? "b-ok" : v.status === "error" ? "b-error" : "b-void"}`}>{k} {v.duration_s ?? ""}{v.duration_s !== undefined ? "s" : ""}</span>)}</div>}
              {r.summary?.steps && r.summary?.report && <div className="muted mono">{["fixtures_discovered", "predictions_generated", "virtual_bets_created", "bets_settled"].map((k) => `${k.replace(/_/g, " ")}: ${r.summary.report[k]}`).join(" · ")}</div>}
              {r.error ? <div className="err-box">{r.error.slice(0, 600)}</div> : !r.summary?.steps && <span className="muted mono">{JSON.stringify(r.summary)?.slice(0, 200)}</span>}</td></tr>)}</tbody></table></div>
      </Card>
      <Card title="Recent warnings & errors">
        {data.recent_errors.length ? <div className="tablewrap"><table><thead><tr><th>Time</th><th>Level</th><th>Component</th><th>Message</th></tr></thead>
          <tbody>{data.recent_errors.map((e: any, i: number) => <tr key={i}><td className="mono">{romeTime(e.ts)}</td><td className={e.level === "ERROR" ? "neg" : "warn"}>{e.level}</td><td className="mono">{e.component}</td><td style={{ fontSize: 11 }}>{e.message}</td></tr>)}</tbody></table></div>
          : <div className="empty">No warnings or errors recorded.</div>}
      </Card>
      <Card title="Reports">
        {reports?.length ? reports.slice(0, 6).map((r: any) => <details key={r.id} style={{ marginBottom: 8 }}><summary className="mono">{r.kind} · {romeTime(r.created_at)}</summary><pre className="md">{r.markdown}</pre></details>)
          : <div className="empty">No reports generated yet.</div>}
      </Card>
    </>
  );
}
