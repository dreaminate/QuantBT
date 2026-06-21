import { type ReactNode, useState } from "react";
import { Pill } from "../../../components/desk";
import { RunVerdictCard } from "../../../components/RunVerdictCard";
import { LiveRunVerdictCard } from "../../../components/LiveRunVerdictCard";
import {
  MOCK_AGENT_RUN,
  MOCK_DATA_SOURCES,
  MOCK_EXEC,
  MOCK_FACTOR_SET,
  MOCK_FIELD_GROUPS,
  MOCK_HYPOTHESIS,
  MOCK_RISK_LIMITS,
  MOCK_RISK_SIZING,
  MOCK_SIGNAL,
  MOCK_WF_WINDOWS,
  type CoworkKind,
} from "./agentMock";

/**
 * 产物工作区 8 张 cowork 卡（agentDeck.md §E）。
 * 全受控展示：内容来自 agentMock，组件不持业务状态（walk-forward 展开除外，纯展示）。
 *
 * 跨台血统标记（R25 治理可见性）：因子集/模型卡的「← 因子台」「← Model台」蓝胶囊
 * **常驻展开、不可折叠藏起**——血统门是治理弱点，不许藏。
 *
 * 零裸 hex：全部 var(--desk-*)；rgba 叠加用 color-mix(token, transparent)。
 */

/** 统一卡壳。 */
function Card({
  icon,
  title,
  badge,
  children,
}: {
  icon: string;
  title: string;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        border: "1px solid var(--desk-border-strong)",
        background: "var(--desk-card)",
        borderRadius: "var(--desk-radius-lg)",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          padding: "12px 16px",
          background: "var(--desk-node-head)",
          borderBottom: "1px solid var(--desk-border)",
          display: "flex",
          alignItems: "center",
          gap: 9,
        }}
      >
        <span aria-hidden style={{ color: "var(--desk-accent)" }}>
          {icon}
        </span>
        <span style={{ fontWeight: 600 }}>{title}</span>
        {badge && <span style={{ marginLeft: "auto" }}>{badge}</span>}
      </div>
      <div style={{ padding: "14px 16px" }}>{children}</div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div
        style={{
          color: "var(--desk-text-dim)",
          fontSize: 11,
          marginBottom: 3,
        }}
      >
        {label}
      </div>
      <div style={{ color: "var(--desk-text-soft)" }}>{children}</div>
    </div>
  );
}

/** 血统胶囊（跨台来源）——常驻渲染、无折叠控件（R25）。 */
function LineageBadge({ children }: { children: ReactNode }) {
  return (
    <span
      data-lineage-badge
      title="跨台血统：来源台与晋级态（常驻可见，不可折叠）"
      style={{
        fontSize: 10.5,
        color: "var(--desk-info)",
        background: "color-mix(in srgb, var(--desk-info) 12%, transparent)",
        padding: "3px 10px",
        borderRadius: "var(--desk-radius-pill)",
        whiteSpace: "nowrap",
      }}
    >
      {children}
    </span>
  );
}

function HypothesisCard() {
  return (
    <Card
      icon="◇"
      title={`假设卡 · ${MOCK_HYPOTHESIS.id}`}
      badge={<Pill tone="warning">exploratory</Pill>}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        <Field label="命题">{MOCK_HYPOTHESIS.proposition}</Field>
        <div>
          <div
            style={{
              color: "var(--desk-text-dim)",
              fontSize: 11,
              marginBottom: 3,
            }}
          >
            可证伪条件
          </div>
          {/* 失败阈值用 danger 色（可证伪门可见）。 */}
          <div style={{ color: "var(--desk-danger)" }}>
            {MOCK_HYPOTHESIS.falsify}
          </div>
        </div>
        <div style={{ display: "flex", gap: 24 }}>
          <Field label="benchmark">{MOCK_HYPOTHESIS.benchmark}</Field>
          <Field label="goal_ref">{MOCK_HYPOTHESIS.goalRef}</Field>
        </div>
      </div>
    </Card>
  );
}

