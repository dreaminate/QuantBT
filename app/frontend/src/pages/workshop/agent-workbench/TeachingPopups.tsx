import { type ReactNode } from "react";
import { Pill } from "../../../components/desk";

/**
 * 研究执行台教学文案弹窗三型（T-041 残余 · agentDeck.md §⑤ 治理可见性）。
 *
 * 与 GatePanel（A3 已建：权限确认 + self-approve 二次确认）**职责分离**——
 * 本文件只做「知情/引导」三类弹窗，全部 **硬透明 + 软决定**（绝不死挡）：
 *
 *  ① FalsifiabilityGuide —— 可证伪 409 引导（D-T024-FALS）：
 *     agent 跑确证回测但假设卡未填 / 可证伪启发式判 low → 引导填假设卡，
 *     非死挡（用户 acknowledge / 仍要跑 后可继续，留痕）。
 *  ② ProvenanceAck —— 实盘因子血统知情确认（D-PROVENANCE）：
 *     上真钱线前列出未过治理流程的因子 + 知情确认（acknowledge 留痕，非死挡）。
 *  ③ RedVerdictAck —— 验证官 red / 弱点知情确认：
 *     red 裁决一等呈现（R25 不淡化）+ 知情确认；裁决措辞走后端 _verdict_note（R7）。
 *
 * 硬不变量：
 *  · 零裸 hex —— 全部 var(--desk-*)。
 *  · 治理弱点常驻展开、**不渲染折叠控件**（R25）—— 三型皆 data-weakness-expanded="true"。
 *  · 裁决措辞禁 证据一致/安全/排除过拟合 等绝对化词（R7），note 由后端供给（prop），不前端杜撰。
 *  · 软决定：确认按钮恒可点（acknowledge 后继续），不做「禁用唯一出口」式死挡。
 */

/** 弹窗外壳：醒目边框 + 标题 + 弱点常驻展开（R25：无折叠控件）。 */
function WeaknessShell({
  testid,
  glyph,
  tone,
  title,
  pill,
  children,
}: {
  testid: string;
  glyph: string;
  /** danger（真钱/red）/ warning（可证伪 low）。 */
  tone: "danger" | "warning";
  title: string;
  pill?: ReactNode;
  children: ReactNode;
}) {
  const toneVar = tone === "danger" ? "var(--desk-danger)" : "var(--desk-warning)";
  return (
    <div
      data-testid={testid}
      // R25：治理弱点常驻展开——无折叠控件、无 collapsed 状态可藏起。
      data-weakness-expanded="true"
      data-tone={tone}
      style={{
        margin: "10px 0",
        border: `1px solid ${toneVar}`,
        background: `color-mix(in srgb, ${toneVar} 9%, transparent)`,
        borderRadius: "var(--desk-radius-lg)",
        padding: "11px 13px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginBottom: 8,
        }}
      >
        <span aria-hidden style={{ color: toneVar, fontWeight: 700 }}>
          {glyph}
        </span>
        <span style={{ color: "var(--desk-text)", fontWeight: 600 }}>
          {title}
        </span>
        {pill}
      </div>
      {children}
    </div>
  );
}

/** 软决定按钮行：知情确认（继续）+ 主推回避动作 + 可取消，恒可点（非死挡）。 */
function AckActions({
  ackLabel,
  ackTestid,
  guideLabel,
  guideTestid,
  onAck,
  onGuide,
  onCancel,
  tone,
}: {
  ackLabel: string;
  ackTestid: string;
  /** 主推的「正确路径」动作（填假设卡 / 回因子台 / 看证据）——非强制。 */
  guideLabel?: string;
  guideTestid?: string;
  onAck: () => void;
  onGuide?: () => void;
  onCancel?: () => void;
  tone: "danger" | "warning";
}) {
  const toneVar = tone === "danger" ? "var(--desk-danger)" : "var(--desk-warning)";
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 4 }}>
      {/* 主推：回正确路径（强调描边），但不挡——只是默认建议。 */}
      {guideLabel && onGuide && (
        <button
          data-testid={guideTestid}
          onClick={onGuide}
          style={btnStyle("var(--desk-accent)")}
        >
          {guideLabel}
        </button>
      )}
      {/* 软决定出口：知情确认后继续（留痕）。恒可点，绝不死挡。 */}
      <button
        data-testid={ackTestid}
        onClick={onAck}
        style={btnStyle(toneVar)}
      >
        {ackLabel}
      </button>
      {onCancel && (
        <button
          data-testid={ackTestid + "-cancel"}
          onClick={onCancel}
          style={btnStyle("var(--desk-border)")}
        >
          先不跑
        </button>
      )}
    </div>
  );
}

