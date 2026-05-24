export function StatusPill({ status }: { status: string }) {
  const className =
    status === "succeeded"
      ? "status-pill success"
      : status === "failed" || status === "interrupted"
        ? "status-pill error"
        : status === "running"
          ? "status-pill active"
          : "status-pill";
  return <span className={className}>{status}</span>;
}
