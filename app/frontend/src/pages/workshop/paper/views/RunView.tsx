import { StatusDot } from "../../../../components/desk";
import { color } from "../colors";
import { svgLine } from "../equity";
import { runHeader, runMetrics, runEquity, schedRows, posPreview, posCount } from "../mock";
import type {
  BookPosition,
  DeskColor,
  PaperMarket,
  PaperMetric,
  PaperRun,
  SchedRow,
} from "../types";
import type { PaperBalanceResp, PaperStatusResp } from "../paperApi";

function money(value: number | undefined, market: PaperMarket): string {
  if (value === undefined || !Number.isFinite(value)) return "不可用";
  const currency = market === "crypto" ? "$" : "¥";
  return currency + Math.round(value).toLocaleString("en-US");
}

function signedPercent(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "不可用";
  return `${value >= 0 ? "+" : ""}${(value * 100).toFixed(2)}%`;
}

function liveMetrics(
  status: PaperStatusResp,
  balance: PaperBalanceResp | undefined,
  equity: number[],
): PaperMetric[] {
  const first = equity[0];
  const last = equity[equity.length - 1];
  const intervalReturn =
    equity.length >= 2 && first !== 0 && first !== undefined && last !== undefined
      ? last / first - 1
      : null;
  const intervalColor: DeskColor =
    intervalReturn === null ? "muted" : intervalReturn >= 0 ? "up" : "down";
  return [
    {
      label: "总权益",
      value: money(balance?.total_equity, status.market),
      color: "flat",
      note: "后端 balance.total_equity",
    },
    {
      label: "净值区间收益",
      value: signedPercent(intervalReturn),
      color: intervalColor,
      note: intervalReturn === null ? "需要至少 2 个净值样本" : "按后端 equity_log 首尾计算",
    },
    {
      label: "已喂入 bars",
      value: String(status.bars_fed),
      color: "flat",
      note: "后端 scheduler 状态",
    },
    {
      label: "MTM 记录",
      value: String(status.mtm_count),
      color: "flat",
      note: "后端 mark-to-market 次数",
    },
  ];
}

/**
 * 运行盘：头部状态 + 4 指标 + 净值曲线 + 调度器 KV + 持仓速览。
 * liveStatus 在场时，所有运行盘数据只取 /api/paper/* 响应；缺项显式标不可用，绝不回借 mock。
 * 未传 liveStatus 时才完整回退 mock。
 */
