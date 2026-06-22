import {
  type CSSProperties,
  type PointerEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  DeskShell,
  DeskTopBar,
  DeskSwitcher,
  SegmentedControl,
  CollapsiblePanel,
  Pill,
  MockBadge,
  GraphCanvas,
  CanvasControls,
  CanvasBanner,
  MiniMap,
  type Selection,
  type Viewport,
  type PortRef,
  type MarqueeRect,
  AgentChat,
  type AgentBlock,
  ChatComposer,
  type PermissionMode,
  Inspector,
  InspectorTabs,
  type InspectorTab,
  ParamRow,
  Dock,
  DockTabs,
  type DockTab,
  SubTabBar,
  clampZoom,
  BUTTON_ZOOM_FACTOR,
  zoomAt,
} from "../components/desk";
import { StrategyWorkshopPage } from "./workshop/StrategyWorkshopPage";
import { IDEPage } from "./workshop/IDEPage";
import { StrategyTemplatesPage } from "./StrategyTemplatesPage";
import {
  MOCK_NODES,
  MOCK_EDGES,
  MOCK_PROPOSAL,
  MOCK_AUTO_NODE,
  MOCK_TRADES,
  MOCK_RUNS,
  MOCK_VERSIONS,
  MOCK_CONTRIBUTION,
  STAGES,
  toNodeView,
  toEdgeView,
  type DomainNode,
  type DomainEdge,
} from "./strategy/mockGraph";
import {
  validateGraph,
  nodeIssues,
  canDelete,
  type ValidationIssue,
  type GraphValidation,
} from "./strategy/graphLogic";
import {
  validateStrategyGraph,
  fetchStrategyVersions,
  forkStrategy,
  fetchLiveSnapshot,
  type BackendVersion,
  type BackendLiveSnapshot,
} from "./strategy/api";

/** runtime 三态（DC runtime：backtest/paper/live）。 */
type Runtime = "backtest" | "paper" | "live";

/**
 * 策略台顶层子视图（SubTabBar）：
 * "console"（默认）= 现有编排画布；其余三个为旧页内嵌（需求录入/代码 IDE/模板起步）。
 */
type ConsoleView = "console" | "intake" | "ide" | "templates";

/** 当前策略名（顶栏 · 对接后端 owner 命名空间下的策略）。 */
const STRATEGY_NAME = "strat_wk_cn_01";

/** mock 当前回测 run_id（backtest 节点血缘）。 */
const CURRENT_RUN_ID = "run_wk_cn_8f2a";

/** 把 DomainNode[] 转成字典。 */
function toDict(arr: DomainNode[]): Record<string, DomainNode> {
  const d: Record<string, DomainNode> = {};
  for (const n of arr) d[n.id] = { ...n, params: { ...n.params } };
  return d;
}

/**
 * 策略台（StrategyConsole · DC parseConsole.md 全文还原，P0 mock 驱动）。
 *
 * data-desk="strategy"（橙 accent）。四区：顶栏 + 左 AgentChat(316) + 中 GraphCanvas
 * + 右 Inspector(340) + 底 Dock(228 默认折叠)。治理三态门硬强制（B6）：
 *  删除门 locked / 校验门 exec 经 gate / 连线门 role=exec 来源限 approvedPortfolio。
 * runtime=live → 画布只读 + 参数 disabled + 🔒Live只读 banner。
 * agentMode=bypass → 治理 gate 仍拦（权限轴 ⟂ 治理轴，不跳门）。
 */
