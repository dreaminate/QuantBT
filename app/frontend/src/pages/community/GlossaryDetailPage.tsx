import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useGlossaryTerm } from "../../features/glossary/useGlossaryTerm";
import { trackEvent } from "../../features/glossary/trackEvent";

/**
 * v0.8.5 · Glossary 词条独立全文页 (/glossary/:slug)
 *
 * patch2 §C W3 / patch1 §D Mode 2 教学层：
 * - 全文 L1+L2+L3+L4 渲染
 * - related 词条侧栏
 * - frontmatter 元数据卡（公式、典型范围、来源）
 * - 该指标在用户历史 runs 的分布（v0.8.5.1 通过 API 接入）
 */

interface RunUsage {
  count: number;
  buckets: { range: string; users: number }[];
}

export function GlossaryDetailPage() {
  const { slug = "" } = useParams<{ slug: string }>();
  const { data, loading, error } = useGlossaryTerm(slug);
  const [usage, setUsage] = useState<RunUsage | null>(null);

  useEffect(() => {
    if (slug) trackEvent("glossary_term_viewed", { slug, depth: "full_page", opened_from: "direct_url" });
  }, [slug]);

  useEffect(() => {
    if (!slug) return;
    fetch(`/api/glossary/${encodeURIComponent(slug)}/usage_in_runs`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setUsage)
      .catch(() => { /* noop */ });
  }, [slug]);

  if (loading) return <div className="cc-card cc-dim">加载中...</div>;
  if (error === "not_found") {
    return (
      <div className="cc-card" style={{ padding: 24 }}>
        <h1>词条不存在: {slug}</h1>
        <Link to="/glossary" className="cc-btn cc-btn--ghost">← 返回词典</Link>
      </div>
    );
  }
  if (!data) return <div className="cc-card cc-dim">无数据</div>;

  const fm = data.frontmatter;

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{fm.display}</h1>
          <div className="cc-soft">
            <span className="cc-chip" style={{ marginRight: 6 }}>{fm.category}</span>
            <span className="cc-chip" style={{ marginRight: 6 }}>{fm.level}</span>
            {fm.unit && <span className="cc-mono cc-dim">单位 {fm.unit}</span>}
          </div>
        </div>
        <div className="cc-page-actions">
          <Link to="/glossary" className="cc-btn cc-btn--ghost cc-btn--sm">← 词典首页</Link>
        </div>
      </div>

      <div className="cc-row" style={{ alignItems: "flex-start", gap: 24 }}>
        <main style={{ flex: 1, minWidth: 0 }}>
          {fm.formula_latex && (
            <div className="cc-card" style={{ marginBottom: 16, padding: 16 }}>
              <div className="cc-section-title">公式</div>
              <pre className="cc-mono" style={{ fontSize: 14, overflow: "auto", margin: 0 }}>
                {fm.formula_latex}
              </pre>
              {fm.typical_range && (
                <div className="cc-soft" style={{ marginTop: 6, fontSize: 12 }}>
                  典型范围 [{fm.typical_range[0]}, {fm.typical_range[1]}]
                </div>
              )}
            </div>
          )}

          {data.l1 && (
            <section className="cc-card" style={{ marginBottom: 16, padding: 16 }}>
              <div className="cc-section-title">L1 · 一句话</div>
              <p style={{ margin: 0, fontSize: 16 }}>{data.l1}</p>
            </section>
          )}

          {data.l2 && (
            <section className="cc-card" style={{ marginBottom: 16, padding: 16 }}>
              <div className="cc-section-title">L2 · 公式与例子</div>
              <pre className="cc-mono" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 14, margin: 0 }}>
                {data.l2}
              </pre>
            </section>
          )}

          {data.l3 && (
            <section className="cc-card" style={{ marginBottom: 16, padding: 16 }}>
              <div className="cc-section-title">L3 · 业界阈值与误区</div>
              <pre className="cc-mono" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 14, margin: 0 }}>
                {data.l3}
              </pre>
            </section>
          )}

          {data.l4 && (
            <section className="cc-card" style={{ marginBottom: 16, padding: 16 }}>
              <div className="cc-section-title">L4 · 延伸阅读</div>
              <pre className="cc-mono" style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", fontSize: 14, margin: 0 }}>
                {data.l4}
              </pre>
            </section>
          )}
        </main>

        <aside style={{ width: 280, flexShrink: 0 }}>
          {fm.related && fm.related.length > 0 && (
            <div className="cc-card" style={{ marginBottom: 16, padding: 16 }}>
              <div className="cc-section-title">相关词条</div>
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {fm.related.map((r) => (
                  <li key={r} style={{ marginBottom: 4 }}>
                    <Link to={`/glossary/${r}`} className="cc-mono" style={{ color: "var(--cc-accent)" }}>
                      → {r}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {fm.aliases && fm.aliases.length > 0 && (
            <div className="cc-card" style={{ marginBottom: 16, padding: 16 }}>
              <div className="cc-section-title">别名</div>
              <div>
                {fm.aliases.map((a) => (
                  <span key={a} className="cc-chip" style={{ marginRight: 4, marginBottom: 4, fontSize: 11 }}>{a}</span>
                ))}
              </div>
            </div>
          )}

          {fm.sources && fm.sources.length > 0 && (
            <div className="cc-card" style={{ padding: 16 }}>
              <div className="cc-section-title">学术来源</div>
              <ol style={{ paddingLeft: 18, margin: 0, fontSize: 12 }}>
                {fm.sources.map((s, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>{s}</li>
                ))}
              </ol>
            </div>
          )}

          {usage && usage.count > 0 && (
            <div className="cc-card" style={{ padding: 16, marginTop: 16 }}>
              <div className="cc-section-title">我的 runs 分布</div>
              <div className="cc-soft" style={{ fontSize: 11, marginBottom: 6 }}>
                {usage.count} 次 run 含此指标
              </div>
              {usage.buckets.map((b) => (
                <div key={b.range} className="cc-row" style={{ justifyContent: "space-between", fontSize: 11 }}>
                  <span className="cc-mono">{b.range}</span>
                  <span>{b.users}</span>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>
    </>
  );
}

export default GlossaryDetailPage;
