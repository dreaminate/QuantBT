import { useState, useEffect, type PointerEvent } from "react";
import {
  CollapsiblePanel,
  Pill,
  MockBadge,
  AgentChat,
  ChatComposer,
  GraphCanvas,
  clampZoom,
  type AgentBlock,
  type NodeView,
  type EdgeView,
  type Selection,
  type Viewport,
  type PortRef,
  type MarqueeRect,
} from "../../../components/desk";
import {
  BUILD_NODES,
  BUILD_EDGES,
  PALETTE,
  BUILD_CODE,
  BUILD_CHAT_SEED,
  type PaletteGroup,
} from "./modelMock";
import { codegenGraph } from "./modelApi";

/**
 * 构建台（build · DC §C）：draw.io 式图编辑器，用共享 GraphCanvas 引擎（不重造）。
 * 左：构建助手 chat（先确认再动手）· 中：画布（节点/连线/缩放/平移/框选）· 右：组件库 palette + 代码面板。
 * 治理：代码面板显式标注「DL 走子进程，主进程不碰 torch」(M6)。P0 mock。
 */

export interface BuildDeckProps {
  chatOpen: boolean;
  onToggleChat: () => void;
  paletteOpen: boolean;
  onTogglePalette: () => void;
  draft: string;
  onDraftChange: (v: string) => void;
  onSend: () => void;
}

export function BuildDeck(props: BuildDeckProps) {
  const [nodes] = useState<NodeView[]>(BUILD_NODES);
  const [edges] = useState<EdgeView[]>(BUILD_EDGES);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1);
  const [selection, setSelection] = useState<Selection>({ nodeIds: [], edgeIds: [] });
  const [marquee, setMarquee] = useState<MarqueeRect | null>(null);
  const [codeOpen, setCodeOpen] = useState(false);

  function onZoom(vp: Viewport): void {
    setPan({ x: vp.panX, y: vp.panY });
    setZoom(clampZoom(vp.zoom));
  }
  function onSelectNode(id: string): void {
    setSelection({ nodeIds: [id], edgeIds: [] });
  }
  function onSelectEdge(id: string): void {
    setSelection({ nodeIds: [], edgeIds: [id] });
  }
  // P0：节点拖拽/连线为 mock（不持久），引擎事件接收但不落实际移动。
  function noopNodeMove(_id: string, _e: PointerEvent<HTMLDivElement>): void {}
  function noopConnect(_ref: PortRef, _side: "in" | "out", _e: PointerEvent<HTMLDivElement>): void {}

  const chatBlocks: AgentBlock[] = BUILD_CHAT_SEED.map((m, i) =>
    m.role === "user"
      ? { id: `u${i}`, type: "user", text: m.text }
      : { id: `a${i}`, type: "say", text: m.text },
  );

  return (
    <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
      {/* 左：构建助手 chat */}
      <CollapsiblePanel
        open={props.chatOpen}
        onToggle={props.onToggleChat}
        side="left"
        width={312}
        label="构建面板"
      >
        <div
          style={{
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 14px",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          <span style={{ color: "var(--desk-accent)" }}>✦</span>
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)" }}>构建面板</span>
          <span style={{ marginLeft: "auto" }}>
            <MockBadge />
          </span>
        </div>
        <AgentChat
          blocks={chatBlocks}
          composer={
            <ChatComposer
              draft={props.draft}
              onDraftChange={props.onDraftChange}
              onSend={props.onSend}
              model="claude（mock）"
              permissionMode="ask"
              branch="fullstack"
              placeholder="> 描述要对图做的修改 / 刷新代码…"
            />
          }
        />
      </CollapsiblePanel>

      {/* 中：画布 */}
      <main style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div
          style={{
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "7px 12px",
            borderBottom: "1px solid var(--desk-border)",
            background: "var(--desk-soft-btn)",
          }}
        >
          <span style={{ fontSize: 11, color: "var(--desk-text-muted)" }}>
            {nodes.length} 节点 · {edges.length} 连线 · 拖动布置 · 端口连线 · ⇧框选
          </span>
          <span style={{ marginLeft: "auto" }}>
            <MockBadge />
          </span>
          <button
            onClick={() => setCodeOpen((c) => !c)}
            style={toolBtnStyle}
          >
            {codeOpen ? "› 收起代码" : "‹ 代码"}
          </button>
        </div>
        <GraphCanvas
          nodes={nodes}
          edges={edges}
          pan={pan}
          zoom={zoom}
          selection={selection}
          marquee={marquee}
          onPan={setPan}
          onZoom={onZoom}
          onSelectNode={onSelectNode}
          onSelectEdge={onSelectEdge}
          onNodeMove={noopNodeMove}
          onConnect={noopConnect}
          onMarquee={setMarquee}
        />
      </main>

      {/* 右：code 面板（条件渲染 · 真 codegen 预览） */}
      {codeOpen && <CodePanel nodes={nodes} edges={edges} />}

      {/* 右：组件库 palette */}
      <CollapsiblePanel
        open={props.paletteOpen}
        onToggle={props.onTogglePalette}
        side="right"
        width={184}
        label="组件库"
      >
        <div
          style={{
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "10px 12px",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)" }}>组件库</span>
          <span style={{ marginLeft: "auto" }}>
            <MockBadge />
          </span>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 10 }}>
          {PALETTE.map((g) => (
            <PaletteSection key={g.title} group={g} />
          ))}
        </div>
      </CollapsiblePanel>
    </div>
  );
}

