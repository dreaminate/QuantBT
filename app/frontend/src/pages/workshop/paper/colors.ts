import { type DeskColor } from "./types";

/**
 * 语义色 → --desk-* token（唯一 hex 出口在 theme-cc.css；此处只引用 var）。
 * paper 台 accent 已由 [data-desk="paper"] 设为绿，故 success=放行/运行中绿。
 */
const MAP: Record<DeskColor, string> = {
  up: "var(--desk-success)",
  down: "var(--desk-danger)",
  warn: "var(--desk-warning)",
  info: "var(--desk-info)",
  flat: "var(--desk-text-soft)",
  dim: "var(--desk-text-dim)",
  muted: "var(--desk-text-muted)",
};

export function color(c: DeskColor): string {
  return MAP[c];
}

/** 涨绿跌红平灰（带 0 判定）。 */
export function pnlColor(v: number): DeskColor {
  return v > 0 ? "up" : v < 0 ? "down" : "flat";
}

/** ≥0 绿 / <0 红（无平态，用于累计/超额）。 */
export function signColor(v: number): DeskColor {
  return v >= 0 ? "up" : "down";
}

/** 带符号百分比格式化。 */
export function pct(v: number, digits = 1): string {
  return (v >= 0 ? "+" : "") + (v * 100).toFixed(digits) + "%";
}
