import { type CSSProperties } from "react";
import { MockBadge } from "./desk/primitives";

/**
 * 因子收益归因卡（消费侧 UI）—— 镜像后端 `eval/attribution_report.build_factor_attribution_report`。
 *
 * 红线（§0/§13 信任层 · 不假绿灯）——本文件硬约束，改前必读：
 *  ① **绝不渲染「已归因」成功绿**：evidence_state 四态全走中性 / 警示色，本文件**不引用成功绿 token**
 *     （测试 SOURCE 扫描守：源码不出现该 token 字面 → 结构性杜绝假绿灯）。
 *     解释占比高也只落中性（explanatory power ≠ 策略质量，镜像 ColdStartStat「充分」用中性色先例）。
 *  ② abstain（insufficient / collinear）→ 警示面板 + 原样 note，**绝不渲染 β / 贡献条**（后端 betas 已空）。
 *  ③ 低 R²（specific_driven）→ 标「特异驱动 · 归因弱」警示，**绝不**标 factor_explained。
 *  ④ note 走后端单一源、**原样渲染**，前端绝不二次拼裁决措辞（防绕过 R7 措辞门）。
 *  ⑤ 零裸 hex：一律 var(--desk-*)；rgba 叠加用 color-mix(token, transparent)。
 *  ⑥ 旁挂独立卡，**绝不 import 冻结 RunDetailPage**（外链跳转，不内嵌）。
 *
 * dataSource="mock"（默认）→ header 挂 <MockBadge/> 诚实角标；"live" → 已接后端报告端点。
 */

export type AttributionStatus = "ok" | "insufficient" | "collinear";
export type EvidenceState =
  | "factor_explained"
  | "specific_driven"
  | "insufficient"
  | "collinear";

/** 镜像后端 report dict（JSON-safe：nan 字段为 null）。 */
export interface FactorAttributionReport {
  available: boolean;
  status: AttributionStatus;
  evidence_state: EvidenceState;
  factor_contributions: Record<string, number | null>;
  specific_contribution: number | null;
  total_return: number | null;
  betas: Record<string, number | null>;
  alpha: number | null;
  r_squared: number | null;
  n_obs: number;
  identity: {
    recomposed: number | null;
    residual: number | null;
    holds: boolean;
  };
  methodology: {
    factor_set_label: string | null;
    return_basis: string | null;
    regression_window: string | null;
    low_explained_floor: number;
  };
  note: string;
  warnings: string[];
}

/**
 * evidence_state → 展示文案 / 语义 token。
 * **铁律：无一态用成功绿 token**（不假绿灯）——可解释只落中性 text-soft，弱点落 warning。
 */
const EVIDENCE_META: Record<
  EvidenceState,
  { label: string; color: string; bg: string }
> = {
  factor_explained: {
    label: "因子可解释",
    color: "var(--desk-text-soft)", // 中性·非成功绿（解释占比≠策略质量）
    bg: "color-mix(in srgb, var(--desk-text-soft) 12%, transparent)",
  },
  specific_driven: {
    label: "特异驱动 · 归因弱",
    color: "var(--desk-warning)",
    bg: "color-mix(in srgb, var(--desk-warning) 15%, transparent)",
  },
  insufficient: {
    label: "证据不足 · 样本不足",
    color: "var(--desk-warning)",
    bg: "color-mix(in srgb, var(--desk-warning) 15%, transparent)",
  },
  collinear: {
    label: "证据不足 · 因子共线",
    color: "var(--desk-warning)",
    bg: "color-mix(in srgb, var(--desk-warning) 15%, transparent)",
  },
};

const RETURN_BASIS_LABEL: Record<string, string> = {
  excess: "超额收益",
  raw: "原始收益",
};
const WINDOW_LABEL: Record<string, string> = {
  full: "全样本",
  rolling: "滚动窗",
};

function pct(v: number | null, digits = 2): string {
  if (v === null || !Number.isFinite(v)) return "N/A";
  return (v * 100).toFixed(digits) + "%";
}

function num(v: number | null, digits = 3): string {
  if (v === null || !Number.isFinite(v)) return "N/A";
  return v.toFixed(digits);
}

export interface FactorAttributionCardProps {
  report: FactorAttributionReport;
  /** 数据来源诚实角标：mock（默认，挂 MockBadge）/ live（已接后端报告端点）。 */
  dataSource?: "mock" | "live";
}

