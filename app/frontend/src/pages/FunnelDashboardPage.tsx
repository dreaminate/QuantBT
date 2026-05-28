import { useEffect, useState } from "react";

/**
 * v0.8.5.1 · /metrics/funnel · 基础漏斗 dashboard
 *
 * 显示 events 表里 v0.8.4 baseline 4 事件 + 后续接入事件的计数。
 * v0.8.6 接入 user_registered / run_completed 后 SQL bucket 会有数据。
 */

interface Funnel {
  total_events: number;
  by_event: { event_name: string; count: number }[];
  first_run_buckets: { bucket: string; users: number; pct: number }[];
}

export function FunnelDashboardPage() {
  const [data, setData] = useState<Funnel | null>(null);

  useEffect(() => {
    fetch("/api/metrics/funnel")
      .then((r) => r.json())
      .then(setData)
      .catch(() => setData(null));
  }, []);

  if (!data) return <div className="cc-card cc-dim">加载中...</div>;

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{"// 漏斗 dashboard"}</h1>
          <div className="cc-soft">v0.8.5.1 baseline · {data.total_events} 个事件总记录</div>
        </div>
      </div>

      <div className="cc-row" style={{ alignItems: "flex-start", gap: 16 }}>
        <section className="cc-card" style={{ flex: 1, padding: 16 }}>
          <div className="cc-section-title">事件计数</div>
          {data.by_event.length === 0 ? (
            <div className="cc-dim">无事件记录</div>
          ) : (
            <table className="cc-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>event_name</th>
                  <th style={{ textAlign: "right" }}>count</th>
                </tr>
              </thead>
              <tbody>
                {data.by_event.map((e) => (
                  <tr key={e.event_name}>
                    <td className="cc-mono">{e.event_name}</td>
                    <td style={{ textAlign: "right" }}>{e.count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="cc-card" style={{ flex: 1, padding: 16 }}>
          <div className="cc-section-title">首次成功 run 耗时分布</div>
          <div className="cc-soft" style={{ fontSize: 11, marginBottom: 8 }}>
            注册 → 首次 run_completed (status=success) 的时间差，目标 p50 &lt; 15 分钟
          </div>
          {data.first_run_buckets.length === 0 ? (
            <div className="cc-dim">
              数据尚未就绪：v0.8.6 接入 user_registered / run_completed 事件后自然有数据。
            </div>
          ) : (
            <table className="cc-table" style={{ width: "100%" }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>bucket</th>
                  <th style={{ textAlign: "right" }}>users</th>
                  <th style={{ textAlign: "right" }}>pct</th>
                </tr>
              </thead>
              <tbody>
                {data.first_run_buckets.map((b) => (
                  <tr key={b.bucket}>
                    <td className="cc-mono">{b.bucket}</td>
                    <td style={{ textAlign: "right" }}>{b.users}</td>
                    <td style={{ textAlign: "right" }}>{b.pct.toFixed(2)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  );
}

export default FunnelDashboardPage;
