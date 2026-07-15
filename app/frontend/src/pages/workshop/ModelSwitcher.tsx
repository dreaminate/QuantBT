import { useCallback, useEffect, useState } from "react";

import { authFetch } from "../../lib/auth";

/**
 * 跨厂商切模型 S7 · 每对话模型切换器
 *
 * 挂在 Mode2ChatPage 的 active-thread header。列已 auth 厂商的可选模型（按 provider 分组）+
 * 顶项「Auto（自动路由）」。选中即 PATCH /api/agent/chat/{threadId}/llm-selection——**下一条消息立即
 * 用新模型**（服务端每次请求现读手选，对话中途可切）。仅 API-key 可路由厂商可切（订阅模型带工具跑不了，
 * 后端 PATCH 已拒；订阅切换待 tool bridge）。凭据从不经前端——只传 provider/model 名。
 */

type ModelEntry = {
  model: string;
  tier?: string;
  selectable: boolean;
  supports_tools?: boolean;
  source?: string;
};
type ProviderEntry = {
  provider: string;
  auth_kind: string;
  authed: boolean;
  selectable: boolean;
  models: ModelEntry[];
};
type Selection = { mode: string; provider?: string; model?: string };

const AUTO_VALUE = "__auto__";
const SEP = "::";

export default function ModelSwitcher({ threadId }: { threadId: string }) {
  const [providers, setProviders] = useState<ProviderEntry[]>([]);
  const [selection, setSelection] = useState<Selection>({ mode: "auto" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [mr, sr] = await Promise.all([
          authFetch("/api/llm/models"),
          authFetch(`/api/agent/chat/${threadId}/llm-selection`),
        ]);
        const md = await mr.json().catch(() => ({}));
        const sd = await sr.json().catch(() => ({}));
        if (!alive) return;
        setProviders(Array.isArray(md?.providers) ? md.providers : []);
        setSelection(sd?.llm_selection || { mode: "auto" });
      } catch {
        if (alive) setError("加载模型列表失败");
      }
    })();
    return () => {
      alive = false;
    };
  }, [threadId]);

  const currentValue =
    selection.mode === "pinned" && selection.provider && selection.model
      ? `${selection.provider}${SEP}${selection.model}`
      : AUTO_VALUE;

  const onChange = useCallback(
    async (value: string) => {
      setBusy(true);
      setError("");
      let body: Selection;
      if (value === AUTO_VALUE) {
        body = { mode: "auto" };
      } else {
        const idx = value.indexOf(SEP);
        body = { mode: "pinned", provider: value.slice(0, idx), model: value.slice(idx + SEP.length) };
      }
      try {
        const r = await authFetch(`/api/agent/chat/${threadId}/llm-selection`, {
          method: "PATCH",
          body: JSON.stringify(body),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          setError(typeof d?.detail === "string" ? d.detail : "切换失败");
          return;
        }
        const d = await r.json().catch(() => ({}));
        setSelection(d?.llm_selection || body);
      } catch {
        setError("切换失败");
      } finally {
        setBusy(false);
      }
    },
    [threadId],
  );

  const selectableProviders = providers.filter((p) => p.authed && p.selectable);
  // stale/未在目录里的当前 pin：仍显示（否则 select 空白，用户不知选的是啥）
  const pinInCatalog =
    selection.mode !== "pinned" ||
    selectableProviders.some(
      (p) =>
        p.provider === selection.provider &&
        p.models.some((m) => m.model === selection.model && m.selectable),
    );

  return (
    <div className="cc-row" style={{ gap: 6, alignItems: "center" }} data-model-switcher>
      <span className="cc-dim" style={{ fontSize: 11 }}>
        模型
      </span>
      <select
        className="cc-select cc-select--sm"
        data-model-select
        value={currentValue}
        disabled={busy}
        onChange={(e) => onChange(e.target.value)}
        title="每对话切模型·下一条消息即生效"
      >
        <option value={AUTO_VALUE}>Auto（自动路由）</option>
        {!pinInCatalog && (
          <option value={currentValue}>
            {selection.provider} / {selection.model}（当前）
          </option>
        )}
        {selectableProviders.map((p) => (
          <optgroup key={p.provider} label={p.provider}>
            {p.models
              .filter((m) => m.selectable)
              .map((m) => (
                <option key={`${p.provider}${SEP}${m.model}`} value={`${p.provider}${SEP}${m.model}`}>
                  {m.model}
                  {m.tier ? ` · ${m.tier}` : ""}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      {error && (
        <span className="cc-dim" style={{ fontSize: 10, color: "var(--cc-danger, #e66)" }} data-model-switch-error>
          {error}
        </span>
      )}
    </div>
  );
}