export function StrategyConsolePage() {
  const navigate = useNavigate();

  // ── 图数据 ──
  const [nodes, setNodes] = useState<Record<string, DomainNode>>(() => toDict(MOCK_NODES));
  const [edges, setEdges] = useState<DomainEdge[]>(() => MOCK_EDGES.map((e) => ({ ...e })));
  const [selection, setSelection] = useState<Selection>({ nodeIds: [], edgeIds: [] });

  // ── 视口 ──
  const [pan, setPan] = useState({ x: 44, y: 70 });
  const [zoom, setZoom] = useState(0.72);
  const [marquee, setMarquee] = useState<MarqueeRect | null>(null);

  // ── 顶层子视图（默认 console = 现有编排 UI，保持原状）──
  const [view, setView] = useState<ConsoleView>("console");

  // ── 模式/运行态 ──
  const [agentMode, setAgentMode] = useState<PermissionMode>("ask");
  const [runtime, setRuntime] = useState<Runtime>("backtest");
  const readOnly = runtime === "live";

  // ── 面板开合 ──
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [dockOpen, setDockOpen] = useState(false);
  const [inspTab, setInspTab] = useState<InspectorTab>("params");
  const [dockTab, setDockTab] = useState<DockTab>("preview");

  // ── Agent ──
  const [draft, setDraft] = useState("");
  const [blocks, setBlocks] = useState<AgentBlock[]>(() => [
    { id: "b1", type: "user", text: "组装 A股周频多因子策略：超额15% / 回撤≤20%，从因子台和 Model台选资产，跑回测。" },
    { id: "b2", type: "think", text: "立题→市场&标的(独立)→数据→因子集(因子台)→Model(Registry引用)→信号→入场退出→仓位优化→PortfolioRisk→FinalRiskGate→执行→回测。" },
    { id: "b3", type: "say", text: "已搭好完整链路（16 节点 / 19 连线），端口全兼容、Final Risk Gate 不可绕过。我还有一条改进建议 ↓（Ask 模式：先看 Ghost 预览再决定）。" },
  ]);
  const [proposalLive, setProposalLive] = useState(true);

  // ── 治理/版本 ──
  const [verMenuOpen, setVerMenuOpen] = useState(false);
  const [diffOn, setDiffOn] = useState(false);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [killArmed, setKillArmed] = useState(true);
  const [ver, setVer] = useState("v3 草稿");

  // ── Undo/Redo（{nodes,edges} 快照栈，视口不进栈）──
  const undoStack = useRef<{ nodes: Record<string, DomainNode>; edges: DomainEdge[] }[]>([]);
  const redoStack = useRef<{ nodes: Record<string, DomainNode>; edges: DomainEdge[] }[]>([]);
  const [, forceTick] = useState(0);

  const surfSize = useRef({ w: 1000, h: 600 });

  function snapshot(): void {
    undoStack.current.push({
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    });
    if (undoStack.current.length > 60) undoStack.current.shift();
    redoStack.current = [];
    forceTick((t) => t + 1);
  }

  // 本地（渲染期 derived）校验：常驻、即时；后端校验是权威复核（runValidate 触发）。
  const localValidation = useMemo(() => validateGraph(nodes, edges), [nodes, edges]);
  // 后端权威校验结果（接真）；null = 尚未向后端复核过，用本地结果兜底显示。
  const [backendValidation, setBackendValidation] = useState<GraphValidation | null>(null);
  const [validateErr, setValidateErr] = useState<string | null>(null);
  // 图一变，旧的后端校验即失效（防显示过期绿灯）——回落本地常驻校验。
  useEffect(() => {
    setBackendValidation(null);
  }, [nodes, edges]);
  const validation = backendValidation ?? localValidation;

  // ── 版本史（接真：GET .../versions）──
  const [versions, setVersions] = useState<BackendVersion[] | null>(null);
  const [versionsErr, setVersionsErr] = useState<string | null>(null);

  // ── Live 只读快照（接真：GET .../live_snapshot；A股 live 永拒）──
  const [liveSnap, setLiveSnap] = useState<BackendLiveSnapshot | null>(null);
  const [liveErr, setLiveErr] = useState<string | null>(null);

  const nodeViews = useMemo(() => Object.values(nodes).map(toNodeView), [nodes]);
  const edgeViews = useMemo(() => edges.map(toEdgeView), [edges]);

  const selNode = selection.nodeIds.length === 1 ? nodes[selection.nodeIds[0]] : undefined;

  // ── 血缘链路（选中成交时高亮 path）──
  const trace = traceId ? MOCK_TRADES.find((t) => t.id === traceId) ?? null : null;

  // ── 视口回调 ──
  const onZoomVp = useCallback((vp: Viewport) => {
    setPan({ x: vp.panX, y: vp.panY });
    setZoom(vp.zoom);
  }, []);
  function zoomBy(factor: number): void {
    const anchor = { x: surfSize.current.w / 2, y: surfSize.current.h / 2 };
    onZoomVp(zoomAt({ panX: pan.x, panY: pan.y, zoom }, anchor, factor));
  }
  function fit(): void {
    const ns = Object.values(nodes);
    if (ns.length === 0) return;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of ns) {
      minX = Math.min(minX, n.x);
      minY = Math.min(minY, n.y);
      maxX = Math.max(maxX, n.x + n.w);
      maxY = Math.max(maxY, n.y + 90);
    }
    const w = surfSize.current.w, h = surfSize.current.h;
    const z = clampZoom(Math.min((w - 80) / (maxX - minX), (h - 80) / (maxY - minY), 1.4));
    setZoom(z);
    setPan({ x: (w - (maxX - minX) * z) / 2 - minX * z, y: (h - (maxY - minY) * z) / 2 - minY * z });
  }

  // ── 选中 ──
  const selectNode = useCallback((id: string) => {
    setSelection({ nodeIds: [id], edgeIds: [] });
    setRightOpen(true);
  }, []);
  const selectEdge = useCallback((id: string) => {
    setSelection({ nodeIds: [], edgeIds: [id] });
  }, []);

  // ── 节点拖拽（live 只读时不动）──
  const dragRef = useRef<{ id: string; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const onNodeMove = useCallback(
    (id: string, e: PointerEvent<HTMLDivElement>) => {
      e.stopPropagation();
      if (selection.nodeIds[0] !== id) setSelection({ nodeIds: [id], edgeIds: [] });
      if (readOnly) return; // Live 只读：节点不可拖
      const n = nodes[id];
      dragRef.current = { id, sx: e.clientX, sy: e.clientY, ox: n.x, oy: n.y, moved: false };
      const onMove = (ev: globalThis.PointerEvent) => {
        const d = dragRef.current;
        if (!d) return;
        const dx = (ev.clientX - d.sx) / zoom;
        const dy = (ev.clientY - d.sy) / zoom;
        if (Math.abs(ev.clientX - d.sx) + Math.abs(ev.clientY - d.sy) > 3) d.moved = true;
        setNodes((prev) => ({ ...prev, [d.id]: { ...prev[d.id], x: d.ox + dx, y: d.oy + dy } }));
      };
      const onUp = () => {
        if (dragRef.current?.moved) snapshot();
        dragRef.current = null;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [nodes, zoom, readOnly, selection.nodeIds],
  );

  // ── 连线（live 只读时不起线；端口门 compat=bad 不建边）──
  const onConnect = useCallback(
    (_ref: PortRef, _side: "in" | "out") => {
      if (readOnly) return;
      // P0：连线门已在 compat() 编码；交互建边走 marquee/手势在后续轮接真，
      // 此处保留回调签名以满足 GraphCanvas 受控契约。
    },
    [readOnly],
  );

  // ── 框选 ──
  const onMarquee = useCallback((rect: MarqueeRect) => {
    setMarquee(rect);
  }, []);

  // ── Undo/Redo ──
  function undo(): void {
    const snap = undoStack.current.pop();
    if (!snap) return;
    redoStack.current.push({
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    });
    setNodes(snap.nodes);
    setEdges(snap.edges);
    setSelection({ nodeIds: [], edgeIds: [] });
    forceTick((t) => t + 1);
  }
  function redo(): void {
    const snap = redoStack.current.pop();
    if (!snap) return;
    undoStack.current.push({
      nodes: JSON.parse(JSON.stringify(nodes)),
      edges: JSON.parse(JSON.stringify(edges)),
    });
    setNodes(snap.nodes);
    setEdges(snap.edges);
    setSelection({ nodeIds: [], edgeIds: [] });
    forceTick((t) => t + 1);
  }
  const canUndo = undoStack.current.length > 0;
  const canRedo = redoStack.current.length > 0;

  // ── 删除门（B6）：locked 节点跳过，不可删 ──
  const deleteSelection = useCallback(() => {
    if (readOnly) return;
    const delIds = selection.nodeIds.filter((id) => canDelete(nodes[id]));
    if (delIds.length === 0 && selection.edgeIds.length === 0) return;
    snapshot();
    setNodes((prev) => {
      const next = { ...prev };
      for (const id of delIds) delete next[id];
      return next;
    });
    setEdges((prev) =>
      prev.filter(
        (e) =>
          !selection.edgeIds.includes(e.id) &&
          !delIds.includes(e.from.node) &&
          !delIds.includes(e.to.node),
      ),
    );
    setSelection({ nodeIds: [], edgeIds: [] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [readOnly, selection, nodes, edges]);

  // Del/Backspace 删选中（删除门：locked 节点跳过）。
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (e.key === "Delete" || e.key === "Backspace") deleteSelection();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deleteSelection]);

  // ── 打开回测详情：单段 navigate('/runs/:runId')（不嵌 RunDetailPage）──
  const openRunDetail = useCallback(
    (runId: string) => {
      navigate(`/runs/${runId}`);
    },
    [navigate],
  );

  // ── 参数编辑（live 只读 / locked 时 ParamRow disabled，此处只在可编辑时入栈）──
  function setParam(nodeId: string, k: string, v: string): void {
    snapshot();
    setNodes((prev) => {
      const n = prev[nodeId];
      const nextState = n.state === "succeeded" ? n.state : "dirty";
      return { ...prev, [nodeId]: { ...n, params: { ...n.params, [k]: v }, state: nextState } };
    });
  }

  // ── Agent send：ask→重挂提议；auto/bypass→事务化加 DrawdownGuard + 可整轮撤销 ──
  function sendAgent(): void {
    const text = draft.trim();
    if (!text) return;
    setDraft("");
    const uid = `u${Date.now()}`;
    setBlocks((prev) => [...prev, { id: uid, type: "user", text }]);
    if (agentMode === "ask") {
      setProposalLive(true);
      setBlocks((prev) => [
        ...prev,
        { id: `s${Date.now()}`, type: "say", text: "已生成提议（Ghost 预览）：先看画布虚线，再决定接受/拒绝。" },
      ]);
    } else {
      applyAuto();
    }
  }

  // ── 接受提议（Ask）：入栈 → 应用 ops → 清提议 → 追加 patch 块 ──
  function acceptProposal(): void {
    snapshot();
    applyOps();
    setProposalLive(false);
    setBlocks((prev) => [
      ...prev,
      {
        id: `p${Date.now()}`,
        type: "patch",
        patchTitle: MOCK_PROPOSAL.title,
        patchId: MOCK_PROPOSAL.patchId,
        affected: "3 处（+1 节点 / +1 连线 / ~1 参数）",
        diff: MOCK_PROPOSAL.diff,
      },
    ]);
  }
  function rejectProposal(): void {
    setProposalLive(false);
    setBlocks((prev) => [
      ...prev,
      { id: `r${Date.now()}`, type: "say", text: "已拒绝该提议，草稿保持不变。" },
    ]);
  }

  /** 应用 MOCK_PROPOSAL.ops（addNode/addEdge/setParam）。 */
  function applyOps(): void {
    setNodes((prev) => {
      const next = { ...prev };
      for (const op of MOCK_PROPOSAL.ops) {
        if (op.op === "addNode") next[op.node.id] = { ...op.node, params: { ...op.node.params } };
        if (op.op === "setParam" && next[op.node]) {
          next[op.node] = { ...next[op.node], params: { ...next[op.node].params, [op.k]: op.v } };
        }
      }
      return next;
    });
    setEdges((prev) => {
      const next = [...prev];
      for (const op of MOCK_PROPOSAL.ops) {
        if (op.op === "addEdge" && !next.some((e) => e.id === op.edge.id)) next.push({ ...op.edge });
      }
      return next;
    });
  }

  // ── Auto/Bypass：事务化加 DrawdownGuard，对话里可整轮撤销 ──
  function applyAuto(): void {
    snapshot();
    setNodes((prev) =>
      prev[MOCK_AUTO_NODE.id]
        ? prev
        : { ...prev, [MOCK_AUTO_NODE.id]: { ...MOCK_AUTO_NODE, params: { ...MOCK_AUTO_NODE.params } } },
    );
    setBlocks((prev) => [
      ...prev,
      {
        id: `auto${Date.now()}`,
        type: "patch",
        patchTitle: "自动加 回撤护栏 DrawdownGuard",
        patchId: "pt_auto",
        affected: "1 处（+1 节点，事务化）",
        diff: [{ sign: "+", text: "DrawdownGuard（滚动回撤>12% 降杠杆）" }],
      },
    ]);
  }
  function revertPatch(id: string): void {
    // undo() 是 LIFO 栈，只能精确撤销最近一次变更：只对「栈顶未撤销 patch」生效，
    // 否则会误伤该 patch 之后的无关编辑（撤错）。
    const lastPatchId = [...blocks].reverse().find((b) => b.type === "patch" && !b.reverted)?.id;
    if (id !== lastPatchId) return;
    undo();
    setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, reverted: true } : b)));
  }

  // ── runtime 切换：清选中；live→只读 + 拉 Live 只读快照（接真）──
  function changeRuntime(r: Runtime): void {
    setRuntime(r);
    setSelection({ nodeIds: [], edgeIds: [] });
    if (r === "live") {
      setLiveErr(null);
      void fetchLiveSnapshot(STRATEGY_NAME)
        .then(setLiveSnap)
        .catch((e: Error) => setLiveErr(e.message));
    }
  }

  // ── 打开版本 popover → 拉真实版本史（lineage append-only）──
  function toggleVersionMenu(): void {
    setVerMenuOpen((o) => {
      const next = !o;
      if (next && versions === null) {
        setVersionsErr(null);
        void fetchStrategyVersions(STRATEGY_NAME)
          .then(setVersions)
          .catch((e: Error) => setVersionsErr(e.message));
      }
      return next;
    });
  }

  // ── 校验（接真）：清选中 + 开右栏 + 向后端权威复核（B6 三层后端再判一次）──
  function runValidate(): void {
    setSelection({ nodeIds: [], edgeIds: [] });
    setRightOpen(true);
    setValidateErr(null);
    void validateStrategyGraph(STRATEGY_NAME, nodes, edges)
      .then((r) => {
        // 后端 {ok,errors,warnings} → 前端 GraphValidation 形状（统一渲染）。
        const issues: ValidationIssue[] = [
          ...r.errors.map((e) => ({ level: "error" as const, nodeId: e.nodeId, text: e.text })),
          ...r.warnings.map((w) => ({ level: "warn" as const, nodeId: w.nodeId, text: w.text })),
        ];
        setBackendValidation({
          issues,
          errorCount: r.errors.length,
          warnCount: r.warnings.length,
          ok: r.ok,
        });
      })
      .catch((e: Error) => setValidateErr(e.message)); // 不假绿灯：后端失败如实标，保留本地校验
  }

  // ── Fork（live 下，接真）：后端策略级 fork（血缘锚 lineage/ids.py）→ runtime→backtest ──
  function fork(): void {
    void forkStrategy(STRATEGY_NAME)
      .then((forked) => {
        setRuntime("backtest");
        setVer(`${forked.name}(fork)`);
        setBlocks((prev) => [
          ...prev,
          { id: `fk${Date.now()}`, type: "say", text: `已 Fork 出可编辑草稿「${forked.name}」（Live 只读 → 草稿，B7；血缘已锚父策略）。` },
        ]);
        setVersions(null); // 版本史失效，下次开 popover 重拉
      })
      .catch((e: Error) => {
        setBlocks((prev) => [
          ...prev,
          { id: `fke${Date.now()}`, type: "say", text: `Fork 失败：${e.message}` },
        ]);
      });
  }

  // ── 成交行 → 高亮血缘链路 + 开 dock 切 lineage ──
  function setTrace(txId: string): void {
    setTraceId(txId);
    setDockOpen(true);
    setDockTab("lineage");
  }

  // 顶栏校验状态文案/语气。
  const errLabel = validation.ok
    ? `✓ 校验通过`
    : `✕ ${validation.errorCount} 错误${validation.warnCount ? ` · ${validation.warnCount} 警告` : ""}`;
  const errTone = validation.ok ? "success" : "danger";

  // ── TOPBAR ──
  const topbar = (
    <DeskTopBar>
      <DeskSwitcher current="strategy" />
      <span style={vDiv} aria-hidden />
      <span style={{ fontWeight: 600 }}>strat_wk_cn_01</span>
      <button style={ghostBtn} onClick={toggleVersionMenu} aria-haspopup="true" data-version-toggle>
        {ver} ▾
      </button>
      <SegmentedControl<Runtime>
        options={[
          { value: "backtest", label: "Backtest" },
          { value: "paper", label: "Paper" },
          { value: "live", label: "Live" },
        ]}
        value={runtime}
        onChange={changeRuntime}
        size="sm"
      />
      {readOnly && (
        <>
          <Pill tone="warning" title="已发布 Live 只读（B7）">🔒 Live 只读</Pill>
          <button style={greenBtn} onClick={fork}>⑂ Fork 草稿</button>
          <button
            style={killArmed ? killArmedBtn : killOffBtn}
            onClick={() => setKillArmed((a) => !a)}
            aria-label="Kill Switch"
          >
            {killArmed ? "● ARMED" : "○ OFF"}
          </button>
        </>
      )}
      <span style={{ flex: 1 }} />
      <button style={iconBtn(canUndo)} disabled={!canUndo} onClick={undo} aria-label="撤销" title="撤销 ⌘Z">↺</button>
      <button style={iconBtn(canRedo)} disabled={!canRedo} onClick={redo} aria-label="重做" title="重做 ⌘⇧Z">↻</button>
      <span style={vDiv} aria-hidden />
      <button style={errBtn(errTone)} onClick={runValidate} data-validate>{errLabel}</button>
      <button style={greenBtn} data-run-backtest onClick={() => { setDockOpen(true); setDockTab("logs"); }}>▷ 运行回测</button>
      <button style={blueBtn} data-compile>{"⟨/⟩"} 编译源码</button>
      <button style={ghostBtn} data-publish>发布 ▸</button>
    </DeskTopBar>
  );

  // ── LEFT · AgentChat ──
  const modeHint: Record<PermissionMode, string> = {
    ask: "Ask：先出 Ghost 提议预览，由你 accept/reject —— 不自动改图。",
    auto: "Auto：事务化直接改草稿（加节点），可整轮 Undo + Patch ID。",
    bypass: "Bypass：批量自跑 —— 但治理门（Final Gate / 发布审批 / 真钱）仍不可绕过。",
  };
  const left = (
    <CollapsiblePanel open={leftOpen} onToggle={() => setLeftOpen((o) => !o)} side="left" width={316} label="Agent">
      <div style={panelHeader}>
        <span style={{ color: "var(--desk-accent)", fontWeight: 700 }}>✳</span>
        <span style={{ fontWeight: 600 }}>Agent</span>
        <div style={{ flex: 1 }} />
        <SegmentedControl<PermissionMode>
          options={[
            { value: "ask", label: "Ask" },
            { value: "auto", label: "Auto" },
            { value: "bypass", label: "Bypass" },
          ]}
          value={agentMode}
          onChange={setAgentMode}
          size="sm"
        />
      </div>
      <div style={modeHintStyle} data-mode-hint>{modeHint[agentMode]}</div>
      <AgentChat
        blocks={(() => {
          // 只在「栈顶未撤销 patch」上挂 revert 入口（undo 为 LIFO，只能撤最近一次，避免撤错）。
          const lastPatchId = [...blocks].reverse().find((b) => b.type === "patch" && !b.reverted)?.id;
          return blocks.map((b) =>
            b.type === "patch" && !b.reverted && b.id === lastPatchId
              ? { ...b, onRevert: () => revertPatch(b.id) }
              : b,
          );
        })()}
        contextLabel={
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            上下文 · 18.4k / 200k <MockBadge label="MOCK 对话" />
          </span>
        }
        composer={
          <>
            {proposalLive && (
              <div style={ghostCard} data-proposal>
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                  <span style={{ color: "var(--desk-ghost)" }}>◇</span>
                  <span style={{ color: "var(--desk-ghost)", fontWeight: 600 }}>{MOCK_PROPOSAL.title}</span>
                  <Pill tone="ghost">Ghost · {MOCK_PROPOSAL.patchId}</Pill>
                </div>
                {MOCK_PROPOSAL.diff.map((d, i) => (
                  <div key={i} style={{ fontSize: 11, color: diffTone(d.sign) }}>{d.sign} {d.text}</div>
                ))}
                <div style={{ fontSize: 10, color: "var(--desk-text-faint)", margin: "6px 0" }}>
                  ↑ 画布上虚线即此提议的 Ghost 预览（影响 {MOCK_PROPOSAL.ops.length} 处）
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <button style={purpleBtn} data-accept onClick={acceptProposal}>✓ 接受 Patch</button>
                  <button style={ghostBtn} data-reject onClick={rejectProposal}>拒绝</button>
                </div>
              </div>
            )}
            <ChatComposer
              draft={draft}
              onDraftChange={setDraft}
              onSend={sendAgent}
              model="sonnet-4.5"
              permissionMode={agentMode}
              branch="strat/weekly-cn"
            />
          </>
        }
      />
    </CollapsiblePanel>
  );

  // ── CENTER · GraphCanvas ──
  // Ghost 预览：提议里的新增节点投进 nodeViews（让 ghost 边能锚定），
  // 节点本体保持 idle 态，连线用 ghostEdges（虚线）。
  const ghostNodeViews = proposalLive
    ? MOCK_PROPOSAL.ops
        .filter((op): op is Extract<typeof op, { op: "addNode" }> => op.op === "addNode")
        .filter((op) => !nodes[op.node.id])
        .map((op) => toNodeView(op.node))
    : [];
  const ghostEdges = proposalLive
    ? MOCK_PROPOSAL.ops
        .filter((op): op is Extract<typeof op, { op: "addEdge" }> => op.op === "addEdge")
        .map((op) => toEdgeView(op.edge))
    : [];
  // 血缘高亮：选中的边集合 = trace.path 的相邻边。
  const traceEdgeIds = useMemo(() => {
    if (!trace) return [];
    const ids: string[] = [];
    for (let i = 0; i < trace.path.length - 1; i++) {
      const a = trace.path[i], b = trace.path[i + 1];
      const e = edges.find((ed) => ed.from.node === a && ed.to.node === b);
      if (e) ids.push(e.id);
    }
    return ids;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trace, edges]);
  const canvasSelection: Selection = trace
    ? { nodeIds: trace.path, edgeIds: traceEdgeIds }
    : selection;

  // 现有编排 UI（console 视图本体）—— 原 DOM 结构保持不变。
  const consoleCenter = (
    <>
      <div style={toolbar}>
        <CanvasControls
          zoom={zoom}
          onZoomOut={() => zoomBy(1 / BUTTON_ZOOM_FACTOR)}
          onZoomIn={() => zoomBy(BUTTON_ZOOM_FACTOR)}
          onFit={fit}
          onAutoLayout={fit}
        />
        <span style={{ fontSize: 10, color: "var(--desk-text-faint)", marginLeft: 8 }} data-canvas-hint>
          {STAGES.length} 阶段 · {Object.keys(nodes).length} 节点 · {edges.length} 连线
        </span>
        <span style={{ flex: 1 }} />
        <MockBadge />
        <span style={{ fontSize: 10.5, color: "var(--desk-text-dim)", marginLeft: 8 }} data-sel-count>
          {selection.nodeIds.length + selection.edgeIds.length > 0
            ? `已选 ${selection.nodeIds.length} 节点 / ${selection.edgeIds.length} 连线`
            : "未选中"}
        </span>
      </div>
      <GraphCanvas
        nodes={[...nodeViews, ...ghostNodeViews]}
        edges={edgeViews}
        pan={pan}
        zoom={zoom}
        selection={canvasSelection}
        ghostEdges={ghostEdges}
        marquee={marquee}
        onPan={setPan}
        onZoom={onZoomVp}
        onSelectNode={selectNode}
        onSelectEdge={selectEdge}
        onNodeMove={onNodeMove}
        onConnect={onConnect}
        onMarquee={onMarquee}
      >
        {readOnly && (
          liveErr ? (
            <CanvasBanner tone="lineage"><span data-live-error>🔒 Live 只读 · 快照加载失败：{liveErr}</span></CanvasBanner>
          ) : liveSnap && !liveSnap.live_allowed ? (
            <CanvasBanner tone="lineage">
              <span data-live-forbidden>⛔ {liveSnap.reason ?? "该资产类别 Live 已禁止"}</span>
            </CanvasBanner>
          ) : liveSnap ? (
            <CanvasBanner tone="lineage">
              <span data-live-snapshot>🔒 Live 只读 · {liveSnap.run_count ?? 0} 次运行（只读聚合，编辑请 Fork 草稿）</span>
            </CanvasBanner>
          ) : (
            <CanvasBanner tone="lineage">🔒 Live 只读 · 画布与参数已锁定（编辑请 Fork 草稿）</CanvasBanner>
          )
        )}
        {!readOnly && diffOn && (
          <CanvasBanner tone="diff" actionLabel="退出对比" onAction={() => setDiffOn(false)}>
            对比 v2 → v3 · +1 新增 / ~2 改动
          </CanvasBanner>
        )}
        {!readOnly && !diffOn && trace && (
          <CanvasBanner tone="lineage" actionLabel="清除高亮" onAction={() => setTraceId(null)}>
            血缘 · {trace.symbol} · 链路 {trace.path.length} 节点
          </CanvasBanner>
        )}
        {/* 节点卡上的「↗打开回测」单段跳转：覆盖在 backtest 节点上方的浮动按钮 */}
        {nodes.backtest?.openRun && (
          <button
            style={openRunFloat}
            data-open-run
            onClick={() => openRunDetail(CURRENT_RUN_ID)}
          >
            ↗ 打开回测
          </button>
        )}
        <MiniMap
          nodes={nodeViews}
          viewport={{ panX: pan.x, panY: pan.y, zoom }}
          viewSize={surfSize.current}
        />
        <div style={legend}>
          <Pill tone="success">● 兼容</Pill>
          <Pill tone="info">◐ 可适配</Pill>
          <Pill tone="warning">⚠ 需转换</Pill>
          <Pill tone="danger">✕ 不兼容</Pill>
        </div>
      </GraphCanvas>
    </>
  );

  // ── CENTER · 顶层 SubTabBar + 子视图切换 ──
  // console（默认）渲染现有编排 UI（consoleCenter，原样）；
  // 其余三个子视图把旧页内嵌进可滚动容器（功能优先、不重写旧页）。
  const center = (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <SubTabBar<ConsoleView>
        tabs={[
          { value: "console", label: "编排画布" },
          { value: "intake", label: "需求录入" },
          { value: "ide", label: "代码 IDE" },
          { value: "templates", label: "模板起步" },
        ]}
        value={view}
        onChange={setView}
      />
      {view === "console" ? (
        consoleCenter
      ) : (
        <div style={{ flex: 1, minHeight: 0, overflow: "auto" }} data-console-embed={view}>
          {view === "intake" && <StrategyWorkshopPage />}
          {view === "ide" && <IDEPage />}
          {view === "templates" && <StrategyTemplatesPage />}
        </div>
      )}
    </div>
  );

  // ── RIGHT · Inspector ──
  const right = rightOpen ? (
    <Inspector
      title={selNode ? selNode.title : "Inspector"}
      onCollapse={() => setRightOpen(false)}
      selectionHead={
        selNode ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }} data-insp-head>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 9, height: 9, borderRadius: 2, background: `var(--desk-${catTone(selNode.cat)})` }} />
              <Pill tone="neutral">{selNode.cat}</Pill>
              <Pill tone={selNode.state === "succeeded" || selNode.state === "valid" ? "success" : "neutral"}>{selNode.state}</Pill>
              {selNode.mock && <MockBadge />}
            </div>
            <div style={{ fontSize: 11.5, color: "var(--desk-text-dim)", lineHeight: 1.5 }}>{selNode.desc}</div>
          </div>
        ) : undefined
      }
      tabs={selNode ? <InspectorTabs value={inspTab} onChange={setInspTab} /> : undefined}
    >
      {selNode ? (
        <InspectorBody
          node={selNode}
          tab={inspTab}
          readOnly={readOnly}
          issues={nodeIssues(selNode.id, validation)}
          onParam={(k, v) => setParam(selNode.id, k, v)}
          onOpenRun={() => openRunDetail(CURRENT_RUN_ID)}
        />
      ) : (
        <GraphValidationOverview
          ok={validation.ok}
          errorCount={validation.errorCount}
          warnCount={validation.warnCount}
          issues={validation.issues}
          onLocate={selectNode}
        />
      )}
    </Inspector>
  ) : (
    <CollapsiblePanel open={false} onToggle={() => setRightOpen(true)} side="right" label="Inspector">
      <span />
    </CollapsiblePanel>
  );

  // ── DOCK ──
  const dock = dockOpen ? (
    <Dock
      tabs={<DockTabs value={dockTab} onChange={setDockTab} />}
      right={<MockBadge />}
      onCollapse={() => setDockOpen(false)}
    >
      <DockBody
        tab={dockTab}
        selNode={selNode}
        trace={trace}
        onTrace={setTrace}
        onOpenRun={() => openRunDetail(CURRENT_RUN_ID)}
        validation={validation}
        nodeCount={Object.keys(nodes).length}
        edgeCount={edges.length}
      />
    </Dock>
  ) : (
    <button style={dockCollapsed} data-dock-collapsed onClick={() => setDockOpen(true)}>
      ▤ 工作台 · 输出/日志/运行历史/血缘溯源 ▴
    </button>
  );

  return (
    <>
      <DeskShell desk="strategy" topbar={topbar} left={left} center={center} right={right} dock={dock} />
      {verMenuOpen && (
        <div style={verPopover} data-version-menu>
          <div style={{ fontWeight: 600, marginBottom: 8 }}>版本历史 · GraphVersion</div>
          {versionsErr && (
            <div style={{ fontSize: 11, color: "var(--desk-danger)", marginBottom: 6 }} data-versions-error>
              ✕ 版本史加载失败：{versionsErr}
            </div>
          )}
          {versions !== null ? (
            versions.length === 0 ? (
              <div style={faint} data-versions-empty>暂无版本史（首次保存后出现）</div>
            ) : (
              versions.map((v, i) => (
                <div key={v.version_id} style={verRow} data-version-row>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: i === 0 ? "var(--desk-accent)" : "var(--desk-text-faint)" }} />
                  <span style={{ flex: 1 }}>{v.label}</span>
                  <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>{v.origin}</span>
                  <span style={{ fontSize: 9.5, color: "var(--desk-text-faint)" }} title={`内容指纹 ${v.content_hash}`}>{v.content_hash.slice(0, 8)}</span>
                </div>
              ))
            )
          ) : versionsErr ? null : (
            // 加载中：暂以 mock 占位（带 MockBadge 诚实标），真实数据返回即替换。
            <>
              {MOCK_VERSIONS.map((v) => (
                <div key={v.vid} style={verRow}>
                  <span style={{ width: 7, height: 7, borderRadius: "50%", background: v.cur ? "var(--desk-accent)" : "var(--desk-text-faint)" }} />
                  <span style={{ flex: 1 }}>{v.label}</span>
                  <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>{v.lifecycle}</span>
                  <button style={tinyBtn} onClick={() => { setDiffOn(true); setVerMenuOpen(false); }}>对比</button>
                </div>
              ))}
              <div style={{ marginTop: 8 }}><MockBadge label="MOCK 版本（加载中）" /></div>
            </>
          )}
        </div>
      )}
    </>
  );
}

