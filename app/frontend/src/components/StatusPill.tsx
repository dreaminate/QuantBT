export function StatusPill({ status }: { status: string }) {
  const labels: Record<string, string> = {
    queued: "等待中",
    running: "运行中",
    succeeded: "已完成",
    completed: "已完成",
    failed: "失败",
    interrupted: "已中断",
  };
  return <span className={`status-pill status-${status}`}>{labels[status] ?? status}</span>;
}
