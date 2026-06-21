import { type CSSProperties, type PointerEvent } from "react";
import { type NodeCat, catColor } from "./types";

/**
 * 端口圆点（DC §4「端口」）：14×14 圆 · border 1.5 · 类别色。
 * 受控：起连线 / hover 兼容性着色都由消费方决定（兼容色 props 传入，不内置业务）。
 * in 在 left:-7、out 在 right:-7（由父布局通过 anchor 定位，本组件只画圆 + 上抛事件）。
 */
export function NodePort({
  cat,
  side,
  /** 端口竖向锚点（相对节点卡顶部，= 38 + i*20）。 */
  top,
  /** hover 兼容性色（消费方算出兼容性后传入；undefined=不 hover）。 */
  hoverColor,
  /** pointerdown：出端口起连线 / 入端口可作放线落点。 */
  onPointerDown,
  /** hover 进入：父用于实时算兼容性。 */
  onPointerEnter,
  /** hover 离开。 */
  onPointerLeave,
  title,
}: {
  cat: NodeCat;
  side: "in" | "out";
  top: number;
  hoverColor?: string;
  onPointerDown?: (e: PointerEvent<HTMLDivElement>) => void;
  onPointerEnter?: (e: PointerEvent<HTMLDivElement>) => void;
  onPointerLeave?: (e: PointerEvent<HTMLDivElement>) => void;
  title?: string;
}) {
  const base = catColor(cat);
  const ring = hoverColor ?? base;
  const style: CSSProperties = {
    position: "absolute",
    top,
    [side === "in" ? "left" : "right"]: -7,
    width: 14,
    height: 14,
    borderRadius: "50%",
    border: `1.5px solid ${ring}`,
    background: hoverColor ?? "var(--desk-card)",
    cursor: "crosshair",
    boxSizing: "border-box",
    transform: "translateY(-50%)",
  };
  return (
    <div
      role="button"
      aria-label={`${side === "in" ? "入" : "出"}端口 ${title ?? ""}`.trim()}
      title={title}
      data-port-side={side}
      style={style}
      onPointerDown={onPointerDown}
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
    />
  );
}
