import { useEffect, useMemo, useState } from "react";
import { MockBadge } from "../../../components/desk";
import { authFetch } from "../../../lib/auth";
import { MetricCell, PanelCard, SectionTitle } from "./parts";
import { famColorVar, famBgVar, icThresholdColor, irThresholdColor } from "./factorData";
import {
  type GateResult,
  type GenSortKey,
  type GeneratorConfig,
  type MiningCandidate,
  GEN_SORT_KEYS,
  DEFAULT_GEN_CONFIG,
  buildMiningCandidates,
  gateEvaluate,
  gatePassColor,
  honestNCount,
} from "./factorLabData";

/** 后端 /api/factors/mine 响应（candidates 与 gate 物理分离）。 */
interface MineResponse {
  candidates: { candidate_id: string; expr: string; fam: string; complexity: number; op_count: number; novelty: number }[];
  gate: { candidate_id: string; ic: number; ir: number; dsr: number; passed: boolean; note: string }[];
  honest_n: { total: number; n_eff: number; duplicates: number };
  pass_count: number;
}

/**
 * F3 · 暴力遍历挖掘视图（生成器配置 + 守门器结果 + 诚实-N 计数）。
 *
 * R16 严格解耦（dev/decisions §R16 / GOAL §3）：
 *  - 生成器只看「结构多样性」（复杂度 / 算子覆盖 / 族多样性 / 新颖度）排序候选；
 *    守门指标（IC/IR/DSR…）绝不进生成器的 fitness/排序。
 *  - 守门器是独立后置环节，才看 IC/IR/DSR。
 *  - 诚实-N：等价公式不重复计入 N_eff（N_eff ≤ N_total）。
 *
 * 全 mock + MockBadge；紫 accent；零裸 hex。
 */

export interface FactorMiningViewProps {
  config: GeneratorConfig;
  sortKey: GenSortKey;
  /** 受控：切换生成器排序键（会被 R16 守卫拦守门指标）。 */
  onSortKey: (k: GenSortKey) => void;
}

