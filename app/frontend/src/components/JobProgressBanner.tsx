import type { JobResponse } from "../types";
import { StatusPill } from "./StatusPill";


export function JobProgressBanner({
  job,
  onViewTasks,
}: {
  job: JobResponse | null | undefined;
  onViewTasks?: () => void;
}) {
  if (!job) {
    return null;
  }

  const active = job.status === "queued" || job.status === "running";
  const showBar = active && job.progress && job.status === "running";

  return (
    <div className="job-progress-banner" role="status" aria-live="polite">
      <div className="job-progress-banner-row">
        <StatusPill status={job.status} />
        <span className="job-progress-banner-id">{job.job_id}</span>
        {active && onViewTasks ? (
          <button type="button" className="ghost-button job-progress-banner-link" onClick={onViewTasks}>
            查看任务
          </button>
        ) : null}
      </div>
      {showBar ? (
        <div className="job-progress">
          <div className="job-progress-header">
            <strong>进度</strong>
            <span>{job.progress!.percent}%</span>
          </div>
          <div className="progress-track" aria-label="进度">
            <div className="progress-fill" style={{ width: `${job.progress!.percent}%` }} />
          </div>
          <p className="muted compact-progress-msg">
            当前阶段: {job.progress!.stage_label}
            {job.progress!.message ? ` - ${job.progress!.message}` : ""}
          </p>
        </div>
      ) : active ? (
        <p className="muted compact-progress-msg">任务正在运行，请稍候...</p>
      ) : job.status === "succeeded" ? (
        <p className="success-text compact-progress-msg">任务完成</p>
      ) : job.status === "failed" || job.status === "interrupted" ? (
        <p className="error-text compact-progress-msg">{job.error ?? job.status}</p>
      ) : null}
    </div>
  );
}
