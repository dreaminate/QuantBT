import { useCallback, useEffect, useMemo, useState } from "react";
import { EvalCharts, type ChartData } from "../../components/charts/EvalCharts";
import {
  ConformalIntervalCard,
  type ConformalIntervalData,
} from "../../components/charts/ConformalIntervalCard";
import {
  CpcvRobustnessCard,
  type CpcvDistributionData,
} from "../../components/charts/CpcvRobustnessCard";

/**
 * 模型中心 · 训练台（Claude Code 风）
 * 结构（清晰三栏 + 底部任务表）：
 *  ┌ 左:配置 ┬ 中:将要跑的代码 + 状态 ┬ 右:模型卡片(优缺点/调参) ┐
 *  └────────── 底部:训练任务列表（状态/指标，轮询） ──────────┘
 * 本质是跑代码：左侧选好 → 中间实时预览生成的训练脚本 → 开训(ML 进程内 / DL 全功率子进程)。
 */

interface ParamSpec {
  type: string;
  default: number;
  min?: number;
  max?: number;
  help?: string;
}
interface ModelCard {
  key: string;
  family: "ml" | "dl";
  display_name: string;
  tasks: string[];
  description: string;
  pros: string[];
  cons: string[];
  tuning_tip: string;
  param_schema: Record<string, ParamSpec>;
  needs_dl: boolean;
  tensorboard: boolean;
  available: boolean;
}
interface Dataset {
  dataset_id: string;
  label: string;
  asset_class: string;
  feature_cols: string[];
  label_col: string;
  rows: number;
}
interface Job {
  job_id: string;
  name: string;
  model: string;
  family: string;
  task: string;
  status: "queued" | "running" | "succeeded" | "failed";
  metrics: Record<string, number>;
  elapsed_seconds?: number | null;
  error?: string | null;
  tensorboard?: boolean;
}

const STATUS_COLOR: Record<string, string> = {
  queued: "var(--cc-text-dim)",
  running: "var(--cc-info)",
  succeeded: "var(--cc-success)",
  failed: "var(--cc-danger)",
};

