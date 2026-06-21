import { type ReactNode } from "react";
import { ChatBubble, type ChatBubbleProps } from "./ChatBubble";

/**
 * Agent 对话容器（parseConsole.md §P2 left agent / agentDeck.md §③）。
 * 受控：blocks 由消费台传入，逐条 map 成 ChatBubble；composer 作为槽下挂。
 * 组件不持业务状态——滚动/折叠/对话流均由消费台或上层壳负责。
 */

/** 单条对话块：唯一 id + ChatBubble 全部 props。 */
export interface AgentBlock extends ChatBubbleProps {
  id: string;
}

export interface AgentChatProps {
  blocks: AgentBlock[];
  /** 顶部上下文标签（如「上下文 · 18.4k / 200k」）。 */
  contextLabel?: ReactNode;
  /** 底部 composer 槽（ChatComposer 实例由消费台注入）。 */
  composer?: ReactNode;
  /** 头部槽（mode 段控等），可选。 */
  header?: ReactNode;
}

export function AgentChat({
  blocks,
  contextLabel,
  composer,
  header,
}: AgentChatProps) {
  return (
    <div
      data-agent-chat
      style={{
        flex: 1,
        minHeight: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {header}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "10px 13px",
        }}
      >
        {contextLabel && (
          <div
            style={{
              fontSize: 10,
              color: "var(--desk-text-faint)",
              marginBottom: 8,
            }}
          >
            {contextLabel}
          </div>
        )}
        {blocks.map((b) => {
          const { id, ...rest } = b;
          return <ChatBubble key={id} {...rest} />;
        })}
      </div>
      {composer}
    </div>
  );
}
