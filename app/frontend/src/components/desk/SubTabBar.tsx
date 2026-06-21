import { type ReactNode } from "react";

/** 二级标签条（因子台/Model台/模拟台 sub-tab 用，受控）。 */
export function SubTabBar<T extends string>({
  tabs,
  value,
  onChange,
  right,
}: {
  tabs: { value: T; label: ReactNode }[];
  value: T;
  onChange: (v: T) => void;
  right?: ReactNode;
}) {
  return (
    <div
      style={{
        flex: "none",
        display: "flex",
        alignItems: "center",
        gap: 4,
        padding: "8px 16px",
        background: "var(--desk-soft-btn)",
        borderBottom: "1px solid var(--desk-border)",
      }}
    >
      {tabs.map((t) => {
        const active = t.value === value;
        return (
          <button
            key={t.value}
            onClick={() => onChange(t.value)}
            style={{
              fontFamily: "inherit",
              fontSize: 11.5,
              padding: "5px 11px",
              borderRadius: "var(--desk-radius-sm)",
              border: "none",
              cursor: "pointer",
              background: active ? "var(--desk-hover)" : "transparent",
              color: active ? "var(--desk-text)" : "var(--desk-text-dim)",
            }}
          >
            {t.label}
          </button>
        );
      })}
      <div style={{ flex: 1 }} />
      {right}
    </div>
  );
}
