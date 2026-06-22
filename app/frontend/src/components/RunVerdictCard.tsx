import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { MockBadge } from "./desk/primitives";

/**
 * R1 裁决卡（DC RunVerdictCard.dc.html → React，pixel-perfect / P0 mock）。
 *
 * 红线（冻结/R7）守则——本文件硬约束，改前必读：
 *  ① 绝不 import / 嵌入冻结回测详情页（本卡新建旁挂，外链路由跳转、不内嵌）。
 *  ② verdict 锁死三态 consistent/concern/blocked（= verification/schema.py），
 *     与 overfit_gate.GateVerdict 的「晋级候选」是两条管线——本卡不混用。
 *  ③ verdictNote 走合规措辞（一致/存疑/不一致 + 适用域 + 未验证项），
 *     禁「可信/安全/保证/排除过拟合/可复现/组织独立」（R7，由 harness 扫描门把守）。
 *  ④ promote 为受控回调 onPromote——前端不伪造写盘；写动作落 ide/promote.py。
 *  ⑤ 零裸 hex：一律 var(--desk-*)；rgba 叠加用 color-mix(token, transparent)。
 *
 * P0：mock 数据驱动，未接真后端端点（GET /verdict /overfit /cost-sensitivity）——
 * 故全卡挂 <MockBadge/> 诚实角标，不假绿灯。
 */

/** 验证官三态裁决（verification/schema.py 锁死，UI 不可越界扩枚举）。 */
export type Verdict = "consistent" | "concern" | "blocked";

/** 验证官三态 ↔ 展示文案/语义 token（绝不与 GateVerdict「晋级候选」混用）。 */
const VERDICT_META: Record<
  Verdict,
  { label: string; color: string; bg: string }
> = {
  consistent: {
    label: "证据一致",
    color: "var(--desk-success)",
    bg: "color-mix(in srgb, var(--desk-success) 15%, transparent)",
  },
  concern: {
    label: "证据存疑",
    color: "var(--desk-warning)",
    bg: "color-mix(in srgb, var(--desk-warning) 15%, transparent)",
  },
  blocked: {
    label: "证据不一致",
    color: "var(--desk-danger)",
    bg: "color-mix(in srgb, var(--desk-danger) 15%, transparent)",
  },
};

/** promote 受控状态（候选 → 已登记），写动作由父层对接后端。 */
export type PromoteState = "candidate" | "registered";

export interface CostCell {
  preset: "optimistic" | "neutral" | "pessimistic";
  sharpe: number;
  excess: number;
}

export interface RunVerdictData {
  runId: string;
  verdict: Verdict;
  /** 双目标 + 风险速读（KPI 4 格）。 */
  kpi: {
    annExcess: number;
    maxDD: number;
    sharpe: number;
    ir: number;
    winWeeks: number;
    turnover: number;
  };
  equity: number[];
  bench: number[];
  cost: CostCell[];
  /**
   * PBO（CSCV 过拟合概率）。后端未算 CSCV/PBO 时为 null/缺失 → 第三态「未知」，
   * 渲染成中性「N/A」，绝不 default 0 再上成功绿（§3 未验证 ≠ 已验证）。
   */
  pbo: number | null;
  /** DSR（Deflated Sharpe）。同 pbo：未算/缺失 → null → 渲染 N/A，绝不假绿灯。 */
  dsr: number | null;
  /**
   * Bootstrap Sharpe 置信区间 [下界, 上界]（多证据三角第三腿，来自 overfit_gate.bootstrap_ci）。
   * 健康判据：下界 > 0（区间不跨零 → 显著）。缺省/NaN → 第三格显示「N/A」（诚实，不假绿灯）。
   */
  bootstrapCI?: [number, number] | null;
  /**
   * 合规裁决说明（一致/存疑/不一致 + 适用域 + 未验证项）。
   * 落地须由后端 verifier._verdict_note 供给——前端 mock 仅占位、禁绝对化措辞。
   */
  verdictNote: string;
  promoteState: PromoteState;
}

const PRESET_LABEL: Record<CostCell["preset"], string> = {
  optimistic: "optimistic",
  neutral: "neutral",
  pessimistic: "pessimistic",
};

const PRESET_LABEL_COLOR: Record<CostCell["preset"], string> = {
  optimistic: "var(--desk-success)",
  neutral: "var(--desk-text-soft)",
  pessimistic: "var(--desk-warning)",
};

function pct(v: number): string {
  return (v * 100).toFixed(1) + "%";
}

/** 折线 path（mock 缩略 svg 用，纯几何无副作用）。 */
function linePath(
  arr: number[],
  W: number,
  H: number,
  pad: number,
  lo: number,
  span: number,
): string {
  if (arr.length < 2) return "";
  const x = (i: number) => pad + (i / (arr.length - 1)) * (W - 2 * pad);
  const y = (v: number) => H - pad - ((v - lo) / span) * (H - 2 * pad);
  return arr
    .map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1))
    .join(" ");
}

