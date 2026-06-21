import { type CSSProperties, type ReactNode } from "react";

/**
 * 因子台共享小件（卡片壳 / 区块标题 / 指标格）。
 * 纯展示、零业务状态、零裸 hex（全 --desk-* token）。
 */

/** 面板卡片壳（bg card + border + radius lg）。 */
export function PanelCard({
  children,
  style,
  accentBorder,
}: {
  children: ReactNode;
  style?: CSSProperties;
  accentBorder?: boolean;
}) {
  return (
    <div
      style={{
        background: "var(--desk-card)",
        border: `1px solid ${
          accentBorder ? "var(--desk-accent)" : "var(--desk-border)"
        }`,
        borderRadius: "var(--desk-radius-lg)",
        padding: "12px 14px",
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** 区块标题行：左侧 accent glyph + 标题 + 右侧槽。 */
export function SectionTitle({
  glyph,
  children,
  right,
}: {
  glyph?: string;
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginBottom: 10,
        fontSize: 11.5,
        fontWeight: 600,
        color: "var(--desk-text-soft)",
      }}
    >
      {glyph && (
        <span aria-hidden style={{ color: "var(--desk-accent)" }}>
          {glyph}
        </span>
      )}
      <span>{children}</span>
      {right && <span style={{ marginLeft: "auto" }}>{right}</span>}
    </div>
  );
}

/** 硬指标格：label + 大数值（阈值色）+ note。 */
export function MetricCell({
  label,
  value,
  color,
  note,
  big = 19,
}: {
  label: string;
  value: string;
  color: string;
  note?: string;
  big?: number;
}) {
  return (
    <div
      style={{
        background: "var(--desk-card)",
        border: "1px solid var(--desk-border)",
        borderRadius: "var(--desk-radius)",
        padding: "11px 13px",
      }}
    >
      <div style={{ fontSize: 10.5, color: "var(--desk-text-faint)" }}>
        {label}
      </div>
      <div style={{ fontSize: big, fontWeight: 700, color, marginTop: 3 }}>
        {value}
      </div>
      {note && (
        <div
          style={{ fontSize: 9.5, color: "var(--desk-text-faint)", marginTop: 2 }}
        >
          {note}
        </div>
      )}
    </div>
  );
}

/** 蓝色「代码 / 公式」框（全台统一表达式即代码质感）。 */
export function CodeBox({
  children,
  label,
  big = 12,
}: {
  children: ReactNode;
  label?: ReactNode;
  big?: number;
}) {
  return (
    <div
      style={{
        background: "var(--desk-code-bg, var(--desk-input))",
        border: "1px solid var(--desk-info)",
        borderRadius: "var(--desk-radius-sm)",
        padding: "12px 14px",
      }}
    >
      {label && (
        <div
          style={{ fontSize: 10, color: "var(--desk-info)", marginBottom: 7 }}
        >
          {label}
        </div>
      )}
      <div
        style={{
          fontSize: big,
          color: "var(--desk-info)",
          lineHeight: 1.6,
          fontWeight: 500,
          whiteSpace: "pre-wrap",
        }}
      >
        {children}
      </div>
    </div>
  );
}
