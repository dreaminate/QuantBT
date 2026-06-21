import {
  AgentChat,
  type AgentBlock,
  ChatComposer,
  MockBadge,
} from "../../../components/desk";
import { ChatHeader } from "./FactorBuildView";
import { type MockFactor } from "./factorData";

export interface ResearchChatMsg {
  role: "user" | "say";
  text: string;
}

export interface AuditCheck {
  title: string;
  icon: string;
  color: string;
  stat: string;
  /** 是否治理弱点（边际/不足/快速衰减/存疑）——R25：默认展开、不折叠、不染绿。 */
  weak: boolean;
  detail: string;
}

/** 后端 /api/factors/{id}/audit 返回（接真时注入）。 */
export interface FactorAuditLive {
  verdict: "consistent" | "concern" | "blocked";
  verdict_note: string;
  disclosure: string;
  tier: string;
  dsr: number;
  sharpe: number;
  n_trials: number;
  pbo: { pbo: number };
  n_eff: { point: number; low: number; high: number };
  bootstrap_ci: { lower: number; upper: number; estimate: number };
  ic: { ic_tstat_nw: number | null; nw_lag: number };
  checks: { key: string; value: number | null; threshold: number; passed: boolean; severe: boolean; direction: string }[];
}

export interface FactorResearchViewProps {
  factor: MockFactor;
  chat: ResearchChatMsg[];
  draft: string;
  onDraft: (v: string) => void;
  onSend: () => void;
  /** 接真审查报告；存在则覆盖 mock 裁决/检查并改挂 LIVE。 */
  live?: FactorAuditLive | null;
}

const _CHECK_LABEL: Record<string, string> = {
  dsr: "Deflated Sharpe（诚实-N 通缩后显著性）",
  pbo: "CSCV 过拟合概率 PBO",
  ic_tstat_nw: "IC Newey-West HAC t（重叠窗口自相关调整）",
  n_eff: "有效独立试验数 N_eff",
};

/** 后端 verdict（一致/存疑/不一致）→ 展示裁决（不假绿灯：consistent≠「真 alpha」断言）。 */
function liveVerdictLabel(v: FactorAuditLive["verdict"]): { label: string; color: string } {
  if (v === "consistent") return { label: "证据一致", color: "var(--desk-success)" };
  if (v === "concern") return { label: "证据存疑", color: "var(--desk-warning)" };
  return { label: "证据不一致", color: "var(--desk-danger)" };
}

/** 把后端 checks 映射成展示卡（弱点 weak=未达标，R25 常驻展开不染绿）。 */
export function buildLiveChecks(live: FactorAuditLive): AuditCheck[] {
  return live.checks.map((c) => {
    const valTxt = c.value == null ? "缺失（未能复算）" : c.value.toFixed(c.key === "n_eff" ? 0 : 3);
    return {
      title: _CHECK_LABEL[c.key] ?? c.key,
      icon: c.passed ? "✓" : c.severe ? "✕" : "△",
      color: c.passed ? "var(--desk-success)" : c.severe ? "var(--desk-danger)" : "var(--desk-warning)",
      stat: c.passed ? "达标" : c.severe ? "严重不达标" : "不达标",
      weak: !c.passed,
      detail: `${valTxt} ${c.direction} 阈值 ${c.threshold}（${c.passed ? "满足" : "未满足"}）。`,
    };
  });
}

export type AuditVerdict = "真 alpha" | "存疑" | "未通过";

/** 审查裁决（R25：仅 icIr>0.5 且 |t|>3 才「真 alpha」；其余存疑/未通过，不假绿灯）。 */
export function auditVerdict(f: MockFactor): AuditVerdict {
  if (f.state === "RETIRED") return "未通过";
  return f.icIr > 0.5 && Math.abs(f.sampleT) > 3 ? "真 alpha" : "存疑";
}

function verdictColor(v: AuditVerdict): string {
  if (v === "真 alpha") return "var(--desk-success)";
  if (v === "存疑") return "var(--desk-warning)";
  return "var(--desk-danger)";
}