export function TrainingBenchPage() {
  const [models, setModels] = useState<ModelCard[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);

  const [dataset, setDataset] = useState("");
  const [modelKey, setModelKey] = useState("");
  const [task, setTask] = useState("");
  const [features, setFeatures] = useState<string[]>([]);
  const [hyper, setHyper] = useState<Record<string, number>>({});
  const [trainFraction, setTrainFraction] = useState(0); // 0=用全程训练; >0=只用前N%(严格无泄露 walk-forward)
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState("");

  // 评价图面板
  const [selectedJob, setSelectedJob] = useState<string | null>(null);
  const [selectedModel, setSelectedModel] = useState("");
  const [selectedIsDl, setSelectedIsDl] = useState(false);
  const [evalCharts, setEvalCharts] = useState<ChartData[]>([]);
  // R23 conformal 校准区间（OOS 真留出覆盖）；null=非回归/无 OOS/calib 不足 → 不渲染（不假绿灯）。
  const [conformal, setConformal] = useState<ConformalIntervalData | null>(null);
  // R4 CPCV 路径稳健性分布；null=未开 compute_cpcv → 不渲染（不假绿灯：未算≠已算）。
  const [cpcv, setCpcv] = useState<CpcvDistributionData | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [evalError, setEvalError] = useState("");
  const [tbBusy, setTbBusy] = useState(false);
  const [btBusy, setBtBusy] = useState(false);
  const [btResult, setBtResult] = useState<Record<string, number> | null>(null);
  const [btMeta, setBtMeta] = useState<{ is_oos: boolean; is_cross_dataset: boolean; strict_oos: boolean; dataset_id: string; n_days: number } | null>(null);
  const [btDataset, setBtDataset] = useState("");  // 回测数据集(空=训练集);换数据集=跨集 OOS
  const [btOosFrac, setBtOosFrac] = useState(0);   // >0=只回测末尾该比例交易日(同集时间后段 OOS)

  const openEval = useCallback((j: Job) => {
    setSelectedJob(j.job_id);
    setSelectedModel(`${j.model} · ${j.family}`);
    setSelectedIsDl(!!j.tensorboard);
    setEvalLoading(true);
    setEvalCharts([]);
    setConformal(null);
    setCpcv(null);
    setEvalError("");
    setBtResult(null);
    fetch(`/api/training/jobs/${j.job_id}/eval`)
      .then(async (r) => {
        if (!r.ok) {
          // 区分"服务端错误"与"成功但无图"，避免错误被静默当作空状态
          const detail = await r.json().catch(() => ({}));
          throw new Error(detail.detail ?? `加载评价图失败 (${r.status})`);
        }
        return r.json();
      })
      .then((body) => {
        setEvalCharts(body.charts ?? []);
        setConformal(body.conformal_interval ?? null);  // R23 OOS 留出覆盖（缺/null→不渲染）
        setCpcv(body.cpcv_distribution ?? null);         // R4 CPCV 路径稳健性（缺/null→不渲染）
      })
      .catch((e) => setEvalError(e instanceof Error ? e.message : "加载评价图失败"))
      .finally(() => setEvalLoading(false));
  }, []);

  const startTensorBoard = useCallback(async () => {
    if (!selectedJob) return;
    setTbBusy(true);
    try {
      const r = await fetch(`/api/training/jobs/${selectedJob}/tensorboard`, { method: "POST" });
      const body = await r.json();
      if (r.ok && body.url) window.open(body.url, "_blank", "noreferrer");
      else alert(body.detail ?? "TensorBoard 启动失败");
    } finally {
      setTbBusy(false);
    }
  }, [selectedJob]);

  const runBacktest = useCallback(async () => {
    if (!selectedJob) return;
    setBtBusy(true);
    setBtResult(null);
    setBtMeta(null);
    try {
      const payload: Record<string, unknown> = { top_n: 5 };
      if (btDataset) payload.dataset_id = btDataset;       // 换数据集 → 跨集样本外
      if (btOosFrac > 0) payload.oos_fraction = btOosFrac; // 同集只回测末尾比例 → 时间后段样本外
      const r = await fetch(`/api/training/jobs/${selectedJob}/backtest`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload),
      });
      const body = await r.json();
      if (!r.ok) {
        alert(body.detail ?? `回测失败 (${r.status})`);
        return;
      }
      setBtResult(body.metrics ?? {});
      setBtMeta({ is_oos: !!body.is_oos, is_cross_dataset: !!body.is_cross_dataset, strict_oos: !!body.strict_oos, dataset_id: body.dataset_id, n_days: body.n_days });
    } finally {
      setBtBusy(false);
    }
  }, [selectedJob, btDataset, btOosFrac]);

  const card = useMemo(() => models.find((m) => m.key === modelKey), [models, modelKey]);
  const ds = useMemo(() => datasets.find((d) => d.dataset_id === dataset), [datasets, dataset]);

  // 初次加载
  useEffect(() => {
    Promise.all([
      fetch("/api/training/models").then((r) => r.json()),
      fetch("/api/training/datasets").then((r) => r.json()),
    ])
      .then(([m, d]: [ModelCard[], Dataset[]]) => {
        setModels(m);
        setDatasets(d);
        if (d[0]) {
          setDataset(d[0].dataset_id);
          setFeatures(d[0].feature_cols);
        }
        const first = m.find((x) => x.key === "xgboost") ?? m[0];
        if (first) {
          setModelKey(first.key);
          setTask(first.tasks[0]);
        }
      })
      .catch(() => setErr("加载模型/数据集失败"));
    refreshJobs();
  }, []);

  // 换模型 → 任务回落到该模型支持的、超参初始化为默认
  useEffect(() => {
    if (!card) return;
    setTask((t) => (card.tasks.includes(t) ? t : card.tasks[0]));
    const init: Record<string, number> = {};
    for (const [k, spec] of Object.entries(card.param_schema)) init[k] = spec.default;
    setHyper(init);
  }, [card?.key]);

  // 任意配置变化 → 预览将要跑的代码
  useEffect(() => {
    if (!card || !task || features.length === 0) return;
    const t = setTimeout(() => {
      fetch("/api/training/codegen", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ model: card.key, task, feature_cols: features, label_col: ds?.label_col ?? "label", hyperparams: hyper }),
      })
        .then((r) => r.json())
        .then((j) => setCode(j.code ?? j.detail ?? ""))
        .catch(() => setCode("// 代码预览失败"));
    }, 150);
    return () => clearTimeout(t);
  }, [card?.key, task, features, hyper, ds?.label_col]);

  const refreshJobs = useCallback(() => {
    fetch("/api/training/jobs")
      .then((r) => r.json())
      .then(setJobs)
      .catch(() => {});
  }, []);

  // 有 running/queued 时轮询
  useEffect(() => {
    if (!jobs.some((j) => j.status === "running" || j.status === "queued")) return;
    const id = setInterval(refreshJobs, 2500);
    return () => clearInterval(id);
  }, [jobs, refreshJobs]);

  const toggleFeature = (f: string) =>
    setFeatures((cur) => (cur.includes(f) ? cur.filter((x) => x !== f) : [...cur, f]));

  const submit = async () => {
    if (!card || !ds) return;
    setSubmitting(true);
    setErr("");
    try {
      const r = await fetch("/api/training/jobs", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: `${card.display_name} · ${task}`,
          model: card.key,
          task,
          dataset_id: ds.dataset_id,
          feature_cols: features,
          label_col: ds.label_col,
          asset_class: ds.asset_class,
          hyperparams: hyper,
          // OOS 无泄露：选了「前 N% 训练」就下发 train_fraction，后端据此只用前段训练、
          // 回测自动取互补后段做严格样本外（service.py/_slice_front_dates + main.py strict_oos）。
          // =0（全程）时 JSON.stringify 自动省略该字段，后端按全样本训练。否则 UI「无泄露」承诺无法兑现。
          train_fraction: trainFraction > 0 ? trainFraction : undefined,
        }),
      });
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        throw new Error(j.detail ?? `提交失败 (${r.status})`);
      }
      setTimeout(refreshJobs, 300);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <div className="cc-page-header">
        <div>
          <p className="eyebrow">模型中心</p>
          <h1 className="cc-page-title">{"// 训练台"}</h1>
          <div className="cc-soft">
            本质是跑代码：选数据/模型/字段 → 预览将要运行的脚本 → 开训。ML 进程内 · DL 全功率子进程(GPU 自动 cuda→mps→cpu)
          </div>
        </div>
        <div className="cc-page-actions">
          <button
            type="button"
            className="cc-btn cc-btn--accent"
            onClick={submit}
            disabled={submitting || !card?.available || features.length === 0}
            title={card && !card.available ? "该模型依赖未安装(如 torch)" : ""}
          >
            {submitting ? "提交中…" : "▶ 开始训练"}
          </button>
        </div>
      </div>

      {err && (
        <div className="cc-card" style={{ marginBottom: 12, padding: 10, borderLeft: "3px solid var(--cc-danger)", background: "var(--cc-danger-soft)" }}>
          <span className="cc-mono" style={{ fontSize: 12 }}>{err}</span>
        </div>
      )}

      <div className="cc-row" style={{ alignItems: "stretch", gap: 12 }}>
        {/* 左：配置 */}
        <aside className="cc-card" style={{ width: 270, padding: 14, flexShrink: 0 }}>
          <Field label="数据集">
            <select className="cc-input" value={dataset} onChange={(e) => { setDataset(e.target.value); const d = datasets.find((x) => x.dataset_id === e.target.value); if (d) setFeatures(d.feature_cols); }}>
              {datasets.map((d) => (
                <option key={d.dataset_id} value={d.dataset_id}>{d.label} ({d.rows} 行)</option>
              ))}
            </select>
          </Field>

          <Field label="模型">
            <select className="cc-input" value={modelKey} onChange={(e) => setModelKey(e.target.value)}>
              <optgroup label="ML">
                {models.filter((m) => m.family === "ml").map((m) => (
                  <option key={m.key} value={m.key}>{m.display_name}</option>
                ))}
              </optgroup>
              <optgroup label="DL（需 torch）">
                {models.filter((m) => m.family === "dl").map((m) => (
                  <option key={m.key} value={m.key} disabled={!m.available}>
                    {m.display_name}{m.available ? "" : " · 未装"}
                  </option>
                ))}
              </optgroup>
            </select>
          </Field>

          <Field label="任务">
            <select className="cc-input" value={task} onChange={(e) => setTask(e.target.value)}>
              {card?.tasks.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>

          <Field label={`特征列（${features.length} 选）`}>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {ds?.feature_cols.map((f) => (
                <label key={f} className="cc-mono" style={{ fontSize: 12, display: "flex", gap: 6, alignItems: "center", cursor: "pointer" }}>
                  <input type="checkbox" checked={features.includes(f)} onChange={() => toggleFeature(f)} />
                  {f}
                </label>
              ))}
            </div>
          </Field>

          <Field label="训练窗口（OOS）">
            <select
              className="cc-input"
              value={trainFraction}
              onChange={(e) => setTrainFraction(Number(e.target.value))}
              title="只用前 N% 交易日训练，留后段做严格无泄露的样本外回测(walk-forward)"
            >
              <option value={0}>全程训练（回测后段=近似OOS）</option>
              <option value={0.7}>前70%训练 · 留后30%严格OOS</option>
              <option value={0.8}>前80%训练 · 留后20%严格OOS</option>
              <option value={0.5}>前50%训练 · 留后50%严格OOS</option>
            </select>
            {trainFraction > 0 && (
              <div className="cc-dim" style={{ fontSize: 11, marginTop: 2 }}>
                训完点「回测」即自动跑后 {Math.round((1 - trainFraction) * 100)}% 样本外（无泄露）
              </div>
            )}
          </Field>

          {card && Object.keys(card.param_schema).length > 0 && (
            <Field label="超参">
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {Object.entries(card.param_schema).map(([k, spec]) => (
                  <label key={k} style={{ fontSize: 12 }} title={spec.help}>
                    <span className="cc-soft" style={{ display: "block", marginBottom: 2 }}>{k}</span>
                    <input
                      className="cc-input"
                      type="number"
                      value={hyper[k] ?? spec.default}
                      min={spec.min}
                      max={spec.max}
                      step={spec.type === "float" ? "any" : 1}
                      onChange={(e) => {
                        const raw = e.target.value;
                        // 清空输入框时回落到默认值，而非 Number("")===0（0 常越过 min，会训出退化模型）
                        const v = raw === "" ? spec.default : Number(raw);
                        setHyper((h) => ({ ...h, [k]: Number.isNaN(v) ? spec.default : v }));
                      }}
                    />
                  </label>
                ))}
              </div>
            </Field>
          )}
        </aside>

        {/* 中：将要跑的代码 */}
        <section className="cc-card" style={{ flex: 1, padding: 14, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <div className="cc-section-title" style={{ marginTop: 0 }}>将要运行的训练代码</div>
          <pre className="cc-mono" style={{ flex: 1, overflow: "auto", fontSize: 12, lineHeight: 1.5, background: "var(--cc-bg-input)", border: "1px solid var(--cc-border)", borderRadius: 6, padding: 12, margin: 0, whiteSpace: "pre", minHeight: 320 }}>
            {code || "// 选好配置后这里显示将要运行的脚本"}
          </pre>
          <div className="cc-soft" style={{ fontSize: 11, marginTop: 8 }}>
            {card?.family === "dl"
              ? "DL：隔离全功率子进程跑 torch，自动选 GPU(cuda/mps)/CPU，训练过程接 TensorBoard。"
              : "ML：进程内直接训练，不加载 torch。"}
            {" "}最后 emit 结果回训练台并登记实验血缘(M12)。
          </div>
        </section>

        {/* 右：模型卡片 */}
        <aside className="cc-card" style={{ width: 300, padding: 14, flexShrink: 0 }}>
          {card ? (
            <>
              <div className="cc-row" style={{ justifyContent: "space-between", alignItems: "center" }}>
                <div className="cc-section-title" style={{ margin: 0 }}>{card.display_name}</div>
                <span className="cc-tag" style={{ fontSize: 10, padding: "1px 6px", borderRadius: 4, background: card.family === "dl" ? "var(--cc-accent-soft)" : "var(--cc-info-soft)", color: card.family === "dl" ? "var(--cc-accent)" : "var(--cc-info)" }}>
                  {card.family.toUpperCase()}
                </span>
              </div>
              <div className="cc-soft" style={{ fontSize: 12, margin: "6px 0 10px" }}>{card.description}</div>
              <div className="cc-soft" style={{ fontSize: 11, marginBottom: 10 }}>
                算力：{card.needs_dl ? "GPU 推荐" : "CPU 即可"} · {card.tensorboard ? "TensorBoard ✓" : "评价图"} · {card.available ? "可用" : "依赖未装"}
              </div>
              <CardList title="✅ 优点" items={card.pros} color="var(--cc-success)" />
              <CardList title="⚠️ 缺点" items={card.cons} color="var(--cc-warning)" />
              {card.tuning_tip && (
                <>
                  <div className="cc-section-title" style={{ fontSize: 12 }}>调参指南</div>
                  <div className="cc-soft" style={{ fontSize: 12, lineHeight: 1.6 }}>{card.tuning_tip}</div>
                </>
              )}
              <div className="cc-soft" style={{ fontSize: 10, marginTop: 10, opacity: 0.7 }}>
                完整卡片(L3/L4 调参表·保存本体)即将以词典式 markdown 接入
              </div>
            </>
          ) : (
            <div className="cc-dim">选择模型查看卡片</div>
          )}
        </aside>
      </div>

      {/* 底部：训练任务 */}
      <div className="cc-card" style={{ marginTop: 12, padding: 14 }}>
        <div className="cc-section-title" style={{ marginTop: 0 }}>训练任务<span className="cc-soft" style={{ fontSize: 11, fontWeight: 400 }}> · 点击成功的任务看评价图</span></div>
        {jobs.length === 0 ? (
          <div className="cc-dim" style={{ fontSize: 12 }}>还没有训练任务</div>
        ) : (
          <table className="cc-table" style={{ width: "100%", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", color: "var(--cc-text-dim)" }}>
                <th style={{ padding: "4px 8px" }}>任务</th>
                <th style={{ padding: "4px 8px" }}>模型</th>
                <th style={{ padding: "4px 8px" }}>状态</th>
                <th style={{ padding: "4px 8px" }}>指标</th>
                <th style={{ padding: "4px 8px" }}>耗时</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((j) => (
                <tr
                  key={j.job_id}
                  onClick={() => j.status === "succeeded" && openEval(j)}
                  style={{
                    borderTop: "1px solid var(--cc-border-soft)",
                    cursor: j.status === "succeeded" ? "pointer" : "default",
                    background: selectedJob === j.job_id ? "var(--cc-bg-hover)" : undefined,
                  }}
                >
                  <td style={{ padding: "5px 8px" }}>{j.name}{j.status === "succeeded" ? " 📊" : ""}</td>
                  <td style={{ padding: "5px 8px" }} className="cc-mono">{j.model}<span className="cc-soft"> · {j.family}</span></td>
                  <td style={{ padding: "5px 8px", color: STATUS_COLOR[j.status] }}>
                    ● {j.status}{j.status === "failed" && j.error ? <span className="cc-soft" title={j.error}> ⓘ</span> : null}
                  </td>
                  <td style={{ padding: "5px 8px" }} className="cc-mono">
                    {Object.entries(j.metrics ?? {}).slice(0, 3).map(([k, v]) => `${k}=${Number(v).toFixed(3)}`).join("  ") || "—"}
                  </td>
                  <td style={{ padding: "5px 8px" }} className="cc-soft">{j.elapsed_seconds != null ? `${j.elapsed_seconds}s` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 评价图面板（选中成功任务后展开） */}
      {selectedJob && (
        <div className="cc-card" style={{ marginTop: 12, padding: 14 }}>
          <div className="cc-row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
            <div className="cc-section-title" style={{ margin: 0 }}>
              评价图<span className="cc-soft" style={{ fontSize: 11, fontWeight: 400 }}> · {selectedModel}</span>
            </div>
            <div className="cc-row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <select
                className="cc-input cc-input--sm"
                value={btDataset}
                onChange={(e) => setBtDataset(e.target.value)}
                title="选另一个数据集 = 跨数据集样本外(OOS)；留空 = 训练数据集(in-sample)"
                style={{ fontSize: 11 }}
              >
                <option value="">回测集：训练集(in-sample)</option>
                {datasets.map((d) => (
                  <option key={d.dataset_id} value={d.dataset_id}>回测集：{d.label}</option>
                ))}
              </select>
              <label className="cc-soft" style={{ fontSize: 11 }} title="只回测末尾这一比例的交易日(同数据集的时间后段样本外)；0=全段">
                OOS后段
                <select className="cc-input cc-input--sm" value={btOosFrac} onChange={(e) => setBtOosFrac(Number(e.target.value))} style={{ fontSize: 11, marginLeft: 4 }}>
                  <option value={0}>全段</option>
                  <option value={0.3}>后30%</option>
                  <option value={0.2}>后20%</option>
                  <option value={0.5}>后50%</option>
                </select>
              </label>
              <button type="button" className="cc-btn cc-btn--accent cc-btn--sm" onClick={runBacktest} disabled={btBusy} title="用此模型回测；换数据集或选OOS后段=样本外">
                {btBusy ? "回测中…" : "▶ 回测"}
              </button>
              {selectedIsDl && (
                <button type="button" className="cc-btn cc-btn--ghost cc-btn--sm" onClick={startTensorBoard} disabled={tbBusy}>
                  {tbBusy ? "启动中…" : "↗ TensorBoard"}
                </button>
              )}
              <button type="button" className="cc-btn cc-btn--ghost cc-btn--sm" onClick={() => setSelectedJob(null)}>关闭</button>
            </div>
          </div>
          {btResult && (
            <div className="cc-card" style={{ marginBottom: 10, padding: 10, background: "var(--cc-bg-soft)" }}>
              <div className="cc-soft" style={{ fontSize: 11, marginBottom: 4, display: "flex", gap: 6, alignItems: "center" }}>
                回测结果（top-5 等权 · shift1 防前视）
                {btMeta && (
                  <span
                    style={{
                      fontSize: 10, padding: "1px 6px", borderRadius: 4,
                      background: btMeta.is_oos ? "var(--cc-success-soft)" : "var(--cc-warning-soft)",
                      color: btMeta.is_oos ? "var(--cc-success)" : "var(--cc-warning)",
                    }}
                    title={btMeta.is_oos ? "样本外:模型没在这段数据上训练过" : "样本内:在训练数据上回测,指标偏乐观,仅供 sanity check"}
                  >
                    {btMeta.is_oos
                      ? btMeta.is_cross_dataset
                        ? "OOS · 跨数据集"
                        : btMeta.strict_oos
                          ? "OOS · 严格无泄露"
                          : "OOS · 时间后段(近似)"
                      : "in-sample(样本内)"}
                  </span>
                )}
                {btMeta && <span style={{ fontSize: 10 }}>· {btMeta.dataset_id} · {btMeta.n_days}天</span>}
              </div>
              <div className="cc-mono" style={{ fontSize: 12 }}>
                {Object.entries(btResult).map(([k, v]) => `${k}=${Number(v).toFixed(4)}`).join("   ") || "（无指标）"}
              </div>
            </div>
          )}
          {evalLoading ? (
            <div className="cc-dim" style={{ fontSize: 12 }}>加载评价图…</div>
          ) : evalError ? (
            <div style={{ fontSize: 12, color: "var(--cc-danger)" }}>{evalError}</div>
          ) : (
            <>
              {/* R23 conformal 校准区间（仅回归 OOS；null→不渲染，不假绿灯）。 */}
              {conformal && (
                <div style={{ marginBottom: 10 }}>
                  <ConformalIntervalCard interval={conformal} />
                </div>
              )}
              {/* R4 CPCV 路径稳健性（opt-in compute_cpcv；null→不渲染，不假绿灯）。 */}
              {cpcv && (
                <div style={{ marginBottom: 10 }}>
                  <CpcvRobustnessCard dist={cpcv} />
                </div>
              )}
              <EvalCharts charts={evalCharts} />
            </>
          )}
        </div>
      )}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="cc-soft" style={{ fontSize: 11, marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

function CardList({ title, items, color }: { title: string; items: string[]; color: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 3, color }}>{title}</div>
      <ul style={{ margin: 0, paddingLeft: 16 }}>
        {items.map((x, i) => (
          <li key={i} className="cc-soft" style={{ fontSize: 12, lineHeight: 1.5 }}>{x}</li>
        ))}
      </ul>
    </div>
  );
}

export default TrainingBenchPage;