// ════════════════════ 子组件 ════════════════════

/** Inspector 选中体 tab 内容（参数/端口/校验/版本血缘）。 */
function InspectorBody({
  node,
  tab,
  readOnly,
  issues,
  onParam,
  onOpenRun,
}: {
  node: DomainNode;
  tab: InspectorTab;
  readOnly: boolean;
  issues: ValidationIssue[];
  onParam: (k: string, v: string) => void;
  onOpenRun: () => void;
}) {
  if (tab === "params") {
    const entries = Object.entries(node.params);
    if (entries.length === 0) return <div style={faint}>该节点无可调参数</div>;
    return (
      <div>
        {entries.map(([k, v]) => (
          <ParamRow
            key={k}
            label={k}
            value={v}
            onChange={(nv) => onParam(k, nv)}
            readOnly={readOnly}
            locked={node.locked}
          />
        ))}
      </div>
    );
  }
  if (tab === "ports") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {node.ins.map((p) => (
          <div key={p.id} style={portCard(p.req)} data-in-port>
            <span style={{ color: "var(--desk-text)" }}>{p.name}</span>
            <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>{p.dt}{p.freq ? ` · ${p.freq}` : ""}{p.req ? " · 必填" : " · 可选"}</span>
          </div>
        ))}
        {node.outs.map((p) => (
          <div key={p.id} style={portCard(false)} data-out-port>
            <span style={{ color: "var(--desk-text)" }}>{p.name}</span>
            <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>{p.dt}{p.freq ? ` · ${p.freq}` : ""} · 输出</span>
          </div>
        ))}
      </div>
    );
  }
  if (tab === "validate") {
    if (issues.length === 0) return <div style={{ color: "var(--desk-success)" }} data-node-valid>✓ 该节点校验通过</div>;
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {issues.map((i, k) => (
          <div key={k} style={{ color: i.level === "error" ? "var(--desk-danger)" : "var(--desk-warning)", fontSize: 11.5 }}>
            {i.level === "error" ? "✕" : "⚠"} {i.text}
          </div>
        ))}
      </div>
    );
  }
  // version / lineage
  const contrib = MOCK_CONTRIBUTION[node.id];
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      <div style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>节点 ID · {node.id}</div>
      <div style={{ fontSize: 11, color: "var(--desk-info)" }}>血缘 · {node.lineage}</div>
      {contrib && (
        <div style={contribCard} data-contribution>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
            <span style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>{CURRENT_RUN_ID}</span>
            <MockBadge />
          </div>
          {contrib.map((c, i) => (
            <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5 }}>
              <span style={{ color: "var(--desk-text-dim)" }}>{c.k}</span>
              <span style={{ color: `var(--desk-${c.tone === "neutral" ? "text-soft" : c.tone})` }}>{c.v}</span>
            </div>
          ))}
          <button style={blueBtn} data-locate-run onClick={onOpenRun}>↗ 在回测详情中定位该节点</button>
        </div>
      )}
    </div>
  );
}

