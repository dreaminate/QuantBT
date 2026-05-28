import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

/**
 * v0.8.5 · Glossary 词典首页 (/glossary)
 *
 * 按 category 分组显示所有词条。
 */

interface GlossarySummary {
  slug: string;
  display: string;
  level: string;
  category: string;
  aliases: string[];
  levels_available: string[];
}

const CATEGORY_LABEL: Record<string, string> = {
  metric: "📊 绩效指标",
  factor: "🧮 因子信号",
  model: "🔬 模型 / CV",
  risk: "⚠️ 风险",
  execution: "⚡ 执行",
  data: "📦 数据",
  portfolio: "📁 组合",
};

const LEVEL_COLOR: Record<string, string> = {
  beginner: "#3eb37a",
  intermediate: "#c98a14",
  advanced: "#cc3344",
};

export function GlossaryIndexPage() {
  const [terms, setTerms] = useState<GlossarySummary[]>([]);
  const [filter, setFilter] = useState("");

  useEffect(() => {
    fetch("/api/glossary")
      .then((r) => r.json())
      .then((d) => setTerms(Array.isArray(d) ? d : []))
      .catch(() => setTerms([]));
  }, []);

  const filtered = terms.filter((t) =>
    !filter
      ? true
      : t.display.toLowerCase().includes(filter.toLowerCase())
        || t.slug.toLowerCase().includes(filter.toLowerCase())
        || t.aliases.some((a) => a.toLowerCase().includes(filter.toLowerCase())),
  );

  const byCategory: Record<string, GlossarySummary[]> = {};
  for (const t of filtered) {
    if (!byCategory[t.category]) byCategory[t.category] = [];
    byCategory[t.category].push(t);
  }

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{"// 量化术语词典"}</h1>
          <div className="cc-soft">{terms.length} 条 baseline · L1 一句话 / L2 公式 / L3 阈值与误区 / L4 延伸阅读</div>
        </div>
        <div className="cc-page-actions">
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="搜索 slug / 中文 / 别名..."
            className="cc-input"
            style={{ width: 240 }}
          />
        </div>
      </div>

      {Object.keys(CATEGORY_LABEL).map((cat) => {
        const items = byCategory[cat];
        if (!items || items.length === 0) return null;
        return (
          <section key={cat} style={{ marginBottom: 24 }}>
            <div className="cc-section-title">{CATEGORY_LABEL[cat]} · {items.length} 条</div>
            <div className="cc-grid">
              {items.map((t) => (
                <Link
                  key={t.slug}
                  to={`/glossary/${t.slug}`}
                  className="cc-card cc-card--hover"
                  style={{ display: "block", textDecoration: "none" }}
                >
                  <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
                    <div className="cc-card-title" style={{ margin: 0 }}>{t.display}</div>
                    <span
                      className="cc-chip"
                      style={{ background: LEVEL_COLOR[t.level], color: "#fff", fontSize: 10 }}
                    >
                      {t.level}
                    </span>
                  </div>
                  <div className="cc-mono cc-dim" style={{ fontSize: 11 }}>{t.slug}</div>
                  {t.aliases.length > 0 && (
                    <div className="cc-soft" style={{ fontSize: 11, marginTop: 4 }}>
                      别名: {t.aliases.slice(0, 3).join(" · ")}
                      {t.aliases.length > 3 && ` +${t.aliases.length - 3}`}
                    </div>
                  )}
                  <div style={{ marginTop: 6 }}>
                    {t.levels_available.map((l) => (
                      <span
                        key={l}
                        className="cc-chip"
                        style={{ marginRight: 2, fontSize: 9 }}
                      >
                        {l}
                      </span>
                    ))}
                  </div>
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </>
  );
}

export default GlossaryIndexPage;
