import {
  CollapsiblePanel,
  Pill,
  MockBadge,
  SegmentedControl,
  AgentChat,
  ChatComposer,
  type AgentBlock,
} from "../../../components/desk";
import {
  RS_FORMULA,
  RS_CONCLUSION,
  RS_PAPERS,
  RS_CHAT_SEED,
} from "./modelMock";

/**
 * 研究台（research · DC §D）：理论判定 + 论文，两栏。
 * 左：研究助手 chat · 右：workspace（∑公式工作台 / ▤论文）。
 * 治理：理论判定只「提炼/判定」不下结论；文章观点须先在因子台 IC 检验（M11，见结论文案）。P0 mock。
 */

export type ResearchTab = "formula" | "papers";

export interface ResearchDeckProps {
  chatOpen: boolean;
  onToggleChat: () => void;
  tab: ResearchTab;
  onTabChange: (t: ResearchTab) => void;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  onToBuild: () => void;
}

export function ResearchDeck(props: ResearchDeckProps) {
  const chatBlocks: AgentBlock[] = RS_CHAT_SEED.map((m, i) =>
    m.role === "user"
      ? { id: `u${i}`, type: "user", text: m.text }
      : { id: `a${i}`, type: "say", text: m.text },
  );

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      {/* 左：研究助手 */}
      <CollapsiblePanel
        open={props.chatOpen}
        onToggle={props.onToggleChat}
        side="left"
        width={340}
        label="研究助手"
      >
        <div
          style={{
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 14px",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          <span style={{ color: "var(--desk-ghost)" }}>⚗</span>
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)" }}>研究助手</span>
          <span style={{ marginLeft: "auto" }}>
            <MockBadge />
          </span>
        </div>
        <AgentChat
          blocks={chatBlocks}
          composer={
            <ChatComposer
              draft={props.draft}
              onDraftChange={props.onDraftChange}
              onSend={props.onSend}
              model="claude（mock）"
              permissionMode="ask"
              branch="fullstack"
              placeholder="> 导入论文 / 问理论可行性…"
            />
          }
        />
      </CollapsiblePanel>

      {/* 右：workspace */}
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", background: "var(--desk-canvas)" }}>
        <div
          style={{
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "8px 16px",
            borderBottom: "1px solid var(--desk-border)",
            background: "var(--desk-soft-btn)",
          }}
        >
          <SegmentedControl<ResearchTab>
            options={[
              { value: "formula", label: "∑ 公式工作台" },
              { value: "papers", label: "▤ 论文" },
            ]}
            value={props.tab}
            onChange={props.onTabChange}
            size="sm"
          />
          <span style={{ marginLeft: "auto" }}>
            <MockBadge />
          </span>
          <button
            onClick={props.onToBuild}
            style={{
              fontFamily: "inherit",
              fontSize: 11,
              padding: "4px 11px",
              borderRadius: "var(--desk-radius-sm)",
              border: "1px solid var(--desk-info)",
              background: "transparent",
              color: "var(--desk-info)",
              cursor: "pointer",
            }}
          >
            架构带去构建台 →
          </button>
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "18px 22px" }}>
          {props.tab === "formula" ? <FormulaWorkspace /> : <PapersWorkspace />}
        </div>
      </main>
    </div>
  );
}

function FormulaWorkspace() {
  return (
    <div style={{ maxWidth: 680, margin: "0 auto" }}>
      <div
        style={{
          borderRadius: "var(--desk-radius-lg)",
          border: "1px solid var(--desk-node-border)",
          background: "var(--desk-card)",
          overflow: "hidden",
          marginBottom: 14,
        }}
      >
        <div
          style={{
            padding: "8px 14px",
            borderBottom: "1px solid var(--desk-border)",
            fontSize: 11,
            color: "var(--desk-ghost)",
          }}
        >
          FactorVAE · forward 推导（候选架构 · 理论判定）
        </div>
        <div style={{ padding: "4px 14px 8px" }}>
          {RS_FORMULA.map((f, i) => (
            <div
              key={i}
              style={{
                display: "flex",
                gap: 12,
                padding: "6px 0",
                borderBottom: "1px solid var(--desk-border-soft)",
              }}
            >
              <span style={{ flex: 1, fontSize: 12.5, color: "var(--desk-text-soft)" }}>{f.expr}</span>
              <span
                style={{
                  flex: "none",
                  fontSize: 10.5,
                  color: `var(--desk-${f.tone})`,
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                {f.icon} {f.note}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* 理论判定结论（隐患黄、不假绿；含 M11 因子门提醒） */}
      <div
        data-rs-conclusion
        style={{
          borderRadius: "var(--desk-radius-lg)",
          border: "1px solid var(--desk-stage-frame-gap)",
          background: "var(--desk-input)",
          padding: "12px 15px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--desk-warning)" }}>
            ○ 理论判定结论（含隐患）
          </span>
        </div>
        <div style={{ fontSize: 12, color: "var(--desk-text-soft)", lineHeight: 1.65 }}>
          {RS_CONCLUSION}
        </div>
      </div>
    </div>
  );
}

function PapersWorkspace() {
  return (
    <div style={{ maxWidth: 760, margin: "0 auto", display: "flex", flexDirection: "column", gap: 12 }}>
      {RS_PAPERS.map((p) => (
        <div
          key={p.title}
          style={{
            borderRadius: "var(--desk-radius-lg)",
            border: "1px solid var(--desk-node-border)",
            background: "var(--desk-card)",
            padding: "12px 15px",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 6 }}>
            <span style={{ fontWeight: 600, fontSize: 13.5, color: "var(--desk-text)" }}>{p.title}</span>
            <Pill tone="ghost">{p.venue}</Pill>
            <span style={{ marginLeft: "auto", fontSize: 10.5, color: "var(--desk-text-faint)" }}>
              {p.arxiv}
            </span>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--desk-text-dim)", lineHeight: 1.6, marginBottom: 6 }}>
            {p.gist}
          </div>
          <div style={{ fontSize: 11, color: "var(--desk-info)" }}>可迁移：{p.transfer}</div>
        </div>
      ))}
    </div>
  );
}