function MarketCard() {
  return (
    <Card icon="▦" title="市场 · equity_cn · 用了哪些数据">
      <div
        style={{ color: "var(--desk-text-dim)", fontSize: 11, marginBottom: 6 }}
      >
        数据源（3）
      </div>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          marginBottom: 12,
        }}
      >
        {MOCK_DATA_SOURCES.map((s) => (
          <div
            key={s.id}
            style={{
              display: "flex",
              gap: 10,
              background: "var(--desk-topbar)",
              border: "1px solid var(--desk-border)",
              borderRadius: "var(--desk-radius)",
              padding: "8px 11px",
            }}
          >
            <span style={{ fontWeight: 600, minWidth: 150 }}>{s.id}</span>
            <span
              style={{
                flex: 1,
                color: "var(--desk-text-muted)",
                fontSize: 12,
              }}
            >
              {s.note}
            </span>
          </div>
        ))}
      </div>
      <div
        style={{ color: "var(--desk-text-dim)", fontSize: 11, marginBottom: 5 }}
      >
        字段宇宙 · 41 列
      </div>
      {MOCK_FIELD_GROUPS.map((g) => (
        <div
          key={g.k}
          style={{ padding: "7px 0", borderBottom: "1px solid var(--desk-border-soft)" }}
        >
          <div
            style={{ color: "var(--desk-text-dim)", fontSize: 11, marginBottom: 2 }}
          >
            {g.k}
          </div>
          <div style={{ color: "var(--desk-text-soft)", fontSize: 12 }}>
            {g.v}
          </div>
        </div>
      ))}
      <div
        style={{
          marginTop: 10,
          color: "var(--desk-text-dim)",
          fontSize: 11.5,
          lineHeight: 1.6,
        }}
      >
        覆盖 5412 只 A股 · 引用列全部命中字段宇宙，无缺失。中证500 基准、周五调仓。
      </div>
    </Card>
  );
}

function FactorSetCard() {
  return (
    <Card
      icon="⊞"
      title="因子集 · fs_core3"
      badge={<LineageBadge>← 因子台 · 选用</LineageBadge>}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {MOCK_FACTOR_SET.map((f) => (
          <div
            key={f.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              background: "var(--desk-topbar)",
              border: "1px solid var(--desk-border)",
              borderLeft: "3px solid var(--desk-success)",
              borderRadius: "var(--desk-radius)",
              padding: "9px 12px",
            }}
          >
            <span style={{ fontWeight: 600, minWidth: 120 }}>{f.id}</span>
            <span
              style={{ flex: 1, color: "var(--desk-text-muted)", fontSize: 12 }}
            >
              {f.note}
            </span>
            <span style={{ fontSize: 11, color: "var(--desk-text-muted)" }}>
              IC {f.ic}
            </span>
            <Pill tone="success">{f.state}</Pill>
          </div>
        ))}
      </div>
      <div
        style={{
          marginTop: 11,
          color: "var(--desk-text-dim)",
          fontSize: 11.5,
          lineHeight: 1.6,
        }}
      >
        两两相关 |ρ| &lt; 0.35（低冗余）· resid_vol 已在因子台被淘汰（t=1.1），不纳入 ·
        策略台只选用 QUALIFIED+ 因子，不在此造因子。
      </div>
    </Card>
  );
}