export function FactorAttributionCard({
  report,
  dataSource = "mock",
}: FactorAttributionCardProps) {
  const meta = EVIDENCE_META[report.evidence_state];
  const isAbstain =
    report.status === "insufficient" || report.status === "collinear";

  // 贡献条归一基准 = max(|各因子贡献|, |特异|)（ok 态才有 β / 贡献）。
  const contribEntries = Object.entries(report.factor_contributions);
  const specific = report.specific_contribution ?? 0;
  const maxAbs = Math.max(
    1e-12,
    ...contribEntries.map(([, v]) => Math.abs(v ?? 0)),
    Math.abs(specific),
  );
  const setLabel =
    report.methodology.factor_set_label?.trim() || "自定义因子集";

  const cardStyle: CSSProperties = {
    background: "var(--desk-card)",
    border: "1px solid var(--desk-border-strong)",
    borderRadius: "var(--desk-radius-lg)",
    overflow: "hidden",
    fontFamily: "var(--desk-mono)",
    color: "var(--desk-text)",
  };

  return (
    <div data-testid="factor-attribution-card" style={cardStyle}>
      {/* header：标题 + MOCK 角标 + evidence pill */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "11px 15px",
          background: "var(--desk-panel)",
          borderBottom: "1px solid var(--desk-border)",
        }}
      >
        <span style={{ color: "var(--desk-accent)" }} aria-hidden>
          ◳
        </span>
        <span style={{ fontWeight: 600 }}>因子收益归因 · {setLabel}</span>
        <span
          style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}
        >
          {dataSource !== "live" && <MockBadge />}
          <span
            data-testid="evidence-pill"
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: meta.color,
              background: meta.bg,
              padding: "3px 11px",
              borderRadius: "var(--desk-radius-pill)",
            }}
          >
            {meta.label}
          </span>
        </span>
      </div>

      {/* 解释占比 R² 行（中性，绝不成功绿；低 R²→ warning 标注） */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 10,
          padding: "12px 15px 6px",
        }}
      >
        <span style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>
          因子解释占比 R²
        </span>
        <span
          data-testid="r2-value"
          style={{
            fontSize: 20,
            fontWeight: 700,
            color:
              report.evidence_state === "specific_driven"
                ? "var(--desk-warning)"
                : "var(--desk-text-soft)", // 中性·非绿
          }}
        >
          {pct(report.r_squared, 1)}
        </span>
        {report.evidence_state === "specific_driven" && (
          <span
            data-testid="r2-weak-note"
            style={{ fontSize: 11, color: "var(--desk-warning)" }}
          >
            归因弱 · 收益主要特异驱动
          </span>
        )}
        <span
          style={{
            marginLeft: "auto",
            fontSize: 10.5,
            color: "var(--desk-text-faint)",
          }}
        >
          有效样本 n={report.n_obs}
        </span>
      </div>

      {/* abstain 面板（insufficient/collinear）：警示 + 原样 note，绝不渲染 β / 贡献条 */}
      {isAbstain ? (
        <div
          data-testid="abstain-panel"
          style={{
            margin: "6px 15px 12px",
            padding: "10px 12px",
            background: "color-mix(in srgb, var(--desk-warning) 9%, transparent)",
            border: "1px solid color-mix(in srgb, var(--desk-warning) 40%, var(--desk-card))",
            borderRadius: "var(--desk-radius)",
          }}
        >
          <div
            style={{
              color: "var(--desk-warning)",
              fontSize: 12,
              fontWeight: 600,
              marginBottom: 4,
            }}
          >
            未给出因子 β —— 证据不足
          </div>
          <div
            data-testid="attribution-note"
            style={{
              color: "var(--desk-text-dim)",
              fontSize: 11.5,
              lineHeight: 1.55,
            }}
          >
            {report.note}
          </div>
        </div>
      ) : (
        <>
          {/* 贡献分解：各因子 β · 累计贡献 + 特异（堆叠 / 瀑布条） */}
          <div style={{ padding: "4px 15px 8px" }}>
            <div
              style={{
                color: "var(--desk-text-faint)",
                fontSize: 11,
                marginBottom: 8,
              }}
            >
              贡献分解 · β × Σ因子收益（累计）
            </div>
            {contribEntries.map(([name, contrib]) => (
              <ContribRow
                key={name}
                name={name}
                beta={report.betas[name] ?? null}
                contrib={contrib}
                maxAbs={maxAbs}
              />
            ))}
            {/* 特异（截距+残差）：未被因子解释的部分，中性弱化色——非「已归因」 */}
            <div
              data-testid="specific-row"
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                padding: "5px 0",
                borderTop: "1px dashed var(--desk-grid-dot)",
                marginTop: 4,
              }}
            >
              <span
                style={{
                  flex: "0 0 116px",
                  color: "var(--desk-text-faint)",
                  fontSize: 11.5,
                }}
              >
                特异（未解释）
              </span>
              <div style={{ flex: 1, height: 12, position: "relative" }}>
                <Bar
                  widthPct={(Math.abs(specific) / maxAbs) * 100}
                  color="var(--desk-text-faint)"
                />
              </div>
              <span
                style={{
                  flex: "0 0 84px",
                  textAlign: "right",
                  color: "var(--desk-text-dim)",
                  fontSize: 11.5,
                }}
              >
                {pct(report.specific_contribution)}
              </span>
            </div>
          </div>
        </>
      )}

      {/* 加总恒等式 footer（命门可见 · 渐进披露）：Σ贡献+特异 ≡ 总收益 */}
      <div
        data-testid="identity-footer"
        style={{
          padding: "9px 15px",
          background: "var(--desk-soft-btn)",
          borderTop: "1px solid var(--desk-border)",
          display: "flex",
          alignItems: "center",
          gap: 8,
          flexWrap: "wrap",
        }}
      >
        <span style={{ fontSize: 10.5, color: "var(--desk-text-faint)" }}>
          加总恒等式 Σ因子贡献 + 特异 ≡ 组合总收益
        </span>
        <span
          data-testid="identity-flag"
          style={{
            fontSize: 10.5,
            fontWeight: 600,
            color: report.identity.holds
              ? "var(--desk-text-soft)" // 闭合=中性陈述（恒等式是代数必然、非绩效绿）
              : "var(--desk-danger)",
          }}
        >
          {report.identity.holds ? "✓ 闭合" : "✗ 破（请核查）"}
        </span>
        <span
          style={{
            marginLeft: "auto",
            fontSize: 10.5,
            color: "var(--desk-text-faint)",
          }}
        >
          总收益 {pct(report.total_return)}
        </span>
      </div>

      {/* ok 态 note（原样渲染·单一源）+ 方法学回显（用户口径，不替拍） */}
      {!isAbstain && (
        <div
          style={{
            padding: "9px 15px 11px",
            borderTop: "1px solid var(--desk-border)",
          }}
        >
          <div
            data-testid="attribution-note"
            style={{
              color: "var(--desk-text-dim)",
              fontSize: 11.5,
              lineHeight: 1.55,
            }}
          >
            {report.note}
          </div>
          <div
            style={{
              marginTop: 6,
              fontSize: 10,
              color: "var(--desk-text-faint)",
              lineHeight: 1.5,
            }}
          >
            方法学（用户口径）：因子集 {setLabel} · 收益口径{" "}
            {report.methodology.return_basis
              ? (RETURN_BASIS_LABEL[report.methodology.return_basis] ??
                report.methodology.return_basis)
              : "未声明"}{" "}
            · 回归窗{" "}
            {report.methodology.regression_window
              ? (WINDOW_LABEL[report.methodology.regression_window] ??
                report.methodology.regression_window)
              : "未声明"}
          </div>
          {report.warnings.length > 0 && (
            <ul
              style={{
                margin: "6px 0 0",
                paddingLeft: 16,
                color: "var(--desk-text-faint)",
                fontSize: 10.5,
                lineHeight: 1.5,
              }}
            >
              {report.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

/** 单因子贡献行：名 · β · 条（按 |贡献|/maxAbs 归一，正负分色）· 数值。 */
function ContribRow({
  name,
  beta,
  contrib,
  maxAbs,
}: {
  name: string;
  beta: number | null;
  contrib: number | null;
  maxAbs: number;
}) {
  const v = contrib ?? 0;
  const positive = v >= 0;
  return (
    <div
      data-testid="contrib-row"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "5px 0",
      }}
    >
      <span
        style={{
          flex: "0 0 116px",
          color: "var(--desk-text-soft)",
          fontSize: 11.5,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={name}
      >
        {name}
        <span style={{ color: "var(--desk-text-faint)", marginLeft: 6 }}>
          β={num(beta, 2)}
        </span>
      </span>
      <div
        data-testid="contrib-bar"
        style={{ flex: 1, height: 12, position: "relative" }}
      >
        <Bar
          widthPct={(Math.abs(v) / maxAbs) * 100}
          color={positive ? "var(--desk-accent)" : "var(--desk-danger)"}
        />
      </div>
      <span
        style={{
          flex: "0 0 84px",
          textAlign: "right",
          color: positive ? "var(--desk-text)" : "var(--desk-danger)",
          fontSize: 11.5,
        }}
      >
        {pct(contrib)}
      </span>
    </div>
  );
}

function Bar({ widthPct, color }: { widthPct: number; color: string }) {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background: "color-mix(in srgb, var(--desk-border) 50%, transparent)",
        borderRadius: 3,
      }}
    >
      <div
        style={{
          width: `${Math.min(100, Math.max(0, widthPct))}%`,
          height: "100%",
          background: color,
          borderRadius: 3,
        }}
      />
    </div>
  );
}

/**
 * mock 报告（诚实：未接真实后端报告端点）。
 * factor_explained 态——note 走合规措辞占位，落地由 build_factor_attribution_report 供给（单一源）。
 */
export const MOCK_FACTOR_ATTRIBUTION: FactorAttributionReport = {
  available: true,
  status: "ok",
  evidence_state: "factor_explained",
  factor_contributions: { value: 0.062, momentum: 0.041, size: -0.018 },
  specific_contribution: 0.025,
  total_return: 0.11,
  betas: { value: 0.83, momentum: 0.57, size: -0.22 },
  alpha: 0.0003,
  r_squared: 0.71,
  n_obs: 312,
  identity: { recomposed: 0.11, residual: 0.0, holds: true },
  methodology: {
    factor_set_label: "风格三因子",
    return_basis: "excess",
    regression_window: "full",
    low_explained_floor: 0.3,
  },
  note:
    "因子解释占比 71.0%：各因子贡献见分解，剩余归特异部分。适用域取决于所选因子集与收益口径"
    + "（用户方法学）；解释占比为因子模型对已实现收益的拟合度、非策略质量结论。",
  warnings: [],
};

/** insufficient mock（样本不足·不出 β）——供 abstain 诚实呈现演示 / 测试。 */
export const MOCK_FACTOR_ATTRIBUTION_INSUFFICIENT: FactorAttributionReport = {
  available: true,
  status: "insufficient",
  evidence_state: "insufficient",
  factor_contributions: {},
  specific_contribution: 0.013,
  total_return: 0.013,
  betas: {},
  alpha: null,
  r_squared: null,
  n_obs: 4,
  identity: { recomposed: 0.013, residual: 0.0, holds: true },
  methodology: {
    factor_set_label: "风格三因子",
    return_basis: "excess",
    regression_window: "full",
    low_explained_floor: 0.3,
  },
  note:
    "样本不足（有效 n=4 < K+2=5）：因子回归无自由度、未给出 β —— 证据不足，不归因到因子（先验断言，未经检验）。",
  warnings: [],
};

/** specific_driven mock（低 R²·特异驱动）——供「不假绿灯」演示 / 测试。 */
export const MOCK_FACTOR_ATTRIBUTION_SPECIFIC: FactorAttributionReport = {
  available: true,
  status: "ok",
  evidence_state: "specific_driven",
  factor_contributions: { value: 0.004, momentum: -0.002 },
  specific_contribution: 0.088,
  total_return: 0.09,
  betas: { value: 0.05, momentum: -0.03 },
  alpha: 0.0028,
  r_squared: 0.06,
  n_obs: 260,
  identity: { recomposed: 0.09, residual: 0.0, holds: true },
  methodology: {
    factor_set_label: "风格二因子",
    return_basis: "excess",
    regression_window: "full",
    low_explained_floor: 0.3,
  },
  note:
    "因子解释占比 6.0%（低于呈现阈值 30%）：组合收益主要由特异 / 未建模部分驱动，未达可解释归因门槛"
    + " —— 不标已归因（阈值为呈现启发，可按方法学调整）。",
  warnings: [],
};
