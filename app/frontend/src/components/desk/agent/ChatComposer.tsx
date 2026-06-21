import { type KeyboardEvent } from "react";
import { type PermissionMode } from "./ChatComposer.types";

/**
 * 底部输入区（agentDeck.md §D / parseConsole.md §P2 composer）。
 * 全受控：draft + onDraftChange + onSend 由消费台持有。
 *
 * permissionMode / sideEffect 是**受控展示值**（props，来自后端 tool_status），
 * composer 只渲染、绝不前端伪造或当作可编辑字段。
 */

export interface ChatComposerProps {
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
  placeholder?: string;
  /** 状态行展示：模型名 / 权限态 / 分支。 */
  model: string;
  permissionMode: PermissionMode;
  branch: string;
  /** 是否可发送（受控，消费台决定，如运行中禁用）。 */
  canSend?: boolean;
}

/** 权限态 glyph：auto ◐ / bypass ⏵ / ask ⏸。 */
const PERM_GLYPH: Record<PermissionMode, string> = {
  ask: "⏸",
  auto: "◐",
  bypass: "⏵",
};

const PERM_COLOR: Record<PermissionMode, string> = {
  ask: "var(--desk-success)",
  auto: "var(--desk-warning)",
  bypass: "var(--desk-danger)",
};

const PERM_LABEL: Record<PermissionMode, string> = {
  ask: "ask",
  auto: "auto",
  bypass: "bypass",
};

export function ChatComposer(props: ChatComposerProps) {
  const {
    draft,
    onDraftChange,
    onSend,
    placeholder = "> 给 agent 下达任务…",
    model,
    permissionMode,
    branch,
    canSend = true,
  } = props;

  const hasContent = draft.trim().length > 0;

  function handleKey(e: KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (canSend && hasContent) onSend();
    }
  }

  return (
    <div
      style={{
        flex: "none",
        borderTop: "1px solid var(--desk-border)",
        background: "var(--desk-bg)",
        padding: "10px 13px",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "flex-end",
          gap: 8,
          border: `1px solid ${
            hasContent ? "var(--desk-border-hover)" : "var(--desk-border)"
          }`,
          background: "var(--desk-topbar)",
          borderRadius: "var(--desk-radius-lg)",
          padding: "8px 11px",
        }}
      >
        <span
          aria-hidden
          style={{
            color: "var(--desk-accent)",
            fontWeight: 700,
            lineHeight: "20px",
          }}
        >
          {">"}
        </span>
        <textarea
          value={draft}
          onChange={(e) => onDraftChange(e.target.value)}
          onKeyDown={handleKey}
          placeholder={placeholder}
          rows={1}
          style={{
            flex: 1,
            resize: "none",
            border: "none",
            outline: "none",
            background: "transparent",
            color: "var(--desk-text)",
            fontFamily: "inherit",
            fontSize: 12.5,
            lineHeight: 1.5,
            maxHeight: 90,
          }}
        />
        <button
          onClick={() => {
            if (canSend && hasContent) onSend();
          }}
          disabled={!canSend || !hasContent}
          style={{
            fontFamily: "inherit",
            fontSize: 12,
            fontWeight: 700,
            padding: "4px 10px",
            borderRadius: "var(--desk-radius-sm)",
            border: "none",
            cursor: canSend && hasContent ? "pointer" : "not-allowed",
            opacity: canSend && hasContent ? 1 : 0.5,
            background: "var(--desk-accent)",
            color: "var(--desk-accent-ink)",
          }}
        >
          ↵ 发送
        </button>
      </div>
      {/* 状态行：受控展示值，permissionMode/sideEffect 不可编辑。 */}
      <div
        data-status-row
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          marginTop: 6,
          fontSize: 10,
          color: "var(--desk-text-faint)",
        }}
      >
        <span>⏺ {model}</span>
        <span aria-hidden>│</span>
        <span
          data-perm-mode={permissionMode}
          style={{ color: PERM_COLOR[permissionMode] }}
        >
          {PERM_GLYPH[permissionMode]} {PERM_LABEL[permissionMode]}
        </span>
        <span aria-hidden>│</span>
        <span>⎇ {branch}</span>
      </div>
    </div>
  );
}