/** 构造 5 条审查 check，弱点显式标 weak（R25）。 */
export function buildChecks(f: MockFactor, totalFactors: number, peakH: number): AuditCheck[] {
  const verdict = auditVerdict(f);
  const pass = verdict === "真 alpha";
  const tStrong = Math.abs(f.sampleT) > 3;
  const decayFast = f.state === "WARNING";
  return [
    {
      title: "多重检验校正（Bonferroni / BHY）",
      icon: pass ? "✓" : "△",
      color: pass ? "var(--desk-success)" : "var(--desk-warning)",
      stat: pass ? "通过" : "边际",
      weak: !pass,
      detail: `在 ${totalFactors} 个候选因子中检验，校正后 p < 0.05 才算数。本因子 deflated Sharpe ${pass ? "为正" : "接近 0"}。`,
    },
    {
      title: "数据窥探 / p-hacking",
      icon: "✓",
      color: "var(--desk-success)",
      stat: "干净",
      weak: false,
      detail: "表达式来自固定算子库 + 经济学动机，非暴力搜索产物；参数（窗口）未做样本内调优。",
    },
    {
      title: "IC 显著性 t 检验",
      icon: tStrong ? "✓" : "△",
      color: tStrong ? "var(--desk-success)" : "var(--desk-warning)",
      stat: `t=${f.sampleT.toFixed(1)}`,
      weak: !tStrong,
      detail: `Newey-West 调整自相关后 |t| ${tStrong ? "> 3，稳健显著" : "< 3，证据不足"}。`,
    },
    {
      title: "IC 衰减 / 半衰期",
      icon: decayFast ? "✕" : "✓",
      color: decayFast ? "var(--desk-danger)" : "var(--desk-success)",
      stat: decayFast ? "快速衰减" : "缓和",
      weak: decayFast,
      detail: `峰值 IC 在 ${peakH} 日，${decayFast ? "近 30 日衰减 >50%，疑似拥挤失效。" : "衰减半衰期足够长，可承载周频调仓。"}`,
    },
    {
      title: "经济学先验",
      icon: "✓",
      color: "var(--desk-success)",
      stat: f.fam,
      weak: false,
      detail: `归属「${f.fam}」族，有公认的行为金融 / 风险补偿解释，非纯统计巧合。`,
    },
  ];
}

const PAPERS = [
  {
    title: "Does the Stock Market Overreact?",
    venue: "JF 1985",
    ref: "De Bondt & Thaler",
    gist: "反转效应的奠基：长期输家组合跑赢赢家组合，行为定价证据。",
    transfer: "反转族因子的理论根",
  },
  {
    title: "Returns to Buying Winners and Selling Losers",
    venue: "JF 1993",
    ref: "Jegadeesh & Titman",
    gist: "动量异象：3-12 月形成期的相对强弱可预测未来收益。",
    transfer: "动量族因子先验",
  },
  {
    title: "…and the Cross-Section of Expected Returns",
    venue: "RFS 2016",
    ref: "Harvey, Liu & Zhu",
    gist: "因子动物园警示：多重检验下大多数已发表因子站不住脚，需更高 t 门槛。",
    transfer: "本台多重检验门槛",
  },
];

