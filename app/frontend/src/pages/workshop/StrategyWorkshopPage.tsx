import { useState } from "react";

/**
 * 策略工坊 · 独立 SPA 页面
 * 路由：/workshop
 * 功能：自然语言 → StrategyGoal slot-fill + JSON 预览 + （后续）一键 run
 */
export function StrategyWorkshopPage() {
  const [text, setText] = useState("我想做 A股 周频 选股策略，回撤 15%，单标的 5%");
  const [goal, setGoal] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setError(null);
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
    }
  };
  return (
    <div style={{ padding: 16 }}>
      <h2>策略工坊</h2>
      <p style={{ color: "#666" }}>
        自然语言一句话 → StrategyGoal Pydantic 对象（三档 cost_model + 一致性硬约束）。
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={3}
        style={{ width: "100%", maxWidth: 800 }}
      />
      <div style={{ marginTop: 8 }}>
        <button type="button" onClick={submit}>解析为 StrategyGoal</button>
      </div>
      {error && <pre style={{ color: "crimson" }}>{error}</pre>}
      {goal && (
        <pre style={{ background: "#fafafa", padding: 12, maxWidth: 1000 }}>
          {JSON.stringify(goal, null, 2)}
        </pre>
      )}
    </div>
  );
}

export default StrategyWorkshopPage;