/** 无选中态：图校验概览（GraphValidationResult）。 */
function GraphValidationOverview({
  ok,
  errorCount,
  warnCount,
  issues,
  onLocate,
}: {
  ok: boolean;
  errorCount: number;
  warnCount: number;
  issues: ValidationIssue[];
  onLocate: (id: string) => void;
}) {
  const glyph = errorCount > 0 ? "✕" : warnCount > 0 ? "⚠" : "✓";
  const color = errorCount > 0 ? "var(--desk-danger)" : warnCount > 0 ? "var(--desk-warning)" : "var(--desk-success)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }} data-graph-validation>
      <div style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>图校验 · GraphValidationResult</div>
      <div style={{ fontSize: 22, color }}>{glyph}</div>
      <div style={{ fontSize: 12, color: "var(--desk-text)" }}>
        {ok ? "整图校验通过（无阻断错误）" : `${errorCount} 错误 · ${warnCount} 警告`}
      </div>
      {issues.map((i, k) => (
        <button
          key={k}
          style={issueRow}
          data-issue
          onClick={() => i.nodeId && onLocate(i.nodeId)}
        >
          <span style={{ color: i.level === "error" ? "var(--desk-danger)" : "var(--desk-warning)" }}>
            {i.level === "error" ? "✕" : "⚠"}
          </span>{" "}
          {i.text}
        </button>
      ))}
      <div style={faint}>连线 · 框选 · Del 删除 · ⌘Z 撤销</div>
    </div>
  );
}

