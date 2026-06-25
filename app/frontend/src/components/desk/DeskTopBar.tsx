import { type ReactNode } from "react";
import { Link } from "react-router-dom";

export type DeskKey = "overview" | "factor" | "model" | "strategy" | "paper" | "agent";

const DESKS: { key: DeskKey; label: string; to: string }[] = [
  { key: "overview", label: "总览台", to: "/overview" },
  { key: "strategy", label: "策略台", to: "/strategy" },
  { key: "factor", label: "因子台", to: "/factors" },
  { key: "model", label: "Model台", to: "/models" },
  { key: "paper", label: "模拟台", to: "/paper" },
  { key: "agent", label: "研究执行台", to: "/agent-workbench" },
];

/** 台切换器：当前台实心 accent，可跳台为 <Link>，soon 台灰占位（不渲染链接，防死链）。 */
export function DeskSwitcher({
  current,
  soon = [],
}: {
  current: DeskKey;
  soon?: DeskKey[];
}) {
  return (
    <div
      style={{
        display: "flex",
        gap: 2,
        background: "var(--desk-soft-btn)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius)",
        padding: 3,
      }}
    >
      {DESKS.map((d) => {
        const base = {
          fontSize: 11,
          padding: "3px 9px",
          borderRadius: "var(--desk-radius-sm)",
        } as const;
        if (d.key === current) {
          return (
            <span
              key={d.key}
              style={{
                ...base,
                background: "var(--desk-accent)",
                color: "var(--desk-accent-ink)",
                fontWeight: 700,
              }}
            >
              {d.label}
            </span>
          );
        }
        if (soon.includes(d.key)) {
          return (
            <span
              key={d.key}
              title="敬请期待"
              style={{ ...base, color: "var(--desk-text-faint)" }}
            >
              {d.label}
            </span>
          );
        }
        return (
          <Link
            key={d.key}
            to={d.to}
            style={{ ...base, color: "var(--desk-text-dim)" }}
          >
            {d.label}
          </Link>
        );
      })}
    </div>
  );
}

/** 顶栏壳：红绿灯点 + ✳ 字标 + children（switcher / actions）。 */
export function DeskTopBar({
  children,
  dots = true,
}: {
  children?: ReactNode;
  dots?: boolean;
}) {
  return (
    <div
      style={{
        flex: "none",
        height: 44,
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "0 14px",
        background: "var(--desk-topbar)",
        borderBottom: "1px solid var(--desk-border)",
      }}
    >
      {dots && (
        <span style={{ display: "flex", gap: 6 }} aria-hidden>
          {[0, 1, 2].map((i) => (
            <span
              key={i}
              style={{
                width: 11,
                height: 11,
                borderRadius: "50%",
                background: "var(--desk-border-strong)",
              }}
            />
          ))}
        </span>
      )}
      <span style={{ color: "var(--desk-accent)", fontWeight: 700 }}>✳</span>
      <span style={{ fontWeight: 600 }}>QuantBT</span>
      {children}
    </div>
  );
}
