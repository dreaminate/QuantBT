/**
 * v0.8.4 Day 5 · 前端埋点 helper (fire-and-forget)。
 *
 * 不阻塞 UI，不抛错；失败默默吞掉（埋点不能因为后端挂了影响用户体验）。
 * v0.8.4 baseline 4 个事件，v0.8.6 起会扩到 10 个。
 */

export type EventName =
  | "run_detail_viewed"
  | "risk_metric_expanded"
  | "glossary_term_viewed"
  | "risk_summary_shown";

let _anonymousId: string | null = null;
function getAnonymousId(): string {
  if (_anonymousId) return _anonymousId;
  try {
    const stored = localStorage.getItem("qb-anon-id");
    if (stored) {
      _anonymousId = stored;
      return stored;
    }
  } catch { /* noop */ }
  const fresh = `anon-${Math.random().toString(36).slice(2, 10)}-${Date.now()}`;
  try { localStorage.setItem("qb-anon-id", fresh); } catch { /* noop */ }
  _anonymousId = fresh;
  return fresh;
}

export function trackEvent(
  eventName: EventName,
  properties: Record<string, unknown> = {},
): void {
  try {
    const token = localStorage.getItem("qb-token");
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (token) headers["authorization"] = `Bearer ${token}`;
    void fetch("/api/events/track", {
      method: "POST",
      headers,
      body: JSON.stringify({
        event_name: eventName,
        anonymous_id: getAnonymousId(),
        app_version: "v0.8.4",
        properties,
      }),
      keepalive: true,
    }).catch(() => { /* swallow */ });
  } catch {
    // 完全 swallow；埋点不能炸 UI
  }
}
