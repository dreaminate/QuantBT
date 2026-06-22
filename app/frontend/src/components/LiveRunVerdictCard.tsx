import { useEffect, useState } from "react";
import { authFetch } from "../lib/auth";
import {
  RunVerdictCard,
  type CostCell,
  type PromoteState,
  type RunVerdictData,
  type Verdict,
} from "./RunVerdictCard";

/**
 * LiveRunVerdictCard · 裁决卡接真（R2 后端接线）。
 *
 * 拉真后端三端点合成 RunVerdictData，喂给纯展示的 RunVerdictCard：
 *   GET /api/runs/{id}/verdict          → 验证官三态 + 合规 note（_verdict_note 供给）
 *   GET /api/runs/{id}/overfit          → PBO/DSR（过拟合三角门，gate_label 另一条管线不混用）
 *   GET /api/runs/{id}/cost-sensitivity → 3 预设 Sharpe/超额（P0 派生，诚实）
 * KPI 从 verdict 端点缺省时用 /api/runs/{id} 的 metrics 兜底（此处只取轻量字段）。
 *
 * 红线守则：
 *  ① verdict 只接受三态（consistent/concern/blocked），后端越界值 fail-closed 成 concern。
 *  ② verdictNote 一律用后端供给（禁前端杜撰绝对化措辞）；后端无则用合规占位（未验证 ≠ 已验证）。
 *  ③ promote 为写动作 → POST /api/runs/{id}/promote（经审批门 approver≠creator），
 *     前端不伪造写盘；后端 422（自审/缺要件）原样上抛父层处理。
 *  ④ dataSource="live"：卡顶区块已接真 → 不挂 mock 角标（modal 内仍 mock → 角标恒挂）。
 */

const THREE_STATE: Verdict[] = ["consistent", "concern", "blocked"];

interface VerdictResp {
  run_id: string;
  verdict: string;
  verdictNote?: string;
  has_authoritative_verdict?: boolean;
}
interface OverfitResp {
  pbo?: number | null;
  dsr_conservative?: number;
  dsr_optimistic?: number;
  // 多证据三角第三腿：GateVerdict.to_dict() 返 [下界, 上界]（NaN→无效，前端显 N/A）。
  bootstrap_ci?: [number, number] | number[];
}
interface CostResp {
  cost?: Array<{ preset: string; sharpe: number; excess: number }>;
}
interface RunMetricsResp {
  metrics?: Record<string, number>;
  market?: string;
  frequency?: string;
}

function asVerdict(v: string): Verdict {
  // 后端越界值（理论不该出现）→ fail-closed 成 concern，绝不假绿灯。
  return (THREE_STATE as string[]).includes(v) ? (v as Verdict) : "concern";
}

function num(v: unknown, d = 0): number {
  return typeof v === "number" && Number.isFinite(v) ? v : d;
}

