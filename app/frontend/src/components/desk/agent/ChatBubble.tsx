import { type ReactNode, useState } from "react";
import { Pill, type DeskTone } from "../primitives";

/**
 * Agent 对话气泡 7 型（agentDeck.md §C / parseConsole.md §P2）。
 * 全部受控：type + 内容由 props 传入，组件不持业务状态。
 *
 * R25 治理不变量：治理弱点类 block（gate / 含 red 裁决 / 血统 / 真钱）
 * 默认展开且**不可折叠藏起**——种「弱点折叠」必抓（对抗 desk hex/折叠扫描）。
 */

export type ChatBlockType =
  | "user"
  | "think"
  | "say"
  | "patch"
  | "todos"
  | "tool"
  | "gate"
  | "workflow";

/** todo 三态：done ☑ / doing ◐ / todo ☐。 */
export type TodoState = "done" | "doing" | "todo";

export interface TodoItem {
  text: string;
  state: TodoState;
}

/** patch diff 行符号：+ 增 / ~ 改 / - 删。 */
export type DiffSign = "+" | "~" | "-";

export interface DiffLine {
  sign: DiffSign;
  text: string;
}

/** gate 权限弹窗的副作用展示值——受控、来自后端 tool_status，不前端伪造。 */
export type SideEffect = "none" | "external" | "realmoney";

export interface ChatBubbleProps {
  type: ChatBlockType;
  /** user/think/say 的正文文本。 */
  text?: string;
  /** patch 卡：标题 + patchId + 受影响摘要 + 是否已撤销。 */
  patchTitle?: string;
  patchId?: string;
  affected?: string;
  reverted?: boolean;
  diff?: DiffLine[];
  /** todos 列表。 */
  todos?: TodoItem[];
  /** tool 行：name(args) + 状态 + 摘要 + cowork 下钻链接。 */
  toolName?: string;
  toolArgs?: string;
  toolStatus?: "running" | "done";
  toolSummary?: string;
  /** gate 权限弹窗：工具名 + 副作用（受控展示）+ 说明 + 三选项回调。 */
  gateTool?: string;
  sideEffect?: SideEffect;
  gateBlurb?: string;
  /** gate 是否治理弱点（red 裁决 / 血统 / 真钱）——强制常驻展开。 */
  governanceWeakness?: boolean;
  onApproveOnce?: () => void;
  onApproveAlways?: () => void;
  onReject?: () => void;
  /** patch 整轮撤销回调。 */
  onRevert?: () => void;
  /** GOAL §7 durable workflow event；只展示客户端白名单摘要，不展开任意原始 payload。 */
  workflowKind?: string;
  workflowRole?: string;
  workflowDesk?: string;
  workflowAt?: string;
  workflowSummary?: string;
}

/** diff sign → 语义色变量。 */
const DIFF_COLOR: Record<DiffSign, string> = {
  "+": "var(--desk-success)",
  "~": "var(--desk-warning)",
  "-": "var(--desk-danger)",
};

const TODO_GLYPH: Record<TodoState, string> = {
  done: "☑",
  doing: "◐",
  todo: "☐",
};

const TODO_COLOR: Record<TodoState, string> = {
  done: "var(--desk-success)",
  doing: "var(--desk-warning)",
  todo: "var(--desk-text-faint)",
};

/** 副作用 → 展示色：真钱红 / 外部黄 / 无副作用灰。 */
const SIDE_EFFECT_TONE: Record<SideEffect, DeskTone> = {
  none: "neutral",
  external: "warning",
  realmoney: "danger",
};

const SIDE_EFFECT_LABEL: Record<SideEffect, string> = {
  none: "side_effect: none",
  external: "side_effect: external",
  realmoney: "side_effect: realmoney",
};

function Glyph({ ch, color }: { ch: string; color: string }): ReactNode {
  return (
    <span aria-hidden style={{ color, marginRight: 6, fontWeight: 700 }}>
      {ch}
    </span>
  );
}

