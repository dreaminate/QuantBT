import { type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ConnectedThemeModeControl } from "../ThemeModeControl";

export type DeskKey = "overview" | "factor" | "model" | "strategy" | "paper" | "agent";

const DESKS: { key: DeskKey; label: string; to: string }[] = [
  { key: "overview", label: "总览台", to: "/overview" },
  { key: "strategy", label: "策略台", to: "/strategy" },
  { key: "factor", label: "因子台", to: "/factors" },
  { key: "model", label: "Model台", to: "/models" },
  { key: "paper", label: "模拟台", to: "/paper" },
  { key: "agent", label: "研究执行台", to: "/agent-workbench" },
];

/** 台切换器：六个台都可点击；当前台只做 active 样式和 aria-current 标记。 */
export function DeskSwitcher({ current }: { current: DeskKey }) {
  return (
    <div
      style={{
        display: "flex",
        flex: "0 0 auto",
        gap: 2,
        background: "var(--desk-soft-btn)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius)",
        padding: 3,
        whiteSpace: "nowrap",
      }}
    >
      {DESKS.map((d) => {
        const active = d.key === current;
        const base = {
          fontSize: 11,
          padding: "3px 9px",
          borderRadius: "var(--desk-radius-sm)",
        } as const;
        return (
          <Link
            key={d.key}
            to={d.to}
            aria-current={active ? "page" : undefined}
            style={{
              ...base,
              display: "inline-flex",
              alignItems: "center",
              whiteSpace: "nowrap",
              background: active ? "var(--desk-accent)" : undefined,
              color: active ? "var(--desk-accent-ink)" : "var(--desk-text-dim)",
              fontWeight: active ? 700 : undefined,
            }}
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
        minWidth: 0,
        overflow: "hidden",
        padding: "0 14px",
        background: "var(--desk-topbar)",
        borderBottom: "1px solid var(--desk-border)",
      }}
    >
      {dots && (
        <span style={{ display: "flex", gap: 6, flex: "0 0 auto" }} aria-hidden>
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
      <span style={{ color: "var(--desk-accent)", fontWeight: 700, flex: "0 0 auto" }}>✳</span>
      <span style={{ fontWeight: 600, flex: "0 0 auto" }}>QuantBT</span>
      {children}
      <ConnectedThemeModeControl />
    </div>
  );
}