function ModelCard() {
  // walk-forward 8 窗口表展开（纯展示态，非业务状态）。
  const [wfOpen, setWfOpen] = useState(false);
  return (
    <Card
      icon="▣"
      title="模型 · lgbm_rank_6f @ v2"
      badge={<LineageBadge>← Model台 · staging</LineageBadge>}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", gap: 24 }}>
          <Field label="task">LambdaRank</Field>
          <div>
            <div
              style={{ color: "var(--desk-text-dim)", fontSize: 11 }}
            >
              CV NDCG@50
            </div>
            <div style={{ color: "var(--desk-success)" }}>0.231 ± 0.016</div>
          </div>
          <button
            onClick={() => setWfOpen((o) => !o)}
            aria-expanded={wfOpen}
            style={{
              cursor: "pointer",
              background: "transparent",
              border: "none",
              padding: 0,
              textAlign: "left",
              fontFamily: "inherit",
            }}
          >
            <div style={{ color: "var(--desk-text-dim)", fontSize: 11 }}>
              walk-forward
            </div>
            <div style={{ color: "var(--desk-success)" }}>
              8/8 窗口正{" "}
              <span style={{ color: "var(--desk-info)" }}>
                {wfOpen ? "▴" : "▾"}
              </span>
            </div>
          </button>
        </div>
        {wfOpen && (
          <div
            data-wf-table
            style={{
              background: "var(--desk-input)",
              border: "1px solid var(--desk-border-soft)",
              borderRadius: "var(--desk-radius)",
              padding: "11px 13px",
              fontSize: 11,
            }}
          >
            <div
              style={{
                lineHeight: 1.55,
                marginBottom: 9,
                color: "var(--desk-text-soft)",
              }}
            >
              滚动前向验证（Model台）：永远用过去训练、用紧接的未来测试，窗口逐段往前滚。下列{" "}
              <span style={{ color: "var(--desk-success)" }}>8/8</span>{" "}
              个样本外窗口超额全为正：
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  color: "var(--desk-text-faint)",
                  paddingBottom: 3,
                  borderBottom: "1px solid var(--desk-border-soft)",
                }}
              >
                <span style={{ width: 26 }}>窗口</span>
                <span style={{ flex: 1 }}>训练段 → 测试段</span>
                <span style={{ width: 56, textAlign: "right" }}>OOS超额</span>
                <span style={{ width: 56, textAlign: "right" }}>NDCG@50</span>
              </div>
              {MOCK_WF_WINDOWS.map((w) => (
                <div key={w.w} style={{ display: "flex", gap: 10 }}>
                  <span style={{ color: "var(--desk-text-faint)", width: 26 }}>
                    {w.w}
                  </span>
                  <span style={{ flex: 1, color: "var(--desk-text-muted)" }}>
                    {w.span}
                  </span>
                  <span
                    style={{
                      width: 56,
                      textAlign: "right",
                      color: w.worst
                        ? "var(--desk-warning)"
                        : "var(--desk-success)",
                    }}
                  >
                    {w.oos}
                  </span>
                  <span
                    style={{
                      width: 56,
                      textAlign: "right",
                      color: "var(--desk-text-muted)",
                    }}
                  >
                    {w.ndcg}
                  </span>
                </div>
              ))}
            </div>
            <div
              style={{
                marginTop: 9,
                color: "var(--desk-text-dim)",
                lineHeight: 1.55,
              }}
            >
              最差窗口 W4（2022 单边下行）仍 +0.9% 为正 → 模型跨时间稳健、非单年运气。策略台只引用、不重算。
            </div>
          </div>
        )}
        <Field label="特征重要度">sue 0.40 · mom 0.37 · ep 0.23</Field>
        <div
          style={{
            color: "var(--desk-text-dim)",
            fontSize: 11.5,
            lineHeight: 1.6,
          }}
        >
          模型回测（Purged-CV / walk-forward）在 Model台 完成并发布。策略台只引用 model_id，不训练 —— 重训去 Model台。
        </div>
      </div>
    </Card>
  );
}

function SignalCard() {
  return (
    <Card icon="⇗" title="信号 · 打分 → 可交易信号">
      <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
        <Field label="信号规则">{MOCK_SIGNAL.rule}</Field>
        <div style={{ display: "flex", gap: 24 }}>
          <Field label="调仓频率">{MOCK_SIGNAL.rebalance}</Field>
          <Field label="方向">{MOCK_SIGNAL.direction}</Field>
          <Field label="候选数">{MOCK_SIGNAL.candidates}</Field>
        </div>
        <div
          style={{
            color: "var(--desk-text-dim)",
            fontSize: 11.5,
            lineHeight: 1.6,
          }}
        >
          模型只出排序分；信号层把分转成"买哪些"的离散决策——排序、分位阈值、调仓节奏在此固化。
        </div>
      </div>
    </Card>
  );
}

/** 风控限额 chip（约束=neutral / 熔断=danger）。 */
function LimitChip({ danger, children }: { danger?: boolean; children: ReactNode }) {
  return (
    <span
      style={{
        fontSize: 12,
        color: danger ? "var(--desk-danger)" : "var(--desk-text-soft)",
        background: danger
          ? "color-mix(in srgb, var(--desk-danger) 12%, transparent)"
          : "var(--desk-topbar)",
        border: `1px solid ${danger ? "var(--desk-danger)" : "var(--desk-border)"}`,
        borderRadius: "var(--desk-radius)",
        padding: "5px 10px",
      }}
    >
      {children}
    </span>
  );
}

