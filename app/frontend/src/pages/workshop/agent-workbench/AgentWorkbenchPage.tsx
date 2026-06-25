import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AgentChat,
  ChatComposer,
  CollapsiblePanel,
  DeskShell,
  DeskSwitcher,
  DeskTopBar,
  MockBadge,
  Pill,
  SegmentedControl,
  SubTabBar,
  type AgentBlock,
  type PermissionMode,
} from "../../../components/desk";
import { Mode2ChatPage } from "../Mode2ChatPage";
import {
  AGENT_FIRST_PROMPT,
  AGENT_SCRIPT,
  MILESTONE_DEFS,
  PERM_DEMO_GATES,
  MOCK_FALSIFIABILITY_GUIDE,
  MOCK_PROVENANCE_ACK,
  MOCK_RED_VERDICT,
  SLASH_CMDS,
  type CoworkKind,
  type MilestoneKey,
  type WorkspaceTab,
} from "./agentMock";
import { MilestoneLadder } from "./MilestoneLadder";
import { CoworkArea } from "./CoworkCards";
import { CodeView, ReportView } from "./WorkspaceViews";
import { GatePanel } from "./GatePanel";
import { HandoffCard } from "./HandoffCard";
import {
  FalsifiabilityGuide,
  ProvenanceAck,
  RedVerdictAck,
} from "./TeachingPopups";
import { streamAgentWorkbench } from "./agentLive";
import { authFetch } from "../../../lib/auth";

/**
 * 研究执行台（独立 agent desk · DeskShell data-desk="agent" 橙 accent · 顶层子标签 workbench/diagnostics）。
 *
 * 覆盖四卡：T-040（对话流+工具可视化+权限三态）· A1（产物工作区）· A2（里程碑+台switcher）
 * · A3（D-PERM 反例 + self-approve 二次确认）。规格 = agentDeck.md + QuantBT Agent.dc.html。
 *
 * P0：纯 mock 剧本（AGENT_SCRIPT 一次性铺满，非真 SSE）+ 可交互 + 常驻 <MockBadge/>。
 * 不碰 App.tsx —— 路由由主控统一接。
 *
 * 治理红线（用 harness 测）：
 *  ① gate side_effect∈{realmoney,external} 即便 bypass/auto 仍渲染确认变体（D-PERM）→ GatePanel。
 *  ② self-approve（批准且不再问 → auto）加二次确认步（T-030）→ GatePanel。
 *  ③ side_effect 受控真值（来自 mock/后端 tool_status），不前端伪造。
 *  ④ 血统/真钱治理弱点 block 常驻展开不可折叠（R25）→ ChatBubble/CoworkCards。
 *  ⑤ handoff 文案止于模拟盘、不导向直接实盘（D-PERM）→ HandoffCard。
 */

const MODEL = "sonnet-4.5";
const BRANCH = "strat/weekly-cn";
const CTX_USED = 18;

type GateState = "pending" | "resolved-once" | "resolved-always" | "resolved-no";

