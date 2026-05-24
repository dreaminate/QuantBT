import type { JobResponse } from "../types";
import { formatNumber } from "../utils";
import { StatusPill } from "./StatusPill";


export function JobPanel({ job }: { job?: JobResponse | null }) {
  if (!job) {
    return (
      <section className="panel panel-soft">
        <div className="panel-header">
          <h3>最近任务</h3>
        </div>
        <p className="muted">还没有任务。</p>
      </section>
    );
  }

  return (
    <section className="panel panel-soft">
      <div className="panel-header split">
        <h3>最近任务</h3>
        <StatusPill status={job.status} />
      </div>
      <dl className="meta-grid compact">
        <div>
          <dt>任务 ID</dt>
          <dd>{job.job_id}</dd>
        </div>
        <div>
          <dt>提交时间</dt>
          <dd>{job.submitted_at}</dd>
        </div>
        {job.started_at ? (
          <div>
            <dt>开始时间</dt>
            <dd>{job.started_at}</dd>
          </div>
        ) : null}
        {job.finished_at ? (
          <div>
            <dt>结束时间</dt>
            <dd>{job.finished_at}</dd>
          </div>
        ) : null}
        {job.duration_seconds != null ? (
          <div>
            <dt>耗时</dt>
            <dd>{formatNumber(job.duration_seconds, 2)} 秒</dd>
          </div>
        ) : null}
      </dl>
      {job.progress ? (
        <div className="job-progress">
          <div className="job-progress-header">
            <strong>进度</strong>
            <span>{job.progress.percent}%</span>
          </div>
          <div className="progress-track" aria-label="进度">
            <div className="progress-fill" style={{ width: `${job.progress.percent}%` }} />
          </div>
          <p className="muted">
            当前阶段: {job.progress.stage_label}
            {job.progress.message ? ` - ${job.progress.message}` : ""}
          </p>
        </div>
      ) : null}
      {job.error ? <p className="error-text">{job.error}</p> : null}
      {job.result ? (
        <pre className="code-block compact-code">{JSON.stringify(job.result, null, 2)}</pre>
      ) : null}
    </section>
  );
}
