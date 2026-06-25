/**
 * R4 CPCV 路径稳健性卡（模型台·report-only）。镜像后端 training.cpcv_oos_metric_distribution
 * （training_job_eval.cpcv_distribution）。组合式多路径 OOS 指标分布——**q05/路径方差 = 过拟合脆弱度**。
 *
 * **不假绿灯（核心）**：
 *  ① dist 缺省/null（未开 compute_cpcv）→ 不渲染（不编造·未算≠已算）。
 *  ② status≠ok（insufficient/unsupported_task）→ 显状态+reason，**绝不渲染假分布**。
 *  ③ 保守分位 q05 < 无技能基线（r2:0 / auc:0.5）→ **脆弱警示色**（部分路径无优于随机=过拟合嫌疑），
 *     绝不上成功绿；q05≥baseline 也用**中性色**（路径稳≠策略好，质量另判）。report-only：不接 gate、不替拍板。
 */

export interface CpcvDistributionData {
  status: "ok" | "insufficient" | "unsupported_task";
  metric: string | null;          // "r2" | "roc_auc"
  baseline: number;               // 无技能参照（r2:0 / auc:0.5）
  n_paths: number;
  n_groups: number;
  k_test_groups: number;
  mean: number;
  std: number;
  q05: number;
  min: number;
  median: number;
  max: number;
  frac_below_0: number;
  reason?: string;
}

function fmt(v: number): string {
  return Number.isFinite(v) ? v.toFixed(3) : "N/A";
}

export function CpcvRobustnessCard({ dist }: { dist?: CpcvDistributionData | null }) {
  // 未算（compute_cpcv 默认关）→ 不渲染（不编造）。
  if (!dist) return null;

  if (dist.status !== "ok") {
    return (
      <div className="cc-card" data-testid="cpcv-card" style={{ padding: 10, minWidth: 0 }}>
        <div className="cc-soft" style={{ fontSize: 12, marginBottom: 4 }}>
          CPCV 路径稳健性（R4·report-only）
        </div>
        <div data-testid="cpcv-nostatus" className="cc-dim" style={{ fontSize: 12 }}>
          {dist.status === "unsupported_task" ? "本任务不适用" : "证据不足"}
          {dist.reason ? ` · ${dist.reason}` : ""}
        </div>
      </div>
    );
  }

  // 保守分位低于无技能基线 → 脆弱（部分路径无优于随机）。
  const fragile = Number.isFinite(dist.q05) && dist.q05 < dist.baseline;

  return (
    <div className="cc-card" data-testid="cpcv-card" style={{ padding: 10, minWidth: 0 }}>
      <div className="cc-soft" style={{ fontSize: 12, marginBottom: 4 }}>
        CPCV 路径稳健性 · {dist.metric}（{dist.n_paths} 路径 · C({dist.n_groups},{dist.k_test_groups})）
      </div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap", alignItems: "baseline" }}>
        {/* q05=保守分位（脆弱度核心）：< baseline 警示色，否则中性（路径稳≠策略好）。 */}
        <Stat
          label={`q05（保守·基线 ${dist.baseline}）`}
          value={fmt(dist.q05)}
          color={fragile ? "var(--cc-warning, #d68910)" : "var(--cc-text-soft, #a0a0a0)"}
        />
        <Stat label="mean" value={fmt(dist.mean)} />
        <Stat label="min" value={fmt(dist.min)} />
        <Stat label="median" value={fmt(dist.median)} />
        <Stat label="max" value={fmt(dist.max)} />
      </div>
      <div
        data-testid="cpcv-note"
        className="cc-dim"
        style={{ fontSize: 10.5, lineHeight: 1.5, marginTop: 6 }}
      >
        {fragile
          ? `保守分位 q05=${fmt(dist.q05)} 低于无技能基线 ${dist.baseline}：部分组合路径 OOS 无优于随机，过拟合/切分敏感（脆弱）。`
          : `q05=${fmt(dist.q05)} ≥ 基线 ${dist.baseline}；路径方差 std=${fmt(dist.std)}（越大越依赖具体切分）。`}
        {" "}report-only·不接 gate（阈值/口径属用户方法学）。
      </div>
    </div>
  );
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div>
      <div className="cc-dim" style={{ fontSize: 10 }}>
        {label}
      </div>
      <div style={{ fontSize: 15, fontWeight: 700, color: color ?? "var(--cc-text, #ddd)" }}>
        {value}
      </div>
    </div>
  );
}

export default CpcvRobustnessCard;
