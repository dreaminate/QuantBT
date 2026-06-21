import { getToken } from "../../../lib/auth";
import {
  type AgentBlock,
  type SideEffect,
} from "../../../components/desk";
import { type MilestoneKey } from "./agentMock";

/**
 * A4 · agent 工作台「接真」SSE 客户端（真 /api/agent/workbench/stream 流）。
 *
 * 把后端结构化事件（user / thinking / say / tool_start / tool_end / gate / milestone /
 * done / error）投影成前端 AgentBlock + 里程碑回调——替代 mock 剧本回放。
 *
 * 治理真值原则（D-PERM / R25）：
 *  · gate 的 side_effect 是**后端真值**（来自 tool_status / runtime._side_effects），
 *    前端原样透传给 GatePanel，绝不伪造或当可编辑字段。
 *  · 用 fetch + ReadableStream 读 SSE（非 EventSource——后者无法带 Authorization header）。
 *
 * EventSource 不可用环境（jsdom 测试）→ 调用方不挂载本 hook，保留 mock + MockBadge。
 */

export type LiveEventKind =
  | "user"
  | "thinking"
  | "say"
  | "tool_start"
  | "tool_end"
  | "gate"
  | "milestone"
  | "done"
  | "error";

export interface LiveCallbacks {
  /** 新增一个对话块（user/thinking/say/tool/gate）。 */
  onBlock: (block: AgentBlock) => void;
  /** 工具结束（更新最近 tool 块的 summary）。 */
  onToolEnd: (result: unknown) => void;
  /** 里程碑点亮。 */
  onMilestone: (key: MilestoneKey) => void;
  /** 流结束。 */
  onDone: (final: string, succeeded: boolean) => void;
  /** 错误（含 LLM 不可用）——诚实呈现，不假绿灯。 */
  onError: (msg: string) => void;
}

let _seq = 0;
function nextId(prefix: string): string {
  _seq += 1;
  return `${prefix}-${Date.now()}-${_seq}`;
}

const TOOL_MS_LABEL: Record<string, MilestoneKey> = {
  立题: "立题",
  市场: "市场",
  因子集: "因子集",
  模型: "模型",
  信号: "信号",
  仓位风控: "仓位风控",
  回测: "回测",
};

/** 解析一条 SSE 帧（event: + data:）。 */
function parseFrame(frame: string): { event: LiveEventKind; data: unknown } | null {
  let event: LiveEventKind = "say";
  let dataLine = "";
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim() as LiveEventKind;
    else if (line.startsWith("data:")) dataLine += line.slice(5).trim();
  }
  if (!dataLine) return null;
  try {
    return { event, data: JSON.parse(dataLine) };
  } catch {
    return null;
  }
}

/**
 * 启动真 SSE 流。返回 abort 函数（卸载时调用）。
 *
 * @param q 用户消息
 * @param permMode 权限三态（ask/auto/bypass）——后端 permission_gate 据此决定 gate 挂起。
 */
export function streamAgentWorkbench(
  q: string,
  permMode: string,
  cb: LiveCallbacks,
): () => void {
  const controller = new AbortController();
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const url = `/api/agent/workbench/stream?q=${encodeURIComponent(
    q,
  )}&permission_mode=${encodeURIComponent(permMode)}`;

  (async () => {
    try {
      const res = await fetch(url, { headers, signal: controller.signal });
      if (!res.ok || !res.body) {
        cb.onError(`流启动失败 (${res.status})`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      // 逐块读，按 \n\n 切帧。
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const parsed = parseFrame(frame);
          if (parsed) dispatch(parsed.event, parsed.data, cb);
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        cb.onError(`[流错误] ${(e as Error).message}`);
      }
    }
  })();

  return () => controller.abort();
}

function dispatch(event: LiveEventKind, data: unknown, cb: LiveCallbacks): void {
  const d = (data ?? {}) as Record<string, unknown>;
  switch (event) {
    case "user":
      cb.onBlock({ id: nextId("u"), type: "user", text: String(d.text ?? "") });
      break;
    case "thinking":
      cb.onBlock({ id: nextId("th"), type: "think", text: String(d.text ?? "") });
      break;
    case "say":
      cb.onBlock({ id: nextId("s"), type: "say", text: String(d.text ?? "") });
      break;
    case "tool_start":
      cb.onBlock({
        id: nextId("t"),
        type: "tool",
        toolName: String(d.tool ?? ""),
        toolStatus: "running",
        sideEffect: (d.side_effect as SideEffect) ?? "none",
      });
      break;
    case "tool_end":
      cb.onToolEnd(d.result);
      break;
    case "gate":
      // side_effect 是后端真值——原样透传（D-PERM：realmoney/external 即便 bypass 仍弹确认）。
      cb.onBlock({
        id: nextId("g"),
        type: "gate",
        gateTool: String(d.tool ?? ""),
        sideEffect: (d.side_effect as SideEffect) ?? "none",
        governanceWeakness: Boolean(d.governance_weakness),
        gateBlurb: `工具 ${d.tool} 需确认（side_effect: ${d.side_effect}）。`,
      });
      break;
    case "milestone": {
      const key = TOOL_MS_LABEL[String(d.key ?? "")];
      if (key) cb.onMilestone(key);
      break;
    }
    case "done":
      cb.onDone(String(d.final_message ?? ""), Boolean(d.succeeded));
      break;
    case "error":
      cb.onError(String(d.error ?? "未知错误"));
      break;
  }
}