/** 确定性伪随机（月度热力 mock 造数，避免每次 render 抖动）。 */
function seed(i: number): number {
  return (((Math.sin(i * 12.9898) * 43758.5453) % 1) + 1) % 1;
}

const HEAT_YEARS = [2019, 2020, 2021, 2022, 2023, 2024] as const;
const MONTHS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12"];

export interface RunVerdictCardProps {
  data: RunVerdictData;
  /**
   * promote 受控回调（写动作）——父层负责对接 POST /api/runs/{id}/promote。
   * 本卡只发意图，不前端伪造写盘。
   */
  onPromote?: (runId: string) => void;
  /** 「完整回测详情页 ↗」外链（落地路由到非冻结 App.tsx 的 /runs/:id）。 */
  detailHref?: string;
  /**
   * 数据来源（诚实角标）：
   *  - "mock"（默认）：未接真后端 → header 挂 <MockBadge/>，不假绿灯。
   *  - "live"：卡顶区块（裁决/KPI/成本/PBO·DSR/note）已接真后端
   *    （GET /verdict /overfit /cost-sensitivity）→ header 不再挂 mock 角标。
   * 注：detail modal 内仍有 mock 区块（持仓/部分指标）→ modal 角标恒挂，区分诚实。
   */
  dataSource?: "mock" | "live";
}

