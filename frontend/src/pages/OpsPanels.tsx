import { useEffect, useState } from "react";
import { useApi } from "../hooks";
import { Card, State, ago, romeTime } from "../ui";

const REPO = "xexino/football-prediction-agent";
const CRON_JOB: Record<string, string> = { "10 5 * * *": "daily", "40 */3 * * *": "results + fixtures/odds", "25 6 * * 1": "weekly", "7,27,47 11-23 * * *": "live" };
const jobLabel = (t?: string) => { const x = (t || "").replace("Autopilot · ", "").replace("Autopilot", "—"); return CRON_JOB[x] ? `${CRON_JOB[x]} (timer)` : x; };

/** Status written by the Autopilot run that published this snapshot (also after failures). */
export function PipelineCard() {
  const { data: ops } = useApi<any>("ops_status", 120000);
  const cur = ops?.current;
  if (!cur) return (
    <Card title="Autopilot pipeline"><div className="empty">No pipeline status published yet (local server, or first run after this release).</div></Card>
  );
  const publishedH = (Date.now() - new Date(ops.generated_at).getTime()) / 3.6e6;
  return (
    <Card title={<>Autopilot pipeline <State s={publishedH > 8 ? "STALE" : cur.state} /></>}
      right={<span className="muted mono">published {ago(ops.generated_at)}</span>}>
      <div className="stages">{Object.entries(cur.stages).map(([k, v]: any) => <span key={k} className={`stage stage-${v}`}>{k}: {v.replace("_", " ")}</span>)}</div>
      <div className="kv">
        <span>Last run</span><span className="mono">{cur.job || "—"} · {cur.event}{cur.schedule ? ` (${cur.schedule})` : ""} · {romeTime(cur.finished_at)} {cur.run_url && <a href={cur.run_url} target="_blank" rel="noreferrer">log</a>}</span>
        <span>Job status</span><span className="mono">{cur.job_status}</span>
        <span>Database</span><span className="mono">restore {cur.database.restore}{cur.database.source ? ` (${cur.database.source})` : ""} · persist {cur.database.persist}{cur.database.persist_detail ? ` — ${cur.database.persist_detail}` : ""}</span>
        <span>Dashboard data</span><span className="mono">{cur.dashboard_data === "fresh" ? "from this run" : "previous snapshot (this run could not export)"}{cur.partial ? " · partial" : ""}</span>
        <span>Last fully successful run</span><span className="mono">{ops.last_success_at ? ago(ops.last_success_at) : "none recorded"}</span>
        <span>Last failed run</span><span className="mono">{ops.last_failure_at ? `${ago(ops.last_failure_at)} (stage: ${ops.last_failure_stage})` : "none recorded"}</span>
        <span>Consecutive failures</span><span className="mono">{ops.consecutive_failures}</span>
      </div>
      {publishedH > 8 && <p className="neg" style={{ fontSize: 12 }}>No run has published for {publishedH.toFixed(0)} h (expected every 3 h). Check the live GitHub run history below and open incident issues.</p>}
      <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>{ops.notes}</p>
    </Card>
  );
}

/** Read directly from the public GitHub API in the browser, so it stays truthful even if publishing stops. */
export function GithubRunsCard() {
  const [runs, setRuns] = useState<any[] | null>(null);
  const [incidents, setIncidents] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/autopilot.yml/runs?per_page=12`);
        if (!r.ok) throw new Error(`GitHub API ${r.status}`);
        const j = await r.json();
        const i = await fetch(`https://api.github.com/repos/${REPO}/issues?labels=autopilot-incident&state=open`);
        if (alive) { setRuns(j.workflow_runs); setIncidents(i.ok ? await i.json() : null); setErr(null); }
      } catch (e: any) { if (alive) setErr(String(e.message || e)); }
    };
    load();
    const t = setInterval(load, 300000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return (
    <Card title="GitHub Actions — live run history" right={<a className="muted" href={`https://github.com/${REPO}/actions/workflows/autopilot.yml`} target="_blank" rel="noreferrer">open in GitHub</a>}>
      {incidents && incidents.length > 0 && <div className="banner banner-err">Open incident: {incidents.map((x: any) => <a key={x.number} href={x.html_url} target="_blank" rel="noreferrer">#{x.number} {x.title}</a>)}</div>}
      {err ? <div className="empty">Live run history unavailable ({err}). GitHub limits anonymous API use to 60 requests per hour per visitor.</div> :
        !runs ? <div className="empty">Loading…</div> :
        <div className="tablewrap"><table><thead><tr><th>Run</th><th>Trigger</th><th>Started</th><th>Result</th></tr></thead><tbody>
          {runs.map((r: any) => <tr key={r.id}><td className="mono"><a href={r.html_url} target="_blank" rel="noreferrer">#{r.run_number}</a> {jobLabel(r.display_title)}</td><td>{r.event}</td><td className="mono">{romeTime(r.run_started_at || r.created_at)}</td>
            <td><State s={r.status !== "completed" ? (r.status === "in_progress" ? "UNKNOWN" : "UNKNOWN") : r.conclusion === "success" ? "HEALTHY" : "FAILED"} /> <span className="muted mono" style={{ fontSize: 11 }}>{r.status !== "completed" ? r.status : r.conclusion}</span></td></tr>)}
        </tbody></table></div>}
      <p className="muted" style={{ fontSize: 11, marginBottom: 0 }}>GitHub may delay or skip scheduled runs. A separate watchdog workflow checks this history every hour and after every run, and opens an <code>autopilot-incident</code> issue when runs fail, hang or do not start.</p>
    </Card>
  );
}