export function RunView({
  run,
  market,
  liveStatus,
  liveSched,
  liveBalance,
  liveEquity,
  livePositions,
}: {
  run: PaperRun;
  market: PaperMarket;
  liveStatus?: PaperStatusResp;
  liveSched?: SchedRow[];
  liveBalance?: PaperBalanceResp;
  liveEquity?: number[];
  livePositions?: BookPosition[];
}) {
  const isLive = liveStatus !== undefined;
  const mockHead = runHeader(run);
  const head = isLive
    ? {
        name: liveStatus.name,
        origin: liveStatus.origin || "来源未返回",
        statText: liveStatus.last_error ? "异常" : liveStatus.running ? "运行中" : "已暂停",
        statColor: (liveStatus.last_error ? "down" : liveStatus.running ? "up" : "warn") as DeskColor,
      }
    : mockHead;
  const equity = isLive ? (liveEquity ?? []) : [];
  const metrics = isLive ? liveMetrics(liveStatus, liveBalance, equity) : runMetrics(run);
  const mockEquity = isLive ? null : runEquity(run);
  const sched = isLive ? (liveSched ?? []) : schedRows(run, market);
  const positions = isLive ? (livePositions ?? []) : posPreview(market);
  const running = isLive ? liveStatus.running : run.status === "running";
  const liveLow = equity.length ? Math.min(...equity) : 0;
  const liveHigh = equity.length ? Math.max(...equity) : 1;
  const livePath = equity.length ? svgLine(equity, 720, 200, liveLow, liveHigh, 8, 0, 720) : "";

  return (
    <div style={{ padding: "18px 22px", maxWidth: 880 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 11, marginBottom: 14 }}>
        <StatusDot color={color(head.statColor)} pulse={running} size={9} />
        <span style={{ fontSize: 17, fontWeight: 700 }}>{head.name}</span>
        <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>{head.origin}</span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 11,
            color: color(head.statColor),
            border: `1px solid ${color(head.statColor)}`,
            padding: "3px 11px",
            borderRadius: "var(--desk-radius-pill)",
          }}
        >
          {head.statText}
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4,minmax(0,1fr))",
          gap: 11,
          marginBottom: 14,
        }}
      >
        {metrics.map((metric) => (
          <div
            key={metric.label}
            style={{
              background: "var(--desk-card)",
              border: "1px solid var(--desk-border)",
              borderRadius: "var(--desk-radius-lg)",
              padding: "11px 14px",
            }}
          >
            <div style={{ fontSize: 10.5, color: "var(--desk-text-muted)" }}>{metric.label}</div>
            <div
              style={{ fontSize: 21, fontWeight: 700, color: color(metric.color), marginTop: 3 }}
            >
              {metric.value}
            </div>
            <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)", marginTop: 2 }}>
              {metric.note}
            </div>
          </div>
        ))}
      </div>

      <div
        style={{
          background: "var(--desk-card)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-lg)",
          padding: "13px 16px",
          marginBottom: 14,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 9 }}>
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)", fontWeight: 600 }}>
            净值曲线 · {isLive ? "后端 equity_log" : "equity log"}
          </span>
          <span style={{ fontSize: 10, color: "var(--desk-text-muted)" }}>
            mark_to_market 每收盘写一笔
          </span>
          {isLive ? (
            <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--desk-text-faint)" }}>
              基准 {liveStatus.bench || "未命名"}：接口未返回序列
            </span>
          ) : (
            <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--desk-success)" }}>
              vs {run.bench}
            </span>
          )}
        </div>
        {isLive ? (
          equity.length ? (
            <>
              <svg
                viewBox="0 0 720 200"
                preserveAspectRatio="none"
                style={{ width: "100%", height: 180, display: "block" }}
                aria-label="后端净值曲线"
              >
                <path d={livePath} fill="none" stroke="var(--desk-success)" strokeWidth={2.2} />
              </svg>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 9.5,
                  color: "var(--desk-text-faint)",
                  marginTop: 3,
                }}
              >
                <span>后端净值样本 {equity.length} 个</span>
                <span>仅展示 total_equity，不推造回测段或基准线</span>
              </div>
            </>
          ) : (
            <div
              data-testid="live-equity-unavailable"
              style={{
                minHeight: 120,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--desk-text-muted)",
                fontSize: 11.5,
                border: "1px dashed var(--desk-border-strong)",
                borderRadius: "var(--desk-radius-sm)",
              }}
            >
              后端 equity_log 暂无可用记录；未显示 mock 净值
            </div>
          )
        ) : (
          <>
            <svg
              viewBox="0 0 720 200"
              preserveAspectRatio="none"
              style={{ width: "100%", height: 180, display: "block" }}
              aria-label="净值曲线"
            >
              <line
                x1={mockEquity?.splitX}
                y1={8}
                x2={mockEquity?.splitX}
                y2={192}
                stroke="var(--desk-border-hover)"
                strokeWidth={1}
                strokeDasharray="3 3"
              />
              <path
                d={mockEquity?.benchPath ?? ""}
                fill="none"
                stroke="var(--desk-text-faint)"
                strokeWidth={1.2}
                strokeDasharray="3 3"
              />
              <path
                d={mockEquity?.histPath ?? ""}
                fill="none"
                stroke="var(--desk-text-faint)"
                strokeWidth={1.6}
              />
              <path d={mockEquity?.paperArea ?? ""} fill="var(--desk-minimap-view)" />
              <path
                d={mockEquity?.paperPath ?? ""}
                fill="none"
                stroke="var(--desk-success)"
                strokeWidth={2.2}
              />
            </svg>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 9.5,
                color: "var(--desk-text-faint)",
                marginTop: 3,
              }}
            >
              <span>← 回测段（样本外延伸）</span>
              <span style={{ color: "var(--desk-border-hover)" }}>▏ 模拟盘上线</span>
              <span style={{ color: "var(--desk-success)" }}>实盘段 →</span>
            </div>
          </>
        )}
      </div>

      <div style={{ display: "flex", gap: 14 }}>
        <div
          style={{
            flex: 1.1,
            background: "var(--desk-card)",
            border: "1px solid var(--desk-border)",
            borderRadius: "var(--desk-radius-lg)",
            padding: "13px 15px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 11.5,
              color: "var(--desk-text-soft)",
              fontWeight: 600,
              marginBottom: 11,
            }}
          >
            <span style={{ color: running ? "var(--desk-success)" : "var(--desk-warning)" }}>⟳</span>
            调度器 · PaperScheduler
            <span
              style={{
                marginLeft: "auto",
                fontSize: 9.5,
                color: running ? "var(--desk-success)" : "var(--desk-warning)",
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}
            >
              <StatusDot
                color={running ? "var(--desk-success)" : "var(--desk-warning)"}
                pulse={running}
                size={6}
              />
              {running ? "活跃" : "暂停"}
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column" }}>
            {sched.length ? (
              sched.map((row) => (
                <div
                  key={row.k}
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    padding: "6px 0",
                    borderBottom: "1px solid var(--desk-border-soft)",
                    fontSize: 11,
                  }}
                >
                  <span style={{ color: "var(--desk-text-muted)" }}>{row.k}</span>
                  <span style={{ color: color(row.color) }}>{row.v}</span>
                </div>
              ))
            ) : (
              <span style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>
                后端未返回调度器字段
              </span>
            )}
          </div>
        </div>
        <div
          style={{
            flex: 1,
            background: "var(--desk-card)",
            border: "1px solid var(--desk-border)",
            borderRadius: "var(--desk-radius-lg)",
            padding: "13px 15px",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              fontSize: 11.5,
              color: "var(--desk-text-soft)",
              fontWeight: 600,
              marginBottom: 10,
            }}
          >
            持仓速览
            <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--desk-text-faint)" }}>
              {isLive ? `后端 ${positions.length} 个` : `top ${posCount(market)}`}
            </span>
          </div>
          {positions.length ? (
            positions.map((position) => (
              <div
                key={position.name}
                style={{
                  display: "flex",
                  alignItems: "center",
                  padding: "5px 0",
                  borderBottom: "1px solid var(--desk-border-soft)",
                }}
              >
                <span
                  style={{
                    flex: 1.6,
                    color: "var(--desk-text-soft)",
                    fontSize: 11.5,
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {position.name}
                </span>
                <span
                  style={{
                    flex: 0.8,
                    textAlign: "right",
                    color: "var(--desk-text-muted)",
                    fontSize: 11,
                  }}
                >
                  {position.w}
                </span>
                <span
                  style={{
                    flex: 0.9,
                    textAlign: "right",
                    color: color(position.pnlColor),
                    fontSize: 11,
                    fontWeight: 600,
                  }}
                >
                  {position.pnl}
                </span>
              </div>
            ))
          ) : (
            <span style={{ color: "var(--desk-text-muted)", fontSize: 11 }}>
              {isLive ? "后端当前无持仓；未显示 mock 持仓" : "暂无持仓"}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