export function RunVerdictCard({
  data,
  onPromote,
  detailHref,
  dataSource = "mock",
}: RunVerdictCardProps) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [drawP, setDrawP] = useState(0);
  // 可编辑成本（modal 内）——纯展示重算，不触发真回测。
  const [cost, setCost] = useState({
    commission: 2.5,
    slippage: 5,
    stamp: 5,
    impact: 3,
  });
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  // 净值绘制动画 drawP 0→1（纯展示）。
  useEffect(() => {
    timer.current = setInterval(() => {
      setDrawP((p) => {
        const next = Math.min(1, p + 0.06);
        if (next >= 1 && timer.current) clearInterval(timer.current);
        return next;
      });
    }, 28);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, []);

  const vm = VERDICT_META[data.verdict];

  const chart = useMemo(() => {
    const W = 600;
    const H = 150;
    const pad = 6;
    const eqFull = data.equity.length >= 2 ? data.equity : [1, 1.1, 1.6];
    const benchFull = data.bench.length >= 2 ? data.bench : [1, 1.05, 1.18];
    const n = Math.max(2, Math.round(eqFull.length * drawP));
    const eq = eqFull.slice(0, n);
    const bench = benchFull.slice(0, Math.max(2, Math.round(benchFull.length * drawP)));
    const all = eqFull.concat(benchFull);
    const lo = Math.min(...all);
    const hi = Math.max(...all) || 1;
    const span = hi - lo || 1;
    const eqPath = linePath(eq, W, H, pad, lo, span);
    const xn = (i: number) => pad + (i / (eqFull.length - 1)) * (W - 2 * pad);
    const areaPath =
      eqPath +
      " L" +
      xn(n - 1).toFixed(1) +
      " " +
      (H - pad) +
      " L" +
      pad.toFixed(1) +
      " " +
      (H - pad) +
      " Z";
    return {
      W,
      H,
      eqPath,
      benchPath: linePath(bench, W, H, pad, lo, span),
      areaPath,
      lo,
      span,
    };
  }, [data.equity, data.bench, drawP]);

  const drawing = drawP < 1;

  const cardStyle: CSSProperties = {
    background: "var(--desk-card)",
    border: "1px solid var(--desk-border-strong)",
    borderRadius: "var(--desk-radius-lg)",
    overflow: "hidden",
    fontFamily: "var(--desk-mono)",
    color: "var(--desk-text)",
  };

  const kpi = data.kpi;

  return (
    <div data-testid="run-verdict-card" style={cardStyle}>
      {/* header：标题 + MOCK 角标 + 裁决 pill */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: "11px 15px",
          background: "var(--desk-panel)",
          borderBottom: "1px solid var(--desk-border)",
        }}
      >
        <span style={{ color: "var(--desk-accent)" }} aria-hidden>
          ◳
        </span>
        <span style={{ fontWeight: 600 }}>回测详情 · {data.runId}</span>
        {drawing && (
          <span style={{ fontSize: 10, color: "var(--desk-warning)" }}>
            ⟳ 生成中 {Math.round(drawP * 100)}%
          </span>
        )}
        <span style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {dataSource !== "live" && <MockBadge />}
          <span
            data-testid="verdict-pill"
            style={{
              fontSize: 11,
              fontWeight: 600,
              color: vm.color,
              background: vm.bg,
              padding: "3px 11px",
              borderRadius: "var(--desk-radius-pill)",
            }}
          >
            {vm.label}
          </span>
        </span>
      </div>

      {/* KPI 4 格 */}
      <div style={{ display: "flex", flexWrap: "wrap", padding: "13px 15px 9px" }}>
        <Kpi
          label="年化超额"
          value={pct(kpi.annExcess)}
          sub="目标 ≥15%"
          valueColor="var(--desk-success)"
        />
        <Kpi
          label="最大回撤"
          value={pct(kpi.maxDD)}
          sub="约束 ≤20%"
          valueColor="var(--desk-success)"
        />
        <Kpi
          label="Sharpe"
          value={kpi.sharpe.toFixed(2)}
          sub={"IR " + kpi.ir.toFixed(2)}
          valueColor="var(--desk-text)"
        />
        <Kpi
          label="周胜率"
          value={pct(kpi.winWeeks)}
          sub={"换手 " + pct(kpi.turnover) + "/周"}
          valueColor="var(--desk-text)"
        />
      </div>

      {/* 净值缩略图 */}
      <div style={{ padding: "4px 15px 10px" }}>
        <div
          style={{
            display: "flex",
            gap: 14,
            alignItems: "center",
            marginBottom: 6,
            fontSize: 11,
          }}
        >
          <LegendSwatch color="var(--desk-accent)" label="策略净值" />
          <LegendSwatch color="var(--desk-text-faint)" label="中证500" />
          {detailHref ? (
            <a
              href={detailHref}
              target="_blank"
              rel="noreferrer"
              style={{
                marginLeft: "auto",
                fontSize: 11,
                color: "var(--desk-info)",
                textDecoration: "none",
                cursor: "pointer",
              }}
            >
              完整回测详情页 ↗
            </a>
          ) : (
            <span style={{ marginLeft: "auto" }} />
          )}
          <button
            type="button"
            onClick={() => setDetailOpen(true)}
            style={{
              fontSize: 11,
              color: "var(--desk-text-muted)",
              cursor: "pointer",
              marginLeft: 12,
              background: "transparent",
              border: "none",
              fontFamily: "inherit",
              padding: 0,
            }}
          >
            卡内预览
          </button>
        </div>
        <svg
          viewBox={`0 0 ${chart.W} ${chart.H}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: 118, display: "block" }}
        >
          <defs>
            <linearGradient id="rvgrad" x1="0" y1="0" x2="0" y2="1">
              <stop
                offset="0%"
                stopColor="var(--desk-accent)"
                stopOpacity="0.22"
              />
              <stop offset="100%" stopColor="var(--desk-accent)" stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={chart.areaPath} fill="url(#rvgrad)" />
          <path
            d={chart.benchPath}
            fill="none"
            stroke="var(--desk-text-faint)"
            strokeWidth="1.4"
            strokeDasharray="3 3"
          />
          <path d={chart.eqPath} fill="none" stroke="var(--desk-accent)" strokeWidth="2" />
        </svg>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            color: "var(--desk-text-faint)",
            fontSize: 10,
            marginTop: 2,
          }}
        >
          <span>2019-01</span>
          <span>2024-12 · 312 周</span>
        </div>
      </div>

      {/* 成本敏感性 3 cell */}
      <div style={{ padding: "4px 15px 12px" }}>
        <div
          style={{
            color: "var(--desk-text-faint)",
            fontSize: 11,
            marginBottom: 6,
          }}
        >
          成本敏感性 · Sharpe / 年化超额
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {data.cost.map((c) => (
            <div
              key={c.preset}
              style={{
                flex: 1,
                background: "var(--desk-panel)",
                border:
                  "1px solid " +
                  (c.preset === "neutral"
                    ? "var(--desk-border-strong)"
                    : "var(--desk-border)"),
                borderRadius: "var(--desk-radius)",
                padding: "8px 10px",
              }}
            >
              <div
                style={{
                  color: PRESET_LABEL_COLOR[c.preset],
                  fontSize: 11,
                  marginBottom: 3,
                }}
              >
                {PRESET_LABEL[c.preset]}
              </div>
              <div
                style={{
                  color: "var(--desk-text)",
                  fontWeight: 700,
                  fontSize: 16,
                }}
              >
                {c.sharpe.toFixed(2)}
              </div>
              <div style={{ color: "var(--desk-text-dim)", fontSize: 11 }}>
                超额 {pct(c.excess)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* footer 裁决区：PBO/DSR + note + promote */}
      <div
        style={{
          padding: "11px 15px",
          background: "var(--desk-soft-btn)",
          borderTop: "1px solid var(--desk-border)",
        }}
      >
        <div style={{ display: "flex", gap: 16, marginBottom: 10 }}>
          <GateStat
            label="PBO"
            value={data.pbo}
            hint="<0.5 健康"
            healthy={(v) => v < 0.5}
          />
          <GateStat
            label="DSR"
            value={data.dsr}
            hint=">0 显著"
            healthy={(v) => v > 0}
          />
          <BootstrapStat ci={data.bootstrapCI} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            data-testid="verdict-note"
            style={{
              flex: 1,
              color: "var(--desk-text-dim)",
              fontSize: 12,
              lineHeight: 1.55,
            }}
          >
            {data.verdictNote}
          </div>
          <PromoteButton
            state={data.promoteState}
            onPromote={() => onPromote?.(data.runId)}
          />
        </div>
      </div>

      {detailOpen && (
        <DetailModal
          data={data}
          vm={vm}
          chartLo={chart.lo}
          chartSpan={chart.span}
          cost={cost}
          setCost={setCost}
          detailHref={detailHref}
          onClose={() => setDetailOpen(false)}
        />
      )}
    </div>
  );
}

function Kpi({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub: string;
  valueColor: string;
}) {
  return (
    <div style={{ flex: 1, minWidth: 88 }}>
      <div style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>{label}</div>
      <div style={{ color: valueColor, fontSize: 21, fontWeight: 700 }}>
        {value}
      </div>
      <div style={{ color: "var(--desk-text-faint)", fontSize: 10.5 }}>{sub}</div>
    </div>
  );
}

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        color: "var(--desk-text-dim)",
      }}
    >
      <span
        style={{ width: 14, height: 2, background: color, display: "inline-block" }}
        aria-hidden
      />
      {label}
    </span>
  );
}

function StatPair({
  label,
  value,
  hint,
  valueColor,
}: {
  label: string;
  value: string;
  hint: string;
  valueColor: string;
}) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 7 }}>
      <span style={{ color: "var(--desk-text-faint)", fontSize: 11 }}>{label}</span>
      <span style={{ color: valueColor, fontWeight: 700 }}>{value}</span>
      <span style={{ color: "var(--desk-text-faint)", fontSize: 10.5 }}>{hint}</span>
    </div>
  );
}

/**
 * 过拟合门单值展示格（PBO / DSR）。
 * 后端未算（null）/缺失/NaN → 「N/A」中性色（对齐 BootstrapStat 的 N/A 做法）——
 * 绝不 default 0 再上成功绿（§3 未验证 ≠ 已验证，不假绿灯）。
 * 仅当有限数才套健康判据上 success/danger 色。
 */
function GateStat({
  label,
  value,
  hint,
  healthy,
}: {
  label: string;
  value: number | null;
  hint: string;
  healthy: (v: number) => boolean;
}) {
  if (value === null || !Number.isFinite(value)) {
    return (
      <StatPair
        label={label}
        value="N/A"
        hint={hint}
        valueColor="var(--desk-text-faint)"
      />
    );
  }
  return (
    <StatPair
      label={label}
      value={value.toFixed(2)}
      hint={hint}
      valueColor={healthy(value) ? "var(--desk-success)" : "var(--desk-danger)"}
    />
  );
}

/**
 * 多证据三角第三腿：Bootstrap Sharpe CI 展示格（与 PBO/DSR 并列）。
 * 健康判据 = 下界 > 0（区间不跨零 → 显著）；缺省/NaN → 「N/A」（诚实不假绿灯）。
 */
function BootstrapStat({ ci }: { ci?: [number, number] | null }) {
  const valid =
    Array.isArray(ci) &&
    ci.length === 2 &&
    Number.isFinite(ci[0]) &&
    Number.isFinite(ci[1]);
  if (!valid) {
    return (
      <StatPair
        label="Bootstrap CI"
        value="N/A"
        hint="下界>0 显著"
        valueColor="var(--desk-text-faint)"
      />
    );
  }
  const [lo, hi] = ci;
  return (
    <StatPair
      label="Bootstrap CI"
      value={`[${lo.toFixed(2)}, ${hi.toFixed(2)}]`}
      hint="下界>0 显著"
      valueColor={lo > 0 ? "var(--desk-success)" : "var(--desk-danger)"}
    />
  );
}

function PromoteButton({
  state,
  onPromote,
}: {
  state: PromoteState;
  onPromote: () => void;
}) {
  const registered = state === "registered";
  return (
    <button
      type="button"
      data-testid="promote-btn"
      disabled={registered}
      onClick={onPromote}
      style={{
        flex: "none",
        background: registered
          ? "color-mix(in srgb, var(--desk-success) 14%, transparent)"
          : "var(--desk-accent)",
        border:
          "1px solid " +
          (registered
            ? "color-mix(in srgb, var(--desk-success) 45%, var(--desk-card))"
            : "var(--desk-accent)"),
        color: registered ? "var(--desk-success)" : "var(--desk-accent-ink)",
        fontFamily: "inherit",
        fontWeight: 700,
        fontSize: 12,
        padding: "8px 15px",
        borderRadius: "var(--desk-radius)",
        cursor: registered ? "default" : "pointer",
      }}
    >
      {registered ? "✓ 已登记对比分析" : "登记为晋级候选 →"}
    </button>
  );
}

// ---- 全屏 detail modal ----

interface CostState {
  commission: number;
  slippage: number;
  stamp: number;
  impact: number;
}

function DetailModal({
  data,
  vm,
  chartLo,
  chartSpan,
  cost,
  setCost,
  detailHref,
  onClose,
}: {
  data: RunVerdictData;
  vm: { label: string; color: string; bg: string };
  chartLo: number;
  chartSpan: number;
  cost: CostState;
  setCost: React.Dispatch<React.SetStateAction<CostState>>;
  detailHref?: string;
  onClose: () => void;
}) {
  const eqFull = data.equity.length >= 2 ? data.equity : [1, 1.1, 1.6];
  const benchFull = data.bench.length >= 2 ? data.bench : [1, 1.05, 1.18];

  const big = useMemo(() => {
    const DW = 800;
    const DH = 200;
    const dpad = 8;
    const dEq = linePath(eqFull, DW, DH, dpad, chartLo, chartSpan);
    const dBench = linePath(benchFull, DW, DH, dpad, chartLo, chartSpan);
    const dArea =
      dEq +
      " L" +
      (DW - dpad) +
      " " +
      (DH - dpad) +
      " L" +
      dpad +
      " " +
      (DH - dpad) +
      " Z";
    let peak = -1e9;
    const dd = eqFull.map((v) => {
      peak = Math.max(peak, v);
      return (v - peak) / peak;
    });
    const ddLo = Math.min(...dd);
    const ddSpan = 0 - ddLo || 1;
    const ddY = (v: number) => DH - 4 - ((0 - v) / ddSpan) * 46;
    const dDD =
      "M" +
      dpad +
      " " +
      (DH - 4) +
      " " +
      dd
        .map(
          (v, i) =>
            "L" +
            (dpad + (i / (dd.length - 1)) * (DW - 2 * dpad)).toFixed(1) +
            " " +
            ddY(v).toFixed(1),
        )
        .join(" ") +
      " L" +
      (DW - dpad) +
      " " +
      (DH - 4) +
      " Z";
    return { dEq, dBench, dArea, dDD };
  }, [eqFull, benchFull, chartLo, chartSpan]);

  const metrics: { k: string; v: string; color: string }[] = [
    { k: "年化收益", v: "24.6%", color: "var(--desk-success)" },
    { k: "年化超额", v: pct(data.kpi.annExcess), color: "var(--desk-success)" },
    { k: "年化波动", v: "13.5%", color: "var(--desk-text-soft)" },
    { k: "Sharpe", v: data.kpi.sharpe.toFixed(2), color: "var(--desk-text)" },
    { k: "Sortino", v: "2.54", color: "var(--desk-text-soft)" },
    { k: "IR", v: data.kpi.ir.toFixed(2), color: "var(--desk-text-soft)" },
    { k: "最大回撤", v: pct(data.kpi.maxDD), color: "var(--desk-danger)" },
    { k: "Calmar", v: "1.56", color: "var(--desk-text-soft)" },
    { k: "周胜率", v: pct(data.kpi.winWeeks), color: "var(--desk-text-soft)" },
    { k: "周换手", v: pct(data.kpi.turnover), color: "var(--desk-text-soft)" },
    { k: "平均持仓", v: "52 只", color: "var(--desk-text-soft)" },
    { k: "盈亏比", v: "1.38", color: "var(--desk-text-soft)" },
  ];

  const heat = HEAT_YEARS.map((year, yi) => ({
    year,
    cells: MONTHS.map((_, mi) => {
      const v = (seed(yi * 13 + mi * 7) - 0.42) * 9;
      const a = Math.min(0.85, Math.abs(v) / 6 + 0.12);
      const baseTok = v >= 0 ? "var(--desk-success)" : "var(--desk-danger)";
      return {
        t: (v >= 0 ? "+" : "") + v.toFixed(1),
        bg: `color-mix(in srgb, ${baseTok} ${Math.round(a * 100)}%, transparent)`,
        fg: Math.abs(v) > 3 ? "var(--desk-text)" : "var(--desk-text-dim)",
      };
    }),
  }));

  const tradeStats = [
    { k: "总交易笔数", v: "8,624" },
    { k: "平均持有", v: "3.2 周" },
    { k: "周胜率", v: pct(data.kpi.winWeeks) },
    { k: "盈亏比", v: "1.38" },
    { k: "单边成本", v: "neutral · ~18bp" },
    { k: "年化换手", v: "21.8x" },
  ];

  // null/缺失/NaN → 「N/A · 未算」中性色，绝不 default 0 再上成功绿（§3 不假绿灯）。
  const pboKnown = data.pbo !== null && Number.isFinite(data.pbo);
  const dsrKnown = data.dsr !== null && Number.isFinite(data.dsr);
  const overfit = [
    {
      k: "PBO (CSCV)",
      v: pboKnown
        ? data.pbo!.toFixed(2) + (data.pbo! < 0.5 ? " 容差内" : " 超容差")
        : "N/A · 未算",
      color: pboKnown
        ? data.pbo! < 0.5
          ? "var(--desk-success)"
          : "var(--desk-danger)"
        : "var(--desk-text-faint)",
    },
    {
      k: "Deflated Sharpe",
      v: dsrKnown ? data.dsr!.toFixed(2) + " · p<0.01" : "N/A · 未算",
      color: dsrKnown
        ? data.dsr! > 0
          ? "var(--desk-success)"
          : "var(--desk-danger)"
        : "var(--desk-text-faint)",
    },
    { k: "honest-N", v: "N_eff = 42", color: "var(--desk-text-soft)" },
    { k: "样本外占比", v: "2024 全年留出", color: "var(--desk-success)" },
  ];

  const holdings: {
    name: string;
    code: string;
    w: string;
    ret: string;
    ind: string;
    color: string;
  }[] = (
    [
      ["紫金矿业", "601899", "2.8%", 14.2, "有色"],
      ["比亚迪", "002594", "2.6%", -6.1, "汽车"],
      ["立讯精密", "002475", "2.4%", 9.3, "电子"],
      ["隆基绿能", "601012", "2.2%", 21.4, "电新"],
      ["万华化学", "600309", "2.1%", -3.2, "化工"],
      ["药明康德", "603259", "2.0%", 7.8, "医药"],
      ["宁德时代", "300750", "1.9%", 12.1, "电新"],
      ["招商银行", "600036", "1.8%", 4.5, "银行"],
    ] as [string, string, string, number, string][]
  ).map(([name, code, w, ret, ind]) => ({
    name,
    code,
    w,
    ind,
    ret: (ret >= 0 ? "+" : "") + ret + "%",
    color: ret >= 0 ? "var(--desk-success)" : "var(--desk-danger)",
  }));

  const setCostKey = (k: keyof CostState, raw: string) => {
    const n = parseFloat(raw);
    setCost((s) => ({ ...s, [k]: Number.isNaN(n) ? 0 : n }));
  };
  const costRows: { k: string; key: keyof CostState }[] = [
    { k: "手续费 佣金", key: "commission" },
    { k: "滑点", key: "slippage" },
    { k: "印花税(卖)", key: "stamp" },
    { k: "冲击成本", key: "impact" },
  ];
  const costTotal = (
    cost.commission +
    cost.slippage +
    cost.stamp / 2 +
    cost.impact
  ).toFixed(1);

  const cardSub: CSSProperties = {
    background: "var(--desk-card)",
    border: "1px solid var(--desk-border)",
    borderRadius: 10,
    padding: "12px 14px",
  };
  const sectionTitle: CSSProperties = {
    fontSize: 11.5,
    color: "var(--desk-text-soft)",
    fontWeight: 600,
    marginBottom: 8,
  };

  return (
    <div
      data-testid="verdict-detail-modal"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "color-mix(in srgb, var(--desk-bg) 74%, transparent)",
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        fontFamily: "var(--desk-mono)",
        color: "var(--desk-text)",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 880,
          maxWidth: "100%",
          maxHeight: "92vh",
          overflowY: "auto",
          background: "var(--desk-soft-btn)",
          border: "1px solid var(--desk-border-strong)",
          borderRadius: 14,
          boxShadow: "0 30px 70px color-mix(in srgb, var(--desk-bg) 60%, transparent)",
        }}
      >
        <div
          style={{
            position: "sticky",
            top: 0,
            zIndex: 5,
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "13px 18px",
            background: "var(--desk-panel)",
            borderBottom: "1px solid var(--desk-border)",
          }}
        >
          <span style={{ color: "var(--desk-accent)" }} aria-hidden>
            ◳
          </span>
          <span style={{ fontWeight: 700, fontSize: 15 }}>
            回测详情 · {data.runId}
          </span>
          <span style={{ fontSize: 11, color: "var(--desk-text-faint)" }}>
            2019-01 → 2024-12 · 312 周 · 中证500 · neutral 成本
          </span>
          <MockBadge />
          <span
            style={{
              marginLeft: "auto",
              fontSize: 11,
              fontWeight: 600,
              color: vm.color,
              background: vm.bg,
              padding: "3px 11px",
              borderRadius: "var(--desk-radius-pill)",
            }}
          >
            {vm.label}
          </span>
          {detailHref && (
            <a
              href={detailHref}
              target="_blank"
              rel="noreferrer"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 5,
                textDecoration: "none",
                background: "var(--desk-accent)",
                border: "1px solid var(--desk-accent)",
                color: "var(--desk-accent-ink)",
                fontFamily: "inherit",
                fontWeight: 700,
                fontSize: 11,
                padding: "4px 11px",
                borderRadius: 7,
                cursor: "pointer",
              }}
            >
              ↗ 打开完整页面
            </a>
          )}
          <button
            type="button"
            onClick={onClose}
            style={{
              background: "transparent",
              border: "1px solid var(--desk-border-strong)",
              color: "var(--desk-text-muted)",
              fontFamily: "inherit",
              fontSize: 11,
              padding: "4px 11px",
              borderRadius: 7,
              cursor: "pointer",
            }}
          >
            ✕ 关闭
          </button>
        </div>

        <div
          style={{
            padding: "16px 18px",
            display: "flex",
            flexDirection: "column",
            gap: 16,
          }}
        >
          {/* metrics grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4,1fr)",
              gap: 10,
            }}
          >
            {metrics.map((m) => (
              <div
                key={m.k}
                style={{
                  background: "var(--desk-card)",
                  border: "1px solid var(--desk-border)",
                  borderRadius: 9,
                  padding: "9px 12px",
                }}
              >
                <div style={{ color: "var(--desk-text-faint)", fontSize: 10.5 }}>
                  {m.k}
                </div>
                <div style={{ color: m.color, fontSize: 17, fontWeight: 700 }}>
                  {m.v}
                </div>
              </div>
            ))}
          </div>

          {/* equity + drawdown */}
          <div style={cardSub}>
            <div style={sectionTitle}>净值曲线 · 相对回撤</div>
            <svg
              viewBox="0 0 800 200"
              preserveAspectRatio="none"
              style={{ width: "100%", height: 190, display: "block" }}
            >
              <defs>
                <linearGradient id="rvgrad2" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor="var(--desk-accent)"
                    stopOpacity="0.18"
                  />
                  <stop
                    offset="100%"
                    stopColor="var(--desk-accent)"
                    stopOpacity="0"
                  />
                </linearGradient>
              </defs>
              <path d={big.dArea} fill="url(#rvgrad2)" />
              <path
                d={big.dBench}
                fill="none"
                stroke="var(--desk-text-faint)"
                strokeWidth="1.3"
                strokeDasharray="3 3"
              />
              <path
                d={big.dEq}
                fill="none"
                stroke="var(--desk-accent)"
                strokeWidth="2"
              />
              <path
                d={big.dDD}
                fill="color-mix(in srgb, var(--desk-danger) 16%, transparent)"
                stroke="var(--desk-danger)"
                strokeWidth="1"
              />
            </svg>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                color: "var(--desk-text-faint)",
                fontSize: 10,
              }}
            >
              <span>策略净值 / 基准（虚） / 回撤（下方红）</span>
              <span>最大回撤 {pct(data.kpi.maxDD)}</span>
            </div>
          </div>

          {/* monthly heatmap */}
          <div style={cardSub}>
            <div style={{ ...sectionTitle, marginBottom: 9 }}>
              月度超额收益热力图
            </div>
            <div style={{ display: "flex", gap: 4, marginBottom: 4 }}>
              <span style={{ width: 34 }} />
              {MONTHS.map((mo) => (
                <span
                  key={mo}
                  style={{
                    flex: 1,
                    textAlign: "center",
                    fontSize: 8.5,
                    color: "var(--desk-text-faint)",
                  }}
                >
                  {mo}
                </span>
              ))}
            </div>
            {heat.map((row) => (
              <div
                key={row.year}
                style={{
                  display: "flex",
                  gap: 4,
                  marginBottom: 4,
                  alignItems: "center",
                }}
              >
                <span
                  style={{
                    width: 34,
                    fontSize: 9,
                    color: "var(--desk-text-faint)",
                  }}
                >
                  {row.year}
                </span>
                {row.cells.map((cell, i) => (
                  <span
                    key={i}
                    style={{
                      flex: 1,
                      height: 18,
                      borderRadius: 3,
                      background: cell.bg,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      fontSize: 8,
                      color: cell.fg,
                    }}
                  >
                    {cell.t}
                  </span>
                ))}
              </div>
            ))}
          </div>

          {/* trade stats | overfit */}
          <div style={{ display: "flex", gap: 14 }}>
            <div style={{ ...cardSub, flex: 1 }}>
              <div style={{ ...sectionTitle, marginBottom: 9 }}>交易统计</div>
              {tradeStats.map((t) => (
                <KvRow key={t.k} k={t.k} v={t.v} />
              ))}
            </div>
            <div style={{ ...cardSub, flex: 1 }}>
              <div style={{ ...sectionTitle, marginBottom: 9 }}>过拟合体检</div>
              {overfit.map((o) => (
                <KvRow key={o.k} k={o.k} v={o.v} valueColor={o.color} bold />
              ))}
            </div>
          </div>

          {/* editable cost */}
          <div style={cardSub}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 9,
              }}
            >
              <span style={{ ...sectionTitle, marginBottom: 0 }}>
                成本设置 · 手续费 / 滑点（bp，可调）
              </span>
              <span
                style={{
                  marginLeft: "auto",
                  fontSize: 11,
                  color: "var(--desk-warning)",
                }}
              >
                单边合计 {costTotal} bp
              </span>
            </div>
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              {costRows.map((row) => (
                <div key={row.key} style={{ flex: 1, minWidth: 120 }}>
                  <div
                    style={{
                      fontSize: 10,
                      color: "var(--desk-text-faint)",
                      marginBottom: 3,
                    }}
                  >
                    {row.k}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                    <input
                      aria-label={row.k}
                      value={cost[row.key]}
                      onChange={(e) => setCostKey(row.key, e.target.value)}
                      type="number"
                      style={{
                        flex: 1,
                        width: "100%",
                        background: "var(--desk-input)",
                        border: "1px solid var(--desk-border-strong)",
                        color: "var(--desk-text)",
                        fontSize: 12,
                        padding: "5px 8px",
                        borderRadius: 6,
                        outline: "none",
                        fontFamily: "inherit",
                      }}
                    />
                    <span style={{ fontSize: 10, color: "var(--desk-text-faint)" }}>
                      bp
                    </span>
                  </div>
                </div>
              ))}
            </div>
            <div
              style={{
                marginTop: 8,
                fontSize: 10,
                color: "var(--desk-text-faint)",
                lineHeight: 1.5,
              }}
            >
              A股双边：买入扣佣金+滑点+冲击；卖出再加印花税 5bp。合计含 ½
              印花税计单边。调整后回测净值与 Sharpe 随成本变化（neutral 预设为基准）。
            </div>
          </div>

          {/* top holdings */}
          <div
            style={{
              background: "var(--desk-card)",
              border: "1px solid var(--desk-border)",
              borderRadius: 10,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                padding: "9px 14px",
                fontSize: 11.5,
                color: "var(--desk-text-soft)",
                fontWeight: 600,
                borderBottom: "1px solid var(--desk-border)",
              }}
            >
              期末持仓 · top 8
            </div>
            <div
              style={{
                display: "flex",
                padding: "6px 14px",
                background: "var(--desk-panel)",
                fontSize: 10,
                color: "var(--desk-text-faint)",
              }}
            >
              <span style={{ flex: 1.4 }}>名称</span>
              <span style={{ flex: 1 }}>代码</span>
              <span style={{ flex: 0.8, textAlign: "right" }}>权重</span>
              <span style={{ flex: 0.8, textAlign: "right" }}>区间收益</span>
              <span style={{ flex: 1, textAlign: "right" }}>行业</span>
            </div>
            {holdings.map((h) => (
              <div
                key={h.code}
                style={{
                  display: "flex",
                  padding: "6px 14px",
                  borderTop: "1px solid var(--desk-grid-dot)",
                  fontSize: 11,
                }}
              >
                <span style={{ flex: 1.4, color: "var(--desk-text-soft)" }}>
                  {h.name}
                </span>
                <span style={{ flex: 1, color: "var(--desk-text-faint)" }}>
                  {h.code}
                </span>
                <span
                  style={{ flex: 0.8, textAlign: "right", color: "var(--desk-text-dim)" }}
                >
                  {h.w}
                </span>
                <span style={{ flex: 0.8, textAlign: "right", color: h.color }}>
                  {h.ret}
                </span>
                <span
                  style={{ flex: 1, textAlign: "right", color: "var(--desk-text-faint)" }}
                >
                  {h.ind}
                </span>
              </div>
            ))}
          </div>

          <div
            style={{
              fontSize: 10.5,
              color: "var(--desk-text-faint)",
              lineHeight: 1.6,
              textAlign: "center",
            }}
          >
            完整回测详情（与 quantbt 回测详情页一致）：净值/回撤、月度热力、交易统计、过拟合体检、持仓。
            {data.verdictNote}
          </div>
        </div>
      </div>
    </div>
  );
}

function KvRow({
  k,
  v,
  valueColor = "var(--desk-text-soft)",
  bold = false,
}: {
  k: string;
  v: string;
  valueColor?: string;
  bold?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        padding: "4px 0",
        borderBottom: "1px solid var(--desk-grid-dot)",
        fontSize: 11.5,
      }}
    >
      <span style={{ color: "var(--desk-text-faint)" }}>{k}</span>
      <span style={{ color: valueColor, fontWeight: bold ? 600 : 400 }}>{v}</span>
    </div>
  );
}

/**
 * P0 mock 数据（诚实：未接真后端，verdictNote 用合规措辞占位）。
 * verdict 取三态之一；note 禁绝对化措辞——落地由 verifier._verdict_note 替换。
 */
export const MOCK_RUN_VERDICT: RunVerdictData = {
  runId: "run-20240601-a1b2",
  verdict: "consistent",
  kpi: {
    annExcess: 0.173,
    maxDD: 0.158,
    sharpe: 1.82,
    ir: 1.41,
    winWeeks: 0.61,
    turnover: 0.42,
  },
  equity: [
    1, 1.04, 1.02, 1.11, 1.18, 1.13, 1.22, 1.31, 1.27, 1.4, 1.52, 1.48, 1.61,
    1.73, 1.69, 1.82,
  ],
  bench: [
    1, 1.02, 1.0, 1.05, 1.09, 1.04, 1.08, 1.12, 1.07, 1.14, 1.19, 1.15, 1.21,
    1.26, 1.22, 1.3,
  ],
  cost: [
    { preset: "optimistic", sharpe: 1.98, excess: 0.191 },
    { preset: "neutral", sharpe: 1.82, excess: 0.173 },
    { preset: "pessimistic", sharpe: 1.51, excess: 0.138 },
  ],
  pbo: 0.18,
  dsr: 1.34,
  bootstrapCI: [0.21, 1.97],
  verdictNote:
    "双目标在容差内、PBO 0.18 / DSR 1.34 未触发熔断。适用域：中证500 成分、周频、2019–2024；未验证项：制度变更稳健性、实盘冲击成本。建议 pessimistic 成本下纸面跟踪 4 周再决定动钱。",
  promoteState: "candidate",
};