function btnStyle(colorVar: string): React.CSSProperties {
  return {
    fontFamily: "inherit",
    fontSize: 11.5,
    padding: "5px 11px",
    borderRadius: "var(--desk-radius-sm)",
    border: `1px solid ${colorVar}`,
    background: "transparent",
    color: colorVar,
    cursor: "pointer",
  };
}

/** 可证伪启发式置信度（对齐后端 falsifiability.FalsifiabilityVerdict.confidence）。 */
export type FalsifiabilityConfidence = "high" | "medium" | "low";

export interface FalsifiabilityGuideProps {
  /** 关联工具（如 backtest.run confirmatory）。 */
  tool: string;
  /** 后端 assess_falsifiability 的 confidence（受控真值，非前端判定）。 */
  confidence: FalsifiabilityConfidence;
  /** 缺失项 / 启发式 flags 的人读摘要（来自后端 flags，逐条列）。 */
  flags: string[];
  /** 假设卡是否完全未填（结构空）——文案侧重「先填卡」。 */
  cardMissing?: boolean;
  /** 知情确认仍要跑（留痕，软决定）。 */
  onAcknowledge: () => void;
  /** 主推：去填 / 修订假设卡。 */
  onFillCard: () => void;
  /** 先不跑（回避动作）。 */
  onCancel: () => void;
}

/**
 * ① 可证伪 409 引导弹窗（D-T024-FALS：硬透明 + 软决定）。
 *
 * agent 要跑确证（confirmatory）回测，但假设卡未填 / 可证伪启发式判 low
 * （疑似套套逻辑、弱机制）→ 醒目引导填假设卡。**绝不自动硬挡晋级**：
 * 知情确认后仍可跑（留痕）。文案引导、不评判研究本身。
 */
export function FalsifiabilityGuide(props: FalsifiabilityGuideProps) {
  const { tool, confidence, flags, cardMissing, onAcknowledge, onFillCard, onCancel } =
    props;
  return (
    <WeaknessShell
      testid="falsifiability-guide"
      glyph="⚠"
      tone="warning"
      title="可证伪性待补 · 确证回测前的引导"
      pill={
        <Pill
          tone="warning"
          title="后端 assess_falsifiability 真值，非前端判定"
        >
          confidence: {confidence}
        </Pill>
      }
    >
      <div
        data-testid="falsifiability-blurb"
        style={{
          fontSize: 11.5,
          color: "var(--desk-text-soft)",
          lineHeight: 1.55,
          marginBottom: 8,
        }}
      >
        {cardMissing
          ? `${tool} 是确证（confirmatory）回测，但本题的假设卡还没填。`
          : `${tool} 是确证（confirmatory）回测，假设卡的可证伪条件启发式判为 ${confidence}。`}
        建议先把假设卡的可证伪条件写清楚（「若 X 则效应消失」+ 可观测阈值），
        这样回测结论才有独立可推翻的判据。这只是引导——你仍可知情后继续跑。
      </div>
      {flags.length > 0 && (
        <ul
          data-testid="falsifiability-flags"
          style={{
            margin: "0 0 9px",
            paddingLeft: 18,
            fontSize: 11,
            color: "var(--desk-warning)",
            lineHeight: 1.6,
          }}
        >
          {flags.map((f, i) => (
            <li key={i}>{f}</li>
          ))}
        </ul>
      )}
      <AckActions
        tone="warning"
        guideLabel="去填假设卡"
        guideTestid="falsifiability-fill"
        ackLabel="知情，仍要跑确证回测"
        ackTestid="falsifiability-ack"
        onGuide={onFillCard}
        onAck={onAcknowledge}
        onCancel={onCancel}
      />
    </WeaknessShell>
  );
}

/** 未过治理流程的因子条目（来自后端血统校验）。 */
export interface UnverifiedFactor {
  /** 因子 id / 名。 */
  id: string;
  /** 卡在哪一步（如「未独立验证」「假设卡未冻结」「未审批」）。 */
  stage: string;
}

export interface ProvenanceAckProps {
  /** 拟上线目的地（文案用，绝不出现「实盘直推」语）。 */
  destination?: string;
  /** 未走完治理流程的因子清单（受控真值，来自后端血统校验）。 */
  unverified: UnverifiedFactor[];
  /** 知情确认（acknowledge 留痕进审计，软决定）。 */
  onAcknowledge: () => void;
  /** 主推：回因子台补治理流程。 */
  onGoFactorDesk: () => void;
  /** 取消（先不上线）。 */
  onCancel: () => void;
}

/**
 * ② 实盘因子血统知情确认弹窗（D-PROVENANCE）。
 *
 * 上真钱线前逐一校验每个因子是否走完治理流程（假设卡→独立验证→审批），
 * 只要有一个未过 → 强制弹窗列出未过因子 + 知情确认后仍可上（你自己的钱与判断）。
 * 知情确认非死挡（acknowledge 留痕进审计）。
 */
