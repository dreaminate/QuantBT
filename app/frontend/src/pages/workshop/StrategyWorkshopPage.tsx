import { useState } from "react";

/**
 * 策略工坊 · Claude Code 风
 * /workshop
 *
 * 自然语言一句话 → StrategyGoal slot-fill；右侧 JSON 实时预览（终端感）。
 */

export function StrategyWorkshopPage() {
  const [text, setText] = useState(
    "我想做 A股 周频 选股策略，目标信息比率，回撤控制在 20%，单标的不超过 5%。",
  );
  const [goal, setGoal] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      const res = await fetch("/api/agent/slot_fill", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setGoal(await res.json());
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">
            <span className="cc-prompt">$</span>strategy-workshop
          </h1>
          <p className="cc-page-subtitle">
            一句话需求 → StrategyGoal（Pydantic schema · M1）。关键词规则提取 · 三档 cost_model · A股/加密一致性硬约束自动校验。
          </p>
        </div>
      </div>

      <div className="cc-grid-lg" style={{ gridTemplateColumns: "1fr 1fr" }}>
        <section className="cc-card">
          <div className="cc-section-title" style={{ marginBottom: 8 }}>
            // input · 一句话需求
          </div>
          <textarea
            className="cc-textarea"
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            placeholder="比如：加密永续 BTC/ETH 趋势策略，允许做空，杠杆 3x"
          />
          <div className="cc-row" style={{ marginTop: 12, justifyContent: "space-between" }}>
            <span className="cc-dim" style={{ fontSize: 11 }}>
              关键词识别：A股/加密/永续/选股/趋势 · 杠杆/回撤/单标的 数值自动提取
            </span>
            <button type="button" className="cc-btn cc-btn--accent" onClick={submit} disabled={busy}>
              {busy ? "解析中…" : "解析为 StrategyGoal ↵"}
            </button>
          </div>
          {error && (
            <div className="cc-chip cc-chip--danger" style={{ marginTop: 12 }}>
              {error}
            </div>
          )}
        </section>

        <section className="cc-card">
          <div className="cc-section-title" style={{ marginBottom: 8 }}>
            // output · StrategyGoal JSON
          </div>
          {!goal ? (
            <div className="cc-dim" style={{ fontSize: 12 }}>
              点击「解析」后这里会显示 Pydantic 校验通过的 StrategyGoal 对象。
            </div>
          ) : (
            <pre className="cc-code" style={{ maxHeight: 480, overflow: "auto" }}>
              {JSON.stringify(goal, null, 2)}
            </pre>
          )}
        </section>
      </div>

      <section className="cc-section" style={{ marginTop: 24 }}>
        <div className="cc-section-header">
          <h2 className="cc-section-title">// 内置预设</h2>
        </div>
        <div className="cc-grid">
          <PresetCard
            name="A股 周频选股 Top 10%"
            ac="equity_cn"
            chipKind="info"
            desc="aiquantclaw 风格 · 截面排序 · IR 目标 · 单标的 5% · 回撤 20%"
            onClick={() => setText("A股 周频 选股 Top 10%，目标 IR，回撤 20%，单标的 5%")}
          />
          <PresetCard
            name="加密永续日频趋势"
            ac="crypto_perp"
            chipKind="warning"
            desc="资金费率成本入账 · 永续多空 · 杠杆 3x · Calmar 目标"
            onClick={() => setText("加密永续 日频 趋势，允许做空，杠杆 3x，目标 Calmar")}
          />
        </div>
      </section>
    </>
  );
}

function PresetCard({
  name,
  ac,
  chipKind,
  desc,
  onClick,
}: {
  name: string;
  ac: string;
  chipKind: "info" | "warning";
  desc: string;
  onClick: () => void;
}) {
  return (
    <div className="cc-card cc-card--hover" onClick={onClick}>
      <div className="cc-row" style={{ justifyContent: "space-between" }}>
        <div className="cc-card-title">{name}</div>
        <span className={`cc-chip cc-chip--${chipKind}`}>{ac}</span>
      </div>
      <div className="cc-soft" style={{ fontSize: 12 }}>
        {desc}
      </div>
    </div>
  );
}

export default StrategyWorkshopPage;
