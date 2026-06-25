import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { trackEvent } from "./trackEvent";

/**
 * v0.8.6.1 · RunDetail 顶部主动建议条
 *
 * 当 risk_summary 含 flag 时，浮出一条诊断入口。
 * 严格隔离 inline style，绑定到冻结页前不破坏布局。
 */

interface Suggestion {
  severity: "info" | "warning" | "critical";
  headline: string;
  detail: string;
  suggested_chat_query: string;
  related_glossary: string[];
  one_variable_hint: string | null;
}

interface Props {
  runId: string;
}

const SEV_PRESET = {
  info: { color: "#4a9eff", bg: "rgba(74,158,255,0.08)" },
  warning: { color: "#c98a14", bg: "rgba(201,138,20,0.08)" },
  critical: { color: "#cc3344", bg: "rgba(204,51,68,0.08)" },
} as const;

export function CoachSuggestionBanner({ runId }: Props) {
  const [sugg, setSugg] = useState<Suggestion | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!runId) return;
    fetch(`/api/runs/${runId}/coach_suggestion`)
      .then((r) => r.json())
      .then((data) => setSugg(data?.suggestion ?? null))
      .catch(() => setSugg(null));
  }, [runId]);

  if (!sugg || dismissed) return null;

  const preset = SEV_PRESET[sugg.severity];
  const chatHref = `/chat?run=${encodeURIComponent(runId)}&q=${encodeURIComponent(sugg.suggested_chat_query)}`;

  return (
    <div
      style={{
        margin: "12px 0",
        padding: 12,
        background: preset.bg,
        borderLeft: `4px solid ${preset.color}`,
        borderRadius: 4,
        fontSize: 13,
        fontFamily: "inherit",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ flex: 1, marginRight: 12 }}>
          <div style={{ fontWeight: 600, color: preset.color, marginBottom: 4 }}>
            {sugg.headline}
          </div>
          <div style={{ color: "var(--cc-text, #e6edf3)", marginBottom: 6 }}>{sugg.detail}</div>
          {sugg.one_variable_hint && (
            <div style={{ marginBottom: 6 }}>
              <span className="cc-dim" style={{ fontSize: 11 }}>下一次只改一个变量：</span>
              <span style={{ fontSize: 12 }}>{sugg.one_variable_hint}</span>
            </div>
          )}
          {sugg.related_glossary.length > 0 && (
            <div style={{ marginBottom: 4 }}>
              <span className="cc-dim" style={{ fontSize: 11 }}>相关词条：</span>
              {sugg.related_glossary.map((slug) => (
                <Link
                  key={slug}
                  to={`/glossary/${slug}`}
                  className="cc-chip"
                  style={{ fontSize: 10, marginLeft: 4, textDecoration: "none" }}
                  onClick={() => trackEvent("glossary_term_viewed", { slug, opened_from: "coach_banner" })}
                >
                  {slug}
                </Link>
              ))}
            </div>
          )}
          <div style={{ marginTop: 8 }}>
            <Link
              to={chatHref}
              className="cc-btn cc-btn--accent cc-btn--sm"
              onClick={() => trackEvent("risk_metric_expanded", { from: "coach_banner", run_id: runId })}
            >
              打开诊断台分析此 run →
            </Link>
          </div>
        </div>
        <button
          type="button"
          className="cc-btn cc-btn--ghost cc-btn--sm"
          onClick={() => setDismissed(true)}
          title="不再显示本次"
          style={{ flexShrink: 0 }}
        >
          ×
        </button>
      </div>
    </div>
  );
}

export default CoachSuggestionBanner;