/** Bootstrap CI 解析：仅当 [下界,上界] 均为有限数才有效；否则 null（前端显 N/A，不假绿灯）。 */
function ciOrNull(ci: unknown): [number, number] | null {
  if (
    Array.isArray(ci) &&
    ci.length === 2 &&
    typeof ci[0] === "number" &&
    typeof ci[1] === "number" &&
    Number.isFinite(ci[0]) &&
    Number.isFinite(ci[1])
  ) {
    return [ci[0], ci[1]];
  }
  return null;
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await authFetch(url);
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = typeof j?.detail === "string" ? j.detail : detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

/** 后端三端点 → RunVerdictData（纯映射，无副作用）。 */
function mapToData(
  runId: string,
  verdict: VerdictResp,
  overfit: OverfitResp,
  cost: CostResp,
  run: RunMetricsResp,
  promoteState: PromoteState,
): RunVerdictData {
  const m = run.metrics ?? {};
  const costCells: CostCell[] = (cost.cost ?? [])
    .filter((c) =>
      ["optimistic", "neutral", "pessimistic"].includes(c.preset),
    )
    .map((c) => ({
      preset: c.preset as CostCell["preset"],
      sharpe: num(c.sharpe),
      excess: num(c.excess),
    }));
  return {
    runId,
    verdict: asVerdict(verdict.verdict),
    kpi: {
      annExcess: num(m.excess_return ?? m.annualized_return),
      maxDD: num(m.max_drawdown),
      sharpe: num(m.sharpe),
      ir: num(m.information_ratio),
      winWeeks: num(m.win_rate),
      turnover: num(m.turnover),
    },
    equity: [],
    bench: [],
    cost: costCells,
    pbo: num(overfit.pbo, 0),
    dsr: num(overfit.dsr_conservative ?? overfit.dsr_optimistic, 0),
    bootstrapCI: ciOrNull(overfit.bootstrap_ci),
    // note 一律后端供给；缺失用合规占位（不杜撰绝对化措辞）。
    verdictNote:
      verdict.verdictNote ||
      "本 run 暂无后端供给的合规裁决说明（未验证 ≠ 已验证）。",
    promoteState,
  };
}

export interface LiveRunVerdictCardProps {
  runId: string;
  detailHref?: string;
  /** 拉取失败时的兜底（一般传 mock 数据 + 由调用方决定是否回退 mock 卡）。 */
  fallback?: RunVerdictData;
}

export function LiveRunVerdictCard({
  runId,
  detailHref,
  fallback,
}: LiveRunVerdictCardProps) {
  const [data, setData] = useState<RunVerdictData | null>(null);
  const [error, setError] = useState<string | null>(null);
  // promoteState 恒 candidate：开门 ≠ 已晋级。真翻「已登记」须经独立 approver≠creator 审批
  // （本卡不自审、不伪造写盘成功）——故按钮不自变 registered。
  const promoteState: PromoteState = "candidate";
  const [promoteMsg, setPromoteMsg] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    setData(null);
    Promise.all([
      fetchJson<VerdictResp>(`/api/runs/${encodeURIComponent(runId)}/verdict`),
      fetchJson<OverfitResp>(`/api/runs/${encodeURIComponent(runId)}/overfit`),
      fetchJson<CostResp>(
        `/api/runs/${encodeURIComponent(runId)}/cost-sensitivity`,
      ),
      fetchJson<RunMetricsResp>(`/api/runs/${encodeURIComponent(runId)}`),
    ])
      .then(([verdict, overfit, cost, run]) => {
        if (!alive) return;
        setData(mapToData(runId, verdict, overfit, cost, run, "candidate"));
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [runId]);

  // promote 写动作：经后端审批门（approver≠creator）。本卡发意图、不伪造写盘。
  const onPromote = async (rid: string) => {
    setPromoteMsg(null);
    try {
      const res = await authFetch(
        `/api/runs/${encodeURIComponent(rid)}/promote`,
        { method: "POST", body: JSON.stringify({}) },
      );
      const j = await res.json().catch(() => ({}));
      if (!res.ok) {
        // 422：自审/缺要件 → 诚实展示缺口，绝不把按钮翻成「已登记」。
        const gaps = Array.isArray(j?.detail?.gaps)
          ? j.detail.gaps.join("；")
          : j?.detail?.reason || `HTTP ${res.status}`;
        setPromoteMsg(`晋级门未放行：${gaps}`);
        return;
      }
      // 门已开（pending，待 approver≠creator 人工审批）——非「已晋级」绿灯。
      setPromoteMsg(
        j?.note || "已开晋级审批门（待 approver≠creator 审批）。",
      );
    } catch (e) {
      setPromoteMsg(e instanceof Error ? e.message : String(e));
    }
  };

  if (error) {
    if (fallback) {
      // 拉取失败 → 回退 mock 卡（诚实挂 mock 角标），不空屏。
      return (
        <div data-testid="live-run-verdict-fallback">
          <div
            style={{
              fontSize: 11,
              color: "var(--desk-warning)",
              marginBottom: 6,
            }}
          >
            裁决卡接真失败，回退示例数据：{error}
          </div>
          <RunVerdictCard
            data={fallback}
            detailHref={detailHref}
            dataSource="mock"
          />
        </div>
      );
    }
    return (
      <div
        data-testid="live-run-verdict-error"
        style={{ fontSize: 12, color: "var(--desk-danger)", padding: 16 }}
      >
        裁决卡加载失败：{error}
      </div>
    );
  }

  if (!data) {
    return (
      <div
        data-testid="live-run-verdict-loading"
        style={{ fontSize: 12, color: "var(--desk-text-faint)", padding: 16 }}
      >
        加载裁决卡…
      </div>
    );
  }

  return (
    <div data-testid="live-run-verdict-card">
      <RunVerdictCard
        data={{ ...data, promoteState }}
        detailHref={detailHref}
        dataSource="live"
        onPromote={onPromote}
      />
      {promoteMsg && (
        <div
          data-testid="live-promote-msg"
          style={{
            fontSize: 11,
            color: "var(--desk-text-dim)",
            marginTop: 6,
            lineHeight: 1.5,
          }}
        >
          {promoteMsg}
        </div>
      )}
    </div>
  );
}
