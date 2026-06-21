import { type ReactNode } from "react";

/** desk 语义色调（全部映射到 --desk-* token，组件内禁裸 hex）。 */
export type DeskTone =
  | "neutral"
  | "accent"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "ghost"
  | "mock";

const TONE_VAR: Record<DeskTone, string> = {
  neutral: "var(--desk-text-dim)",
  accent: "var(--desk-accent)",
  success: "var(--desk-success)",
  warning: "var(--desk-warning)",
  danger: "var(--desk-danger)",
  info: "var(--desk-info)",
  ghost: "var(--desk-ghost)",
  mock: "var(--desk-info)",
};

/** 单色 pill / badge（radius pill、border 1）。 */
export function Pill({
  tone = "neutral",
  children,
  title,
}: {
  tone?: DeskTone;
  children: ReactNode;
  title?: string;
}) {
  const c = TONE_VAR[tone];
  return (
    <span
      title={title}
      style={{
        fontSize: 11,
        lineHeight: 1.4,
        padding: "2px 8px",
        borderRadius: "var(--desk-radius-pill)",
        border: `1px solid ${c}`,
        color: c,
        background: "transparent",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

/** MOCK 数据诚实角标（蓝、常驻可见、不可折叠藏起）。 */
export function MockBadge({ label = "MOCK 数据" }: { label?: string }) {
  return (
    <Pill tone="mock" title="非真实后端数据，待接真">
      {label}
    </Pill>
  );
}

/** 状态脉冲点。running 态带呼吸动画。 */
export function StatusDot({
  color = "var(--desk-text-dim)",
  pulse = false,
  size = 7,
}: {
  color?: string;
  pulse?: boolean;
  size?: number;
}) {
  return (
    <span
      aria-hidden
      style={{
        display: "inline-block",
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        animation: pulse ? "desk-pulse 1s ease-in-out infinite" : undefined,
      }}
    />
  );
}

/** 段控（受控）：value + onChange，激活态实心 accent。 */
export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  size = "md",
}: {
  options: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  size?: "sm" | "md";
}) {
  const pad = size === "sm" ? "3px 8px" : "4px 11px";
  const fs = size === "sm" ? 10 : 11;
  return (
    <div
      role="tablist"
      style={{
        display: "inline-flex",
        gap: 2,
        background: "var(--desk-soft-btn)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius)",
        padding: 3,
      }}
    >
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.value)}
            style={{
              fontFamily: "inherit",
              fontSize: fs,
              fontWeight: active ? 700 : 400,
              padding: pad,
              borderRadius: "var(--desk-radius-sm)",
              border: "none",
              cursor: "pointer",
              background: active ? "var(--desk-accent)" : "transparent",
              color: active ? "var(--desk-accent-ink)" : "var(--desk-text-dim)",
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
