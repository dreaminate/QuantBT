import { MockBadge, SegmentedControl } from "../../../components/desk";
import { MetricCell, PanelCard, SectionTitle } from "./parts";
import {
  type MockFactor,
  icThresholdColor,
  irThresholdColor,
  svgBars,
  svgLine,
} from "./factorData";

/** 后端实测数据（接入真实数据时由容器注入；缺省=纯 mock）。 */
export interface FactorEvalLive {
  /** /api/factors/{id}/ic 当前 horizon 的截面 IC 报告。 */
  ic?: {
    ic_mean: number | null;
    rank_ic_mean: number | null;
    ic_ir: number | null;
    ic_tstat_nw: number | null;
    sample_count: number;
  } | null;
  /** /api/factors/{id}/ic_decay 各 horizon。 */
  decay?: { horizon: number; ic_mean: number | null; rank_ic_mean: number | null; ic_ir: number | null }[] | null;
  /** /api/factors/{id}/layered_backtest。 */
  layered?: {
    effective_quantiles: number;
    long_short_spread: number;
    monotonic: boolean;
    buckets: { quantile: number; mean_return: number; n_obs: number }[];
  } | null;
}

export interface FactorEvalViewProps {
  factor: MockFactor;
  horizon: number;
  onHorizon: (h: number) => void;
  /** 后端数据；传入后每个缺失区块单独显示不可用，绝不回落 mock。 */
  live?: FactorEvalLive | null;
}

const LAYER_COLORS = [
  "var(--desk-info)",
  "color-mix(in srgb, var(--desk-info) 60%, var(--desk-text-dim))",
  "var(--desk-text-dim)",
  "color-mix(in srgb, var(--desk-success) 50%, var(--desk-warning))",
  "var(--desk-success)",
];
const LAYER_NAMES = ["Q1 低", "Q2", "Q3", "Q4", "Q5 高"];
const HS = [1, 3, 5, 10, 20];

