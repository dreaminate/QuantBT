import { useMemo } from "react";
import { CollapsiblePanel, MockBadge, StatusDot } from "../../../components/desk";
import { CodeBox, MetricCell, PanelCard, SectionTitle } from "./parts";
import {
  type LifecycleState,
  type MockFactor,
  LIFECYCLE_PATH,
  STATE_GLYPH,
  STATE_SUB,
  STATE_THRESH,
  eventsFor,
  famBgVar,
  famColorVar,
  icThresholdColor,
  irThresholdColor,
  stateBgVar,
  stateColorVar,
  svgBars,
  svgLine,
  tThresholdColor,
} from "./factorData";

const FILTERS: (LifecycleState | "ALL")[] = [
  "ALL",
  "NEW",
  "QUALIFIED",
  "PROBATION",
  "OBSERVATION",
  "WARNING",
  "RETIRED",
];

export interface FactorLibraryViewProps {
  factors: MockFactor[];
  selected: MockFactor;
  onSelect: (id: string) => void;
  listOpen: boolean;
  onToggleList: () => void;
  lifeFilter: LifecycleState | "ALL";
  onLifeFilter: (f: LifecycleState | "ALL") => void;
}

/** 因子库 view：左可折叠列表（五态 filter）+ 右因子详情。 */
export function FactorLibraryView({
  factors,
  selected,
  onSelect,
  listOpen,
  onToggleList,
  lifeFilter,
  onLifeFilter,
}: FactorLibraryViewProps) {
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of factors) c[f.state] = (c[f.state] ?? 0) + 1;
    return c;
  }, [factors]);

  const list = factors.filter(
    (f) => lifeFilter === "ALL" || f.state === lifeFilter,
  );

  return (
    <div style={{ flex: 1, minWidth: 0, display: "flex" }}>
      <CollapsiblePanel
        open={listOpen}
        onToggle={onToggleList}
        side="left"
        width={312}
        label="因子库"
      >
        {/* 头部 */}
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
          <span style={{ fontWeight: 600, fontSize: 12.5 }}>因子库</span>
          <span style={{ fontSize: 10.5, color: "var(--desk-text-faint)" }}>
            {factors.length} 因子
          </span>
          <button
            onClick={onToggleList}
            title="折叠因子库"
            style={{
              marginLeft: "auto",
              background: "transparent",
              border: "none",
              cursor: "pointer",
              color: "var(--desk-text-muted)",
              fontFamily: "inherit",
              fontSize: 13,
            }}
          >
            ‹
          </button>
        </div>

        {/* 生命周期 filter */}
        <div
          style={{
            flex: "none",
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
            padding: "8px 11px",
            borderBottom: "1px solid var(--desk-border-soft)",
          }}
        >
          {FILTERS.map((s) => {
            const active = lifeFilter === s;
            const c =
              s === "ALL" ? "var(--desk-text-soft)" : stateColorVar(s);
            const n = s === "ALL" ? factors.length : counts[s] ?? 0;
            return (
              <button
                key={s}
                onClick={() => onLifeFilter(s)}
                aria-pressed={active}
                style={{
                  fontFamily: "inherit",
                  fontSize: 9.5,
                  padding: "2px 8px",
                  borderRadius: "var(--desk-radius-pill)",
                  cursor: "pointer",
                  border: `1px solid ${active ? c : "var(--desk-border-strong)"}`,
                  color: active ? c : "var(--desk-text-faint)",
                  background: active
                    ? "color-mix(in srgb, var(--desk-text) 3%, transparent)"
                    : "transparent",
                }}
              >
                {s === "ALL" ? "全部" : s} {n}
              </button>
            );
          })}
        </div>

        {/* 因子卡列表 */}
        <div style={{ flex: 1, minHeight: 0, overflowY: "auto", padding: 8 }}>
          {list.map((f) => {
            const on = f.id === selected.id;
            return (
              <button
                key={f.id}
                onClick={() => onSelect(f.id)}
                aria-pressed={on}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  padding: "9px 11px",
                  borderRadius: "var(--desk-radius-lg)",
                  marginBottom: 6,
                  cursor: "pointer",
                  fontFamily: "inherit",
                  border: `1px solid ${
                    on ? "var(--desk-accent)" : "var(--desk-border-soft)"
                  }`,
                  background: on ? stateBgVar(f.state) : "var(--desk-card)",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <StatusDot
                    color={stateColorVar(f.state)}
                    pulse={f.state === "OBSERVATION"}
                  />
                  <span
                    style={{
                      fontWeight: 600,
                      fontSize: 12,
                      color: "var(--desk-text)",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      flex: 1,
                    }}
                  >
                    {f.id}
                  </span>
                  <span
                    style={{
                      fontSize: 9,
                      padding: "1px 6px",
                      borderRadius: "var(--desk-radius-lg)",
                      color: stateColorVar(f.state),
                      background: stateBgVar(f.state),
                    }}
                  >
                    {f.state}
                  </span>
                </div>
                <div
                  style={{
                    fontSize: 10,
                    color: "var(--desk-text-muted)",
                    marginTop: 4,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {f.formula}
                </div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 8,
                    marginTop: 5,
                    fontSize: 10,
                  }}
                >
                  <span style={{ color: "var(--desk-text-faint)" }}>{f.fam}</span>
                  <span
                    style={{ marginLeft: "auto", color: icThresholdColor(f.icMean) }}
                  >
                    IC {f.icMean.toFixed(3)}
                  </span>
                  <span style={{ color: "var(--desk-text-muted)" }}>
                    IR {f.icIr.toFixed(2)}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </CollapsiblePanel>

      <DetailPane factor={selected} />
    </div>
  );
}

function DetailPane({ factor: sel }: { factor: MockFactor }) {
  const curIdx = LIFECYCLE_PATH.indexOf(sel.state);

  const metrics = [
    { label: "IC 均值", value: sel.icMean.toFixed(3), color: icThresholdColor(sel.icMean), note: "5日 horizon" },
    { label: "Rank-IC", value: sel.rankIc.toFixed(3), color: sel.rankIc >= 0.02 ? "var(--desk-success)" : "var(--desk-text-soft)", note: "Spearman" },
    { label: "IC-IR", value: sel.icIr.toFixed(2), color: irThresholdColor(sel.icIr), note: "μ/σ 稳定性" },
    { label: "sample t", value: sel.sampleT.toFixed(1), color: tThresholdColor(sel.sampleT), note: "显著性" },
  ];

  const icBars = svgBars(sel.series, 320, 110, 55);
  const ma = sel.series.map((_, i) => {
    const s = Math.max(0, i - 19);
    const win = sel.series.slice(s, i + 1);
    return win.reduce((a, b) => a + b, 0) / win.length;
  });
  const maMax = Math.max(0.08, ...ma.map((v) => Math.abs(v)));
  const icMa = ma
    .map((v, i) => `${i ? "L" : "M"}${((i / 59) * 320).toFixed(1)} ${(55 - (v / maMax) * 46).toFixed(1)}`)
    .join(" ");

  const dmax = Math.max(0.02, ...sel.decay.map((d) => Math.abs(d.ic)));
  const decayPts = sel.decay.map((d, i) => ({ x: 12 + (i / 4) * 196, y: 55 - (d.ic / dmax) * 42 }));
  const decayPath = decayPts.map((p, i) => `${i ? "L" : "M"}${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(" ");
  const decayArea = `${decayPath} L208 55 L12 55 Z`;
  const peakH = sel.decay.reduce((a, b) => (Math.abs(b.ic) > Math.abs(a.ic) ? b : a)).h;

  const opChain = Array.from(new Set(sel.formula.match(/[a-z_]+(?=\()/g) ?? [])).slice(0, 4).join(" · ") || "—";
  const kind = /rank|zscore|cs_|demean|winsor/.test(sel.formula) ? "截面 + 时序" : "纯时序";
  const turnover = sel.fam === "动量" ? "中（周频）" : sel.fam === "反转" ? "高" : "低";
  const events = eventsFor(sel);

  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        overflowY: "auto",
        background: "var(--desk-canvas)",
        padding: "18px 22px",
      }}
    >
      <div style={{ maxWidth: 820 }}>
        {/* header */}
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span style={{ fontSize: 17, fontWeight: 700 }}>{sel.id}</span>
          <span style={{ fontSize: 10.5, color: "var(--desk-text-faint)" }}>v1</span>
          <span
            style={{
              fontSize: 10.5,
              fontWeight: 600,
              color: famColorVar(sel.fam),
              background: famBgVar(sel.fam),
              padding: "3px 9px",
              borderRadius: "var(--desk-radius-lg)",
            }}
          >
            {sel.fam}
          </span>
          <div style={{ marginLeft: "auto", textAlign: "right" }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: stateColorVar(sel.state) }}>
              {sel.state}
            </div>
            <div style={{ fontSize: 10.5, color: "var(--desk-text-faint)", marginTop: 3 }}>
              2026-05-27 入库
            </div>
          </div>
        </div>
        <div style={{ fontSize: 12, color: "var(--desk-node-line)", margin: "8px 0 12px" }}>
          {sel.desc}
        </div>

        <div style={{ marginBottom: 14 }}>
          <CodeBox>{sel.formula}</CodeBox>
        </div>

        {/* 五态机 */}
        <PanelCard style={{ marginBottom: 14, padding: "14px 16px" }}>
          <SectionTitle
            glyph="◷"
            right={
              <span style={{ fontSize: 10.5, fontWeight: 400, color: "var(--desk-text-faint)" }}>
                阈值参数化 · 每次评估写 event_log
              </span>
            }
          >
            因子五态机 · M11 生命周期
          </SectionTitle>
          <div style={{ display: "flex", alignItems: "stretch" }}>
            {LIFECYCLE_PATH.map((p, i) => {
              const c = stateColorVar(p);
              const active = i === curIdx;
              const passed = i < curIdx;
              const reached = i <= curIdx;
              return (
                <div
                  key={p}
                  style={{
                    flex: 1,
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "center",
                    position: "relative",
                  }}
                >
                  <div
                    style={{
                      width: 30,
                      height: 30,
                      borderRadius: "50%",
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 13,
                      fontWeight: 700,
                      ...(active
                        ? {
                            background: c,
                            color: "var(--desk-accent-ink)",
                            boxShadow: `0 0 0 4px color-mix(in srgb, ${c} 20%, transparent)`,
                          }
                        : passed
                          ? { background: "transparent", color: c, border: `2px solid ${c}` }
                          : {
                              background: "var(--desk-card)",
                              color: "var(--desk-text-faint)",
                              border: "2px solid var(--desk-border-strong)",
                            }),
                    }}
                  >
                    {STATE_GLYPH[p]}
                  </div>
                  <div
                    style={{
                      fontSize: 10.5,
                      color: reached ? c : "var(--desk-text-faint)",
                      fontWeight: active ? 700 : 500,
                      marginTop: 7,
                    }}
                  >
                    {p}
                  </div>
                  <div
                    style={{
                      fontSize: 9,
                      color: "var(--desk-text-faint)",
                      marginTop: 2,
                      textAlign: "center",
                      minHeight: 24,
                      lineHeight: 1.4,
                    }}
                  >
                    {STATE_SUB[p]}
                  </div>
                  {i < 5 && (
                    <div
                      aria-hidden
                      style={{
                        position: "absolute",
                        top: 14,
                        right: -1,
                        width: "calc(100% - 8px)",
                        height: 1,
                        transform: "translateX(50%)",
                      }}
                    >
                      <div
                        style={{
                          height: 1,
                          background: i < curIdx ? c : "var(--desk-border-strong)",
                        }}
                      />
                      <div
                        style={{
                          position: "absolute",
                          top: -7,
                          left: "50%",
                          transform: "translateX(-50%)",
                          fontSize: 8,
                          color: "var(--desk-text-muted)",
                          whiteSpace: "nowrap",
                          background: "var(--desk-card)",
                          padding: "0 4px",
                        }}
                      >
                        {STATE_THRESH[i]}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </PanelCard>

        {/* 硬指标 4 卡 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4,1fr)",
            gap: 10,
            marginBottom: 14,
          }}
        >
          {metrics.map((m) => (
            <MetricCell key={m.label} {...m} />
          ))}
        </div>

        {/* IC 时序 + 衰减 */}
        <div style={{ display: "flex", gap: 14, marginBottom: 14 }}>
          <PanelCard style={{ flex: 1.4 }}>
            <SectionTitle
              right={
                <span style={{ fontSize: 10.5, fontWeight: 700, color: icThresholdColor(sel.icMean) }}>
                  μ {sel.icMean.toFixed(3)}
                </span>
              }
            >
              日度 IC 序列{" "}
              <span style={{ fontSize: 10, fontWeight: 400, color: "var(--desk-text-muted)" }}>
                近 60 交易日
              </span>
            </SectionTitle>
            <svg viewBox="0 0 320 110" preserveAspectRatio="none" style={{ width: "100%", height: 96, display: "block" }}>
              <line x1="0" y1="55" x2="320" y2="55" stroke="var(--desk-border-strong)" strokeWidth="1" strokeDasharray="2 3" />
              <path d={icBars} stroke={icThresholdColor(sel.icMean)} strokeWidth="2.4" opacity="0.85" />
              <path d={icMa} fill="none" stroke="var(--desk-text)" strokeWidth="1.4" />
            </svg>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 9,
                color: "var(--desk-text-faint)",
                marginTop: 2,
              }}
            >
              <span>−60d</span>
              <span style={{ color: "var(--desk-text-soft)" }}>— 20日均线</span>
              <span>今日</span>
            </div>
          </PanelCard>
          <PanelCard style={{ flex: 1 }}>
            <SectionTitle
              right={
                <span style={{ fontSize: 10, fontWeight: 400, color: "var(--desk-text-muted)" }}>
                  峰值 @{peakH}日
                </span>
              }
            >
              IC 衰减曲线
            </SectionTitle>
            <svg viewBox="0 0 220 110" preserveAspectRatio="none" style={{ width: "100%", height: 96, display: "block" }}>
              <line x1="0" y1="55" x2="220" y2="55" stroke="var(--desk-border-strong)" strokeWidth="1" strokeDasharray="2 3" />
              <path d={decayArea} fill="color-mix(in srgb, var(--desk-accent) 12%, transparent)" />
              <path d={decayPath} fill="none" stroke="var(--desk-accent)" strokeWidth="2" />
              {decayPts.map((p, i) => (
                <circle key={i} cx={p.x} cy={p.y} r="2.6" fill="var(--desk-accent)" />
              ))}
            </svg>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 9,
                color: "var(--desk-text-faint)",
                marginTop: 2,
              }}
            >
              {["1d", "3d", "5d", "10d", "20d"].map((l) => (
                <span key={l}>{l}</span>
              ))}
            </div>
          </PanelCard>
        </div>

        {/* 动机 + event log */}
        <div style={{ display: "flex", gap: 14 }}>
          <PanelCard style={{ flex: 1.2, padding: "13px 15px" }}>
            <SectionTitle glyph="✎">因子动机 · 想抓什么 alpha</SectionTitle>
            <div
              style={{
                background: "color-mix(in srgb, var(--desk-accent) 12%, transparent)",
                borderLeft: "3px solid var(--desk-accent)",
                borderRadius: "var(--desk-radius-sm)",
                padding: "9px 12px",
                color: "var(--desk-text-soft)",
                fontSize: 12,
                lineHeight: 1.65,
              }}
            >
              {sel.why}
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(2,1fr)",
                gap: "8px 16px",
                marginTop: 11,
              }}
            >
              <MotiveCell label="算子链" value={opChain} color="var(--desk-info)" />
              <MotiveCell label="截面 / 时序" value={kind} color="var(--desk-text-soft)" />
              <MotiveCell label="换手代理" value={turnover} color="var(--desk-text-soft)" />
              <MotiveCell label="前视检查" value="✓ 无穿越" color="var(--desk-success)" />
            </div>
          </PanelCard>
          <PanelCard style={{ flex: 1, padding: "13px 15px" }}>
            <SectionTitle glyph="≣">lifecycle_event_log</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column" }}>
              {events.map((e, i) => (
                <div key={i} style={{ display: "flex", gap: 10, paddingBottom: 11 }}>
                  <div
                    style={{
                      flex: "none",
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "center",
                    }}
                  >
                    <span
                      style={{
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background: e.color,
                        flex: "none",
                      }}
                    />
                    {e.line && (
                      <span
                        style={{
                          width: 1,
                          flex: 1,
                          background: "var(--desk-node-border)",
                          marginTop: 3,
                        }}
                      />
                    )}
                  </div>
                  <div style={{ flex: 1, minWidth: 0, paddingBottom: 2 }}>
                    <div style={{ fontSize: 11.5, color: "var(--desk-text-soft)" }}>
                      <span style={{ color: "var(--desk-text-muted)" }}>{e.from}</span>{" "}
                      → <span style={{ color: e.color, fontWeight: 600 }}>{e.to}</span>
                    </div>
                    <div
                      style={{
                        fontSize: 10,
                        color: "var(--desk-text-muted)",
                        marginTop: 2,
                        lineHeight: 1.5,
                      }}
                    >
                      {e.reason}
                    </div>
                    <div style={{ fontSize: 9, color: "var(--desk-text-faint)", marginTop: 2 }}>
                      {e.when}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </PanelCard>
        </div>

        <div style={{ marginTop: 14 }}>
          <MockBadge label="MOCK 数据 · 详情合成（IC/衰减/event_log 待接后端）" />
        </div>
      </div>
    </div>
  );
}

function MotiveCell({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div>
      <div style={{ color: "var(--desk-text-muted)", fontSize: 10, marginBottom: 2 }}>
        {label}
      </div>
      <div style={{ color, fontSize: 11 }}>{value}</div>
    </div>
  );
}