/** Dock 内容区 6 互斥视图（mock fixture）。 */
function DockBody({
  tab,
  selNode,
  trace,
  onTrace,
  onOpenRun,
  validation,
  nodeCount,
  edgeCount,
}: {
  tab: DockTab;
  selNode: DomainNode | undefined;
  trace: import("./strategy/mockGraph").MockTrade | null;
  onTrace: (id: string) => void;
  onOpenRun: () => void;
  validation: import("./strategy/graphLogic").GraphValidation;
  nodeCount: number;
  edgeCount: number;
}) {
  if (tab === "preview") {
    return (
      <div data-dock-preview>
        <div style={faint}>输出预览 · {selNode ? selNode.title : "未选中节点"}</div>
        {selNode?.mock && <div style={{ marginTop: 6 }}><MockBadge /></div>}
      </div>
    );
  }
  if (tab === "schema") {
    const sch = selNode?.outs.find((p) => p.schema)?.schema ?? "（无 schema）";
    return <pre style={pre} data-dock-schema>{sch}</pre>;
  }
  if (tab === "stats") {
    return (
      <div data-dock-stats style={{ display: "flex", gap: 24 }}>
        <Stat label="节点" value={`${nodeCount}`} />
        <Stat label="连线" value={`${edgeCount}`} />
        <Stat label="错误" value={`${validation.errorCount}`} />
        <Stat label="警告" value={`${validation.warnCount}`} />
      </div>
    );
  }
  if (tab === "logs") {
    return (
      <div data-dock-logs style={{ display: "flex", flexDirection: "column", gap: 2, fontSize: 10.5 }}>
        <div style={{ color: "var(--desk-text-faint)" }}>[09:14:02] ▷ 运行回测 · 17 节点入队…（mock 流式）</div>
        <div style={{ color: "var(--desk-success)" }}>[09:14:08] ✓ 完成 · 超额 17.3% / 回撤 15.8% / DSR 1.34</div>
        <div style={{ marginTop: 6 }}><MockBadge label="MOCK 日志" /></div>
      </div>
    );
  }
  if (tab === "history") {
    return (
      <div data-dock-history>
        <table style={{ width: "100%", fontSize: 10.5, fontVariantNumeric: "tabular-nums", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ color: "var(--desk-text-muted)" }}>
              <th style={th}>run_id</th><th style={th}>时间</th><th style={th}>超额</th><th style={th}>回撤</th><th style={th}>Sharpe</th><th style={th}>状态</th>
            </tr>
          </thead>
          <tbody>
            {MOCK_RUNS.map((r) => (
              <tr key={r.id} style={{ color: "var(--desk-text-soft)" }}>
                <td style={td}>{r.id}</td><td style={td}>{r.when}</td><td style={td}>{r.excess}</td><td style={td}>{r.dd}</td><td style={td}>{r.sharpe}</td>
                <td style={{ ...td, color: r.status === "warning" ? "var(--desk-warning)" : "var(--desk-success)" }}>{r.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop: 6 }}><MockBadge /></div>
      </div>
    );
  }
  // lineage
  return (
    <div data-dock-lineage>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: "var(--desk-text-dim)" }}>回测概览 · {CURRENT_RUN_ID}</span>
        <MockBadge />
        <button style={blueBtn} data-lineage-open-run onClick={onOpenRun}>↗ 回测详情</button>
      </div>
      <table style={{ width: "100%", fontSize: 10.5, fontVariantNumeric: "tabular-nums", borderCollapse: "collapse" }}>
        <thead>
          <tr style={{ color: "var(--desk-text-muted)" }}>
            <th style={th}>标的</th><th style={th}>方向</th><th style={th}>数量</th><th style={th}>价格</th><th style={th}>盈亏</th><th style={th}>收益</th>
          </tr>
        </thead>
        <tbody>
          {MOCK_TRADES.map((t) => (
            <tr
              key={t.id}
              style={{ color: "var(--desk-text-soft)", cursor: "pointer", background: trace?.id === t.id ? "var(--desk-hover)" : undefined }}
              data-trade-row
              onClick={() => onTrace(t.id)}
            >
              <td style={td}>{t.symbol}</td><td style={td}>{t.side}</td><td style={td}>{t.qty}</td><td style={td}>{t.px}</td>
              <td style={{ ...td, color: t.pnl.startsWith("-") ? "var(--desk-danger)" : "var(--desk-success)" }}>{t.pnl}</td>
              <td style={{ ...td, color: t.ret.startsWith("-") ? "var(--desk-danger)" : "var(--desk-success)" }}>{t.ret}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {trace && (
        <div style={{ marginTop: 8, fontSize: 11, color: "var(--desk-warning)" }} data-trace-chain>
          血缘链路 · {trace.path.join(" ← ")}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: "var(--desk-text-muted)" }}>{label}</div>
      <div style={{ fontSize: 14, color: "var(--desk-text)", fontVariantNumeric: "tabular-nums" }}>{value}</div>
    </div>
  );
}

// ════════════════════ 样式 / 工具 ════════════════════

function diffTone(sign: "+" | "~" | "-"): string {
  return sign === "+" ? "var(--desk-success)" : sign === "~" ? "var(--desk-warning)" : "var(--desk-danger)";
}

/** 节点类别 → tone（CSS 变量后缀），仅用于 selectionHead 色块/内联 token。 */
function catTone(cat: DomainNode["cat"]): string {
  switch (cat) {
    case "factor": return "success";
    case "model": return "ghost";
    case "signal": return "warning";
    case "risk": return "danger";
    case "exec": return "accent";
    default: return "info";
  }
}

const vDiv: CSSProperties = { width: 1, height: 18, background: "var(--desk-border)" };
const panelHeader: CSSProperties = {
  flex: "none", display: "flex", alignItems: "center", gap: 8,
  padding: "9px 13px", borderBottom: "1px solid var(--desk-border)",
};
const modeHintStyle: CSSProperties = {
  flex: "none", padding: "6px 13px", borderBottom: "1px solid var(--desk-border)",
  fontSize: 9.5, color: "var(--desk-text-faint)", lineHeight: 1.6,
};
const toolbar: CSSProperties = {
  flex: "none", display: "flex", alignItems: "center", gap: 6,
  padding: "7px 12px", borderBottom: "1px solid var(--desk-border)", background: "var(--desk-card)",
};
const ghostBtn: CSSProperties = {
  fontFamily: "inherit", fontSize: 11, padding: "4px 9px", borderRadius: "var(--desk-radius-sm)",
  background: "transparent", border: "1px solid var(--desk-border)", color: "var(--desk-text-dim)", cursor: "pointer",
};
const greenBtn: CSSProperties = {
  fontFamily: "inherit", fontSize: 11, padding: "4px 9px", borderRadius: "var(--desk-radius-sm)",
  background: "transparent", border: "1px solid var(--desk-success)", color: "var(--desk-success)", cursor: "pointer",
};
const blueBtn: CSSProperties = {
  fontFamily: "inherit", fontSize: 11, padding: "4px 9px", borderRadius: "var(--desk-radius-sm)",
  background: "transparent", border: "1px solid var(--desk-info)", color: "var(--desk-info)", cursor: "pointer", marginTop: 6,
};
const purpleBtn: CSSProperties = {
  fontFamily: "inherit", fontSize: 11.5, padding: "5px 11px", borderRadius: "var(--desk-radius-sm)",
  background: "transparent", border: "1px solid var(--desk-ghost)", color: "var(--desk-ghost)", cursor: "pointer",
};
const killArmedBtn: CSSProperties = {
  fontFamily: "inherit", fontSize: 11, padding: "4px 9px", borderRadius: "var(--desk-radius-sm)",
  background: "transparent", border: "1px solid var(--desk-danger)", color: "var(--desk-danger)", cursor: "pointer",
};
const killOffBtn: CSSProperties = {
  fontFamily: "inherit", fontSize: 11, padding: "4px 9px", borderRadius: "var(--desk-radius-sm)",
  background: "transparent", border: "1px solid var(--desk-border)", color: "var(--desk-text-faint)", cursor: "pointer",
};
function iconBtn(enabled: boolean): CSSProperties {
  return {
    fontFamily: "inherit", fontSize: 13, padding: "2px 7px", borderRadius: "var(--desk-radius-sm)",
    background: "transparent", border: "none",
    color: enabled ? "var(--desk-text-dim)" : "var(--desk-text-faint)",
    cursor: enabled ? "pointer" : "not-allowed", opacity: enabled ? 1 : 0.5,
  };
}
function errBtn(tone: "success" | "danger"): CSSProperties {
  return {
    fontFamily: "inherit", fontSize: 11.5, padding: "5px 11px", borderRadius: "var(--desk-radius-sm)",
    background: "var(--desk-soft-btn)", border: `1px solid var(--desk-${tone})`, color: `var(--desk-${tone})`, cursor: "pointer",
  };
}
const ghostCard: CSSProperties = {
  margin: "0 13px 10px", border: "1px dashed var(--desk-ghost)", background: "var(--desk-card)",
  borderRadius: "var(--desk-radius-lg)", padding: "10px 12px",
};
const openRunFloat: CSSProperties = {
  position: "absolute", right: 180, bottom: 12, zIndex: 6,
  fontFamily: "inherit", fontSize: 11, padding: "4px 10px", borderRadius: "var(--desk-radius-sm)",
  background: "var(--desk-card)", border: "1px solid var(--desk-info)", color: "var(--desk-info)", cursor: "pointer",
};
const legend: CSSProperties = {
  position: "absolute", left: 12, bottom: 12, display: "flex", gap: 6, zIndex: 5,
};
const dockCollapsed: CSSProperties = {
  flex: "none", height: 30, width: "100%", textAlign: "left", padding: "0 14px",
  background: "var(--desk-soft-btn)", border: "none", borderTop: "1px solid var(--desk-border)",
  color: "var(--desk-text-dim)", fontFamily: "inherit", fontSize: 11, cursor: "pointer",
};
const verPopover: CSSProperties = {
  position: "absolute", top: 48, left: 196, width: 282, zIndex: 80,
  background: "var(--desk-topbar)", border: "1px solid var(--desk-border-strong)",
  borderRadius: "var(--desk-radius-lg)", padding: 12, fontSize: 11.5, color: "var(--desk-text)",
};
const verRow: CSSProperties = { display: "flex", alignItems: "center", gap: 8, padding: "5px 0" };
const tinyBtn: CSSProperties = {
  fontFamily: "inherit", fontSize: 10, padding: "2px 6px", borderRadius: "var(--desk-radius-sm)",
  background: "transparent", border: "1px solid var(--desk-border)", color: "var(--desk-text-dim)", cursor: "pointer",
};
const faint: CSSProperties = { fontSize: 11, color: "var(--desk-text-faint)" };
const pre: CSSProperties = {
  fontFamily: "inherit", fontSize: 10.5, color: "var(--desk-text-soft)",
  background: "var(--desk-input)", borderRadius: "var(--desk-radius-sm)", padding: 10, margin: 0, whiteSpace: "pre-wrap",
};
function portCard(req: boolean): CSSProperties {
  return {
    display: "flex", flexDirection: "column", gap: 2, padding: "7px 9px",
    background: "var(--desk-input)", border: "1px solid var(--desk-border)",
    borderLeft: `2px solid var(--desk-${req ? "warning" : "border-strong"})`,
    borderRadius: "var(--desk-radius-sm)",
  };
}
const contribCard: CSSProperties = {
  display: "flex", flexDirection: "column", gap: 4, padding: "9px 11px",
  background: "var(--desk-input)", border: "1px solid var(--desk-border)", borderRadius: "var(--desk-radius-sm)",
};
const issueRow: CSSProperties = {
  textAlign: "left", fontFamily: "inherit", fontSize: 11.5, padding: "6px 8px",
  background: "var(--desk-input)", border: "1px solid var(--desk-border)", borderRadius: "var(--desk-radius-sm)",
  color: "var(--desk-text-soft)", cursor: "pointer",
};
const th: CSSProperties = { textAlign: "left", padding: "3px 6px", fontWeight: 400 };
const td: CSSProperties = { padding: "3px 6px" };

export default StrategyConsolePage;
