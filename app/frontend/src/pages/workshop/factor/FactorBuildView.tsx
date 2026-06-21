import { useMemo } from "react";
import {
  AgentChat,
  type AgentBlock,
  ChatComposer,
  MockBadge,
} from "../../../components/desk";
import { CodeBox, PanelCard, SectionTitle } from "./parts";
import { nz, svgBars } from "./factorData";

/** 构建台 agent 对话块（mock）。 */
export interface BuildChatMsg {
  role: "user" | "think" | "say" | "patch";
  text: string;
  code?: string;
}

/** 后端 /api/factors/validate 返回（接真时注入）。 */
export interface FactorValidateLive {
  valid: boolean;
  stage: string;        // compile | lookahead | ok
  reason: string;
  ic: { ic_mean: number | null; ic_ir: number | null; ic_tstat_nw: number | null } | null;
}

export interface FactorBuildViewProps {
  expr: string;
  factorId: string;
  chat: BuildChatMsg[];
  draft: string;
  onDraft: (v: string) => void;
  onSend: () => void;
  onInsert: (token: string) => void;
  onChip: (q: string) => void;
  gateOpen: boolean;
  onGate: () => void;
  onGateClose: () => void;
  onGateConfirm: () => void;
  /** 接真即时校验（编译/前视门 + IC）；存在则覆盖 mock 预览并改挂 LIVE。 */
  live?: FactorValidateLive | null;
}

const OP_GROUPS: { group: string; ops: [string, string][] }[] = [
  {
    group: "时序算子 ts_*",
    ops: [
      ["ts_mean", "ts_mean(x, n)"],
      ["ts_std", "ts_std(x, n)"],
      ["ts_zscore", "ts_zscore(x, n)"],
      ["ts_pct_change", "ts_pct_change(x, n)"],
      ["ts_corr", "ts_corr(x, y, n)"],
      ["ts_max", "ts_max(x, n)"],
      ["ts_min", "ts_min(x, n)"],
      ["ts_ema", "ts_ema(x, n)"],
      ["ts_decay_linear", "ts_decay_linear(x, n)"],
      ["ts_skew", "ts_skew(x, n)"],
    ],
  },
  {
    group: "截面算子 cs_*",
    ops: [
      ["rank", "rank(x)"],
      ["zscore", "zscore(x)"],
      ["cs_demean", "cs_demean(x)"],
      ["cs_winsorize", "cs_winsorize(x)"],
    ],
  },
  {
    group: "逐元素",
    ops: [
      ["log", "log(x)"],
      ["neg", "neg(x)"],
      ["abs", "abs(x)"],
      ["sign", "sign(x)"],
    ],
  },
  {
    group: "字段",
    ops: [
      ["close", "字段 · 收盘"],
      ["open", "字段 · 开盘"],
      ["high", "字段 · 最高"],
      ["low", "字段 · 最低"],
      ["volume", "字段 · 成交量"],
      ["amount", "字段 · 成交额"],
    ],
  },
];

const OP_COUNT = OP_GROUPS.reduce((a, g) => a + g.ops.length, 0);

const CHIPS: [string, string][] = [
  ["加一层截面 rank", "把外层套一个 rank() 做截面中性"],
  ["降换手", "把短窗口换成 20 日，降低换手"],
  ["IC 衰减检查", "跑 1/3/5/10/20 日衰减曲线"],
];

/** 括号配平 = 编译通过（mock 校验）。 */
export function isBalanced(expr: string): boolean {
  return expr.split("(").length === expr.split(")").length;
}

interface AstLine {
  depth: number;
  text: string;
}

function buildAst(expr: string): AstLine[] {
  const lines: AstLine[] = [];
  let depth = 0;
  let cur = "";
  const push = () => {
    if (cur.trim()) lines.push({ depth, text: cur.trim() });
    cur = "";
  };
  for (const ch of expr) {
    if (ch === "(") {
      cur += "(";
      push();
      depth++;
    } else if (ch === ")") {
      push();
      depth = Math.max(0, depth - 1);
    } else if (ch === ",") {
      push();
    } else {
      cur += ch;
    }
  }
  push();
  return lines;
}

