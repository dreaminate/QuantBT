import { type CSSProperties, type PointerEvent } from "react";
import { StatusDot, Pill } from "../primitives";
import { NodePort } from "./NodePort";
import {
  type NodeView,
  type PortRef,
  type Compat,
  catColor,
  stateColor,
  isPulsing,
  compatColor,
} from "./types";
import { PORT_TOP_BASE, PORT_TOP_STEP } from "./geometry";

/**
 * 节点卡（DC §4「节点卡」，受控）。
 * head（7×7 类别色点 + 标题省略 + 可选 🔒lock + 6×6 state 圆点，running 用 StatusDot pulse）
 * + body（行 + 可选 badge）+ 进/出端口（NodePort）。选中态 border var(--desk-accent)。
 * 引擎只渲染 + 上抛事件：拖拽/选中/连线/lock 规则由消费方处理。
 */
export function NodeCard({
  node,
  selected = false,
  /** 当前 hover 的入端口兼容性（{ port → compat }），用于端口着色。 */
  portCompat,
  onHeadPointerDown,
  onSelect,
  onPortPointerDown,
  onPortPointerEnter,
  onPortPointerLeave,
}: {
  node: NodeView;
  selected?: boolean;
  portCompat?: Record<string, Compat>;
  /** head pointerdown：进入拖拽（消费方在 locked 时自行 return）。 */
  onHeadPointerDown?: (id: string, e: PointerEvent<HTMLDivElement>) => void;
  /** click：单选该节点 + 开 Inspector。 */
  onSelect?: (id: string) => void;
  /** 端口 pointerdown：起/落连线。 */
  onPortPointerDown?: (ref: PortRef, side: "in" | "out", e: PointerEvent<HTMLDivElement>) => void;
  onPortPointerEnter?: (ref: PortRef, side: "in" | "out") => void;
  onPortPointerLeave?: (ref: PortRef, side: "in" | "out") => void;
}) {
  const cat = catColor(node.cat);
  const portRows = Math.max(node.ins.length, node.outs.length);
  const minH = PORT_TOP_BASE + Math.max(0, portRows - 1) * PORT_TOP_STEP + 16;

  const wrapStyle: CSSProperties = {
    position: "absolute",
    left: node.x,
    top: node.y,
    width: node.w,
    minHeight: minH,
    boxSizing: "border-box",
    background: "var(--desk-card)",
    border: `1.5px solid ${selected ? "var(--desk-accent)" : "var(--desk-node-border)"}`,
    borderRadius: "var(--desk-radius-lg)",
    boxShadow: selected ? "var(--desk-node-shadow-sel)" : "var(--desk-node-shadow)",
    color: "var(--desk-text)",
  };

  const headStyle: CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 7,
    padding: "5px 9px",
    background: selected ? "var(--desk-hover)" : "var(--desk-node-head)",
    borderTopLeftRadius: "var(--desk-radius-lg)",
    borderTopRightRadius: "var(--desk-radius-lg)",
    cursor: "grab",
  };

  return (
    <div data-node-id={node.id} style={wrapStyle} onClick={() => onSelect?.(node.id)}>
      {/* head */}
      <div
        data-node-head={node.id}
        style={headStyle}
        onPointerDown={(e) => onHeadPointerDown?.(node.id, e)}
      >
        {/* 7×7 类别色点 */}
        <span
          aria-hidden
          style={{
            width: 7,
            height: 7,
            borderRadius: 2,
            background: cat,
            flex: "none",
          }}
        />
        {/* 标题省略 */}
        <span
          style={{
            flex: 1,
            minWidth: 0,
            fontSize: 11.5,
            fontWeight: 600,
            color: "var(--desk-text)",
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {node.title}
        </span>
        {/* 可选 🔒 lock */}
        {node.locked && (
          <span aria-label="locked" title="不可删除/绕过" style={{ flex: "none", fontSize: 11 }}>
            🔒
          </span>
        )}
        {/* 6×6 state 圆点（running pulse） */}
        <StatusDot color={stateColor(node.state)} pulse={isPulsing(node.state)} size={6} />
      </div>

      {/* body */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2, padding: "6px 9px" }}>
        {node.lines.map((line, i) => (
          <span
            key={i}
            style={{
              fontSize: 10,
              color: "var(--desk-node-line)",
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {line}
          </span>
        ))}
        {node.badge && (
          <span style={{ marginTop: 2 }}>
            <Pill tone="info">{node.badge}</Pill>
          </span>
        )}
      </div>

      {/* 入端口 */}
      {node.ins.map((p, i) => (
        <NodePort
          key={p.id}
          cat={node.cat}
          side="in"
          top={PORT_TOP_BASE + i * PORT_TOP_STEP}
          hoverColor={portCompat?.[p.id] ? compatColor(portCompat[p.id]) : undefined}
          title={p.name}
          onPointerDown={(e) => onPortPointerDown?.({ node: node.id, port: p.id }, "in", e)}
          onPointerEnter={() => onPortPointerEnter?.({ node: node.id, port: p.id }, "in")}
          onPointerLeave={() => onPortPointerLeave?.({ node: node.id, port: p.id }, "in")}
        />
      ))}

      {/* 出端口 */}
      {node.outs.map((p, i) => (
        <NodePort
          key={p.id}
          cat={node.cat}
          side="out"
          top={PORT_TOP_BASE + i * PORT_TOP_STEP}
          title={p.name}
          onPointerDown={(e) => onPortPointerDown?.({ node: node.id, port: p.id }, "out", e)}
          onPointerEnter={() => onPortPointerEnter?.({ node: node.id, port: p.id }, "out")}
          onPointerLeave={() => onPortPointerLeave?.({ node: node.id, port: p.id }, "out")}
        />
      ))}
    </div>
  );
}
