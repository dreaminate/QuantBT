import { type CSSProperties } from "react";

/**
 * DC `style="{{ s }}"` 动态 CSS 字符串 → React 内联 style 对象（G1 d11d1426）。
 * 对齐 DC support.js cssToObj 语义：kebab→camel；`--var` 自定义属性原样保留。
 */
export function cssToObj(css: string): CSSProperties {
  const out: Record<string, string> = {};
  for (const decl of css.split(";")) {
    const i = decl.indexOf(":");
    if (i === -1) continue;
    const rawKey = decl.slice(0, i).trim();
    const val = decl.slice(i + 1).trim();
    if (!rawKey || !val) continue;
    const key = rawKey.startsWith("--")
      ? rawKey
      : rawKey.replace(/-([a-z])/g, (_m, c: string) => c.toUpperCase());
    out[key] = val;
  }
  return out as CSSProperties;
}