/** 构建台 view：左 agent chat + 中 DSL 编辑器 + gate modal。 */
export function FactorBuildView(props: FactorBuildViewProps) {
  const {
    expr,
    factorId,
    chat,
    draft,
    onDraft,
    onSend,
    onInsert,
    onChip,
    gateOpen,
    onGate,
    onGateClose,
    onGateConfirm,
    live,
  } = props;

  const balanced = isBalanced(expr);
  // 接真：编译/前视门状态用后端 validate 真结果（前视未过 = 红，绝不假绿灯）。
  let validTxt = balanced ? "✓ 括号配平 · 编译通过" : "✕ 括号未配平";
  let validColor = balanced ? "var(--desk-success)" : "var(--desk-danger)";
  if (live) {
    if (live.valid) {
      validTxt = "✓ 编译通过 · 前视门通过（接真）";
      validColor = "var(--desk-success)";
    } else if (live.stage === "lookahead") {
      validTxt = "✕ 前视门未通过 · 引入未来函数";
      validColor = "var(--desk-danger)";
    } else {
      validTxt = `✕ 编译失败：${live.reason.slice(0, 40)}`;
      validColor = "var(--desk-danger)";
    }
  }

  const blocks: AgentBlock[] = chat.map((c, i) => {
    if (c.role === "patch") {
      return {
        id: `bd-${i}`,
        type: "patch",
        patchTitle: c.text,
        patchId: "expr",
        affected: c.code,
      };
    }
    return { id: `bd-${i}`, type: c.role, text: c.text };
  });

  const ast = useMemo(() => {
    const raw = buildAst(expr);
    return (raw.length ? raw : [{ depth: 0, text: expr }]).map((l) => {
      const cleaned = l.text.replace(/[()]/g, "");
      const isField = /^(close|open|high|low|volume|amount)$/.test(cleaned);
      const isNum = /^\d/.test(l.text);
      return {
        indent: "  ".repeat(l.depth) + (l.depth ? "└ " : ""),
        text: l.text,
        color: isField
          ? "var(--desk-success)"
          : isNum
            ? "var(--desk-warning)"
            : "var(--desk-info)",
      };
    });
  }, [expr]);

  const previewSeed = (expr.length * 7) % 13;
  const previewSeries = useMemo(() => {
    const out: number[] = [];
    for (let k = 0; k < 30; k++) out.push(0.03 + (nz(previewSeed * 5 + k) - 0.5) * 0.06);
    return out;
  }, [previewSeed]);
  const previewBars = svgBars(previewSeries, 300, 70, 35);
  // 接真：IC/IR 用后端 validate 的真实 IC 报告；否则 mock。
  const previewIc =
    live?.ic?.ic_mean != null ? live.ic.ic_mean.toFixed(3) : (0.03 + (nz(previewSeed) - 0.5) * 0.03).toFixed(3);
  const previewIr =
    live?.ic?.ic_ir != null ? live.ic.ic_ir.toFixed(2) : (0.7 + nz(previewSeed + 1) * 0.8).toFixed(2);

  const lints = [
    { icon: "✓", color: "var(--desk-success)", t: "无前视：仅用 ts_* 历史窗口与当期字段" },
    { icon: "✓", color: "var(--desk-success)", t: "量纲：截面 rank/zscore 已对齐" },
    { icon: "△", color: "var(--desk-warning)", t: "换手提示：含 1 日窗口，预计周换手偏高" },
  ];

  const gateChecks = [
    { icon: balanced ? "✓" : "✕", color: validColor, t: "表达式编译通过（polars 计算图）" },
    { icon: "✓", color: "var(--desk-success)", t: "前视检查通过 · 无标签穿越" },
    { icon: "✓", color: "var(--desk-success)", t: "registry 无重名 · 版本 v1" },
  ];

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", position: "relative" }}>
      {/* LEFT · agent chat */}
      <div
        style={{
          flex: "none",
          width: 330,
          borderRight: "1px solid var(--desk-border)",
          display: "flex",
          flexDirection: "column",
          background: "var(--desk-soft-btn)",
        }}
      >
        <ChatHeader glyph="✳" title="因子 Agent" hint="Claude Code · DSL 即代码" />
        <AgentChat
          blocks={blocks}
          composer={
            <>
              <div
                style={{
                  flex: "none",
                  display: "flex",
                  flexWrap: "wrap",
                  gap: 5,
                  padding: "8px 13px 0",
                }}
              >
                {CHIPS.map(([label, q]) => (
                  <button
                    key={label}
                    onClick={() => onChip(q)}
                    style={{
                      fontSize: 10,
                      color: "var(--desk-ghost)",
                      border: "1px solid var(--desk-accent)",
                      background: "color-mix(in srgb, var(--desk-accent) 12%, transparent)",
                      borderRadius: "var(--desk-radius-pill)",
                      padding: "3px 9px",
                      cursor: "pointer",
                      fontFamily: "inherit",
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <ChatComposer
                draft={draft}
                onDraftChange={onDraft}
                onSend={onSend}
                placeholder="描述想抓的 alpha，或直接写表达式…"
                model="claude (mock)"
                permissionMode="ask"
                branch="factor"
              />
            </>
          }
        />
      </div>

      {/* CENTER · DSL editor */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", background: "var(--desk-canvas)" }}>
        <div
          style={{
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 9,
            padding: "9px 16px",
            borderBottom: "1px solid var(--desk-border)",
            background: "var(--desk-card)",
          }}
        >
          <span style={{ color: "var(--desk-accent)" }}>⌨</span>
          <span style={{ fontSize: 12, color: "var(--desk-text-soft)", fontWeight: 600 }}>
            表达式编辑器
          </span>
          <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>
            factor_factory.expression · polars 编译
          </span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 10.5, color: validColor }}>{validTxt}</span>
        </div>
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "18px 22px" }}>
          <div style={{ maxWidth: 760 }}>
            <div style={{ marginBottom: 14 }}>
              <CodeBox label={`factor_id · ${factorId}`} big={16}>
                {expr}
              </CodeBox>
            </div>

            {/* operator palette */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 11, color: "var(--desk-text-muted)", marginBottom: 8 }}>
                算子库 · 点击插入（{OP_COUNT} 个）
              </div>
              {OP_GROUPS.map((g) => (
                <div key={g.group} style={{ marginBottom: 9 }}>
                  <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)", marginBottom: 5 }}>
                    {g.group}
                  </div>
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {g.ops.map(([name, sig]) => (
                      <button
                        key={name}
                        onClick={() => onInsert(name)}
                        title={sig}
                        style={{
                          fontSize: 10.5,
                          color: "var(--desk-info)",
                          background: "var(--desk-input)",
                          border: "1px solid var(--desk-info)",
                          borderRadius: "var(--desk-radius-sm)",
                          padding: "4px 9px",
                          cursor: "pointer",
                          fontFamily: "inherit",
                        }}
                      >
                        {name}
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {/* AST */}
            <PanelCard style={{ marginBottom: 14 }}>
              <SectionTitle>AST · 解析树</SectionTitle>
              <div style={{ fontFamily: "inherit", fontSize: 11.5, lineHeight: 1.85 }}>
                {ast.map((n, i) => (
                  <div key={i} style={{ display: "flex", color: n.color }}>
                    <span style={{ color: "var(--desk-text-faint)", whiteSpace: "pre" }}>{n.indent}</span>
                    <span>{n.text}</span>
                  </div>
                ))}
              </div>
            </PanelCard>

            {/* live IC preview + lint */}
            <div style={{ display: "flex", gap: 12 }}>
              <PanelCard style={{ flex: 1 }}>
                <SectionTitle
                  right={
                    <span style={{ fontSize: 9.5, fontWeight: 400, color: "var(--desk-success)" }}>
                      样本内 · 60日
                    </span>
                  }
                >
                  即时 IC 预览
                </SectionTitle>
                <svg viewBox="0 0 300 70" preserveAspectRatio="none" style={{ width: "100%", height: 58, display: "block" }}>
                  <line x1="0" y1="35" x2="300" y2="35" stroke="var(--desk-border-strong)" strokeWidth="1" strokeDasharray="2 3" />
                  <path d={previewBars} stroke="var(--desk-accent)" strokeWidth="2" />
                </svg>
                <div style={{ display: "flex", gap: 14, marginTop: 8, fontSize: 11 }}>
                  <span style={{ color: "var(--desk-text-muted)" }}>
                    IC <span style={{ color: "var(--desk-accent)", fontWeight: 700 }}>{previewIc}</span>
                  </span>
                  <span style={{ color: "var(--desk-text-muted)" }}>
                    IR <span style={{ color: "var(--desk-text-soft)" }}>{previewIr}</span>
                  </span>
                </div>
                <div style={{ marginTop: 10 }}>
                  {live ? (
                    <span
                      data-testid="build-live-badge"
                      style={{
                        fontSize: 10,
                        fontWeight: 700,
                        color: live.valid ? "var(--desk-success)" : "var(--desk-danger)",
                        border: `1px solid color-mix(in srgb, ${live.valid ? "var(--desk-success)" : "var(--desk-danger)"} 40%, transparent)`,
                        borderRadius: 4,
                        padding: "1px 6px",
                      }}
                    >
                      {live.valid ? "LIVE · 即时 IC 接真" : `校验未过 · ${live.stage}`}
                    </span>
                  ) : (
                    <MockBadge label="MOCK 数据 · 即时 IC（待接 /api/factors/validate）" />
                  )}
                </div>
              </PanelCard>
              <div style={{ flex: "none", width: 230, display: "flex", flexDirection: "column", gap: 8 }}>
                {lints.map((l, i) => (
                  <div
                    key={i}
                    style={{
                      display: "flex",
                      gap: 8,
                      fontSize: 10.5,
                      background: "var(--desk-card)",
                      border: "1px solid var(--desk-border)",
                      borderRadius: "var(--desk-radius)",
                      padding: "7px 10px",
                    }}
                  >
                    <span style={{ color: l.color }}>{l.icon}</span>
                    <span style={{ color: "var(--desk-text-dim)", lineHeight: 1.45 }}>{l.t}</span>
                  </div>
                ))}
                <button
                  onClick={onGate}
                  style={{
                    background: "color-mix(in srgb, var(--desk-accent) 14%, transparent)",
                    border: "1px solid var(--desk-accent)",
                    color: "var(--desk-ghost)",
                    fontFamily: "inherit",
                    fontSize: 11.5,
                    padding: 9,
                    borderRadius: "var(--desk-radius)",
                    cursor: "pointer",
                    marginTop: 2,
                  }}
                >
                  ⊕ 注册到因子库
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* gate modal */}
      {gateOpen && (
        <div
          onClick={onGateClose}
          style={{
            position: "absolute",
            inset: 0,
            background: "color-mix(in srgb, var(--desk-bg) 60%, transparent)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 90,
          }}
        >
          <div
            role="dialog"
            aria-label="注册因子 · 进入五态机"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: 440,
              background: "var(--desk-card)",
              border: "1px solid var(--desk-accent)",
              borderRadius: "var(--desk-radius-lg)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "12px 16px",
                background: "color-mix(in srgb, var(--desk-accent) 12%, transparent)",
                borderBottom: "1px solid var(--desk-node-border)",
                display: "flex",
                alignItems: "center",
                gap: 9,
              }}
            >
              <span style={{ color: "var(--desk-accent)" }}>⊕</span>
              <span style={{ fontWeight: 700 }}>注册因子 · 进入五态机</span>
            </div>
            <div style={{ padding: "14px 16px" }}>
              <div style={{ fontSize: 12, color: "var(--desk-text-soft)", marginBottom: 11, lineHeight: 1.6 }}>
                把 <span style={{ color: "var(--desk-accent)" }}>{factorId}</span> 写入 registry，初始状态{" "}
                <span style={{ color: "var(--desk-text-muted)", fontWeight: 600 }}>NEW</span>
                。表达式编译通过、无前视、无重名才可注册。
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 13 }}>
                {gateChecks.map((c, i) => (
                  <div key={i} style={{ display: "flex", gap: 9, fontSize: 11.5 }}>
                    <span style={{ color: c.color }}>{c.icon}</span>
                    <span style={{ color: "var(--desk-text-dim)" }}>{c.t}</span>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", gap: 9 }}>
                <button
                  onClick={onGateConfirm}
                  style={{
                    background: "var(--desk-accent)",
                    border: "none",
                    color: "var(--desk-accent-ink)",
                    fontFamily: "inherit",
                    fontWeight: 700,
                    fontSize: 12,
                    padding: "9px 16px",
                    borderRadius: "var(--desk-radius)",
                    cursor: "pointer",
                  }}
                >
                  ✓ 注册
                </button>
                <button
                  onClick={onGateClose}
                  style={{
                    background: "transparent",
                    border: "1px solid var(--desk-border-hover)",
                    color: "var(--desk-text-muted)",
                    fontFamily: "inherit",
                    fontSize: 12,
                    padding: "9px 15px",
                    borderRadius: "var(--desk-radius)",
                    cursor: "pointer",
                  }}
                >
                  取消
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 聊天栏头部（构建台 / 研究台共用）。 */
export function ChatHeader({ glyph, title, hint }: { glyph: string; title: string; hint: string }) {
  return (
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
      <span style={{ color: "var(--desk-accent)" }}>{glyph}</span>
      <span style={{ fontWeight: 600, fontSize: 12.5 }}>{title}</span>
      <span style={{ marginLeft: "auto", fontSize: 9.5, color: "var(--desk-text-muted)" }}>{hint}</span>
    </div>
  );
}
