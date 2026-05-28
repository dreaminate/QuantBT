import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { trackEvent } from "../glossary/trackEvent";

/**
 * v0.8.5.1 · 首次 run 引导 banner
 *
 * 出现条件：localStorage 没标记 "qb-first-run-completed"
 * 5 步引导：登录 → 跑 demo → 看风险卡 → 改一个变量 → 看 Mode 2 教练
 */

interface Step {
  key: string;
  label: string;
  href: string;
  done?: boolean;
}

export function OnboardingBanner() {
  const [dismissed, setDismissed] = useState<boolean>(() => {
    try {
      return localStorage.getItem("qb-onboarding-dismissed") === "1";
    } catch {
      return false;
    }
  });
  const [firstRunDone, setFirstRunDone] = useState<boolean>(() => {
    try {
      return localStorage.getItem("qb-first-run-completed") === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    // 监听 cross-tab 变化
    const handler = () => {
      try {
        setFirstRunDone(localStorage.getItem("qb-first-run-completed") === "1");
      } catch { /* noop */ }
    };
    window.addEventListener("storage", handler);
    return () => window.removeEventListener("storage", handler);
  }, []);

  if (dismissed || firstRunDone) return null;

  const dismiss = () => {
    try { localStorage.setItem("qb-onboarding-dismissed", "1"); } catch { /* noop */ }
    setDismissed(true);
    trackEvent("run_detail_viewed", { from_page: "onboarding_dismissed" });
  };

  const steps: Step[] = [
    { key: "demo", label: "1. 跑一个 demo 回测", href: "/runs" },
    { key: "risk", label: "2. 看 RunDetail 风险卡", href: "/runs" },
    { key: "glossary", label: "3. 点指标 ⓘ 看解释", href: "/glossary" },
    { key: "fork", label: "4. Fork 改一个变量", href: "/strategies" },
    { key: "ide", label: "5. IDE 写自己的策略", href: "/ide" },
  ];

  return (
    <div
      className="cc-card"
      style={{
        marginBottom: 16,
        padding: 16,
        background: "linear-gradient(135deg, rgba(74,158,255,0.08), rgba(74,158,255,0.02))",
        borderLeft: "4px solid var(--cc-accent, #4a9eff)",
      }}
    >
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>👋 新手 5 步引导</div>
          <div className="cc-soft" style={{ fontSize: 12 }}>
            QuantBT 不是收益机器，是研究和风控工坊。先跑通流程，再看你能不能证明策略有效。
          </div>
        </div>
        <button
          type="button"
          className="cc-btn cc-btn--ghost cc-btn--sm"
          onClick={dismiss}
          title="不再显示"
        >
          ×
        </button>
      </div>
      <ol style={{ paddingLeft: 18, margin: 0, fontSize: 13 }}>
        {steps.map((s) => (
          <li key={s.key} style={{ marginBottom: 4 }}>
            <Link to={s.href} className="cc-mono" style={{ color: "var(--cc-accent)" }}>
              {s.label} →
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

export default OnboardingBanner;

/** 在 RunDetail 跑出第一个成功 run 后调，标记 onboarding 完成。 */
export function markFirstRunCompleted(): void {
  try { localStorage.setItem("qb-first-run-completed", "1"); } catch { /* noop */ }
}