/** 评测台 view：硬指标 5 卡 + 分层回测 + 累计 IC + 衰减表。 */
export function FactorEvalView({ factor: sel, horizon, onHorizon, live }: FactorEvalViewProps) {
  const selH = sel.decay.find((d) => d.h === horizon) ?? sel.decay[2];

  // 一旦容器注入后端 payload，缺失项必须明确不可用，不能再用 mock 补洞。
  const liveIc = live?.ic ?? null;
  const liveLayered = live?.layered ?? null;
  const liveDecay = live?.decay ?? null;
  const hasLivePayload = live != null;
  const liveComplete = Boolean(liveIc && liveLayered?.buckets.length && liveDecay?.length);
  const unavailableColor = "var(--desk-text-faint)";
  const liveMetric = (value: number | null | undefined, digits: number) =>
    value == null ? "不可用" : value.toFixed(digits);
  const metrics = hasLivePayload
    ? [
        {
          label: `IC@${horizon}d`,
          value: liveMetric(liveIc?.ic_mean, 3),
          color: liveIc?.ic_mean == null ? unavailableColor : icThresholdColor(liveIc.ic_mean),
        },
        { label: "Rank-IC", value: liveMetric(liveIc?.rank_ic_mean, 3), color: liveIc?.rank_ic_mean == null ? unavailableColor : "var(--desk-text-soft)" },
        {
          label: "IC-IR",
          value: liveMetric(liveIc?.ic_ir, 2),
          color: liveIc?.ic_ir == null ? unavailableColor : irThresholdColor(liveIc.ic_ir),
        },
        {
          label: "NW t",
          value: liveMetric(liveIc?.ic_tstat_nw, 2),
          color: liveIc?.ic_tstat_nw == null
            ? unavailableColor
            : Math.abs(liveIc.ic_tstat_nw) >= 3
              ? "var(--desk-success)"
              : "var(--desk-warning)",
        },
        { label: "样本期", value: liveIc ? String(liveIc.sample_count) : "不可用", color: liveIc ? "var(--desk-text-dim)" : unavailableColor },
      ]
    : [
        { label: `IC@${horizon}d`, value: selH.ic.toFixed(3), color: icThresholdColor(selH.ic) },
        { label: "Rank-IC", value: (selH.ic * 1.06).toFixed(3), color: "var(--desk-text-soft)" },
        { label: "IC-IR", value: sel.icIr.toFixed(2), color: irThresholdColor(sel.icIr) },
        { label: "胜率", value: `${(50 + sel.icIr * 6).toFixed(0)}%`, color: "var(--desk-text-soft)" },
        { label: "样本期", value: "504", color: "var(--desk-text-dim)" },
      ];

  const allL = sel.layers.flat();
  const lo = Math.min(...allL);
  const hi = Math.max(...allL);
  const layerPaths = sel.layers.map((arr, b) => ({
    path: svgLine(arr, 460, 200, lo, hi, 8),
    color: LAYER_COLORS[b],
    width: b === 0 || b === 4 ? 2.2 : 1.4,
  }));
  // 真实后端：分层 legend / 多空价差用后端分位组合均收益（buckets），否则 mock 累计净值终点。
  const legend = liveLayered
    ? liveLayered.buckets.map((bk, b) => {
        const r = bk.mean_return * 100;
        return {
          color: LAYER_COLORS[Math.min(b, LAYER_COLORS.length - 1)],
          name: `Q${bk.quantile}${b === 0 ? " 低" : b === liveLayered.buckets.length - 1 ? " 高" : ""}`,
          ret: `${r >= 0 ? "+" : ""}${r.toFixed(2)}%`,
          retColor: r >= 0 ? "var(--desk-success)" : "var(--desk-danger)",
        };
      })
    : sel.layers.map((arr, b) => {
        const r = (arr[arr.length - 1] - 1) * 100;
        return {
          color: LAYER_COLORS[b],
          name: LAYER_NAMES[b],
          ret: `${r >= 0 ? "+" : ""}${r.toFixed(1)}%`,
          retColor: r >= 0 ? "var(--desk-success)" : "var(--desk-danger)",
        };
      });
  const spread = liveLayered
    ? liveLayered.long_short_spread * 100
    : (sel.layers[4][39] - sel.layers[0][39]) * 100;
  const spreadTxt = `${spread >= 0 ? "+" : ""}${spread.toFixed(liveLayered ? 2 : 1)}%`;
  // R25：弱单调/无单调 不染绿。接入真实数据时单调性用后端 monotonic 旗（不靠价差阈值猜）。
  const monoOk = liveLayered ? liveLayered.monotonic && Math.abs(spread) > 0.5 : spread > 3;
  const monoWeak = liveLayered ? !monoOk && Math.abs(spread) > 0 : spread > 0;
  const mono = monoOk ? "单调性好 ✓" : monoWeak ? "弱单调 △" : "无单调性 ✕";
  const monoColor = monoOk ? "var(--desk-success)" : monoWeak ? "var(--desk-warning)" : "var(--desk-danger)";

  let cum = 0;
  const cumArr = sel.series.map((v) => (cum += v));
  const cumPath = svgLine(cumArr, 320, 120, Math.min(0, ...cumArr), Math.max(0.1, ...cumArr), 8);
  const icBars = svgBars(sel.series, 320, 120, 60);
  const hit = `${(50 + sel.icIr * 6).toFixed(0)}%`;

  const decayTable = liveDecay
    ? liveDecay.map((d) => {
        const ic = d.ic_mean;
        return {
          h: `${d.horizon} 日`,
          ic: liveMetric(ic, 3),
          rankIc: liveMetric(d.rank_ic_mean, 3),
          ir: liveMetric(d.ic_ir, 2),
          selected: d.horizon === horizon,
          icColor: ic == null ? unavailableColor : icThresholdColor(ic),
        };
      })
    : sel.decay.map((d) => ({
        h: `${d.h} 日`,
        ic: d.ic.toFixed(3),
        rankIc: (d.ic * 1.06).toFixed(3),
        ir: (d.ic / 0.04).toFixed(2),
        selected: d.h === horizon,
        icColor: icThresholdColor(d.ic),
      }));

  return (
    <div style={{ flex: 1, minWidth: 0, overflowY: "auto", background: "var(--desk-canvas)", padding: "18px 22px" }}>
      <div style={{ maxWidth: 920 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 16 }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>{sel.id}</span>
          <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>{sel.formula}</span>
          <span style={{ marginLeft: "auto", display: "flex", gap: 10, alignItems: "center" }}>
            {hasLivePayload ? (
              <span
                data-testid={liveComplete ? "eval-live-badge" : "eval-partial-badge"}
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  color: liveComplete ? "var(--desk-success)" : "var(--desk-warning)",
                  border: `1px solid color-mix(in srgb, ${liveComplete ? "var(--desk-success)" : "var(--desk-warning)"} 40%, transparent)`,
                  borderRadius: 4,
                  padding: "1px 6px",
                }}
              >
                {liveComplete ? "后端 · IC / 分位均值 / 衰减" : "后端数据不完整 · 不混入 MOCK"}
              </span>
            ) : (
              <MockBadge label="MOCK 数据 · 分层回测合成（待接 /api/factors/{id}/layered_backtest）" />
            )}
            <SegmentedControl
              size="sm"
              value={String(horizon)}
              onChange={(v) => onHorizon(Number(v))}
              options={HS.map((h) => ({ value: String(h), label: `${h}d` }))}
            />
          </span>
        </div>

        {/* 硬指标 5 卡 */}
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(5,1fr)",
            gap: 10,
            marginBottom: 14,
          }}
        >
          {metrics.map((m) => (
            <MetricCell key={m.label} label={m.label} value={m.value} color={m.color} big={17} />
          ))}
        </div>

        {/* 分层回测 */}
        <PanelCard style={{ marginBottom: 14, padding: "13px 16px" }}>
          <SectionTitle
            right={liveLayered ? <span style={{ fontSize: 11, fontWeight: 600, color: monoColor }}>{mono}</span> : hasLivePayload ? <span style={{ fontSize: 11, color: unavailableColor }}>不可用</span> : <span style={{ fontSize: 11, fontWeight: 600, color: monoColor }}>{mono}</span>}
          >
            {hasLivePayload ? "分层回测 · 分位均值" : "分层回测 · 五分位累计净值"}{" "}
            <span style={{ fontSize: 10, fontWeight: 400, color: "var(--desk-text-muted)" }}>
              {hasLivePayload ? "后端未返回累计净值序列" : "按因子值排序分 5 组 · 等权 · 504 交易日 · 周度调仓"}
            </span>
          </SectionTitle>
          <div style={{ display: "flex", gap: 16 }}>
            {hasLivePayload ? (
              <div
                data-testid="layer-cumulative-unavailable"
                style={{ flex: 1, height: 200, display: "grid", placeItems: "center", color: unavailableColor, fontSize: 11, border: "1px dashed var(--desk-border)" }}
              >
                {liveLayered ? "后端仅返回分位均值，累计净值序列不可用" : "分层回测后端结果不可用"}
              </div>
            ) : (
              <svg viewBox="0 0 460 200" preserveAspectRatio="none" style={{ flex: 1, height: 200, display: "block" }}>
                <line x1="0" y1="100" x2="460" y2="100" stroke="var(--desk-border)" strokeWidth="1" />
                {layerPaths.map((l, i) => (
                  <path key={i} d={l.path} fill="none" stroke={l.color} strokeWidth={l.width} />
                ))}
              </svg>
            )}
            {(!hasLivePayload || liveLayered) && <div
              style={{
                flex: "none",
                width: 150,
                display: "flex",
                flexDirection: "column",
                gap: 6,
                justifyContent: "center",
              }}
            >
              {legend.map((l) => (
                <div key={l.name} style={{ display: "flex", alignItems: "center", gap: 7, fontSize: 10.5 }}>
                  <span style={{ width: 12, height: 3, background: l.color, flex: "none" }} />
                  <span style={{ color: "var(--desk-text-dim)", whiteSpace: "nowrap" }}>{l.name}</span>
                  <span style={{ marginLeft: "auto", color: l.retColor, fontWeight: 600 }}>{l.ret}</span>
                </div>
              ))}
              <div
                style={{
                  marginTop: 6,
                  paddingTop: 8,
                  borderTop: "1px solid var(--desk-hover)",
                  display: "flex",
                  justifyContent: "space-between",
                  fontSize: 10.5,
                }}
              >
                <span style={{ color: "var(--desk-text-muted)" }}>多空 Q5−Q1</span>
                <span style={{ color: monoColor, fontWeight: 700 }}>{spreadTxt}</span>
              </div>
            </div>}
          </div>
        </PanelCard>

        {/* 累计 IC + 衰减表 */}
        <div style={{ display: "flex", gap: 14 }}>
          <PanelCard style={{ flex: 1.3 }}>
            <SectionTitle
              right={
                <span style={{ fontSize: 10.5, fontWeight: 400, color: "var(--desk-text-muted)" }}>
                  {hasLivePayload ? "后端未返回序列" : `命中率 ${hit}`}
                </span>
              }
            >
              IC 序列 · 累计
            </SectionTitle>
            {hasLivePayload ? (
              <div data-testid="ic-series-unavailable" style={{ height: 120, display: "grid", placeItems: "center", color: unavailableColor, fontSize: 11 }}>
                IC 序列不可用；后端仅返回汇总指标
              </div>
            ) : (
              <>
                <svg viewBox="0 0 320 120" preserveAspectRatio="none" style={{ width: "100%", height: 104, display: "block" }}>
                  <line x1="0" y1="60" x2="320" y2="60" stroke="var(--desk-border-strong)" strokeWidth="1" strokeDasharray="2 3" />
                  <path d={icBars} stroke={icThresholdColor(sel.icMean)} strokeWidth="2" opacity="0.8" />
                  <path d={cumPath} fill="none" stroke="var(--desk-accent)" strokeWidth="1.8" />
                </svg>
                <div style={{ fontSize: 9, color: "var(--desk-text-faint)", marginTop: 3 }}>
                  柱 = 日度 IC · 紫线 = 累计 IC
                </div>
              </>
            )}
          </PanelCard>
          <PanelCard style={{ flex: 1 }}>
            <SectionTitle>IC 衰减表 · horizon</SectionTitle>
            <div style={{ display: "flex", flexDirection: "column" }}>
              <div
                style={{
                  display: "flex",
                  fontSize: 10,
                  color: "var(--desk-text-faint)",
                  paddingBottom: 5,
                  borderBottom: "1px solid var(--desk-hover)",
                }}
              >
                <span style={{ flex: 1 }}>horizon</span>
                <span style={{ flex: 1, textAlign: "right" }}>IC</span>
                <span style={{ flex: 1, textAlign: "right" }}>Rank-IC</span>
                <span style={{ flex: 1, textAlign: "right" }}>IR</span>
              </div>
              {hasLivePayload && (!liveDecay || liveDecay.length === 0) ? (
                <div data-testid="decay-unavailable" style={{ padding: "18px 0", textAlign: "center", color: unavailableColor, fontSize: 11 }}>
                  IC 衰减后端结果不可用
                </div>
              ) : decayTable.map((r) => (
                <div
                  key={r.h}
                  style={{
                    display: "flex",
                    fontSize: 11,
                    padding: "6px 0",
                    borderBottom: "1px solid var(--desk-border-soft)",
                  }}
                >
                  <span style={{ flex: 1, color: r.selected ? "var(--desk-accent)" : "var(--desk-text-dim)" }}>
                    {r.h}
                  </span>
                  <span style={{ flex: 1, textAlign: "right", color: r.icColor }}>{r.ic}</span>
                  <span style={{ flex: 1, textAlign: "right", color: "var(--desk-text-dim)" }}>{r.rankIc}</span>
                  <span style={{ flex: 1, textAlign: "right", color: "var(--desk-text-dim)" }}>{r.ir}</span>
                </div>
              ))}
            </div>
          </PanelCard>
        </div>
      </div>
    </div>
  );
}
