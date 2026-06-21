import { StatusDot } from "../../../components/desk";
import { MILESTONE_DEFS, type MilestoneKey } from "./agentMock";

/**
 * 里程碑进度线（agentDeck.md §B）：7 节点 立题→市场→因子集→模型→信号→风控→回测。
 * dot 三态：active（橙脉冲）/ reached（绿实心）/ 未达（空心边框）。
 * reached 节点可点 → 跳对应 cowork 产物卡 + 滚动锚点（onGoto 由消费台实现）。
 */

export interface MilestoneLadderProps {
  reached: MilestoneKey[];
  active: MilestoneKey | null;
  /** 动态 sub 文案（因子集→fs_core3 / 模型→v2·staging / 回测→拍板✓）。 */
  subs: Partial<Record<MilestoneKey, string>>;
  onGoto: (key: MilestoneKey) => void;
}

export function MilestoneLadder({
  reached,
  active,
  subs,
  onGoto,
}: MilestoneLadderProps) {
  const order = MILESTONE_DEFS.map((m) => m.key);
  const activeIdx = active ? order.indexOf(active) : -1;

  return (
    <div
      data-milestone-ladder
      style={{
        flex: "none",
        background: "var(--desk-soft-btn)",
        borderBottom: "1px solid var(--desk-border)",
        padding: "8px 18px 9px",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", marginBottom: 5 }}>
        <span
          style={{
            fontSize: 9.5,
            letterSpacing: 1,
            color: "var(--desk-text-faint)",
          }}
        >
          策略台 · 组装 + 回测
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 9.5,
            color: "var(--desk-text-faint)",
          }}
        >
          终点：候选策略 → 交接模拟台
        </span>
      </div>
      <div style={{ display: "flex" }}>
        {MILESTONE_DEFS.map((m, i) => {
          const isReached = reached.includes(m.key);
          const isActive = m.key === active;
          const clickable = isReached;
          const leftLit = i <= activeIdx && activeIdx >= 0;
          const rightLit = i < activeIdx && activeIdx >= 0;
          return (
            <button
              key={m.key}
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onGoto(m.key)}
              data-ms-node={m.key}
              data-ms-reached={isReached ? "true" : "false"}
              data-ms-active={isActive ? "true" : "false"}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                gap: 4,
                background: "transparent",
                border: "none",
                fontFamily: "inherit",
                cursor: clickable ? "pointer" : "default",
                padding: 0,
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  width: "100%",
                  height: 12,
                }}
              >
                <span
                  style={{
                    flex: 1,
                    height: 2,
                    background:
                      i === 0
                        ? "transparent"
                        : leftLit
                          ? "var(--desk-success)"
                          : "var(--desk-border)",
                  }}
                />
                {isActive ? (
                  <StatusDot color="var(--desk-accent)" pulse size={11} />
                ) : isReached ? (
                  <StatusDot color="var(--desk-success)" size={9} />
                ) : (
                  <span
                    aria-hidden
                    style={{
                      width: 9,
                      height: 9,
                      borderRadius: "50%",
                      background: "transparent",
                      border: "1.5px solid var(--desk-border-strong)",
                    }}
                  />
                )}
                <span
                  style={{
                    flex: 1,
                    height: 2,
                    background:
                      i === order.length - 1
                        ? "transparent"
                        : rightLit
                          ? "var(--desk-success)"
                          : "var(--desk-border)",
                  }}
                />
              </div>
              <span
                style={{
                  fontSize: 11.5,
                  fontWeight: isActive ? 700 : 500,
                  color: isActive
                    ? "var(--desk-accent)"
                    : isReached
                      ? "var(--desk-text-soft)"
                      : "var(--desk-text-faint)",
                }}
              >
                {m.label}
              </span>
              <span
                style={{
                  fontSize: 9,
                  height: 11,
                  color: isActive
                    ? "var(--desk-accent)"
                    : "var(--desk-text-faint)",
                }}
              >
                {subs[m.key] ?? ""}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
