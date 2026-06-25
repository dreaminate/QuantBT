/**
 * R23 conformal 校准区间披露卡（模型台·OOS 真留出覆盖率）。
 * 镜像后端 model_eval.conformal_prediction_band 输出（training_job_eval.conformal_interval）。
 *
 * **不假绿灯（核心）**：
 *  ① abstained=true（calib 不足）→ 「证据不足」警示色，**绝不渲染假区间/假覆盖**（band/coverage 为 null）。
 *  ② 单次留出覆盖率是**带噪估计**（二项抽样 + exchangeability 依赖，后端 note 已述）→ **中性色、绝不上成功绿**
 *     当作「达标」（跨多次训练取均值方判校准）。
 *  ③ interval 缺省/null（非回归任务等）→ 不渲染（不编造）。
 *  ④ 合规说明走后端 note 单一源、原样渲染（不在 UI 重拼措辞）。
 */

export interface ConformalIntervalData {
  alpha: number;
  target_coverage: number;
  n_calib: number;
  n_test: number;
  abstained: boolean;
  /** 预测区间半宽 q̂；abstained 时为 null（不给假区间）。 */
  band_half_width: number | null;
  /** 留出集真实测覆盖率；abstained / 无有效点时为 null。 */
  empirical_coverage: number | null;
  n_test_dropped_nonfinite?: number;
  /** 后端合规说明（单一源）。 */
  note: string;
}

function pct(v: number): string {
  return (v * 100).toFixed(1) + "%";
}

export function ConformalIntervalCard({
  interval,
}: {
  interval?: ConformalIntervalData | null;
}) {
  // null/缺省（非回归任务 / 无 OOS）→ 不渲染（不编造校准结论）。
  if (!interval) return null;

  const { abstained, band_half_width, empirical_coverage, target_coverage, n_test, note } = interval;

  return (
    <div
      className="cc-card"
      data-testid="conformal-interval-card"
      style={{ padding: 10, minWidth: 0 }}
    >
      <div className="cc-soft" style={{ fontSize: 12, marginBottom: 4 }}>
        校准区间 · OOS 留出覆盖（R23 conformal）
      </div>
      {abstained ? (
        // 不假绿灯：calib 不足 → 证据不足警示色，绝不给假区间/假覆盖。
        <div
          data-testid="conformal-abstained"
          style={{ fontSize: 13, fontWeight: 600, color: "var(--cc-warning, #d68910)" }}
        >
          证据不足 · 未给校准区间
        </div>
      ) : (
        <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "baseline" }}>
          <Stat
            label="预测区间半宽"
            value={band_half_width != null ? `±${band_half_width.toPrecision(3)}` : "N/A"}
          />
          <Stat label="目标覆盖" value={pct(target_coverage)} />
          {/* 单次留出覆盖率：中性色（带噪估计、绝不当达标绿）。 */}
          <Stat
            label={`留出实测覆盖 (n=${n_test})`}
            value={empirical_coverage != null ? pct(empirical_coverage) : "N/A"}
            neutral
          />
        </div>
      )}
      {/* 后端合规说明单一源、原样渲染（含「单次含抽样噪声、跨多次取均值方判校准」caveat）。 */}
      <div
        data-testid="conformal-note"
        className="cc-dim"
        style={{ fontSize: 10.5, lineHeight: 1.5, marginTop: 6 }}
      >
        {note}
      </div>
    </div>
  );
}

function Stat({
  label,
  value,
  neutral = false,
}: {
  label: string;
  value: string;
  neutral?: boolean;
}) {
  return (
    <div>
      <div className="cc-dim" style={{ fontSize: 10 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 15,
          fontWeight: 700,
          // 中性色：单次覆盖/半宽都是事实陈述，绝不上成功绿当「达标」（不假绿灯）。
          color: neutral ? "var(--cc-text-soft, #a0a0a0)" : "var(--cc-text, #ddd)",
        }}
      >
        {value}
      </div>
    </div>
  );
}

export default ConformalIntervalCard;