function PaletteSection({ group }: { group: PaletteGroup }) {
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontSize: 10, color: `var(--desk-${group.tone})`, marginBottom: 6 }}>
        {group.title}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
        {group.items.map((it) => (
          <button
            key={it.type}
            data-palette-item={it.type}
            style={{
              fontFamily: "inherit",
              fontSize: 10.5,
              padding: "4px 9px",
              borderRadius: "var(--desk-radius-sm)",
              border: "1px solid var(--desk-border)",
              background: "var(--desk-card)",
              color: "var(--desk-text-soft)",
              cursor: "pointer",
            }}
          >
            {it.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * 代码面板：真 codegen 预览（图→nn.Module 字符串，POST /api/training/codegen graph 路径）。
 * 后端纯字符串拼装、主进程绝不 import torch（M6）；编译/训练走子进程属后续。
 * 接真前 / fetch 失败 → 回退 BUILD_CODE mock 并保留 MockBadge（不假绿）。
 */
function CodePanel({ nodes, edges }: { nodes: NodeView[]; edges: EdgeView[] }) {
  const [code, setCode] = useState<string | null>(null);
  const [live, setLive] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    codegenGraph(nodes, edges)
      .then((res) => {
        if (cancelled) return;
        setCode(res.code);
        setLive(true);
        setErr(null);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setLive(false);
        setErr(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [nodes, edges]);

  const shown = live && code ? code : BUILD_CODE.join("\n");

  return (
    <aside
      data-code-panel
      style={{
        flex: "none",
        width: 344,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        background: "var(--desk-panel)",
        borderLeft: "1px solid var(--desk-border)",
      }}
    >
      <div
        style={{
          flex: "none",
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "9px 13px",
          borderBottom: "1px solid var(--desk-border)",
        }}
      >
        <Pill tone="info">model.py</Pill>
        <span style={{ marginLeft: "auto" }}>
          {live ? (
            <Pill tone="success" title="后端 graph codegen 实时生成（主进程不碰 torch）">
              实时 codegen
            </Pill>
          ) : (
            <MockBadge />
          )}
        </span>
        <button style={toolBtnStyle}>▷ 跑训练</button>
      </div>
      {/* M6 子进程隔离标注：DL 编译走子进程，主进程不碰 torch */}
      <div
        data-subprocess-note
        style={{
          flex: "none",
          padding: "7px 13px",
          fontSize: 10.5,
          lineHeight: 1.5,
          color: "var(--desk-warning)",
          borderBottom: "1px solid var(--desk-border)",
          background: "var(--desk-input)",
        }}
      >
        ⚠ DL 走子进程，主进程不碰 torch（隔离全功率子进程跑 torch，自动选 cuda/mps/cpu — M6）
      </div>
      {err && !live && (
        <div
          data-codegen-error
          style={{
            flex: "none",
            padding: "6px 13px",
            fontSize: 10,
            color: "var(--desk-text-faint)",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          codegen 未接通，回退预览（{err}）
        </div>
      )}
      <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "10px 13px" }}>
        <pre
          data-code-body
          style={{
            margin: 0,
            fontFamily: "inherit",
            fontSize: 11,
            lineHeight: 1.6,
            color: "var(--desk-text-soft)",
            whiteSpace: "pre-wrap",
          }}
        >
          {shown}
        </pre>
      </div>
    </aside>
  );
}

const toolBtnStyle: React.CSSProperties = {
  fontFamily: "inherit",
  fontSize: 11,
  padding: "3px 9px",
  borderRadius: "var(--desk-radius-sm)",
  border: "1px solid var(--desk-border)",
  background: "transparent",
  color: "var(--desk-text-dim)",
  cursor: "pointer",
};
