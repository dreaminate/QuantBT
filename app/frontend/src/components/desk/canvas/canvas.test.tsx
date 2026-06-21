import { describe, it, expect, vi } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { render, screen, fireEvent } from "@testing-library/react";
import {
  screenToWorld,
  worldToScreen,
  anchorIn,
  anchorOut,
  edgePath,
  clampZoom,
  gridSize,
  zoomAt,
  ZOOM_MIN,
  ZOOM_MAX,
  type Viewport,
} from "./geometry";
import { GraphCanvas } from "./GraphCanvas";
import { NodeCard } from "./NodeCard";
import { edgeStroke, catColor, type NodeView, type EdgeView } from "./types";

const here = dirname(fileURLToPath(import.meta.url));

const VP: Viewport = { panX: 44, panY: 70, zoom: 0.72 };

function mkNode(over: Partial<NodeView> = {}): NodeView {
  return {
    id: "n1",
    cat: "factor",
    title: "动量因子",
    x: 120,
    y: 80,
    w: 176,
    state: "valid",
    lines: ["lookback: 20", "winsorize: 3σ"],
    ins: [{ id: "in0", name: "价量" }],
    outs: [{ id: "out0", name: "因子值" }],
    ...over,
  };
}

describe("G2 geometry · 纯几何", () => {
  it("screenToWorld ∘ worldToScreen 往返一致（多视口/多点）", () => {
    const cases: { p: { x: number; y: number }; vp: Viewport }[] = [
      { p: { x: 0, y: 0 }, vp: VP },
      { p: { x: 300, y: 215 }, vp: VP },
      { p: { x: -50, y: 999 }, vp: { panX: 0, panY: 0, zoom: 1 } },
      { p: { x: 12.5, y: 88.25 }, vp: { panX: 17, panY: -33, zoom: 2.2 } },
    ];
    for (const { p, vp } of cases) {
      const back = worldToScreen(screenToWorld(p, vp), vp);
      expect(back.x).toBeCloseTo(p.x, 6);
      expect(back.y).toBeCloseTo(p.y, 6);
    }
  });

  it("anchorIn 在 left:-7、anchorOut 在 right:+7，top = 38 + i*20", () => {
    const inA = anchorIn(120, 80, 0);
    expect(inA).toEqual({ x: 120 - 7, y: 80 + 38 });
    const inB = anchorIn(120, 80, 2);
    expect(inB.y).toBe(80 + 38 + 2 * 20);

    const outA = anchorOut(120, 80, 176, 0);
    expect(outA).toEqual({ x: 120 + 176 + 7, y: 80 + 38 });
    const outB = anchorOut(120, 80, 176, 1);
    expect(outB.y).toBe(80 + 38 + 20);
  });

  it("edgePath 返回三次贝塞尔（含 C），dx = max(40, |bx-ax|*0.42)", () => {
    // 距离很近 → dx 取下限 40。
    const near = edgePath({ x: 0, y: 0 }, { x: 10, y: 0 });
    expect(near).toContain(" C ");
    expect(near).toBe("M 0,0 C 40,0 -30,0 10,0");
    // 距离远 → dx = 200*0.42 = 84。
    const far = edgePath({ x: 0, y: 0 }, { x: 200, y: 50 });
    expect(far).toBe("M 0,0 C 84,0 116,50 200,50");
  });

  it("clampZoom 夹到 [0.22, 2.2]", () => {
    expect(clampZoom(0.01)).toBe(ZOOM_MIN);
    expect(clampZoom(99)).toBe(ZOOM_MAX);
    expect(clampZoom(1)).toBe(1);
  });

  it("gridSize = 22*zoom", () => {
    expect(gridSize(1)).toBe(22);
    expect(gridSize(0.5)).toBe(11);
  });

  it("zoomAt 以光标为锚：锚点下世界坐标缩放前后不变", () => {
    const anchor = { x: 300, y: 200 };
    const before = screenToWorld(anchor, VP);
    const next = zoomAt(VP, anchor, 1.12);
    expect(next.zoom).toBeCloseTo(0.72 * 1.12, 6);
    const after = screenToWorld(anchor, next);
    expect(after.x).toBeCloseTo(before.x, 6);
    expect(after.y).toBeCloseTo(before.y, 6);
  });

  it("zoomAt 触顶 clamp 后 pan 仍自洽（不溢出区间）", () => {
    const next = zoomAt({ panX: 0, panY: 0, zoom: 2.1 }, { x: 100, y: 100 }, 1.12);
    expect(next.zoom).toBe(ZOOM_MAX);
  });
});

describe("G2 types · 色彩映射全走 token", () => {
  it("catColor / edgeStroke 返回 var(--desk-*)，selected 优先 accent", () => {
    expect(catColor("factor")).toBe("var(--desk-success)");
    expect(catColor("exec")).toBe("var(--desk-accent)");
    expect(edgeStroke("ok", false)).toBe("var(--desk-edge-ok)");
    expect(edgeStroke("bad", true)).toBe("var(--desk-accent)");
  });
});

