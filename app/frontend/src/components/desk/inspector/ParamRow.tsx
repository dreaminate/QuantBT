/**
 * Inspector 参数行（parseConsole.md §P5 参数 tab）。
 * 受控：value + onChange 由消费台持有。
 * readonly / locked（含 Live 只读、Final Gate 锁节点）→ input disabled。
 */

export interface ParamRowProps {
  label: string;
  value: string;
  onChange: (v: string) => void;
  /** 可选说明气泡（? 圆点 title）。 */
  tip?: string;
  /** 只读 / 锁定 → disabled。任一为真即不可编辑。 */
  readOnly?: boolean;
  locked?: boolean;
}

export function ParamRow({
  label,
  value,
  onChange,
  tip,
  readOnly = false,
  locked = false,
}: ParamRowProps) {
  const disabled = readOnly || locked;
  return (
    <div
      data-param-row
      style={{
        display: "grid",
        gridTemplateColumns: "108px 1fr",
        gap: 8,
        alignItems: "center",
        marginBottom: 8,
      }}
    >
      <label
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          fontSize: 11,
          color: "var(--desk-text-muted)",
        }}
      >
        {label}
        {tip && (
          <span
            title={tip}
            aria-label={tip}
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: 13,
              height: 13,
              borderRadius: "50%",
              background: "var(--desk-info)",
              color: "var(--desk-accent-ink)",
              fontSize: 9,
              cursor: "help",
            }}
          >
            ?
          </span>
        )}
      </label>
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: "100%",
          background: "var(--desk-input)",
          border: "1px solid var(--desk-border)",
          borderRadius: "var(--desk-radius-sm)",
          color: "var(--desk-text-soft)",
          padding: "5px 8px",
          fontFamily: "inherit",
          fontSize: 11.5,
          outline: "none",
          opacity: disabled ? 0.6 : 1,
          cursor: disabled ? "not-allowed" : "text",
        }}
      />
    </div>
  );
}