export function ProvenanceAck(props: ProvenanceAckProps) {
  const { destination, unverified, onAcknowledge, onGoFactorDesk, onCancel } = props;
  return (
    <WeaknessShell
      testid="provenance-ack"
      glyph="⛔"
      tone="danger"
      title="因子血统未过治理流程 · 真钱上线前知情确认"
      pill={
        <Pill tone="danger" title="后端血统校验真值，不前端伪造">
          未过 {unverified.length}
        </Pill>
      }
    >
      <div
        data-testid="provenance-blurb"
        style={{
          fontSize: 11.5,
          color: "var(--desk-text-soft)",
          lineHeight: 1.55,
          marginBottom: 8,
        }}
      >
        本策略{destination ? `（拟上线：${destination}）` : ""}用到的下列因子还没走完
        治理流程（假设卡 → 独立验证 → 审批）。血统门不硬拦——列出未过项，
        你知情确认后仍可上，这次确认会留痕进审计。
      </div>
      <ul
        data-testid="provenance-list"
        style={{
          margin: "0 0 9px",
          paddingLeft: 18,
          fontSize: 11.5,
          color: "var(--desk-text)",
          lineHeight: 1.7,
        }}
      >
        {unverified.map((f) => (
          <li key={f.id} data-testid="provenance-item">
            <span style={{ color: "var(--desk-text)" }}>{f.id}</span>
            <span style={{ color: "var(--desk-danger)", marginLeft: 8 }}>
              {f.stage}
            </span>
          </li>
        ))}
      </ul>
      <AckActions
        tone="danger"
        guideLabel="回因子台补治理流程"
        guideTestid="provenance-go-factor"
        ackLabel="知情确认，留痕后继续"
        ackTestid="provenance-ack-btn"
        onGuide={onGoFactorDesk}
        onAck={onAcknowledge}
        onCancel={onCancel}
      />
    </WeaknessShell>
  );
}

export interface RedVerdictAckProps {
  /** 关联 run / 工具。 */
  subject: string;
  /**
   * 验证官裁决措辞——**必须由后端 verifier._verdict_note 供给**，前端不杜撰、
   * 不含 R7 禁词（证据一致/安全/排除过拟合…）。本组件原样呈现，不做绝对化包装。
   */
  verdictNote: string;
  /** 弱点逐条（来自后端，一等呈现，不折叠）。 */
  weaknesses: string[];
  /** 知情确认（软决定，留痕）。 */
  onAcknowledge: () => void;
  /** 主推：下钻看完整证据（旁挂裁决卡 / RunVerdictCard，不嵌冻结页）。 */
  onViewEvidence: () => void;
  /** 取消。 */
  onCancel: () => void;
}

/**
 * ③ red 裁决知情确认弹窗（R25 一等呈现 + R7 措辞 + 软决定）。
 *
 * 验证官给出 red / 弱点 → 一等呈现（醒目、常驻展开、不淡化、绝不渲染成绿色通过），
 * 弱点逐条列出 + 知情确认。措辞走后端 _verdict_note（prop），前端不杜撰绝对化词。
 */
export function RedVerdictAck(props: RedVerdictAckProps) {
  const { subject, verdictNote, weaknesses, onAcknowledge, onViewEvidence, onCancel } =
    props;
  return (
    <WeaknessShell
      testid="red-verdict-ack"
      glyph="●"
      tone="danger"
      title={`验证官裁决 · ${subject}`}
      pill={
        <Pill tone="danger" title="验证官独立挑战结论（异模型）">
          red
        </Pill>
      }
    >
      {/* 裁决措辞：原样呈现后端 _verdict_note，前端不包装（R7）。 */}
      <div
        data-testid="red-verdict-note"
        style={{
          fontSize: 11.5,
          color: "var(--desk-text-soft)",
          lineHeight: 1.55,
          marginBottom: 8,
        }}
      >
        {verdictNote}
      </div>
      <div
        style={{
          fontSize: 10.5,
          color: "var(--desk-text-faint)",
          marginBottom: 4,
        }}
      >
        弱点（一等呈现 · 不折叠）：
      </div>
      <ul
        data-testid="red-verdict-weaknesses"
        style={{
          margin: "0 0 9px",
          paddingLeft: 18,
          fontSize: 11.5,
          color: "var(--desk-danger)",
          lineHeight: 1.7,
        }}
      >
        {weaknesses.map((w, i) => (
          <li key={i} data-testid="red-verdict-weakness">
            {w}
          </li>
        ))}
      </ul>
      <AckActions
        tone="danger"
        guideLabel="下钻看完整证据"
        guideTestid="red-verdict-evidence"
        ackLabel="知情，已读弱点后继续"
        ackTestid="red-verdict-ack-btn"
        onGuide={onViewEvidence}
        onAck={onAcknowledge}
        onCancel={onCancel}
      />
    </WeaknessShell>
  );
}
