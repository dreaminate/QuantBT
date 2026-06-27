import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { authFetch, getStoredUser } from "../../lib/auth";

/**
 * v0.8.2 · 聚宽风 IDE + 代码生成/说明面板
 *
 * - 左：策略文件列表 (我的策略 + 新建)
 * - 中：代码编辑器 (textarea + 行号槽) + 顶部 toolbar(运行/保存/生成)
 * - 右：tab(运行输出 / 代码生成)
 *
 * 用户代码协议：
 *   quantbt.emit_result({"equity_curve": [...], "trades": [...], "sharpe": 1.5, ...})
 *   后端解析最后一行 __QUANTBT_RESULT__ JSON 落到 result.json
 *
 * 沙箱：subprocess + resource.setrlimit + socket monkey-patch + wallclock timeout
 * 顶部 banner 红条提示"仅原型验证用"
 */

interface StrategyFile {
  strategy_id: string;
  owner_username: string;
  name: string;
  code: string;
  asset_class: string;
  description: string;
  updated_at_utc: string;
  market_data_use_validation_refs?: string[];
}

interface IDERun {
  run_id: string;
  strategy_id: string;
  owner_username: string;
  status: string;
  started_at_utc: string;
  market_data_use_validation_refs?: string[];
  finished_at_utc: string | null;
  exit_code: number | null;
  error: string | null;
  stdout_excerpt: string;
  stderr_excerpt: string;
  duration_s: number;
  result_keys: string[];
}

const DEFAULT_TEMPLATE = `"""聚宽风策略模板 (v0.8.2)。

约束：
- 沙箱禁止 socket/subprocess/os.system/chdir/import requests
- 必须用 quantbt.emit_result({...}) 在末尾发出结果
- 可用：numpy / pandas / polars / math / 标准库 (除黑名单)
"""

import math, random

random.seed(42)

# 模拟一条 100 个点的 equity curve
equity_curve = []
equity = 1.0
for i in range(100):
    daily_ret = random.gauss(0.0005, 0.012)  # 日收益率
    equity *= (1 + daily_ret)
    equity_curve.append({"t": i, "equity": equity})

# 简单算 sharpe
rets = [equity_curve[i]["equity"] / equity_curve[i-1]["equity"] - 1 for i in range(1, 100)]
mean = sum(rets) / len(rets)
std = math.sqrt(sum((r - mean) ** 2 for r in rets) / len(rets))
sharpe = (mean / std) * math.sqrt(252) if std > 0 else 0.0

quantbt.emit_result({
    "equity_curve": equity_curve,
    "metrics": {
        "sharpe": round(sharpe, 3),
        "final_equity": round(equity, 4),
        "total_return": round(equity - 1, 4),
    },
})
`;

function splitMarketDataUseValidationRefs(raw: string): string[] {
  return raw
    .split(/[,\n]/)
    .map((ref) => ref.trim())
    .filter(Boolean);
}

interface GenerationContext {
  connectors: { name: string; asset_class?: string; kind?: string }[];
  factors: { factor_id: string; lifecycle_state?: string; description?: string }[];
  operators: { name?: string }[];
  rules: string[];
  code_skeleton: string;
  emit_result_schema: Record<string, unknown>;
}