/** 研究台 view：左审查 chat + 右 alpha 真伪审查报告。 */
export function FactorResearchView({
  factor: sel,
  chat,
  draft,
  onDraft,
  onSend,
  live,
}: FactorResearchViewProps) {
  const peakH = sel.decay.reduce((a, b) => (Math.abs(b.ic) > Math.abs(a.ic) ? b : a)).h;
  // 接真：裁决/检查/摘要全用后端 audit；否则 mock。
  const liveVd = live ? liveVerdictLabel(live.verdict) : null;
  const verdict = live ? liveVd!.label : auditVerdict(sel);
  const vc = live ? liveVd!.color : verdictColor(verdict as AuditVerdict);
  const checks = live ? buildLiveChecks(live) : buildChecks(sel, 15, peakH);

  const summary = live
    ? live.verdict_note
    : verdict === "未通过"
      ? "退役因子：多重检验后不显著，且与现有因子高度共线。保留作对照样本，不进组合。"
      : verdict === "真 alpha"
        ? "经多重检验校正后 IC 仍显著，且有经济学先验支撑——判定为真实 alpha。需在 OBSERVATION 期持续监控实盘衰减。"
        : "样本内显著但 t 值偏弱，存在数据挖掘风险。建议样本外再观察一个季度，或加经济学约束。";

  const blocks: AgentBlock[] = chat.map((c, i) => ({
    id: `rs-${i}`,
    type: c.role === "user" ? "user" : "say",
    text: c.text,
  }));

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex" }}>
      {/* LEFT · research chat */}
      <div
        style={{
          flex: "none",
          width: 336,
          borderRight: "1px solid var(--desk-border)",
          display: "flex",
          flexDirection: "column",
          background: "var(--desk-soft-btn)",
        }}
      >
        <ChatHeader glyph="⚗" title="学术审查" hint="academic audit" />
        <AgentChat
          blocks={blocks}
          composer={
            <ChatComposer
              draft={draft}
              onDraftChange={onDraft}
              onSend={onSend}
              placeholder="质询这个因子是否真 alpha…"
              model="claude (mock)"
              permissionMode="ask"
              branch="factor"
            />
          }
        />
      </div>

      {/* RIGHT · audit report */}
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", background: "var(--desk-canvas)", padding: "18px 24px" }}>
        <div style={{ maxWidth: 780 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
            <span style={{ fontSize: 16, fontWeight: 700 }}>{sel.id}</span>
            <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>alpha 真伪审查</span>
            <span
              data-audit-verdict={verdict}
              style={{
                marginLeft: "auto",
                fontSize: 11,
                fontWeight: 700,
                color: vc,
                background: `color-mix(in srgb, ${vc} 12%, transparent)`,
                border: `1px solid ${vc}`,
                padding: "4px 12px",
                borderRadius: "var(--desk-radius-pill)",
              }}
            >
              {verdict}
            </span>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--desk-node-line)", marginBottom: 12, lineHeight: 1.6 }}>
            {summary}
          </div>
          <div style={{ marginBottom: 16 }}>
            {live ? (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <span
                  data-testid="audit-live-badge"
                  style={{
                    alignSelf: "flex-start",
                    fontSize: 10,
                    fontWeight: 700,
                    color: "var(--desk-success)",
                    border: "1px solid color-mix(in srgb, var(--desk-success) 40%, transparent)",
                    borderRadius: 4,
                    padding: "1px 6px",
                  }}
                >
                  LIVE · 审查接真（{live.tier} 档）
                </span>
                {/* 多证据三角硬指标行（DSR/PBO/N_eff/Bootstrap/IC-NW） */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 8 }}>
                  {[
                    { k: "DSR", v: live.dsr.toFixed(3) },
                    { k: "PBO", v: live.pbo.pbo.toFixed(3) },
                    { k: "N_eff", v: `${live.n_eff.point} [${live.n_eff.low},${live.n_eff.high}]` },
                    { k: "SR CI", v: `[${live.bootstrap_ci.lower.toFixed(2)}, ${live.bootstrap_ci.upper.toFixed(2)}]` },
                    { k: `IC-NW t (lag${live.ic.nw_lag})`, v: live.ic.ic_tstat_nw == null ? "—" : live.ic.ic_tstat_nw.toFixed(2) },
                  ].map((m) => (
                    <div
                      key={m.k}
                      style={{
                        background: "var(--desk-card)",
                        border: "1px solid var(--desk-border)",
                        borderRadius: "var(--desk-radius-lg)",
                        padding: "7px 9px",
                      }}
                    >
                      <div style={{ fontSize: 9, color: "var(--desk-text-muted)" }}>{m.k}</div>
                      <div style={{ fontSize: 12, fontWeight: 700, color: "var(--desk-text)" }}>{m.v}</div>
                    </div>
                  ))}
                </div>
                <div style={{ fontSize: 10, color: "var(--desk-text-faint)", lineHeight: 1.6 }}>
                  {live.disclosure}
                </div>
              </div>
            ) : (
              <MockBadge label="MOCK 数据 · 审查报告合成（待接 /api/factors/{id}/audit）" />
            )}
          </div>

          {/* audit checks —— R25：弱点常驻展开（detail 永远渲染），不折叠不染绿 */}
          <div style={{ display: "flex", flexDirection: "column", gap: 9, marginBottom: 16 }}>
            {checks.map((c, i) => (
              <div
                key={i}
                data-check
                data-weak={c.weak}
                style={{
                  background: "var(--desk-card)",
                  border: `1px solid ${c.weak ? c.color : "var(--desk-node-border)"}`,
                  borderRadius: "var(--desk-radius-lg)",
                  padding: "11px 14px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                  <span style={{ fontSize: 14, color: c.color }}>{c.icon}</span>
                  <span style={{ fontSize: 12, color: "var(--desk-text)", fontWeight: 600 }}>{c.title}</span>
                  <span style={{ marginLeft: "auto", fontSize: 10.5, color: c.color, fontWeight: 600 }}>
                    {c.stat}
                  </span>
                </div>
                <div
                  data-check-detail
                  style={{ fontSize: 10.5, color: "var(--desk-text-muted)", marginTop: 6, lineHeight: 1.6 }}
                >
                  {c.detail}
                </div>
              </div>
            ))}
          </div>

          {/* papers */}
          <div style={{ fontSize: 11, color: "var(--desk-text-muted)", marginBottom: 9 }}>
            相关文献 · 因子方法论
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {PAPERS.map((p) => (
              <div
                key={p.title}
                style={{
                  background: "var(--desk-card)",
                  border: "1px solid var(--desk-border)",
                  borderRadius: "var(--desk-radius-lg)",
                  padding: "11px 14px",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 5 }}>
                  <span style={{ fontSize: 12, color: "var(--desk-info)", fontWeight: 600 }}>{p.title}</span>
                  <span style={{ fontSize: 9.5, color: "var(--desk-text-muted)" }}>{p.venue}</span>
                  <span style={{ marginLeft: "auto", fontSize: 9.5, color: "var(--desk-info)" }}>{p.ref}</span>
                </div>
                <div style={{ fontSize: 10.5, color: "var(--desk-node-line)", lineHeight: 1.6 }}>{p.gist}</div>
                <div style={{ fontSize: 10, color: "var(--desk-accent)", marginTop: 5 }}>借鉴 · {p.transfer}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
