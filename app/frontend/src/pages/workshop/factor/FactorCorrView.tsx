import { useMemo } from "react";
import { MockBadge } from "../../../components/desk";
import { PanelCard, SectionTitle } from "./parts";
import { type MockFactor, type Market, nz } from "./factorData";

export interface CorrPair {
  a: string;
  b: string;
  rho: number;
}

/** 后端 /api/factors/correlation 返回（接真时注入）。 */
export interface FactorCorrLive {
  factor_ids: string[];
  matrix: number[][];
  redundant_pairs: { a: string; b: string; spearman: number }[];
  threshold: number;
  sample_count: number;
}

export interface FactorCorrViewProps {
  factors: MockFactor[];
  market: Market;
  pair: CorrPair | null;
  onPair: (p: CorrPair | null) => void;
  /** 接真相关矩阵；存在则覆盖合成矩阵并改挂 LIVE。 */
  live?: FactorCorrLive | null;
}

function corrShort(id: string): string {
  return id.replace("alpha_", "").slice(0, 12);
}

function corrVal(a: MockFactor, b: MockFactor): number {
  if (a.id === b.id) return 1;
  let r =
    a.fam === b.fam
      ? 0.55 + nz(a.id.length + b.id.length) * 0.4
      : (nz(a.id.length * 3 + b.id.length) - 0.5) * 0.7;
  if (a.icMean > 0 !== b.icMean > 0) r = -Math.abs(r) * 0.8;
  return Math.max(-0.95, Math.min(0.95, r));
}

/** 单元格背底：正相关偏红、负相关偏蓝，alpha 随 |ρ|，全 token color-mix。 */
function cellBg(v: number): string {
  if (v >= 0.999) return "var(--desk-border-strong)";
  const pct = (12 + Math.abs(v) * 70).toFixed(0);
  const base = v > 0 ? "var(--desk-danger)" : "var(--desk-info)";
  return `color-mix(in srgb, ${base} ${pct}%, transparent)`;
}

