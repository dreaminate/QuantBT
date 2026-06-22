/**
 * v0.8.4 Day 3 · 字段 ⓘ 按钮 + 渐进披露 popover。
 *
 * 设计：
 * - 默认只显示一个轻量 ⓘ icon（inline，不破坏冻结页布局）
 * - 点击 → 弹 popover 显示 L1 + L2（hover tooltip + 公式例子）
 * - popover 底部 "查看 L3 / L4" 按需展开
 * - 404 / 词条未生成 → fallback 文案 "该词条还未生成"
 *
 * 严格隔离：本组件不依赖任何 jq-* 样式，所有 className 用独立 ig-* (info-glossary)
 * 前缀；inline style 兜底，无需新 CSS 文件。
 */

import { useEffect, useRef, useState } from "react";
import { trackEvent } from "./trackEvent";
import { useGlossaryTerm } from "./useGlossaryTerm";

interface Props {
  slug: string | null;
  /** label 之后的间距文字方向（zh: 中文 label 后紧贴）*/
  ariaLabel?: string;
}

export function GlossaryInfoButton({ slug, ariaLabel }: Props) {
  const [open, setOpen] = useState(false);
  const [showDeep, setShowDeep] = useState(false);
  const boxRef = useRef<HTMLDivElement | null>(null);
  const { data, loading, error } = useGlossaryTerm(open ? slug : null);

  // 点 popover 外面收起
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) {
        setOpen(false);
        setShowDeep(false);
      }
    };
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  // slug 不存在 → 不渲染（保持冻结页原貌）
  if (!slug) return null;

  return (
    <span ref={boxRef} style={{ position: "relative", display: "inline-block", marginLeft: 4 }}>
      <button
        type="button"
        aria-label={ariaLabel ?? `查看 ${slug} 词条`}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          setOpen((v) => {
            const next = !v;
            if (next && slug) trackEvent("glossary_term_viewed", { slug, depth: "l2", opened_from: "rundetail_card" });
            return next;
          });
          if (open) setShowDeep(false);
        }}
        style={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 14,
          height: 14,
          padding: 0,
          border: "1px solid currentColor",
          borderRadius: "50%",
          fontSize: 9,
          lineHeight: 1,
          fontFamily: "inherit",
          background: "transparent",
          color: "var(--cc-dim, #888)",
          cursor: "pointer",
          opacity: 0.6,
          verticalAlign: "middle",
        }}
        title="点击查看该指标的术语解释"
      >
        i
      </button>
      {open && (
        <div
          role="dialog"
          style={{
            position: "absolute",
            zIndex: 999,
            top: "calc(100% + 6px)",
            left: 0,
            minWidth: 320,
            maxWidth: 480,
            background: "var(--cc-bg-elev, #1a1f2a)",
            color: "var(--cc-text, #e6edf3)",
            border: "1px solid var(--cc-border, rgba(255,255,255,0.12))",
            borderRadius: 6,
            padding: 12,
            boxShadow: "0 6px 20px rgba(0,0,0,0.4)",
            fontSize: 12,
            lineHeight: 1.5,
            textAlign: "left",
            fontWeight: "normal",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {loading && <div style={{ opacity: 0.7 }}>加载中…</div>}
          {error === "not_found" && (
            <div style={{ opacity: 0.7 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>{slug}</div>
              <div style={{ fontStyle: "italic", color: "var(--cc-dim, #888)" }}>
                该词条暂未收录，内容完善中。
              </div>
            </div>
          )}
          {data && (
            <>
              <div style={{ fontWeight: 600, marginBottom: 6 }}>{data.frontmatter.display}</div>
              {data.l1 && (
                <div style={{ marginBottom: 8, color: "var(--cc-text, #e6edf3)" }}>
                  <span style={{ fontSize: 10, color: "var(--cc-dim, #888)", marginRight: 4 }}>L1</span>
                  {data.l1}
                </div>
              )}
              {data.l2 && (
                <div style={{ marginBottom: 8 }}>
                  <span style={{ fontSize: 10, color: "var(--cc-dim, #888)", marginRight: 4 }}>L2</span>
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      fontFamily: "inherit",
                      fontSize: 11,
                      margin: 0,
                      maxHeight: 200,
                      overflow: "auto",
                    }}
                  >
                    {data.l2}
                  </pre>
                </div>
              )}
              {!showDeep && (data.l3 || data.l4) && (
                <button
                  type="button"
                  onClick={() => {
                    setShowDeep(true);
                    if (slug) trackEvent("risk_metric_expanded", { slug, depth: "l3l4", opened_from: "glossary_popover" });
                  }}
                  style={{
                    background: "transparent",
                    border: "1px solid var(--cc-border, rgba(255,255,255,0.2))",
                    borderRadius: 4,
                    padding: "2px 8px",
                    fontSize: 11,
                    color: "inherit",
                    cursor: "pointer",
                  }}
                >
                  查看 L3 / L4 ↓
                </button>
              )}
              {showDeep && data.l3 && (
                <div style={{ marginTop: 8 }}>
                  <span style={{ fontSize: 10, color: "var(--cc-dim, #888)" }}>L3 业界阈值与误区</span>
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      fontFamily: "inherit",
                      fontSize: 11,
                      margin: "2px 0 8px 0",
                      maxHeight: 240,
                      overflow: "auto",
                    }}
                  >
                    {data.l3}
                  </pre>
                </div>
              )}
              {showDeep && data.l4 && (
                <div>
                  <span style={{ fontSize: 10, color: "var(--cc-dim, #888)" }}>L4 延伸阅读</span>
                  <pre
                    style={{
                      whiteSpace: "pre-wrap",
                      fontFamily: "inherit",
                      fontSize: 11,
                      margin: "2px 0 0 0",
                      maxHeight: 200,
                      overflow: "auto",
                    }}
                  >
                    {data.l4}
                  </pre>
                </div>
              )}
              {data.frontmatter.sources && data.frontmatter.sources.length > 0 && (
                <div
                  style={{
                    marginTop: 8,
                    paddingTop: 6,
                    borderTop: "1px solid var(--cc-border, rgba(255,255,255,0.08))",
                    fontSize: 10,
                    color: "var(--cc-dim, #888)",
                  }}
                >
                  来源: {data.frontmatter.sources.slice(0, 2).join(" · ")}
                </div>
              )}
              <div style={{ marginTop: 8, textAlign: "right" }}>
                <a
                  href={`/glossary/${slug}`}
                  style={{
                    fontSize: 11,
                    color: "var(--cc-accent, #4a9eff)",
                    textDecoration: "none",
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  📖 打开专页 →
                </a>
              </div>
            </>
          )}
        </div>
      )}
    </span>
  );
}