export function AgentWorkbenchPage() {
  // 顶层子标签：workbench（默认工作台）/ coach（诊断台）。
  const [view, setView] = useState<"workbench" | "coach">("workbench");

  // 权限三态（D-PERM 权限轴）。
  const [permMode, setPermMode] = useState<PermissionMode>("ask");

  // 剧本推进：cursor 指向下一个待铺事件。autoplay 一次性把全脚本铺到 gate 为止。
  const [cursor, setCursor] = useState(0);
  const cursorRef = useRef(0);
  const didInit = useRef(false);
  const [blocks, setBlocks] = useState<AgentBlock[]>([]);
  const [reached, setReached] = useState<MilestoneKey[]>([]);
  const [activeMs, setActiveMs] = useState<MilestoneKey | null>(null);
  const [unlocked, setUnlocked] = useState<Set<CoworkKind>>(new Set());

  // gate 解析态（按事件 id）。
  const [gateStates, setGateStates] = useState<Record<string, GateState>>({});
  // handoff 是否已提交。
  const [handoffSubmitted, setHandoffSubmitted] = useState(false);
  // 是否已跑到回测拍板（解锁 handoff + report tab）。
  const [reportReady, setReportReady] = useState(false);

  // 工作区。
  const [wsTab, setWsTab] = useState<WorkspaceTab>("cowork");
  const [coworkOverride, setCoworkOverride] = useState<CoworkKind | null>(null);

  // 折叠 + splitter。
  const [chatOpen, setChatOpen] = useState(true);
  const [wsOpen, setWsOpen] = useState(true);
  const [chatW, setChatW] = useState(440);
  const splitRef = useRef<{ x0: number; w0: number } | null>(null);

  // composer + slash。
  const [draft, setDraft] = useState("");
  const [slashOpen, setSlashOpen] = useState(false);

  // D-PERM 反例 gate 注入（手动触发，让「bypass 也拦真钱」可见）。
  const [demoGate, setDemoGate] = useState<"realmoney" | "external" | null>(
    null,
  );
  const [demoGateState, setDemoGateState] = useState<GateState | null>(null);

  // T-041 教学文案弹窗三型（硬透明 + 软决定，绝不死挡；手动触发可见）。
  type TeachKind = "falsifiability" | "provenance" | "redVerdict" | null;
  const [teachPopup, setTeachPopup] = useState<TeachKind>(null);
  // 知情确认留痕回执（acknowledge 后的诚实记账文案）。
  const [teachNote, setTeachNote] = useState<string | null>(null);

  // 真实流：LIVE 模式（真 /api/agent/workbench/stream SSE）默认开（DS-2：陌生人默认走真实流，不放假绿灯 mock）。
  // mock 剧本退居「看演示」显式入口——仅当用户主动点「看演示」(demoMode) 才铺脚本、且全程挂 MockBadge。
  const [liveMode, setLiveMode] = useState(true);
  // demoMode：显式「看演示」（mock 剧本回放）入口。默认 false（默认真实流，不自动放 mock）。
  const [demoMode, setDemoMode] = useState(false);
  const [liveErr, setLiveErr] = useState<string | null>(null);
  // 真回测 run_id：从 LIVE 流 backtest.run 的 tool_end result 里读取（business_tools 产真 run_id）。
  // 存在 → 裁决卡走 LiveRunVerdictCard 三个真实端点；缺 → 回退 mock + MockBadge（诚实，不假绿灯）。
  const [liveRunId, setLiveRunId] = useState<string | null>(null);
  const liveAbort = useRef<(() => void) | null>(null);
  // §M5：是否已为「当前这次进入 live」自动起过首条 prompt（一次性守卫）。
  // 仅在进 live 时为 false → 自动铺 AGENT_FIRST_PROMPT 一次；进 demo 时复位（演示会清空 live 对话，
  // 回切 live 应重新起一次，不留空白接真台）。同一 live 会话里 effect 再跑不重复自动起、不冲掉用户对话。
  const didAutoStartLiveRef = useRef(false);
  // handoff 提交回执（真 /api/strategy/submit_candidate）。
  const [handoffNote, setHandoffNote] = useState<string | null>(null);
  // handoff 提交失败的诚实错误（§3：失败不显「已提交」绿，显红报错）。
  const [handoffError, setHandoffError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const anchorIds = useRef<Record<string, string>>({});

  /** 把剧本从 cursor 往后铺，遇到 pending gate 即停（等用户决策）。 */
  const advance = useCallback(() => {
    // 纯计算从 cursorRef 往后铺；所有 setState 在 updater 外单次执行，
    // 避免「setCursor updater 内调用其它 setState」被 StrictMode 双调而重复铺块。
    let i = cursorRef.current;
    const newBlocks: AgentBlock[] = [];
    const newReached: MilestoneKey[] = [];
    const newUnlock: CoworkKind[] = [];
    const gateUpdates: Record<string, "pending" | "resolved-once"> = {};
    let lastActive: MilestoneKey | null = null;
    let hitReport = false;
    let stop = false;

    while (i < AGENT_SCRIPT.length && !stop) {
      const ev = AGENT_SCRIPT[i];
      if (ev.ms) {
        newReached.push(ev.ms);
        lastActive = ev.ms;
        if (ev.cowork) anchorIds.current[ev.ms] = ev.id;
      }
      if (ev.unlock) {
        newUnlock.push(ev.unlock);
        if (ev.unlock === "run") hitReport = true;
      }
      newBlocks.push({ id: ev.id, ...ev.block });
      i += 1;
      // gate 事件：若需确认则停在此（块已铺、pending 等决策）。
      if (ev.block.type === "gate") {
        const se = ev.block.sideEffect ?? "none";
        const needs =
          se === "realmoney" || se === "external" || permMode === "ask";
        if (needs) {
          gateUpdates[ev.id] = "pending";
          stop = true;
        } else {
          gateUpdates[ev.id] = "resolved-once";
        }
      }
    }

    cursorRef.current = i;
    setCursor(i);
    if (newBlocks.length) setBlocks((b) => [...b, ...newBlocks]);
    if (newReached.length) {
      setReached((r) => Array.from(new Set([...r, ...newReached])));
      if (lastActive) setActiveMs(lastActive);
    }
    if (newUnlock.length)
      setUnlocked((u) => {
        const n = new Set(u);
        newUnlock.forEach((k) => n.add(k));
        return n;
      });
    if (Object.keys(gateUpdates).length)
      setGateStates((g) => ({ ...g, ...gateUpdates }));
    if (hitReport) setReportReady(true);
  }, [permMode]);

  // 「看演示」入口：mock autoplay 只在 demoMode 下铺到第一道 gate（StrictMode 双挂载守卫，只跑一次）。
  // 默认真实流（liveMode=true / demoMode=false）→ 不自动放 mock 剧本（DS-2 blocker #1：不放假绿灯 mock）。
  useEffect(() => {
    if (!demoMode) return;
    if (didInit.current) return;
    didInit.current = true;
    advance();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [demoMode]);

  // 进「看演示」：关 LIVE、开 demoMode、复位剧本游标后从头铺 mock。
  const enterDemo = useCallback(() => {
    liveAbort.current?.();
    liveAbort.current = null;
    setLiveMode(false);
    setLiveErr(null);
    setDemoMode(true);
    // 复位 live 自动起守卫：演示已清空 live 对话，回切 live 应重新自动起一次首条 prompt（M5）。
    didAutoStartLiveRef.current = false;
    // 复位游标，让 demoMode effect 的守卫能重新铺一遍（重复进出演示也稳定）。
    didInit.current = false;
    cursorRef.current = 0;
    setCursor(0);
    setBlocks([]);
    setReached([]);
    setActiveMs(null);
    setUnlocked(new Set());
    setGateStates({});
    anchorIds.current = {};
  }, []);

  // 回到真实流：关 demoMode、开 LIVE（liveMode effect 会启动真流）。
  const enterLive = useCallback(() => {
    setDemoMode(false);
    didInit.current = false;
    setLiveMode(true);
  }, []);

  // splitter 拖拽。
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const s = splitRef.current;
      if (!s) return;
      const w = Math.max(280, Math.min(760, s.w0 + (e.clientX - s.x0)));
      setChatW(w);
    };
    const up = () => {
      splitRef.current = null;
    };
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
    return () => {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
    };
  }, []);

  const restart = useCallback(() => {
    setCursor(0);
    cursorRef.current = 0;
    setBlocks([]);
    setReached([]);
    setActiveMs(null);
    setUnlocked(new Set());
    setGateStates({});
    setHandoffSubmitted(false);
    setHandoffNote(null);
    setHandoffError(null);
    setReportReady(false);
    setWsTab("cowork");
    setCoworkOverride(null);
    setDemoGate(null);
    setDemoGateState(null);
    setTeachPopup(null);
    setTeachNote(null);
    setPermMode("ask");
    setLiveRunId(null); // 重放回 mock 剧本：清旧真 run_id，裁决卡回 mock + MockBadge。
    anchorIds.current = {};
    // 下一帧重新铺。
    requestAnimationFrame(() => advance());
  }, [advance]);

  // gate 决策。
  const resolveGate = useCallback(
    (id: string, kind: "once" | "always" | "no") => {
      if (kind === "no") {
        setGateStates((g) => ({ ...g, [id]: "resolved-no" }));
        setBlocks((b) => [
          ...b,
          {
            id: "no-" + id,
            type: "say",
            text: "好的，已取消。要换 pessimistic 成本预设，还是先调因子集再回测？",
          },
        ]);
        return;
      }
      if (kind === "always") setPermMode("auto");
      setGateStates((g) => ({
        ...g,
        [id]: kind === "always" ? "resolved-always" : "resolved-once",
      }));
      // 批准后同步继续铺剩余剧本（cursor 已越过该 gate，advance 接着铺到下一道门/终点）。
      advance();
    },
    [advance],
  );

  // 里程碑跳转：切 cowork + 滚动锚点。
  const gotoMs = useCallback(
    (key: MilestoneKey) => {
      if (!reached.includes(key)) return;
      const def = MILESTONE_DEFS.find((m) => m.key === key);
      if (def) {
        setCoworkOverride(def.cowork);
        setWsTab("cowork");
      }
      const anchor = anchorIds.current[key];
      if (anchor) {
        requestAnimationFrame(() => {
          const el = document.getElementById("blk-" + anchor);
          const sc = scrollRef.current;
          if (el && sc) {
            sc.scrollTop +=
              el.getBoundingClientRect().top -
              sc.getBoundingClientRect().top -
              40;
          }
        });
      }
    },
    [reached],
  );

  // 真实流：启动真 SSE 流（替代 mock 剧本）。结构化事件投影成 blocks + 里程碑。
  const startLive = useCallback(
    (prompt: string) => {
      liveAbort.current?.();
      setLiveErr(null);
      setLiveRunId(null); // 新流重置：旧 run_id 不串到本次（回测产真前裁决卡走 mock）。
      setBlocks([]);
      setReached([]);
      setActiveMs(null);
      const reachedSet = new Set<MilestoneKey>();
      liveAbort.current = streamAgentWorkbench(prompt, permMode, {
        onBlock: (b) => setBlocks((prev) => [...prev, b]),
        onToolEnd: (result) => {
          // backtest.run 的 result 带真 run_id（business_tools 产真 run）→ 贯穿裁决卡。
          // 其它工具的 result 无 run_id；只在确为非空字符串时更新，避免误清真值。
          if (result && typeof result === "object") {
            const rid = (result as { run_id?: unknown }).run_id;
            if (typeof rid === "string" && rid) setLiveRunId(rid);
          }
          setBlocks((prev) => {
            // 更新最近 running tool 块的 summary（真实流结果）。
            const next = [...prev];
            for (let i = next.length - 1; i >= 0; i--) {
              if (next[i].type === "tool" && next[i].toolStatus === "running") {
                next[i] = {
                  ...next[i],
                  toolStatus: "done",
                  toolSummary:
                    typeof result === "object"
                      ? JSON.stringify(result).slice(0, 200)
                      : String(result),
                };
                break;
              }
            }
            return next;
          });
        },
        onMilestone: (key) => {
          reachedSet.add(key);
          setReached(Array.from(reachedSet));
          setActiveMs(key);
        },
        onDone: () => {
          liveAbort.current = null;
        },
        onError: (msg) => {
          setLiveErr(msg);
          liveAbort.current = null;
        },
      });
    },
    [permMode],
  );

  // LIVE 模式开关：开 → 跑真流；关 → 回 mock 剧本。
  // §M5：进 live 时仅自动铺 AGENT_FIRST_PROMPT 一次（didAutoStartLiveRef 守一次性）。
  // 同一 live 会话里 effect 再跑（如其它 state 变化触发）不重复自动起、不冲掉用户已发对话；
  // 进 demo 会复位该守卫，回切 live 重新起一次（演示已清空 live 对话，避免空白接真台）。
  useEffect(() => {
    if (liveMode) {
      if (!didAutoStartLiveRef.current) {
        didAutoStartLiveRef.current = true;
        startLive(AGENT_FIRST_PROMPT);
      }
    } else {
      liveAbort.current?.();
      liveAbort.current = null;
    }
    return () => {
      liveAbort.current?.();
      liveAbort.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveMode]);

  // 真实流：handoff 提交真调 /api/strategy/submit_candidate（止于模拟盘）。
  // §3 不假绿灯：仅后端【明确 ok】才显「已提交」；失败（未登录/网络/后端错）→
  // 不 submitted、显式报错（绝不「（mock 回执）已提交」伪成功）。
  const submitHandoff = useCallback(async () => {
    setHandoffNote(null);
    setHandoffError(null);
    try {
      const res = await authFetch("/api/strategy/submit_candidate", {
        method: "POST",
        body: JSON.stringify({
          run_id: "run_wk_cn_8f2a",
          name: "weekly_cn_multifactor",
          destination: "paper_desk",
          factor_set: "fs_core3",
          model_id: "lgbm_rank_6f@v2",
        }),
      });
      if (res.ok) {
        const body = await res.json();
        setHandoffSubmitted(true);
        setHandoffNote(
          `候选 ${body.candidate_id ?? ""} 已进模拟台候选池（destination=${body.destination}）。`,
        );
      } else {
        // 真端点不可用（如未登录 401 / 后端错）→ 失败显错，不伪「已提交」。
        setHandoffSubmitted(false);
        setHandoffError(
          `提交失败（HTTP ${res.status}）：需登录或后端不可用，候选未进模拟台。`,
        );
      }
    } catch {
      setHandoffSubmitted(false);
      setHandoffError("提交失败（网络不可用）：候选未进模拟台，请重试。");
    }
  }, []);

  const send = useCallback(() => {
    const d = draft.trim();
    if (!d) return;
    setDraft("");
    setSlashOpen(false);
    if (d === "/permissions") return;

    // 真实流态（默认）：消息驱动真流，不落任何 mock 块（§3 不假绿灯，blocker #1）。
    if (liveMode) {
      if (d === "/clear" || d === "/restart") {
        // 真流重置：清空并用首条 prompt 重起真 SSE 流。
        startLive(AGENT_FIRST_PROMPT);
        return;
      }
      // 用户真消息 → 重起真流（后端 user 事件会回显该消息，不前端伪造 ack）。
      startLive(d);
      return;
    }

    // 演示态（看演示 · mock 剧本）：保持原 mock 回放语义。
    if (d === "/clear" || d === "/restart") {
      restart();
      return;
    }
    setBlocks((b) => [
      ...b,
      { id: "u-" + Date.now(), type: "user", text: d },
      {
        id: "ack-" + Date.now(),
        type: "say",
        text: "（看演示 mock：策略台脚本已跑到回测拍板 + 模拟台交接。点「↻ 重放」或进度线节点回看。）",
      },
    ]);
  }, [draft, liveMode, restart, startLive]);

  const onDraftChange = useCallback((v: string) => {
    setDraft(v);
    setSlashOpen(v.startsWith("/"));
  }, []);

  // 当前 cowork。
  const cowork: CoworkKind | null = useMemo(() => {
    if (coworkOverride) return coworkOverride;
    const def = MILESTONE_DEFS.find((m) => m.key === activeMs);
    return def ? def.cowork : null;
  }, [coworkOverride, activeMs]);

  // 里程碑动态 sub。
  const subs = useMemo<Partial<Record<MilestoneKey, string>>>(() => {
    const s: Partial<Record<MilestoneKey, string>> = {};
    if (unlocked.has("factorSet")) s["因子集"] = "fs_core3";
    if (unlocked.has("model")) s["模型"] = "v2·staging";
    if (unlocked.has("run")) s["回测"] = "拍板✓";
    return s;
  }, [unlocked]);

  // 全剧本是否跑完（最后一个 say 已铺）→ 解锁 handoff。
  const scriptDone =
    cursor >= AGENT_SCRIPT.length &&
    !Object.values(gateStates).includes("pending");

  return (
    <DeskShell
      desk="agent"
      topbar={
        <DeskTopBar>
          <DeskSwitcher current="agent" soon={[]} />
          <span
            style={{
              color: "var(--desk-text-faint)",
              fontSize: 11,
              marginLeft: 4,
            }}
          >
            ~/strategies/weekly-cn
          </span>
          <div style={{ flex: 1 }} />
          {/* 默认真实流（DS-2）：LIVE = 真 /api/agent/workbench/stream；「演示」= 显式 mock 剧本回放。
              切到演示即关 LIVE、挂 MockBadge（诚实角标）；回 LIVE 即关演示、起真流。 */}
          <button
            data-live-toggle
            data-demo-toggle
            aria-pressed={liveMode}
            onClick={() => (liveMode ? enterDemo() : enterLive())}
            title={
              liveMode
                ? "切到「看演示」：mock 剧本回放（全程 MockBadge，不是真流）"
                : "回到真实流：/api/agent/workbench/stream"
            }
            style={{
              background: liveMode ? "var(--desk-accent)" : "transparent",
              border: "1px solid var(--desk-border)",
              color: liveMode ? "var(--desk-canvas)" : "var(--desk-text-muted)",
              fontFamily: "inherit",
              fontWeight: liveMode ? 700 : 400,
              fontSize: 10,
              padding: "4px 9px",
              borderRadius: "var(--desk-radius-sm)",
              cursor: "pointer",
            }}
          >
            {liveMode ? "● LIVE · 真实流" : "▶ 演示回放（mock）"}
          </button>
          {liveMode ? (
            <span
              data-live-badge
              style={{
                fontSize: 10,
                color: "var(--desk-accent)",
                fontWeight: 700,
              }}
            >
              LIVE
            </span>
          ) : (
            <MockBadge />
          )}
          {/* 「↻ 重放」仅在演示模式有意义（重铺 mock 剧本）；真实流隐藏（由消息推进）。 */}
          {demoMode && (
            <button
              onClick={restart}
              style={{
                background: "transparent",
                border: "1px solid var(--desk-border)",
                color: "var(--desk-text-muted)",
                fontFamily: "inherit",
                fontSize: 11,
                padding: "5px 10px",
                borderRadius: "var(--desk-radius-sm)",
                cursor: "pointer",
              }}
            >
              ↻ 重放
            </button>
          )}
        </DeskTopBar>
      }
      center={
        <>
          <SubTabBar<"workbench" | "coach">
            tabs={[
              { value: "workbench", label: "工作台" },
              { value: "coach", label: "诊断台" },
            ]}
            value={view}
            onChange={setView}
          />
          {view === "coach" ? (
            <div style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
              <Mode2ChatPage />
            </div>
          ) : (
            <>
              <MilestoneLadder
                reached={reached}
                active={activeMs}
                subs={subs}
                onGoto={gotoMs}
              />
          <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
            {/* LEFT · CHAT */}
            <CollapsiblePanel
              open={chatOpen}
              onToggle={() => setChatOpen((o) => !o)}
              side="left"
              width={wsOpen ? chatW : 9999}
              label="对话"
            >
              <div
                ref={scrollRef}
                style={{ flex: 1, minHeight: 0, overflowY: "auto" }}
                data-chat-scroll
              >
                <div style={{ padding: "8px 16px" }}>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--desk-text-faint)",
                      marginBottom: 8,
                    }}
                  >
                    上下文 · {CTX_USED}.0k / 200k
                  </div>
                  {liveMode && liveErr && (
                    <div
                      data-live-error
                      style={{
                        margin: "0 0 10px",
                        padding: "8px 11px",
                        fontSize: 11.5,
                        color: "var(--desk-danger)",
                        border: "1px solid var(--desk-danger)",
                        borderRadius: "var(--desk-radius-sm)",
                        background:
                          "color-mix(in srgb, var(--desk-danger) 8%, transparent)",
                      }}
                    >
                      实时流错误（诚实呈现，不假绿灯）：{liveErr}
                    </div>
                  )}
                  {blocks.map((b) => (
                    <div id={"blk-" + b.id} key={b.id}>
                      {b.type === "gate" ? (
                        <GateBlockSlot
                          block={b}
                          state={gateStates[b.id]}
                          permMode={permMode}
                          onResolve={resolveGate}
                        />
                      ) : (
                        <ChatBubbleRow block={b} />
                      )}
                    </div>
                  ))}

                  {/* D-PERM 反例 gate（手动注入，证明 bypass 也拦真钱/external）。 */}
                  {demoGate && (
                    <div id="blk-demo-gate">
                      <GatePanel
                        gateTool={PERM_DEMO_GATES[demoGate].gateTool}
                        sideEffect={PERM_DEMO_GATES[demoGate].sideEffect}
                        gateBlurb={PERM_DEMO_GATES[demoGate].gateBlurb}
                        governanceWeakness={
                          PERM_DEMO_GATES[demoGate].governanceWeakness
                        }
                        permMode={permMode}
                        onApproveOnce={() => {
                          setDemoGateState("resolved-once");
                          setDemoGate(null);
                        }}
                        onApproveAlways={() => {
                          setPermMode("auto");
                          setDemoGateState("resolved-always");
                          setDemoGate(null);
                        }}
                        onReject={() => {
                          setDemoGateState("resolved-no");
                          setDemoGate(null);
                        }}
                      />
                    </div>
                  )}
                  {demoGateState && (
                    <div
                      style={{
                        margin: "0 0 10px 18px",
                        fontSize: 11.5,
                        color: "var(--desk-text-dim)",
                      }}
                    >
                      D-PERM 反例已记录：治理门按受控 side_effect 拦截，与权限模式无关。
                    </div>
                  )}

                  {/* T-041 教学文案弹窗（硬透明 + 软决定）。 */}
                  <div style={{ marginLeft: 18 }}>
                    {teachPopup === "falsifiability" && (
                      <FalsifiabilityGuide
                        tool={MOCK_FALSIFIABILITY_GUIDE.tool}
                        confidence={MOCK_FALSIFIABILITY_GUIDE.confidence}
                        flags={MOCK_FALSIFIABILITY_GUIDE.flags}
                        cardMissing={MOCK_FALSIFIABILITY_GUIDE.cardMissing}
                        onFillCard={() => {
                          setTeachPopup(null);
                          setTeachNote(
                            "已切到立题 · 假设卡：补可证伪条件后再跑确证回测。",
                          );
                          setCoworkOverride("hypothesis");
                          setWsTab("cowork");
                        }}
                        onAcknowledge={() => {
                          setTeachPopup(null);
                          setTeachNote(
                            "已知情：可证伪 confidence=low 仍要跑确证回测，已记进 honest-N 账本（needs_human_review）。",
                          );
                        }}
                        onCancel={() => {
                          setTeachPopup(null);
                          setTeachNote("已取消本次确证回测。");
                        }}
                      />
                    )}
                    {teachPopup === "provenance" && (
                      <ProvenanceAck
                        destination={MOCK_PROVENANCE_ACK.destination}
                        unverified={MOCK_PROVENANCE_ACK.unverified}
                        onGoFactorDesk={() => {
                          setTeachPopup(null);
                          setTeachNote(
                            "已记录：回因子台补血统流程（假设卡→独立验证→审批）。",
                          );
                        }}
                        onAcknowledge={() => {
                          setTeachPopup(null);
                          setTeachNote(
                            "已知情确认：因子血统未过治理流程仍上线，acknowledge 已留痕进审计。",
                          );
                        }}
                        onCancel={() => {
                          setTeachPopup(null);
                          setTeachNote("已取消本次上线。");
                        }}
                      />
                    )}
                    {teachPopup === "redVerdict" && (
                      <RedVerdictAck
                        subject={MOCK_RED_VERDICT.subject}
                        verdictNote={MOCK_RED_VERDICT.verdictNote}
                        weaknesses={MOCK_RED_VERDICT.weaknesses}
                        onViewEvidence={() => {
                          setTeachPopup(null);
                          setTeachNote("已切到回测产物：下钻看完整证据。");
                          setCoworkOverride("run");
                          setWsTab("cowork");
                        }}
                        onAcknowledge={() => {
                          setTeachPopup(null);
                          setTeachNote(
                            "已知情：验证官 red 裁决与弱点已读，acknowledge 已留痕。",
                          );
                        }}
                        onCancel={() => {
                          setTeachPopup(null);
                          setTeachNote("已取消。");
                        }}
                      />
                    )}
                    {teachNote && (
                      <div
                        data-testid="teach-note"
                        style={{
                          margin: "0 0 10px",
                          fontSize: 11.5,
                          color: "var(--desk-text-dim)",
                        }}
                      >
                        {teachNote}
                      </div>
                    )}
                  </div>

                  {/* handoff（剧本跑完才出，终点止于模拟台）。提交真调 submit_candidate 端点。 */}
                  {scriptDone && reportReady && (
                    <div id="blk-handoff">
                      <HandoffCard
                        submitted={handoffSubmitted}
                        onSubmit={submitHandoff}
                      />
                      {handoffNote && (
                        <div
                          data-handoff-note
                          style={{
                            margin: "4px 0 10px 18px",
                            fontSize: 11.5,
                            color: "var(--desk-text-dim)",
                          }}
                        >
                          {handoffNote}
                        </div>
                      )}
                      {/* §3 失败诚实呈现：未提交成功时显红，绝不伪「已提交」。 */}
                      {handoffError && (
                        <div
                          data-handoff-error
                          data-testid="handoff-error"
                          role="alert"
                          style={{
                            margin: "4px 0 10px 18px",
                            padding: "8px 11px",
                            fontSize: 11.5,
                            color: "var(--desk-danger)",
                            border: "1px solid var(--desk-danger)",
                            borderRadius: "var(--desk-radius-sm)",
                            background:
                              "color-mix(in srgb, var(--desk-danger) 8%, transparent)",
                          }}
                        >
                          {handoffError}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* INPUT + STATUS */}
              <div>
                {slashOpen && (
                  <div
                    data-slash-panel
                    style={{
                      margin: "8px 13px 0",
                      background: "var(--desk-topbar)",
                      border: "1px solid var(--desk-border-strong)",
                      borderRadius: "var(--desk-radius-lg)",
                      overflow: "hidden",
                    }}
                  >
                    {SLASH_CMDS.map((s) => (
                      <button
                        key={s.cmd}
                        onClick={() => {
                          setDraft(s.cmd);
                          setSlashOpen(false);
                        }}
                        style={{
                          display: "flex",
                          gap: 10,
                          padding: "7px 12px",
                          width: "100%",
                          cursor: "pointer",
                          border: "none",
                          borderBottom: "1px solid var(--desk-border)",
                          background: "transparent",
                          fontFamily: "inherit",
                          textAlign: "left",
                        }}
                      >
                        <span
                          style={{
                            color: "var(--desk-accent)",
                            minWidth: 96,
                            fontSize: 12.5,
                          }}
                        >
                          {s.cmd}
                        </span>
                        <span
                          style={{
                            color: "var(--desk-text-muted)",
                            fontSize: 11.5,
                          }}
                        >
                          {s.desc}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
                {/* 权限三态切换（受控 · 显式 UI，对齐后端 permission_mode）。 */}
                <div
                  data-perm-switch
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "8px 13px 0",
                  }}
                >
                  <span
                    style={{ fontSize: 10, color: "var(--desk-text-faint)" }}
                  >
                    权限
                  </span>
                  <SegmentedControl<PermissionMode>
                    size="sm"
                    value={permMode}
                    onChange={setPermMode}
                    options={[
                      { value: "ask", label: "ask" },
                      { value: "auto", label: "auto" },
                      { value: "bypass", label: "bypass" },
                    ]}
                  />
                  <div style={{ flex: 1 }} />
                  {/* D-PERM 反例触发器：注入真钱/external gate。 */}
                  <button
                    data-demo-realmoney
                    onClick={() => {
                      setDemoGate("realmoney");
                      setDemoGateState(null);
                    }}
                    title="演示：side_effect=realmoney 即便 bypass/auto 仍弹确认"
                    style={demoBtnStyle()}
                  >
                    ⛔ 真钱反例
                  </button>
                  <button
                    data-demo-external
                    onClick={() => {
                      setDemoGate("external");
                      setDemoGateState(null);
                    }}
                    title="演示：side_effect=external 治理门不随权限放宽"
                    style={demoBtnStyle()}
                  >
                    ↗ external 反例
                  </button>
                </div>
                {/* T-041 教学文案弹窗触发器（硬透明 + 软决定，绝不死挡）。 */}
                <div
                  data-teach-triggers
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    padding: "6px 13px 0",
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{ fontSize: 10, color: "var(--desk-text-faint)" }}
                  >
                    教学
                  </span>
                  <button
                    data-teach-falsifiability
                    onClick={() => {
                      setTeachPopup("falsifiability");
                      setTeachNote(null);
                    }}
                    title="可证伪 confidence=low：确证回测前的引导（非死挡）"
                    style={demoBtnStyle()}
                  >
                    ⚠ 可证伪引导
                  </button>
                  <button
                    data-teach-provenance
                    onClick={() => {
                      setTeachPopup("provenance");
                      setTeachNote(null);
                    }}
                    title="实盘因子血统未过治理流程：知情确认（留痕，非死挡）"
                    style={demoBtnStyle()}
                  >
                    ⛔ 血统警告
                  </button>
                  <button
                    data-teach-red-verdict
                    onClick={() => {
                      setTeachPopup("redVerdict");
                      setTeachNote(null);
                    }}
                    title="验证官 red 裁决：一等呈现 + 知情确认"
                    style={demoBtnStyle()}
                  >
                    ● red 裁决
                  </button>
                </div>
                <ChatComposer
                  draft={draft}
                  onDraftChange={onDraftChange}
                  onSend={send}
                  placeholder="回复，或 / 命令…"
                  model={MODEL}
                  permissionMode={permMode}
                  branch={BRANCH}
                />
              </div>
            </CollapsiblePanel>

            {/* SPLITTER */}
            {chatOpen && wsOpen && (
              <div
                data-splitter
                onPointerDown={(e) => {
                  e.preventDefault();
                  splitRef.current = { x0: e.clientX, w0: chatW };
                }}
                style={{
                  flex: "none",
                  width: 5,
                  cursor: "col-resize",
                  background: "var(--desk-border-soft)",
                  alignSelf: "stretch",
                }}
              />
            )}

            {/* RIGHT · WORKSPACE */}
            <CollapsiblePanel
              open={wsOpen}
              onToggle={() => setWsOpen((o) => !o)}
              side="right"
              width={9999}
              label="产物工作区"
            >
              <WorkspaceInner
                tab={wsTab}
                onTab={setWsTab}
                reportReady={reportReady}
                cowork={cowork}
                unlocked={unlocked}
                reached={reached}
                liveRunId={liveRunId ?? undefined}
                liveMode={liveMode}
                liveError={liveErr ?? undefined}
                onClose={() => setWsOpen(false)}
              />
            </CollapsiblePanel>
          </div>
            </>
          )}
        </>
      }
    />
  );
}

function demoBtnStyle(): React.CSSProperties {
  return {
    background: "transparent",
    border: "1px solid var(--desk-border)",
    color: "var(--desk-text-muted)",
    fontFamily: "inherit",
    fontSize: 10,
    padding: "3px 8px",
    borderRadius: "var(--desk-radius-sm)",
    cursor: "pointer",
  };
}

/** 普通对话块（非 gate）——直接复用 G3 AgentChat 的逐条渲染。 */
function ChatBubbleRow({ block }: { block: AgentBlock }) {
  // 复用 AgentChat 的单块渲染：用单元素 blocks 包一层，复用 ChatBubble + ↗ 链接行为。
  return <AgentChat blocks={[block]} />;
}

/** gate 块：按解析态渲染 GatePanel（pending）或回执文案（resolved）。 */
function GateBlockSlot({
  block,
  state,
  permMode,
  onResolve,
}: {
  block: AgentBlock;
  state: GateState | undefined;
  permMode: PermissionMode;
  onResolve: (id: string, kind: "once" | "always" | "no") => void;
}) {
  if (state === "pending" || state === undefined) {
    return (
      <GatePanel
        gateTool={block.gateTool ?? ""}
        sideEffect={block.sideEffect ?? "none"}
        gateBlurb={block.gateBlurb ?? ""}
        governanceWeakness={block.governanceWeakness}
        permMode={permMode}
        onApproveOnce={() => onResolve(block.id, "once")}
        onApproveAlways={() => onResolve(block.id, "always")}
        onReject={() => onResolve(block.id, "no")}
      />
    );
  }
  const note: Record<Exclude<GateState, "pending">, ReactNode> = {
    "resolved-once": (
      <span style={{ color: "var(--desk-success)" }}>✓ 已批准本次执行。</span>
    ),
    "resolved-always": (
      <span style={{ color: "var(--desk-success)" }}>
        ✓ 已批准，{block.gateTool} 不再询问（→auto）。
      </span>
    ),
    "resolved-no": (
      <span style={{ color: "var(--desk-danger)" }}>✗ 已拒绝，等待新指示。</span>
    ),
  };
  return (
    <div
      style={{
        margin: "8px 0 8px 18px",
        fontSize: 12.5,
      }}
    >
      {note[state]}
    </div>
  );
}

/** 工作区内部：tab 栏 + 内容（cowork / code / report）。 */
function WorkspaceInner({
  tab,
  onTab,
  reportReady,
  cowork,
  unlocked,
  reached,
  liveRunId,
  liveMode,
  liveError,
  onClose,
}: {
  tab: WorkspaceTab;
  onTab: (t: WorkspaceTab) => void;
  reportReady: boolean;
  cowork: CoworkKind | null;
  unlocked: Set<CoworkKind>;
  reached: MilestoneKey[];
  /** 真回测 run_id（LIVE 流产），贯穿到裁决卡真实端点；缺省走 mock + MockBadge。 */
  liveRunId?: string;
  /** 接真态标记：LIVE 态无 run_id 时裁决卡显诚实空态/错态，不退 mock 绿（§3）。 */
  liveMode?: boolean;
  /** 接真态回测失败原因：有则裁决卡显诚实错态。 */
  liveError?: string;
  onClose: () => void;
}) {
  const hint =
    tab === "cowork"
      ? "实时产物 · 点对话 ↗ 或进度线节点切换"
      : tab === "code"
        ? "可复现配置 · 随进度累积"
        : "回测报告";
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        display: "flex",
        flexDirection: "column",
        background: "var(--desk-canvas)",
        width: "100%",
      }}
    >
      <div
        style={{
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 3,
          padding: "7px 14px",
          borderBottom: "1px solid var(--desk-border)",
          background: "var(--desk-card)",
        }}
      >
        <WsTab on={tab === "cowork"} onClick={() => onTab("cowork")}>
          ◳ 产物
        </WsTab>
        <WsTab on={tab === "code"} onClick={() => onTab("code")}>
          ⌨ Strategy.yaml
        </WsTab>
        {reportReady && (
          <WsTab on={tab === "report"} onClick={() => onTab("report")}>
            ▤ Report.md
          </WsTab>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>
          {hint}
        </span>
        <Pill tone="mock">MOCK</Pill>
        <button
          onClick={onClose}
          aria-label="收起产物工作区"
          style={{
            marginLeft: 8,
            fontSize: 13,
            color: "var(--desk-text-faint)",
            cursor: "pointer",
            background: "transparent",
            border: "none",
            fontFamily: "inherit",
          }}
        >
          ›
        </button>
      </div>
      <div
        style={{
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: "18px 20px",
        }}
      >
        {tab === "cowork" && (
          <CoworkArea
            cowork={cowork}
            unlocked={unlocked}
            liveRunId={liveRunId}
            liveMode={liveMode}
            liveError={liveError}
          />
        )}
        {tab === "code" && <CodeView reached={reached} />}
        {tab === "report" && reportReady && <ReportView />}
      </div>
    </div>
  );
}

function WsTab({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      aria-selected={on}
      style={{
        background: on ? "var(--desk-hover)" : "transparent",
        color: on ? "var(--desk-text)" : "var(--desk-text-dim)",
        border: "none",
        fontFamily: "inherit",
        fontSize: 11.5,
        padding: "5px 12px",
        borderRadius: "var(--desk-radius-sm)",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}