export function ChatBubble(props: ChatBubbleProps) {
  const { type } = props;

  if (type === "workflow") {
    const isFailure = props.workflowKind === "FailureDetected";
    return (
      <div
        data-block="workflow"
        data-workflow-kind={props.workflowKind}
        style={{
          margin: "8px 0",
          borderLeft: `2px solid ${
            isFailure ? "var(--desk-danger)" : "var(--desk-border-strong)"
          }`,
          padding: "5px 0 5px 10px",
          fontSize: 11.5,
        }}
      >
        <div style={{ display: "flex", gap: 7, alignItems: "baseline", flexWrap: "wrap" }}>
          <span
            style={{
              color: isFailure ? "var(--desk-danger)" : "var(--desk-accent)",
              fontWeight: 700,
            }}
          >
            {props.workflowKind}
          </span>
          {(props.workflowRole || props.workflowDesk) && (
            <span style={{ color: "var(--desk-text-dim)" }}>
              {[props.workflowRole, props.workflowDesk].filter(Boolean).join(" · ")}
            </span>
          )}
          {props.workflowAt && (
            <span style={{ color: "var(--desk-text-faint)", marginLeft: "auto" }}>
              {props.workflowAt}
            </span>
          )}
        </div>
        {props.workflowSummary && (
          <div style={{ color: "var(--desk-text-soft)", marginTop: 3, overflowWrap: "anywhere" }}>
            {props.workflowSummary}
          </div>
        )}
      </div>
    );
  }

  if (type === "user") {
    return (
      <div style={{ margin: "13px 0 5px", lineHeight: 1.55 }} data-block="user">
        <Glyph ch=">" color="var(--desk-accent)" />
        <span style={{ color: "var(--desk-text-soft)" }}>{props.text}</span>
      </div>
    );
  }

  if (type === "think") {
    return (
      <div style={{ margin: "9px 0" }} data-block="think">
        <Glyph ch="✻" color="var(--desk-text-muted)" />
        <span
          style={{
            color: "var(--desk-text-dim)",
            fontStyle: "italic",
            fontSize: 12,
          }}
        >
          {props.text}
        </span>
      </div>
    );
  }

  if (type === "say") {
    return (
      <div style={{ margin: "8px 0", lineHeight: 1.55 }} data-block="say">
        <Glyph ch="●" color="var(--desk-accent)" />
        <span style={{ color: "var(--desk-text)" }}>{props.text}</span>
      </div>
    );
  }

  if (type === "todos") {
    return (
      <div style={{ margin: "9px 0" }} data-block="todos">
        <div style={{ marginBottom: 4 }}>
          <Glyph ch="●" color="var(--desk-accent)" />
          <span style={{ color: "var(--desk-text)" }}>Update Todos</span>
        </div>
        <div
          style={{
            borderLeft: "1px solid var(--desk-border)",
            paddingLeft: 11,
            display: "flex",
            flexDirection: "column",
            gap: 3,
          }}
        >
          {(props.todos ?? []).map((t, i) => (
            <div key={i} style={{ fontSize: 12.5 }}>
              <Glyph ch={TODO_GLYPH[t.state]} color={TODO_COLOR[t.state]} />
              <span
                style={{
                  color:
                    t.state === "done"
                      ? "var(--desk-text-faint)"
                      : "var(--desk-text-soft)",
                  textDecoration:
                    t.state === "done" ? "line-through" : undefined,
                }}
              >
                {t.text}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (type === "tool") {
    const running = props.toolStatus === "running";
    return (
      <div style={{ margin: "8px 0", fontSize: 12.5 }} data-block="tool">
        <Glyph
          ch={running ? "◐" : "●"}
          color={running ? "var(--desk-warning)" : "var(--desk-success)"}
        />
        <span style={{ color: "var(--desk-text-soft)" }}>
          {props.toolName}
          <span style={{ color: "var(--desk-text-faint)" }}>
            ({props.toolArgs ?? ""})
          </span>
        </span>
        {props.toolStatus === "done" && props.toolSummary && (
          <div
            style={{ marginTop: 3, paddingLeft: 17, color: "var(--desk-success)" }}
          >
            ⎿ {props.toolSummary}
          </div>
        )}
      </div>
    );
  }

  if (type === "patch") {
    return (
      <div
        data-block="patch"
        style={{
          margin: "9px 0",
          border: "1px solid var(--desk-border-strong)",
          background: "var(--desk-topbar)",
          borderRadius: "var(--desk-radius-lg)",
          padding: "9px 12px",
        }}
      >
        <div
          style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}
        >
          <Glyph ch="⟳" color="var(--desk-text-dim)" />
          <span style={{ color: "var(--desk-text)", fontWeight: 600 }}>
            {props.patchTitle}
          </span>
          {props.patchId && <Pill tone="neutral">{props.patchId}</Pill>}
        </div>
        {props.affected && (
          <div
            style={{
              fontSize: 11,
              color: "var(--desk-text-dim)",
              marginBottom: 6,
            }}
          >
            受影响 · {props.affected}
          </div>
        )}
        {(props.diff ?? []).map((d, i) => (
          <div key={i} style={{ fontSize: 11.5, color: DIFF_COLOR[d.sign] }}>
            {d.sign} {d.text}
          </div>
        ))}
        <div style={{ marginTop: 6 }}>
          {props.reverted ? (
            <span style={{ color: "var(--desk-success)", fontSize: 11.5 }}>
              ✓ 整轮已撤销
            </span>
          ) : (
            <button
              onClick={props.onRevert}
              style={{
                fontFamily: "inherit",
                fontSize: 11.5,
                padding: "4px 10px",
                borderRadius: "var(--desk-radius-sm)",
                border: "1px solid var(--desk-danger)",
                background: "transparent",
                color: "var(--desk-danger)",
                cursor: "pointer",
              }}
            >
              ↺ 整轮撤销 Patch
            </button>
          )}
        </div>
      </div>
    );
  }

  // gate：权限弹窗。治理弱点强制常驻展开（R25）。
  return <GateBubble {...props} />;
}

function GateBubble(props: ChatBubbleProps) {
  const sideEffect: SideEffect = props.sideEffect ?? "none";
  // 治理弱点：gate 本身 + red 裁决 / 血统 / 真钱副作用 → 强制常驻展开。
  const weakness =
    props.governanceWeakness === true ||
    sideEffect === "realmoney" ||
    sideEffect === "external";
  // 仅「非弱点」的 gate 允许折叠；弱点类永远 expanded、不渲染折叠控件（R25）。
  const [collapsed, setCollapsed] = useState(false);
  const expanded = weakness ? true : !collapsed;

  const seTone = SIDE_EFFECT_TONE[sideEffect];

  return (
    <div
      data-block="gate"
      data-governance-weakness={weakness ? "true" : "false"}
      data-expanded={expanded ? "true" : "false"}
      style={{
        margin: "10px 0",
        border: "1px solid var(--desk-border-strong)",
        background: "var(--desk-card)",
        borderRadius: "var(--desk-radius-lg)",
        padding: "10px 12px",
      }}
    >
      <div
        style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}
      >
        <Glyph ch="⛔" color="var(--desk-danger)" />
        <span style={{ color: "var(--desk-text)", fontWeight: 600 }}>
          权限确认 · {props.gateTool}
        </span>
        <Pill tone={seTone} title="后端 tool_status 真值，不可前端伪造">
          {SIDE_EFFECT_LABEL[sideEffect]}
        </Pill>
        {/* 折叠控件仅对非治理弱点 gate 渲染——弱点类不可折叠藏起（R25）。 */}
        {!weakness && (
          <button
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "展开" : "折叠"}
            style={{
              marginLeft: "auto",
              fontFamily: "inherit",
              fontSize: 11,
              padding: "2px 8px",
              borderRadius: "var(--desk-radius-sm)",
              border: "1px solid var(--desk-border)",
              background: "transparent",
              color: "var(--desk-text-dim)",
              cursor: "pointer",
            }}
          >
            {collapsed ? "▾" : "▴"}
          </button>
        )}
      </div>
      {expanded && (
        <>
          {props.gateBlurb && (
            <div
              style={{
                fontSize: 11.5,
                color: "var(--desk-text-soft)",
                lineHeight: 1.55,
                marginBottom: 8,
              }}
            >
              {props.gateBlurb}
            </div>
          )}
          {weakness && (
            <div
              style={{
                fontSize: 11,
                color: "var(--desk-danger)",
                marginBottom: 8,
              }}
            >
              治理弱点：bypass 也不跳此门（权限轴 ⟂ 治理轴）
            </div>
          )}
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            <GateButton tone="success" onClick={props.onApproveOnce}>
              1. 批准本次
            </GateButton>
            <GateButton tone="warning" onClick={props.onApproveAlways}>
              2. 批准且不再问
            </GateButton>
            <GateButton tone="danger" onClick={props.onReject}>
              3. 拒绝 · 告诉怎么改
            </GateButton>
          </div>
        </>
      )}
    </div>
  );
}

function GateButton({
  tone,
  onClick,
  children,
}: {
  tone: DeskTone;
  onClick?: () => void;
  children: ReactNode;
}) {
  const c = `var(--desk-${tone})`;
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: "inherit",
        fontSize: 11.5,
        padding: "5px 11px",
        borderRadius: "var(--desk-radius-sm)",
        border: `1px solid ${c}`,
        background: "transparent",
        color: c,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