export function FactorMiningView({ config, sortKey, onSortKey }: FactorMiningViewProps) {
  const mockCands = useMemo(() => buildMiningCandidates(), []);

  // 接真 POST /api/factors/mine：生成器排序键 + 守门 + 诚实-N 全走后端（R16 解耦在后端强制）。
  // 后端到达即覆盖；离线/未登录/响应非 mine 形 → 回落本地 mock。
  const [server, setServer] = useState<MineResponse | null>(null);
  const [mineLive, setMineLive] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setServer(null);
    authFetch("/api/factors/mine", {
      method: "POST",
      body: JSON.stringify({
        exprs: mockCands.map((c) => ({ expr: c.expr, fam: c.fam })),
        sort_key: sortKey,
      }),
    })
      .then(async (r) => {
        const j = await r.json().catch(() => null);
        if (cancelled || !j || !Array.isArray(j.candidates) || !Array.isArray(j.gate)) return;
        setServer(j as MineResponse);
        setMineLive(true);
      })
      .catch(() => {
        if (!cancelled) setMineLive(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mockCands, sortKey]);

  // 候选（生成器排序，结构维度）——优先用后端排序结果，否则本地排序回落。
  const ranked: MiningCandidate[] = useMemo(() => {
    if (server) {
      return server.candidates.map((c) => ({
        id: c.candidate_id,
        expr: c.expr,
        fam: c.fam as MiningCandidate["fam"],
        complexity: c.complexity,
        opCount: c.op_count,
        novelty: c.novelty,
      }));
    }
    const arr = [...mockCands];
    arr.sort((a, b) => {
      switch (sortKey) {
        case "complexity":
          return b.complexity - a.complexity;
        case "op_coverage":
          return b.opCount - a.opCount;
        case "novelty":
          return b.novelty - a.novelty;
        case "family_diversity":
          return a.fam.localeCompare(b.fam);
      }
    });
    return arr;
  }, [server, mockCands, sortKey]);

  // 守门器：独立后置环节，才出现 IC/IR/DSR。后端到达用后端裁决，否则本地。
  const gateById = useMemo(() => {
    if (server) {
      const m = new Map<string, GateResult>();
      for (const g of server.gate)
        m.set(g.candidate_id, {
          candidateId: g.candidate_id,
          ic: g.ic,
          ir: g.ir,
          dsr: g.dsr,
          passed: g.passed,
          note: g.note,
        });
      return m;
    }
    const gate = gateEvaluate(mockCands);
    return new Map(gate.map((g) => [g.candidateId, g]));
  }, [server, mockCands]);

  // 诚实-N：等价公式不抬高 N_eff（后端走 lineage.config_hash 归一）。
  const { total, nEff } = useMemo(() => {
    if (server) return { total: server.honest_n.total, nEff: server.honest_n.n_eff };
    return honestNCount(mockCands.map((c) => c.expr));
  }, [server, mockCands]);
  const dupes = total - nEff;
  const passCount = server
    ? server.pass_count
    : ranked.filter((c) => gateById.get(c.id)?.passed).length;

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex", background: "var(--desk-canvas)" }}>
      {/* LEFT · 生成器配置面板（绝无守门指标） */}
      <div
        style={{
          flex: "none",
          width: 320,
          borderRight: "1px solid var(--desk-border)",
          overflowY: "auto",
          padding: "14px 14px",
          background: "var(--desk-soft-btn)",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <PanelCard>
          <SectionTitle glyph="⚙">生成器 · 遍历配置</SectionTitle>
          <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)", lineHeight: 1.5, marginBottom: 10 }}>
            只决定「生成什么」。守门指标（IC/IR/DSR）在此不可见 —— 解耦由设计强制（R16）。
          </div>

          <ConfigRow label="算子组">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {config.ops.map((o) => (
                <span key={o} style={chipStyle}>{o}</span>
              ))}
            </div>
          </ConfigRow>
          <ConfigRow label="字段">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {config.fields.map((f) => (
                <span key={f} style={chipStyle}>{f}</span>
              ))}
            </div>
          </ConfigRow>
          <ConfigRow label="窗口候选">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {config.windows.map((w) => (
                <span key={w} style={chipStyle}>{w}</span>
              ))}
            </div>
          </ConfigRow>
          <ConfigRow label="最大嵌套深度">
            <span style={{ fontSize: 12, color: "var(--desk-text-soft)", fontWeight: 600 }}>{config.maxDepth}</span>
          </ConfigRow>
        </PanelCard>

        <PanelCard>
          <SectionTitle glyph="↧">候选排序键（fitness）</SectionTitle>
          <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)", lineHeight: 1.5, marginBottom: 9 }}>
            仅结构多样性维度。守门指标不在选项里 —— 防止「先看结果再生成」的选择偏误。
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
            {GEN_SORT_KEYS.map((k) => {
              const active = k.value === sortKey;
              return (
                <button
                  key={k.value}
                  data-sortkey={k.value}
                  onClick={() => onSortKey(k.value)}
                  style={{
                    fontSize: 10,
                    fontFamily: "inherit",
                    padding: "4px 9px",
                    borderRadius: "var(--desk-radius-pill)",
                    cursor: "pointer",
                    border: `1px solid ${active ? "var(--desk-accent)" : "var(--desk-border)"}`,
                    background: active
                      ? "color-mix(in srgb, var(--desk-accent) 16%, transparent)"
                      : "transparent",
                    color: active ? "var(--desk-ghost)" : "var(--desk-text-dim)",
                  }}
                >
                  {k.label}
                </button>
              );
            })}
          </div>
        </PanelCard>

        {/* 诚实-N 计数 */}
        <PanelCard accentBorder>
          <SectionTitle glyph="∮">诚实-N 守门人</SectionTitle>
          <div style={{ display: "flex", gap: 9 }}>
            <MetricCell label="生成总数 N" value={String(total)} color="var(--desk-text-soft)" big={20} />
            <MetricCell
              label="有效独立 N_eff"
              value={String(nEff)}
              color="var(--desk-accent)"
              big={20}
              note={dupes > 0 ? `去掉 ${dupes} 个等价改写` : "无等价重复"}
            />
          </div>
          <div
            data-honest-n
            style={{ fontSize: 9.5, color: "var(--desk-text-muted)", lineHeight: 1.5, marginTop: 8 }}
          >
            多重检验校正（Bonferroni/BHY）按 N_eff={nEff} 而非 N={total} 算 —— 等价公式不灌水门槛。
          </div>
        </PanelCard>
      </div>

      {/* RIGHT · 候选列表（生成器排序）＋ 守门器结果（独立列） */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
        <div
          style={{
            flex: "none",
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "9px 16px",
            borderBottom: "1px solid var(--desk-border)",
            background: "var(--desk-card)",
          }}
        >
          <span style={{ color: "var(--desk-accent)" }}>⛏</span>
          <span style={{ fontSize: 12, fontWeight: 600, color: "var(--desk-text-soft)" }}>遍历候选 × 守门</span>
          <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>
            左半=生成器排序（结构）· 右半=守门器评判（独立）
          </span>
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 10.5, color: gatePassColor(passCount > 0) }}>守门通过 {passCount}/{total}</span>
          <MockBadge
            label={
              mineLive
                ? "已接真 /api/factors/mine · 生成/守门后端解耦 + 诚实-N"
                : "MOCK 数据 · 遍历挖掘合成（离线回落 · 待接 /api/factors/mine）"
            }
          />
        </div>

        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: "14px 16px" }}>
          {/* 解耦标识：两栏明确分开 */}
          <div style={{ display: "flex", gap: 10, marginBottom: 8, fontSize: 9.5 }}>
            <div style={{ flex: 1, color: "var(--desk-accent)" }}>◀ 生成器视野（结构维度，无守门指标）</div>
            <div style={{ flex: "none", width: 250, color: "var(--desk-info)" }}>守门器视野（IC/IR/DSR）▶</div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            {ranked.map((c, rank) => {
              const g = gateById.get(c.id);
              return (
                <div
                  key={c.id}
                  data-candidate={c.id}
                  style={{
                    display: "flex",
                    gap: 10,
                    border: "1px solid var(--desk-border)",
                    borderRadius: "var(--desk-radius)",
                    overflow: "hidden",
                    background: "var(--desk-card)",
                  }}
                >
                  {/* 生成器半区：rank + 结构属性 */}
                  <div style={{ flex: 1, minWidth: 0, padding: "9px 11px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 4 }}>
                      <span style={{ fontSize: 10, color: "var(--desk-accent)", fontWeight: 700 }}>#{rank + 1}</span>
                      <span
                        style={{
                          fontSize: 9,
                          padding: "1px 6px",
                          borderRadius: "var(--desk-radius-pill)",
                          border: `1px solid ${famColorVar(c.fam)}`,
                          background: famBgVar(c.fam),
                          color: famColorVar(c.fam),
                        }}
                      >
                        {c.fam}
                      </span>
                    </div>
                    <code style={{ display: "block", fontSize: 11, color: "var(--desk-info)", wordBreak: "break-all" }}>
                      {c.expr}
                    </code>
                    <div style={{ display: "flex", gap: 12, marginTop: 5, fontSize: 9.5, color: "var(--desk-text-faint)" }}>
                      <span>复杂度 {c.complexity}</span>
                      <span>算子 {c.opCount}</span>
                      <span>新颖度 {c.novelty.toFixed(2)}</span>
                    </div>
                  </div>

                  {/* 守门器半区：独立列，IC/IR/DSR + 裁决（不达标不染绿） */}
                  <div
                    data-gate={c.id}
                    style={{
                      flex: "none",
                      width: 250,
                      padding: "9px 11px",
                      borderLeft: "1px solid var(--desk-border)",
                      background: "var(--desk-soft-btn)",
                    }}
                  >
                    <div style={{ display: "flex", gap: 12, fontSize: 10 }}>
                      <span style={{ color: "var(--desk-text-muted)" }}>
                        IC <span style={{ color: g ? icThresholdColor(Math.abs(g.ic)) : "var(--desk-text-soft)", fontWeight: 700 }}>{g?.ic.toFixed(3)}</span>
                      </span>
                      <span style={{ color: "var(--desk-text-muted)" }}>
                        IR <span style={{ color: g ? irThresholdColor(g.ir) : "var(--desk-text-soft)", fontWeight: 700 }}>{g?.ir.toFixed(2)}</span>
                      </span>
                      <span style={{ color: "var(--desk-text-muted)" }}>
                        DSR <span style={{ color: g && g.dsr >= 0 ? "var(--desk-text-soft)" : "var(--desk-danger)", fontWeight: 700 }}>{g?.dsr.toFixed(2)}</span>
                      </span>
                    </div>
                    <div
                      data-gate-pass={g?.passed ? "true" : "false"}
                      style={{ marginTop: 6, fontSize: 10, color: gatePassColor(!!g?.passed) }}
                    >
                      {g?.passed ? "✓ 守门通过" : `△ 未过 · ${g?.note}`}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* 加密短样本 DSR caveat（show + caveat，非 hide；R16=B / P3） */}
          <div
            style={{
              marginTop: 12,
              fontSize: 9.5,
              color: "var(--desk-warning)",
              padding: "7px 11px",
              borderRadius: "var(--desk-radius-sm)",
              border: "1px solid var(--desk-warning)",
              background: "color-mix(in srgb, var(--desk-warning) 10%, transparent)",
              lineHeight: 1.5,
            }}
          >
            ⚠ 加密短样本：DSR 照常显示但不可作单点裁决（短样本 + 幸存者偏差使偏度/峰度修正失真，R16=B / P3）。
          </div>
        </div>
      </div>
    </div>
  );
}

const chipStyle = {
  fontSize: 9.5,
  padding: "2px 7px",
  borderRadius: "var(--desk-radius-pill)",
  border: "1px solid var(--desk-border)",
  background: "var(--desk-input)",
  color: "var(--desk-text-dim)",
} as const;

function ConfigRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 9 }}>
      <div style={{ fontSize: 9.5, color: "var(--desk-text-faint)", marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

export { DEFAULT_GEN_CONFIG };
export default FactorMiningView;
