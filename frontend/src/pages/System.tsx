import { useApi } from "../hooks";
import { Card, Loading, Stat, Status, ago, romeTime } from "../ui";

export default function System() {
  const { data, error } = useApi<any>("system", 30000);
  const { data: reports } = useApi<any>("reports", 300000);
  if (!data) return <Loading error={error} />;
  const last = data.recent_runs.find((r: any) => r.status === "success");
  const errs = data.recent_runs.filter((r: any) => r.status === "error").length;
  return (
    <>
      <div className="topbar"><div><h1>System Health</h1><div className="sub">Scheduler, jobs, database and recent errors · refresh 30s</div></div></div>
      <div className="grid g4">
        <Stat label="Backend" value={<span className="pos">{data.backend.toUpperCase()}</span>} delta={`v${data.version}`} />
        <Stat label="Scheduler" value={data.scheduler_running ? <span className="pos">RUNNING</span> : <span className="warn">OFF</span>} delta={data.scheduler_running ? "APScheduler in-process" : "static snapshot or disabled"} />
        <Stat label="Database" value={`${data.database.size_mb} MB`} delta={`${data.database.counts.fixtures.toLocaleString()} fixtures · ${data.database.backups.length} backups`} />
        <Stat label="Last successful job" value={last ? ago(last.finished_at) : "—"} delta={`${last?.job || ""} · ${errs} failed in recent runs`} tone={errs ? "warn" : ""} />
      </div>
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
            <td style={{ fontSize: 11 }}>{r.error ? <div className="err-box">{r.error.slice(0, 600)}</div> : <span className="muted mono">{JSON.stringify(r.summary)?.slice(0, 240)}</span>}</td></tr>)}</tbody></table></div>
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