export function IDEPage() {
  const me = getStoredUser();
  // 用稳定的身份代理做 effect 依赖：getStoredUser() 每次 render 返回新对象引用，
  // 直接进依赖数组会触发无限重拉（请求风暴）。
  const userId = me?.user_id ?? null;
  const navigate = useNavigate();
  const [strategies, setStrategies] = useState<StrategyFile[]>([]);
  const [currentName, setCurrentName] = useState<string | null>(null);
  const [code, setCode] = useState(DEFAULT_TEMPLATE);
  const [assetClass, setAssetClass] = useState("crypto_perp");
  const [description, setDescription] = useState("");
  const [marketDataUseValidationRefs, setMarketDataUseValidationRefs] = useState("");
  const [recentRuns, setRecentRuns] = useState<IDERun[]>([]);
  const [activeRun, setActiveRun] = useState<IDERun | null>(null);
  const [running, setRunning] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rightTab, setRightTab] = useState<"output" | "codegen">("output");
  const [generationPrompt, setGenerationPrompt] = useState("帮我写一个 RSI 双门限均值回归 + 1% 单标的上限的策略");
  const [generationMode, setGenerationMode] = useState<"write" | "explain" | "fix">("write");
  const [generationBusy, setGenerationBusy] = useState(false);
  const [generationReply, setGenerationReply] = useState("");
  const [generationContext, setGenerationContext] = useState<GenerationContext | null>(null);
  const [showContext, setShowContext] = useState(false);
  const [promoting, setPromoting] = useState(false);

  const reload = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        authFetch("/api/ide/strategies").then((res) => res.json()),
        authFetch("/api/ide/runs?limit=20").then((res) => res.json()),
      ]);
      setStrategies(Array.isArray(s) ? s : []);
      setRecentRuns(Array.isArray(r) ? r : []);
    } catch {
      setStrategies([]);
      setRecentRuns([]);
    }
  }, []);

  useEffect(() => {
    if (userId) reload();
  }, [userId, reload]);

  useEffect(() => {
    if (!userId) return;
    authFetch("/api/ide/ai_context")
      .then((r) => (r.ok ? r.json() : null))
      .then((c) => c && setGenerationContext(c))
      .catch(() => {/* noop */});
  }, [userId]);

  const openStrategy = (s: StrategyFile) => {
    setCurrentName(s.name);
    setCode(s.code);
    setAssetClass(s.asset_class);
    setDescription(s.description || "");
    setMarketDataUseValidationRefs((s.market_data_use_validation_refs || []).join("\n"));
    setActiveRun(null);
  };

  const newStrategy = () => {
    const name = prompt("策略名 (字母数字 - _):", "my_strategy_v1");
    if (!name) return;
    setCurrentName(name);
    setCode(DEFAULT_TEMPLATE);
    setAssetClass("crypto_perp");
    setDescription("");
    setMarketDataUseValidationRefs("");
    setActiveRun(null);
  };

  const save = async (): Promise<string | null> => {
    let targetName = currentName;
    if (!targetName) {
      const name = prompt("策略名 (字母数字 - _):", "my_strategy_v1");
      if (!name) return null;
      setCurrentName(name);
      targetName = name;
    }
    const validationRefs = splitMarketDataUseValidationRefs(marketDataUseValidationRefs);
    setSaving(true);
    try {
      const res = await authFetch("/api/ide/strategies", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: targetName,
          code,
          asset_class: assetClass,
          description,
          market_data_use_validation_refs: validationRefs,
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "save 失败" }));
        alert(err.detail || "save 失败");
        return null;
      }
      await reload();
      return targetName;
    } finally {
      setSaving(false);
    }
  };

  const run = async () => {
    if (!currentName) {
      alert("先保存策略");
      return;
    }
    setRunning(true);
    setActiveRun(null);
    setRightTab("output");
    try {
      // 自动 save then run
      const savedName = await save();
      if (!savedName) return;
      const res = await authFetch(`/api/ide/strategies/${savedName}/run`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          market_data_use_validation_refs: splitMarketDataUseValidationRefs(marketDataUseValidationRefs),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "run 失败" }));
        alert(err.detail || "run 失败");
        return;
      }
      const run: IDERun = await res.json();
      setActiveRun(run);
      reload();
    } finally {
      setRunning(false);
    }
  };

  const remove = async (s: StrategyFile) => {
    if (!confirm(`确认删除策略 ${s.name}？`)) return;
    await authFetch(`/api/ide/strategies/${s.name}`, { method: "DELETE" });
    if (currentName === s.name) {
      setCurrentName(null);
      setCode(DEFAULT_TEMPLATE);
    }
    reload();
  };

  const askModel = async () => {
    if (!generationPrompt.trim()) return;
    setGenerationBusy(true);
    setGenerationReply("");
    try {
      const res = await authFetch("/api/ide/ai_complete", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          prompt: generationPrompt,
          context_code: code,
          mode: generationMode,
          market_data_use_validation_refs: splitMarketDataUseValidationRefs(marketDataUseValidationRefs),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "模型调用失败" }));
        setGenerationReply(`[ERROR] ${err.detail || res.status}`);
        return;
      }
      const data = await res.json();
      setGenerationReply(data.code || "(LLM 无内容)");
    } catch (err) {
      setGenerationReply(`[ERROR] ${String(err)}`);
    } finally {
      setGenerationBusy(false);
    }
  };

  const promoteRun = async () => {
    if (!activeRun) return;
    if (!activeRun.result_keys.includes("equity_curve")) {
      alert("emit_result 必须包含 equity_curve 才能提升为正式 Run");
      return;
    }
    setPromoting(true);
    try {
      const validationRefs =
        activeRun.market_data_use_validation_refs && activeRun.market_data_use_validation_refs.length > 0
          ? activeRun.market_data_use_validation_refs
          : splitMarketDataUseValidationRefs(marketDataUseValidationRefs);
      const res = await authFetch(`/api/ide/runs/${activeRun.run_id}/promote`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ market_data_use_validation_refs: validationRefs }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "promote 失败" }));
        alert(err.detail || "promote 失败");
        return;
      }
      const data: { run_id: string; run_url: string } = await res.json();
      navigate(data.run_url);
    } finally {
      setPromoting(false);
    }
  };

  const insertGenerationReply = () => {
    if (!generationReply || generationReply.startsWith("[ERROR]")) return;
    if (generationMode === "explain") {
      // 解释模式：作为 docstring 插到顶部
      setCode(`"""模型说明:\n${generationReply}\n"""\n\n${code}`);
    } else {
      // 写/修复模式：直接替换 OR 追加
      const append = confirm("追加到当前代码末尾？(取消则覆盖全部)");
      setCode(append ? `${code}\n\n# === 模型生成 ===\n${generationReply}` : generationReply);
    }
  };

  if (!me) {
    return (
      <div className="cc-card cc-dim" style={{ padding: 24 }}>
        请先登录后使用 IDE。
      </div>
    );
  }

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{"// IDE · 策略代码工坊"}</h1>
          <div className="cc-soft">策略代码编辑器 · 子进程沙箱运行你的策略 · 代码生成与说明</div>
        </div>
        <div className="cc-page-actions">
          <button type="button" className="cc-btn" onClick={save} disabled={saving || running}>
            {saving ? "saving..." : "💾 保存"}
          </button>
          <button type="button" className="cc-btn cc-btn--accent" onClick={run} disabled={running || saving}>
            {running ? "running..." : "▶ 运行"}
          </button>
        </div>
      </div>

      <div className="cc-card" style={{ marginBottom: 12, padding: 10, borderLeft: "3px solid var(--cc-red, #c44)", background: "rgba(196, 68, 68, 0.05)" }}>
        <span className="cc-mono" style={{ fontSize: 12 }}>
          ⚠ 沙箱提示：代码运行在 subprocess + rlimit + socket-block 的受限沙箱中，wallclock 30s / CPU 15s / 内存 2GB。
          禁止网络 / subprocess / os.system / chdir。仅做原型验证，**非 hardened sandbox**。
        </span>
      </div>

      <div className="cc-row" style={{ alignItems: "stretch", gap: 12 }}>
        {/* 左：策略列表 */}
        <aside className="cc-card" style={{ width: 220, padding: 12, flexShrink: 0 }}>
          <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <div className="cc-section-title" style={{ margin: 0 }}>策略</div>
            <button type="button" className="cc-btn cc-btn--ghost cc-btn--sm" onClick={newStrategy}>+ 新建</button>
          </div>
          {strategies.length === 0 ? (
            <div className="cc-dim" style={{ fontSize: 12 }}>还没有策略，点 + 新建</div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {strategies.map((s) => (
                <li key={s.strategy_id} style={{ marginBottom: 4 }}>
                  <div
                    className={`cc-row ${currentName === s.name ? "cc-row--active" : ""}`}
                    style={{
                      justifyContent: "space-between",
                      padding: "4px 6px",
                      cursor: "pointer",
                      borderRadius: 4,
                      background: currentName === s.name ? "var(--cc-bg-elev, rgba(255,255,255,0.05))" : "transparent",
                    }}
                    onClick={() => openStrategy(s)}
                  >
                    <span className="cc-mono" style={{ fontSize: 13 }}>{s.name}</span>
                    <button
                      type="button"
                      className="cc-btn cc-btn--ghost cc-btn--sm"
                      onClick={(e) => { e.stopPropagation(); remove(s); }}
                      title="删除"
                      style={{ padding: "0 4px" }}
                    >×</button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <div className="cc-section-title" style={{ marginTop: 16, marginBottom: 6 }}>最近 run</div>
          {recentRuns.length === 0 ? (
            <div className="cc-dim" style={{ fontSize: 12 }}>没有运行历史</div>
          ) : (
            <ul style={{ listStyle: "none", padding: 0, margin: 0, fontSize: 11 }}>
              {recentRuns.slice(0, 10).map((r) => (
                <li key={r.run_id} style={{ marginBottom: 2, cursor: "pointer" }} onClick={() => { setActiveRun(r); setRightTab("output"); }}>
                  <span className={`cc-chip ${r.status === "ok" ? "cc-chip--green" : r.status === "timeout" ? "cc-chip--yellow" : "cc-chip--red"}`} style={{ marginRight: 4 }}>
                    {r.status}
                  </span>
                  <span className="cc-mono cc-dim">{r.started_at_utc.slice(11, 19)}</span>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* 中：编辑器 */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="cc-card" style={{ padding: 0, overflow: "hidden" }}>
            <div className="cc-row" style={{ padding: "6px 10px", borderBottom: "1px solid var(--cc-border, rgba(255,255,255,0.08))", gap: 8 }}>
              <span className="cc-mono" style={{ fontSize: 12 }}>
                {currentName ? `${currentName}.py` : "(未命名)"}
              </span>
              <select
                value={assetClass}
                onChange={(e) => setAssetClass(e.target.value)}
                className="cc-select cc-select--sm"
                style={{ fontSize: 11 }}
              >
                <option value="crypto_perp">crypto_perp</option>
                <option value="crypto_spot">crypto_spot</option>
                <option value="equity_cn">equity_cn</option>
              </select>
              <input
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="策略描述（可选）"
                className="cc-input cc-input--sm"
                style={{ flex: 1, fontSize: 11 }}
              />
            </div>
            <div className="cc-row" style={{ padding: "6px 10px", borderBottom: "1px solid var(--cc-border, rgba(255,255,255,0.08))", gap: 8 }}>
              <span className="cc-mono cc-dim" style={{ fontSize: 11, flexShrink: 0 }}>MarketDataUse refs</span>
              <input
                value={marketDataUseValidationRefs}
                onChange={(e) => setMarketDataUseValidationRefs(e.target.value)}
                placeholder="market_data_use:...（逗号或换行分隔）"
                className="cc-input cc-input--sm"
                style={{ flex: 1, fontSize: 11 }}
              />
            </div>
            <CodeEditor code={code} onChange={setCode} />
          </div>
        </div>

        {/* 右：输出 / 代码生成 */}
        <aside className="cc-card" style={{ width: 360, padding: 0, flexShrink: 0, overflow: "hidden" }}>
          <div className="cc-tabs" style={{ marginBottom: 0, borderBottom: "1px solid var(--cc-border, rgba(255,255,255,0.08))" }}>
            <a
              className={`cc-tab ${rightTab === "output" ? "active" : ""}`}
              onClick={() => setRightTab("output")}
              style={{ cursor: "pointer" }}
            >
              运行输出
            </a>
            <a
              className={`cc-tab ${rightTab === "codegen" ? "active" : ""}`}
              onClick={() => setRightTab("codegen")}
              style={{ cursor: "pointer" }}
            >
              代码生成
            </a>
          </div>
          <div style={{ padding: 12, maxHeight: "70vh", overflow: "auto" }}>
            {rightTab === "output" ? (
              <RunOutput
                run={activeRun}
                running={running}
                onPromote={promoteRun}
                promoting={promoting}
              />
            ) : (
              <CodeGenerationPanel
                prompt={generationPrompt}
                setPrompt={setGenerationPrompt}
                mode={generationMode}
                setMode={setGenerationMode}
                busy={generationBusy}
                reply={generationReply}
                onAsk={askModel}
                onInsert={insertGenerationReply}
                context={generationContext}
                showContext={showContext}
                onToggleContext={() => setShowContext(!showContext)}
              />
            )}
          </div>
        </aside>
      </div>
    </>
  );
}

function CodeEditor({ code, onChange }: { code: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLTextAreaElement | null>(null);
  const lineCount = useMemo(() => code.split("\n").length, [code]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Tab") {
      e.preventDefault();
      const ta = e.currentTarget;
      const start = ta.selectionStart;
      const end = ta.selectionEnd;
      const next = code.slice(0, start) + "    " + code.slice(end);
      onChange(next);
      // 调整光标位置
      requestAnimationFrame(() => {
        ta.selectionStart = ta.selectionEnd = start + 4;
      });
    }
  };

  return (
    <div className="cc-row" style={{ alignItems: "stretch", gap: 0, background: "var(--cc-bg-code, #0d1117)" }}>
      <div
        className="cc-mono cc-dim"
        style={{
          width: 44,
          textAlign: "right",
          padding: "10px 6px",
          fontSize: 12,
          userSelect: "none",
          borderRight: "1px solid var(--cc-border, rgba(255,255,255,0.08))",
          background: "rgba(255,255,255,0.02)",
          lineHeight: "18px",
        }}
      >
        {Array.from({ length: lineCount }, (_, i) => (
          <div key={i}>{i + 1}</div>
        ))}
      </div>
      <textarea
        ref={ref}
        value={code}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        spellCheck={false}
        wrap="off"
        className="cc-mono"
        style={{
          flex: 1,
          minHeight: 480,
          padding: "10px 12px",
          background: "transparent",
          color: "var(--cc-text, #e6edf3)",
          border: 0,
          outline: 0,
          resize: "vertical",
          fontSize: 13,
          lineHeight: "18px",
          tabSize: 4,
          whiteSpace: "pre",
          overflowWrap: "normal",
          overflowX: "auto",
        }}
      />
    </div>
  );
}

function RunOutput({ run, running, onPromote, promoting }: { run: IDERun | null; running: boolean; onPromote: () => void; promoting: boolean }) {
  const [riskPreview, setRiskPreview] = useState<{ trust_level?: string; summary?: string; flags?: any[] } | null>(null);

  useEffect(() => {
    if (!run || run.status !== "ok" || !run.result_keys.includes("equity_curve")) {
      setRiskPreview(null);
      return;
    }
    fetch(`/api/ide/runs/${run.run_id}/risk_preview`, {
      headers: localStorage.getItem("qb-token") ? { authorization: `Bearer ${localStorage.getItem("qb-token")}` } : undefined,
    })
      .then((r) => r.json())
      .then((d) => setRiskPreview(d?.risk_summary || null))
      .catch(() => setRiskPreview(null));
  }, [run?.run_id, run?.status, run?.result_keys?.join(",")]);

  if (running) return <div className="cc-dim">⏳ 沙箱运行中... (wallclock ≤ 30s)</div>;
  if (!run) return <div className="cc-dim">未运行。保存代码 → ▶ 运行</div>;
  const chipClass = run.status === "ok" ? "cc-chip--green" : run.status === "timeout" ? "cc-chip--yellow" : "cc-chip--red";
  const canPromote = run.status === "ok" && run.result_keys.includes("equity_curve");
  const trustColor = riskPreview?.trust_level === "ok" ? "#1f9a52"
    : riskPreview?.trust_level === "caution" ? "#c98a14"
    : riskPreview?.trust_level === "high_risk" ? "#cc3344"
    : "#888";
  const trustLabel = riskPreview?.trust_level === "ok" ? "证据一致"
    : riskPreview?.trust_level === "caution" ? "存疑"
    : riskPreview?.trust_level === "high_risk" ? "高风险"
    : riskPreview?.trust_level === "insufficient_data" ? "信息不足"
    : null;

  return (
    <div>
      <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <span className={`cc-chip ${chipClass}`}>{run.status.toUpperCase()}</span>
        <span className="cc-mono cc-dim" style={{ fontSize: 11 }}>{run.duration_s.toFixed(2)}s · exit={run.exit_code}</span>
      </div>
      {canPromote && trustLabel && (
        <div
          style={{
            marginBottom: 8,
            padding: 8,
            background: `${trustColor}1a`,
            borderLeft: `3px solid ${trustColor}`,
            borderRadius: 4,
            fontSize: 12,
          }}
        >
          <div style={{ fontWeight: 600, color: trustColor }}>● {trustLabel}（提升前预览）</div>
          {riskPreview?.summary && <div className="cc-soft" style={{ marginTop: 4 }}>{riskPreview.summary}</div>}
          {riskPreview?.flags && riskPreview.flags.length > 0 && (
            <ul style={{ paddingLeft: 16, margin: "4px 0 0 0", fontSize: 11 }}>
              {riskPreview.flags.slice(0, 3).map((f: any) => (
                <li key={f.name}>{f.message}</li>
              ))}
            </ul>
          )}
        </div>
      )}
      {canPromote && (
        <button
          type="button"
          className="cc-btn cc-btn--accent"
          onClick={onPromote}
          disabled={promoting}
          style={{ width: "100%", marginBottom: 8 }}
          title="把沙箱结果落到 runs/<id> 跑 metrics，进 RunDetail 三联图"
        >
          {promoting ? "promoting..." : "⤴ 提升为正式 Run · 进 /runs/<id>"}
        </button>
      )}
      {run.error && (
        <div className="cc-card" style={{ padding: 8, marginBottom: 8, fontSize: 12, color: "var(--cc-red, #f55)" }}>
          {run.error}
        </div>
      )}
      {run.result_keys.length > 0 && (
        <div style={{ marginBottom: 8 }}>
          <div className="cc-section-title" style={{ fontSize: 11 }}>emit_result keys</div>
          {run.result_keys.map((k) => (
            <span key={k} className="cc-chip" style={{ marginRight: 4, fontSize: 10 }}>{k}</span>
          ))}
        </div>
      )}
      {run.stdout_excerpt && (
        <details open style={{ marginBottom: 8 }}>
          <summary className="cc-mono cc-dim" style={{ fontSize: 11, cursor: "pointer" }}>stdout</summary>
          <pre className="cc-mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", margin: "4px 0", maxHeight: 240, overflow: "auto" }}>{run.stdout_excerpt}</pre>
        </details>
      )}
      {run.stderr_excerpt && (
        <details open>
          <summary className="cc-mono" style={{ fontSize: 11, cursor: "pointer", color: "var(--cc-red, #f55)" }}>stderr</summary>
          <pre className="cc-mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", margin: "4px 0", maxHeight: 240, overflow: "auto", color: "var(--cc-red, #f55)" }}>{run.stderr_excerpt}</pre>
        </details>
      )}
    </div>
  );
}

function CodeGenerationPanel(props: {
  prompt: string;
  setPrompt: (v: string) => void;
  mode: "write" | "explain" | "fix";
  setMode: (m: "write" | "explain" | "fix") => void;
  busy: boolean;
  reply: string;
  onAsk: () => void;
  onInsert: () => void;
  context: GenerationContext | null;
  showContext: boolean;
  onToggleContext: () => void;
}) {
  const { prompt, setPrompt, mode, setMode, busy, reply, onAsk, onInsert, context, showContext, onToggleContext } = props;
  return (
    <div>
      <div className="cc-row" style={{ justifyContent: "space-between", marginTop: 0 }}>
        <div className="cc-section-title" style={{ margin: 0 }}>代码生成</div>
        {context && (
          <button
            type="button"
            className="cc-btn cc-btn--ghost cc-btn--sm"
            onClick={onToggleContext}
            title="查看发送给模型的上下文"
            style={{ fontSize: 10 }}
          >
            ⓘ 上下文 {context.connectors.length}·{context.factors.length}·{context.operators.length}
          </button>
        )}
      </div>
      {showContext && context && (
        <div className="cc-card" style={{ padding: 8, marginTop: 6, marginBottom: 8, fontSize: 11, maxHeight: 180, overflow: "auto" }}>
          <div className="cc-mono cc-dim">connector · {context.connectors.length}</div>
          <div style={{ marginBottom: 4 }}>
            {context.connectors.slice(0, 6).map((c) => (
              <span key={c.name} className="cc-chip" style={{ marginRight: 4, fontSize: 10 }}>{c.name}</span>
            ))}
          </div>
          <div className="cc-mono cc-dim">factor · {context.factors.length}（已过滤 RETIRED）</div>
          <div style={{ marginBottom: 4 }}>
            {context.factors.slice(0, 6).map((f) => (
              <span key={f.factor_id} className="cc-chip" style={{ marginRight: 4, fontSize: 10 }}>{f.factor_id}</span>
            ))}
            {context.factors.length > 6 && <span className="cc-dim" style={{ fontSize: 10 }}>+{context.factors.length - 6}</span>}
          </div>
          <div className="cc-mono cc-dim">operator · {context.operators.length}</div>
          <div className="cc-dim" style={{ fontSize: 10 }}>
            {context.operators.slice(0, 8).map((o) => o.name).join(", ")}{context.operators.length > 8 ? "..." : ""}
          </div>
          <div className="cc-mono cc-dim" style={{ marginTop: 6 }}>沙箱规则</div>
          <ul style={{ paddingLeft: 16, margin: "2px 0 0 0", fontSize: 10 }}>
            {context.rules.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="cc-row" style={{ gap: 4, marginBottom: 8 }}>
        {(["write", "explain", "fix"] as const).map((m) => (
          <button
            key={m}
            type="button"
            className={`cc-btn cc-btn--sm ${mode === m ? "cc-btn--accent" : "cc-btn--ghost"}`}
            onClick={() => setMode(m)}
          >
            {m === "write" ? "✎ 写" : m === "explain" ? "📖 解释" : "🔧 修复"}
          </button>
        ))}
      </div>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder={
          mode === "write" ? "描述你想写什么策略..." :
          mode === "explain" ? "想解释哪段代码？(默认解释左侧全文)" :
          "代码报什么错？把 stderr 关键行粘进来"
        }
        className="cc-input"
        style={{ width: "100%", minHeight: 80, fontSize: 12, fontFamily: "inherit" }}
      />
      <button
        type="button"
        className="cc-btn cc-btn--accent"
        onClick={onAsk}
        disabled={busy || !prompt.trim()}
        style={{ marginTop: 8, width: "100%" }}
      >
        {busy ? "生成中..." : "✦ 生成"}
      </button>
      {reply && (
        <div style={{ marginTop: 12 }}>
          <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 4 }}>
            <span className="cc-section-title" style={{ margin: 0, fontSize: 11 }}>模型返回</span>
            <button type="button" className="cc-btn cc-btn--sm" onClick={onInsert}>
              ↪ 插入编辑器
            </button>
          </div>
          <pre className="cc-mono" style={{ fontSize: 11, whiteSpace: "pre-wrap", maxHeight: 320, overflow: "auto", background: "rgba(255,255,255,0.03)", padding: 8, borderRadius: 4 }}>
            {reply}
          </pre>
        </div>
      )}
    </div>
  );
}

export default IDEPage;