function PortfolioCard() {
  return (
    <Card icon="⛨" title="风控 + 执行机制">
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 9,
            }}
          >
            <span
              style={{
                color: "var(--desk-danger)",
                fontSize: 12.5,
                fontWeight: 600,
              }}
            >
              ⛨ 风控
            </span>
            <span style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>
              仓位是风控的一部分
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
            <div>
              <div
                style={{
                  color: "var(--desk-text-dim)",
                  fontSize: 11,
                  marginBottom: 4,
                }}
              >
                仓位构建
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {MOCK_RISK_SIZING.map((s) => (
                  <LimitChip key={s}>{s}</LimitChip>
                ))}
              </div>
            </div>
            <div>
              <div
                style={{
                  color: "var(--desk-text-dim)",
                  fontSize: 11,
                  marginBottom: 4,
                }}
              >
                风险限额
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                {MOCK_RISK_LIMITS.map((s) => (
                  <LimitChip key={s} danger>
                    {s}
                  </LimitChip>
                ))}
              </div>
            </div>
          </div>
        </div>
        <div
          style={{
            borderTop: "1px solid var(--desk-border-soft)",
            paddingTop: 13,
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              marginBottom: 9,
            }}
          >
            <span
              style={{
                color: "var(--desk-accent)",
                fontSize: 12.5,
                fontWeight: 600,
              }}
            >
              ⇗ 执行机制
            </span>
            <span style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>
              由信号触发 · 信号给候选名单，执行机制决定如何进出
            </span>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
            <Field label="进入">{MOCK_EXEC.enter}</Field>
            <Field label="退出">{MOCK_EXEC.exit}</Field>
          </div>
        </div>
      </div>
    </Card>
  );
}

function RunCard({ liveRunId }: { liveRunId?: string }) {
  // 切真：有真 run_id → LiveRunVerdictCard 拉后端三端点（verdict/overfit/cost-sensitivity）。
  // 无（agent mock 剧本默认）→ 退回 mock 卡，header 恒挂 MockBadge（诚实，不假绿灯）。
  return (
    <div data-cowork-card="run">
      {liveRunId ? (
        <LiveRunVerdictCard
          runId={liveRunId}
          detailHref={`/runs/${encodeURIComponent(liveRunId)}`}
          fallback={MOCK_AGENT_RUN}
        />
      ) : (
        <RunVerdictCard data={MOCK_AGENT_RUN} />
      )}
    </div>
  );
}

/** 空态占位。 */
function CoworkEmpty() {
  return (
    <div
      style={{
        color: "var(--desk-text-faint)",
        fontSize: 13,
        textAlign: "center",
        padding: "80px 20px",
        lineHeight: 2,
        whiteSpace: "pre-line",
      }}
    >
      {"组装开始后\n假设卡 / 因子集 / 模型卡 / 回测拍板\n会在这里逐步出现"}
    </div>
  );
}

export interface CoworkAreaProps {
  /** 当前展示的产物卡（null = 空态）。 */
  cowork: CoworkKind | null;
  /** 已解锁的产物卡集合——未解锁时即便选中也回落空态。 */
  unlocked: Set<CoworkKind>;
  /**
   * 真回测 run_id（可选）：提供则回测裁决卡接真后端（authFetch verdict/overfit/cost-sensitivity）；
   * 缺省（mock 剧本）则裁决卡走 mock + MockBadge。
   */
  liveRunId?: string;
}

/** 产物区：按 cowork + 解锁态渲染对应卡片。 */
export function CoworkArea({ cowork, unlocked, liveRunId }: CoworkAreaProps) {
  const show = cowork && unlocked.has(cowork) ? cowork : null;
  return (
    <div style={{ maxWidth: 620, margin: "0 auto" }} data-cowork-area>
      {show === null && <CoworkEmpty />}
      {show === "hypothesis" && <HypothesisCard />}
      {show === "market" && <MarketCard />}
      {show === "factorSet" && <FactorSetCard />}
      {show === "model" && <ModelCard />}
      {show === "signal" && <SignalCard />}
      {show === "portfolio" && <PortfolioCard />}
      {show === "run" && <RunCard liveRunId={liveRunId} />}
    </div>
  );
}