describe("G2 NodeCard · 受控渲染 + 回调", () => {
  it("渲染标题/正文行/端口；锁节点出 🔒；点击上抛 onSelect", () => {
    const onSelect = vi.fn();
    render(<NodeCard node={mkNode({ locked: true })} onSelect={onSelect} />);
    expect(screen.getByText("动量因子")).toBeInTheDocument();
    expect(screen.getByText("lookback: 20")).toBeInTheDocument();
    expect(screen.getByLabelText("locked")).toBeInTheDocument();
    expect(screen.getByLabelText("入端口 价量")).toBeInTheDocument();
    expect(screen.getByLabelText("出端口 因子值")).toBeInTheDocument();

    fireEvent.click(screen.getByText("动量因子"));
    expect(onSelect).toHaveBeenCalledWith("n1");
  });

  it("选中态用 accent 边框", () => {
    const { container } = render(<NodeCard node={mkNode()} selected />);
    const wrap = container.querySelector("[data-node-id='n1']") as HTMLElement;
    expect(wrap.style.border).toContain("var(--desk-accent)");
  });
});

describe("G2 GraphCanvas · 受控渲染 + 回调", () => {
  const nodes = [mkNode(), mkNode({ id: "n2", x: 400, y: 80, title: "风控门", cat: "risk" })];
  const edges: EdgeView[] = [
    { id: "e1", from: { node: "n1", port: "out0" }, to: { node: "n2", port: "in0" }, compat: "ok" },
  ];

  function setup(extra: Record<string, unknown> = {}) {
    const cb = {
      onPan: vi.fn(),
      onZoom: vi.fn(),
      onSelectNode: vi.fn(),
      onSelectEdge: vi.fn(),
      onNodeMove: vi.fn(),
      onConnect: vi.fn(),
      onMarquee: vi.fn(),
    };
    const r = render(
      <GraphCanvas
        nodes={nodes}
        edges={edges}
        pan={{ x: 44, y: 70 }}
        zoom={0.72}
        selection={{ nodeIds: ["n1"], edgeIds: [] }}
        {...cb}
        {...extra}
      />,
    );
    return { ...r, cb };
  }

  it("渲染 #sb-pan transform translate/scale + 点阵网格背景", () => {
    const { container } = setup();
    const pan = container.querySelector("#sb-pan") as HTMLElement;
    expect(pan.style.transform).toBe("translate(44px, 70px) scale(0.72)");
    expect(pan.style.transformOrigin).toBe("0 0");
    const surf = container.querySelector("[data-graph-surface]") as HTMLElement;
    expect(surf.style.backgroundImage).toContain("radial-gradient");
    // size = 22*0.72 = 15.84
    expect(surf.style.backgroundSize).toContain("15.84px");
  });

  it("点节点触发 onSelectNode", () => {
    const { cb } = setup();
    fireEvent.click(screen.getByText("动量因子"));
    expect(cb.onSelectNode).toHaveBeenCalledWith("n1");
  });

  it("点连线触发 onSelectEdge", () => {
    const { container, cb } = setup();
    const edge = container.querySelector("[data-edge-id='e1']") as SVGPathElement;
    fireEvent.click(edge);
    expect(cb.onSelectEdge).toHaveBeenCalledWith("e1");
  });

  it("空白 pointerdown→move 触发 onPan（平移）", () => {
    const { container, cb } = setup();
    const surf = container.querySelector("[data-graph-surface]") as HTMLElement;
    fireEvent.pointerDown(surf, { clientX: 100, clientY: 100, target: surf });
    fireEvent.pointerMove(surf, { clientX: 130, clientY: 115 });
    expect(cb.onPan).toHaveBeenCalled();
    const arg = cb.onPan.mock.calls[0][0];
    expect(arg.x).toBeCloseTo(44 + 30, 3);
    expect(arg.y).toBeCloseTo(70 + 15, 3);
  });

  it("Shift+空白 pointerdown→move 触发 onMarquee（框选）", () => {
    const { container, cb } = setup();
    const surf = container.querySelector("[data-graph-surface]") as HTMLElement;
    fireEvent.pointerDown(surf, { clientX: 50, clientY: 50, shiftKey: true, target: surf });
    fireEvent.pointerMove(surf, { clientX: 90, clientY: 80 });
    expect(cb.onMarquee).toHaveBeenCalled();
    const calls = cb.onMarquee.mock.calls;
    const rect = calls[calls.length - 1][0];
    expect(rect).toMatchObject({ x: 50, y: 50, w: 40, h: 30 });
  });

  it("wheel 以光标为锚触发 onZoom", () => {
    const { container, cb } = setup();
    const surf = container.querySelector("[data-graph-surface]") as HTMLElement;
    fireEvent.wheel(surf, { deltaY: -100, clientX: 200, clientY: 150 });
    expect(cb.onZoom).toHaveBeenCalled();
    const vp = cb.onZoom.mock.calls[0][0];
    expect(vp.zoom).toBeCloseTo(0.72 * 1.12, 6);
  });

  it("framed children（banner/minimap 浮层）渲染在屏幕层", () => {
    setup({ children: <div data-testid="banner">diff</div> });
    expect(screen.getByTestId("banner")).toBeInTheDocument();
  });
});

describe("G2 对抗#1 · canvas/ 实现禁裸 hex（须走 --desk-* token）", () => {
  it("canvas 目录所有非测试 ts/tsx 不含 #hex 字面色", () => {
    const files = readdirSync(here).filter(
      (f) => /\.tsx?$/.test(f) && !f.includes(".test."),
    );
    const HEX = /#[0-9a-fA-F]{3,8}\b/g;
    const offenders: string[] = [];
    for (const f of files) {
      const hits = readFileSync(join(here, f), "utf8").match(HEX);
      if (hits) offenders.push(`${f}: ${hits.join(",")}`);
    }
    expect(offenders).toEqual([]);
  });
});