/** 相关性 view：相关矩阵 + 配对详情 + 去冗余簇 + 拥挤度。 */
export function FactorCorrView({ factors, market, pair, onPair, live }: FactorCorrViewProps) {
  // 接真：矩阵的因子顺序与值来自后端 factor_ids/matrix；否则用 mock 9 因子合成。
  const liveIndex = useMemo(() => {
    if (!live) return null;
    const idx = new Map<string, number>();
    live.factor_ids.forEach((id, i) => idx.set(id, i));
    return idx;
  }, [live]);
  const cm = useMemo(() => {
    if (live) {
      // 只展示后端矩阵里有的因子（按矩阵顺序）。
      const byId = new Map(factors.map((f) => [f.id, f] as const));
      return live.factor_ids
        .map((id) => byId.get(id))
        .filter((f): f is MockFactor => !!f)
        .slice(0, 12);
    }
    return factors.slice(0, 9);
  }, [factors, live]);
  // 接真单元格值：从后端矩阵按 factor_ids 索引取；缺则回落合成。
  const cellValue = (a: MockFactor, b: MockFactor): number => {
    if (a.id === b.id) return 1;
    if (live && liveIndex) {
      const ia = liveIndex.get(a.id);
      const ib = liveIndex.get(b.id);
      if (ia != null && ib != null) return live.matrix[ia][ib];
    }
    return corrVal(a, b);
  };
  const cols = cm.map((f) => corrShort(f.id));
  const window = market === "equity_cn" ? "504 交易日" : "365 日";

  const MOCK_CLUSTERS = [
    {
      rho: "0.82",
      keep: "alpha_vol_adj_mom_20d",
      members: [
        { id: "alpha_vol_adj_mom_20d", ir: "1.58", keep: true },
        { id: "alpha_mom_xs_20d", ir: "1.36", keep: false },
      ],
    },
    {
      rho: "0.74",
      keep: "alpha_reversal_5d",
      members: [
        { id: "alpha_reversal_5d", ir: "1.12", keep: true },
        { id: "alpha_reversal_residual_20d", ir: "0.88", keep: false },
      ],
    },
    {
      rho: "0.71",
      keep: "alpha_xs_demean_log_volume",
      members: [
        { id: "alpha_xs_demean_log_volume", ir: "0.93", keep: true },
        { id: "alpha_vol_to_avg_20d", ir: "0.46", keep: false },
      ],
    },
  ];
  // 接真：冗余簇来自后端 redundant_pairs（|ρ|≥阈值的对）；留 1 = mock IR 更高者（IR 仍 mock，
  // 后端无组合 IR——R25 诚实：建议非自动删，只摆证据）。否则 mock 簇。
  const irOf = (id: string): number => factors.find((f) => f.id === id)?.icIr ?? 0;
  const clusters = live
    ? live.redundant_pairs.map((p) => {
        const aIr = irOf(p.a);
        const bIr = irOf(p.b);
        const aKeep = aIr >= bIr;
        return {
          rho: Math.abs(p.spearman).toFixed(2),
          keep: aKeep ? p.a : p.b,
          members: [
            { id: p.a, ir: aIr.toFixed(2), keep: aKeep },
            { id: p.b, ir: bIr.toFixed(2), keep: !aKeep },
          ],
        };
      })
    : MOCK_CLUSTERS;

  const crowdRows = [
    { k: "平均 |ρ|（已选 9 因子）", v: "0.38", pct: "38%", color: "var(--desk-warning)" },
    { k: "有效独立维度", v: "5.2 / 9", pct: "58%", color: "var(--desk-success)" },
    { k: "最大簇占比", v: "动量 3 个", pct: "33%", color: "var(--desk-accent)" },
  ];

  let verdict = "";
  let pairColor = "var(--desk-text-soft)";
  if (pair) {
    const ab = Math.abs(pair.rho);
    pairColor = ab > 0.7 ? "var(--desk-danger)" : ab > 0.4 ? "var(--desk-warning)" : "var(--desk-success)";
    verdict =
      ab > 0.7
        ? "高度冗余 — 二者定价同一风险，组合里只保留 IR 更高的一个。"
        : ab > 0.4
          ? "中度相关 — 可共存但需控制合计权重，避免风格暴露过载。"
          : "低相关 — 提供独立信息，适合一起进组合分散风险。";
  }

  return (
    <div style={{ flex: 1, minWidth: 0, overflowY: "auto", background: "var(--desk-canvas)", padding: "20px 24px" }}>
      <div style={{ maxWidth: 1000 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
          <div style={{ fontSize: 12, color: "var(--desk-text-muted)" }}>
            因子相关矩阵 · 拥挤度与去冗余 · Spearman rank-corr，{window}
          </div>
          <span style={{ marginLeft: "auto" }}>
            {live ? (
              <span
                data-testid="corr-live-badge"
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: "var(--desk-success)",
                  border: "1px solid color-mix(in srgb, var(--desk-success) 40%, transparent)",
                  borderRadius: 4,
                  padding: "1px 6px",
                }}
              >
                LIVE · 矩阵接真（{live.sample_count} 期）
              </span>
            ) : (
              <MockBadge label="MOCK 数据 · 相关矩阵合成（待接 /api/factors/correlation）" />
            )}
          </span>
        </div>
        <div style={{ fontSize: 11, color: "var(--desk-text-faint)", marginBottom: 16 }}>
          高相关 = 重复定价同一风险，组合里只该留一个。点单元格看配对详情；右侧给去冗余建议。
        </div>

        <div style={{ display: "flex", gap: 18, alignItems: "flex-start" }}>
          {/* 矩阵 */}
          <div style={{ flex: "none" }}>
            <div style={{ display: "inline-flex", flexDirection: "column" }}>
              <div style={{ display: "flex" }}>
                <div style={{ width: 104, flex: "none" }} />
                {cols.map((c) => (
                  <div
                    key={c}
                    style={{
                      width: 38,
                      flex: "none",
                      fontSize: 9,
                      color: "var(--desk-text-muted)",
                      textAlign: "center",
                      whiteSpace: "nowrap",
                      transform: "rotate(-45deg)",
                      transformOrigin: "center",
                      height: 30,
                    }}
                  >
                    {c}
                  </div>
                ))}
              </div>
              {cm.map((a, ri) => (
                <div key={a.id} style={{ display: "flex", alignItems: "center" }}>
                  <div
                    style={{
                      width: 104,
                      flex: "none",
                      fontSize: 10,
                      color: "var(--desk-text-dim)",
                      textAlign: "right",
                      paddingRight: 8,
                      whiteSpace: "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }}
                  >
                    {corrShort(a.id)}
                  </div>
                  {cm.map((b, ci) => {
                    const v = ri === ci ? 1 : cellValue(a, b);
                    const red = Math.abs(v) > 0.7 && ri !== ci;
                    const txt =
                      ri === ci
                        ? "·"
                        : v.toFixed(1).replace("0.", ".").replace("-0.", "-.");
                    return (
                      <button
                        key={b.id}
                        onClick={() => onPair({ a: a.id, b: b.id, rho: v })}
                        title={`${corrShort(a.id)} × ${corrShort(b.id)} = ${v.toFixed(2)}`}
                        style={{
                          width: 38,
                          height: 30,
                          flex: "none",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: 9,
                          fontFamily: "inherit",
                          cursor: "pointer",
                          color:
                            ri === ci
                              ? "var(--desk-text-faint)"
                              : Math.abs(v) > 0.5
                                ? "var(--desk-text)"
                                : "var(--desk-text-dim)",
                          background: cellBg(v),
                          border: `1px solid ${red ? "var(--desk-danger)" : "var(--desk-bg)"}`,
                        }}
                      >
                        {txt}
                      </button>
                    );
                  })}
                </div>
              ))}
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 9,
                marginTop: 14,
                fontSize: 9.5,
                color: "var(--desk-text-muted)",
              }}
            >
              <span>−1</span>
              <div
                style={{
                  width: 140,
                  height: 9,
                  borderRadius: 3,
                  background:
                    "linear-gradient(90deg, var(--desk-info), var(--desk-hover) 48%, var(--desk-hover) 52%, var(--desk-danger))",
                }}
              />
              <span>+1</span>
              <span style={{ marginLeft: 12, color: "var(--desk-danger)" }}>
                ■ |ρ|&gt;0.7 冗余
              </span>
            </div>
          </div>

          {/* 去冗余 / 拥挤度 */}
          <div style={{ flex: 1, minWidth: 260, display: "flex", flexDirection: "column", gap: 12 }}>
            {pair && (
              <PanelCard accentBorder>
                <SectionTitle
                  glyph="⊞"
                  right={
                    <button
                      onClick={() => onPair(null)}
                      aria-label="关闭配对详情"
                      style={{
                        background: "transparent",
                        border: "none",
                        cursor: "pointer",
                        fontSize: 11,
                        color: "var(--desk-text-faint)",
                        fontFamily: "inherit",
                      }}
                    >
                      ✕
                    </button>
                  }
                >
                  配对详情
                </SectionTitle>
                <div style={{ fontSize: 11, color: "var(--desk-text-soft)", lineHeight: 1.7 }}>
                  {corrShort(pair.a)}
                  <br />
                  <span style={{ color: "var(--desk-text-faint)" }}>vs</span>
                  <br />
                  {corrShort(pair.b)}
                </div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "10px 0" }}>
                  <span style={{ fontSize: 24, fontWeight: 700, color: pairColor }}>
                    {pair.rho.toFixed(2)}
                  </span>
                  <span style={{ fontSize: 10.5, color: "var(--desk-text-muted)" }}>
                    rank-corr
                  </span>
                </div>
                <div style={{ fontSize: 10.5, color: pairColor, lineHeight: 1.6 }}>{verdict}</div>
              </PanelCard>
            )}

            <PanelCard>
              <SectionTitle>冗余簇 · 建议每簇保留 1 个</SectionTitle>
              <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                {live && clusters.length === 0 && (
                  <div style={{ fontSize: 10.5, color: "var(--desk-text-muted)", lineHeight: 1.6 }}>
                    当前阈值 |ρ|≥{live.threshold} 下无冗余对（无高度同质因子）。
                  </div>
                )}
                {clusters.map((c) => (
                  <div
                    key={c.keep}
                    style={{
                      background: "color-mix(in srgb, var(--desk-text) 3%, transparent)",
                      border: "1px solid var(--desk-node-border)",
                      borderRadius: "var(--desk-radius)",
                      padding: "9px 11px",
                    }}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 6 }}>
                      <span style={{ fontSize: 10, color: "var(--desk-danger)" }}>
                        |ρ|≈{c.rho}
                      </span>
                      <span
                        style={{
                          marginLeft: "auto",
                          fontSize: 9.5,
                          color: "var(--desk-success)",
                          border: "1px solid color-mix(in srgb, var(--desk-success) 40%, transparent)",
                          borderRadius: "var(--desk-radius-lg)",
                          padding: "1px 7px",
                        }}
                      >
                        留 1
                      </span>
                    </div>
                    {c.members.map((m) => (
                      <div
                        key={m.id}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          gap: 6,
                          fontSize: 10.5,
                          padding: "2px 0",
                        }}
                      >
                        <span style={{ color: m.keep ? "var(--desk-success)" : "var(--desk-text-faint)" }}>
                          {m.keep ? "★" : "→"}
                        </span>
                        <span style={{ color: m.keep ? "var(--desk-text-soft)" : "var(--desk-text-muted)" }}>
                          {m.id}
                        </span>
                        <span style={{ marginLeft: "auto", color: "var(--desk-text-faint)" }}>
                          IR {m.ir}
                        </span>
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </PanelCard>

            <PanelCard>
              <SectionTitle>组合拥挤度</SectionTitle>
              <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
                {crowdRows.map((c) => (
                  <div key={c.k}>
                    <div
                      style={{
                        display: "flex",
                        justifyContent: "space-between",
                        fontSize: 10.5,
                        color: "var(--desk-text-muted)",
                        marginBottom: 3,
                      }}
                    >
                      <span>{c.k}</span>
                      <span style={{ color: c.color }}>{c.v}</span>
                    </div>
                    <div
                      style={{
                        height: 6,
                        background: "var(--desk-hover)",
                        borderRadius: 3,
                        overflow: "hidden",
                      }}
                    >
                      <div style={{ height: "100%", width: c.pct, background: c.color }} />
                    </div>
                  </div>
                ))}
              </div>
            </PanelCard>
          </div>
        </div>
      </div>
    </div>
  );
}
