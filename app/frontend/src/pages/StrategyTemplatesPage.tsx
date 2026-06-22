import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authFetch, getStoredUser } from "../lib/auth";

/**
 * v0.9.3 · /templates · 策略模板广场
 *
 * 列出 3 个内置模板，一键 fork 到 IDE 名下。
 */

interface TemplateSummary {
  template_id: string;
  name: string;
  asset_class: string;
  description: string;
  expected_metrics: Record<string, number>;
  code_length: number;
}

const ASSET_COLOR: Record<string, string> = {
  crypto_perp: "#f0b90b",
  crypto_spot: "#4a9eff",
  equity_cn: "#cc3344",
};

export function StrategyTemplatesPage() {
  const me = getStoredUser();
  const navigate = useNavigate();
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [forking, setForking] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/strategies/templates")
      .then((r) => r.json())
      .then((d) => setTemplates(Array.isArray(d) ? d : []))
      .catch(() => setTemplates([]));
  }, []);

  const fork = async (t: TemplateSummary) => {
    if (!me) { alert("请先登录"); return; }
    const name = prompt("Fork 后的策略名 (字母数字 - _):", `${t.template_id}_fork`);
    if (!name) return;
    setForking(t.template_id);
    try {
      const r = await authFetch(`/api/strategies/templates/${t.template_id}/fork_to_ide`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({ detail: "fork 失败" }));
        alert(err.detail || "fork 失败");
        return;
      }
      const data = await r.json();
      navigate(data.ide_url || "/ide");
    } finally {
      setForking(null);
    }
  };

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{"// 策略模板广场"}</h1>
          <div className="cc-soft">
            一键 fork 模板进 IDE 修改 + 跑沙箱 · 每个模板含 expected_metrics 防过拟合参照
          </div>
        </div>
      </div>

      <div className="cc-grid">
        {templates.map((t) => (
          <div key={t.template_id} className="cc-card" style={{ padding: 20 }}>
            <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
              <div className="cc-card-title">{t.name}</div>
              <span className="cc-chip" style={{ background: ASSET_COLOR[t.asset_class], color: "#fff", fontSize: 11 }}>
                {t.asset_class}
              </span>
            </div>
            <div className="cc-mono cc-dim" style={{ fontSize: 11, marginBottom: 8 }}>{t.template_id}</div>
            <div className="cc-soft" style={{ fontSize: 13, marginBottom: 12 }}>{t.description}</div>

            <div className="cc-section-title" style={{ fontSize: 11, marginBottom: 4 }}>预期指标 (复现时参照)</div>
            <ul style={{ paddingLeft: 18, fontSize: 11, color: "var(--cc-dim, #888)", marginBottom: 12 }}>
              {Object.entries(t.expected_metrics).map(([k, v]) => (
                <li key={k}>{k}: {typeof v === "number" ? v.toFixed(2) : String(v)}</li>
              ))}
            </ul>

            <div className="cc-row" style={{ justifyContent: "space-between", marginTop: 12 }}>
              <span className="cc-dim" style={{ fontSize: 11 }}>{t.code_length} 字符</span>
              <button
                type="button"
                className="cc-btn cc-btn--accent cc-btn--sm"
                disabled={forking === t.template_id}
                onClick={() => fork(t)}
              >
                {forking === t.template_id ? "forking..." : "↪ Fork 到我的 IDE"}
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="cc-card" style={{ marginTop: 16, padding: 16 }}>
        <div className="cc-section-title">使用提示</div>
        <ul className="cc-soft" style={{ fontSize: 13, paddingLeft: 18 }}>
          <li>Fork 后会自动在你 IDE 名下创建一份副本，原模板不变。</li>
          <li>沙箱 wallclock ≤ 30s，模板代码已优化在限制内跑完。</li>
          <li>跑完后看 risk preview chip 判断可信度，PBO/DSR 不达标先别 promote。</li>
          <li>有问题去 /chat 打开 Mode 2 对话台，会自动绑定你的 active_run 上下文。</li>
        </ul>
      </div>
    </>
  );
}

export default StrategyTemplatesPage;
