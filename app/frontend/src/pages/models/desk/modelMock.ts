/**
 * Model台 P0 mock 数据 + 视图模型类型（DC Model台.dc.html → React）。
 * 全为 mock：凡消费区块挂 <MockBadge/>（诚实，不假绿灯）。
 * 治理 load-bearing 字段（晋级门 approver/reason/risk_restated、Purged-CV/embargo、
 * DL 子进程隔离）来自设计稿，与后端 422/INV-5/M6 对齐。
 */

import type { NodeView, EdgeView } from "../../../components/desk";

export type Family = "ml" | "dl" | "code";
export type JobStatus = "queued" | "running" | "succeeded" | "failed";
export type Stage = "dev" | "staging" | "production" | "archived";

/** family → desk tone（ml 绿 / dl 蓝 / code 黄）。 */
export const FAMILY_TONE: Record<Family, "success" | "info" | "warning"> = {
  ml: "success",
  dl: "info",
  code: "warning",
};

export const FAMILY_LABEL: Record<Family, string> = {
  ml: "ml",
  dl: "dl",
  code: "code",
};

/** stage → desk tone（dev 灰 / staging 黄 / production 绿 / archived 暗）。 */
export const STAGE_TONE: Record<Stage, "neutral" | "warning" | "success" | "ghost"> = {
  dev: "neutral",
  staging: "warning",
  production: "success",
  archived: "ghost",
};

export const STAGE_LABEL: Record<Stage, string> = {
  dev: "dev",
  staging: "staging",
  production: "production",
  archived: "archived",
};

// ---------------------------------------------------------------------------
// 作业台（jobs）
// ---------------------------------------------------------------------------

export interface IoGroup {
  group: string;
  type: string;
  fields: string;
}

export interface IoSpec {
  inCount: number;
  outCount: number;
  inGroups: IoGroup[];
  outGroups: IoGroup[];
  inSrc: string;
  inPre: string;
  outNote: string;
}

export interface JobDetail {
  why: string;
  data: string;
  window: string;
  label: string;
  design: string;
  arch: string;
  hparams: string;
  sections: [string, string][];
}

export interface TrainJob {
  id: string;
  name: string;
  family: Family;
  arch: string;
  task: string;
  status: JobStatus;
  elapsed: string;
  ndcg?: string;
  detail: JobDetail;
}

/** IO 数据规格单一来源（dashboard / registry drill-in / build io 节点三处共用）。 */
export const IO_SPEC: IoSpec = {
  inCount: 28,
  outCount: 3,
  inSrc: "equity_cn 5412 标的 · 日频量价+财务 · QUALIFIED 因子集 fs_core3",
  inPre: "横截面 zscore + winsor(1%/99%) + 行业中性化（防数据泄漏：仅用 t 时点可见信息）",
  outNote: "截面排序分，越大越靠前；asof_date 周五对齐。",
  inGroups: [
    { group: "动量 / 反转 · 5", type: "f32", fields: "mom_20d · mom_60d · mom_120d · reversal_5d · reversal_10d" },
    { group: "价值 · 4", type: "f32", fields: "ep_ttm · bp · sp_ttm · div_yield" },
    { group: "质量 · 5", type: "f32", fields: "roe_ttm · gross_margin · asset_turn · debt_ratio · accrual" },
    { group: "预期 / 情绪 · 5", type: "f32", fields: "sue · analyst_rev_1m · est_eps_chg · north_flow_z · holder_chg" },
    { group: "流动性 / 风险 · 6", type: "f32", fields: "turnover_z · amihud · vol_20d · vol_60d · beta_60d · ivol" },
    { group: "行业 / 市值 · 3", type: "f32/int", fields: "log_mktcap · industry_id(29) · float_ratio" },
  ],
  outGroups: [
    { group: "主输出 · 1", type: "f32 [N,1]", fields: "score — 截面排序原始分（越大越靠前）" },
    { group: "对齐键 · 2", type: "date / str", fields: "asof_date — 截面日期（周五对齐） · ticker — 标的代码" },
  ],
};

const DESIGN_SECTIONS: [string, string][] = [
  ["正则化", "dropout + weight_decay 抑制过拟合；早停监控 val 指标。"],
  ["参数初始化", "线性层 Kaiming/Xavier，归一化层 γ=1/β=0，注意力投影小方差初始化。"],
  ["训练策略", "AdamW + cosine warmup；梯度裁剪 1.0；混合精度（AMP）省显存。"],
  ["防数据泄漏", "Purged k-fold + embargo，标签前视窗口与训练集隔离，杜绝穿越。"],
  ["风险与权衡", "容量越大越易过拟合小样本；与基线对比确认增量真实，未达标则回退。"],
];

export const JOBS: TrainJob[] = [
  {
    id: "trn-9a2f",
    name: "lgbm_rank_6f",
    family: "ml",
    arch: "LightGBM",
    task: "lambdarank",
    status: "succeeded",
    elapsed: "8.2s",
    ndcg: "0.231",
    detail: {
      why: "为策略台 fs_core3 做排序基线——LambdaRank 直接优化截面 NDCG。先有一个证据更清楚、成本更低、可解释的基准，再谈深度模型是否带来增量。",
      data: "equity_cn 5412 标的 · 日频量价+财务+SUE · 28 个 QUALIFIED 因子",
      window: "训练 2019-01 ~ 2023-12 · OOS 留 2024 全年",
      label: "fwd_ret_5（5 日前向收益）截面排序",
      design: "梯度提升树对因子做非线性交互，lambdarank 目标以成对排序逼近截面 NDCG。",
      arch: "LightGBM · 800 trees · num_leaves 63 · max_depth 6 · feature_fraction 0.8",
      hparams: "lr 0.03 · early_stopping 50 · purged_kfold(6) embargo 1% · seed 7",
      sections: DESIGN_SECTIONS,
    },
  },
  {
    id: "trn-7c41",
    name: "tcn_alpha_v1",
    family: "dl",
    arch: "TCN · 6 blocks",
    task: "regression",
    status: "running",
    elapsed: "live",
    detail: {
      why: "lgbm 在 2022 单边市动量失效、尾部回撤大。想用 TCN 捕捉非线性的跨期时序依赖，补动量衰减那一段，看能否压低尾部。",
      data: "equity_cn 5412 标的 · 日频 · 28 因子序列（回看 120 日窗）",
      window: "训练 2019-01 ~ 2023-12 · OOS 留 2024",
      label: "fwd_ret_5（5 日前向收益）",
      design: "每只股票的因子时间序列做膨胀因果卷积，捕捉跨期动量衰减；末层接 ranking 头做截面打分。",
      arch: "TCN · 6 dilated blocks · kernel 3 · dilations [1,2,4,8,16,32] · channels [64,64,128,128,256,256] · dropout 0.1 · 1.8M 参数",
      hparams: "AdamW lr 3e-4 cosine·warmup 5 · batch 256 · 60 epochs · weight_decay 1e-2 · purged_kfold(5) embargo 1% · grad_clip 1.0",
      sections: DESIGN_SECTIONS,
    },
  },
  {
    id: "trn-5d18",
    name: "xsec_transformer",
    family: "dl",
    arch: "Transformer",
    task: "ranking",
    status: "queued",
    elapsed: "—",
    detail: {
      why: "把每日截面当 set，用注意力建模个股相互作用（置换不变）。排队中。",
      data: "equity_cn 5412 标的 · 日频 · 28 因子截面 set",
      window: "训练 2019-01 ~ 2023-12 · OOS 留 2024",
      label: "fwd_ret_5 截面排序",
      design: "Set Transformer 截面注意力，置换不变聚合后接排序头。",
      arch: "Set Transformer · 4 ISAB · 8 heads · d_model 256",
      hparams: "AdamW lr 2e-4 · batch cross_section · purged_kfold(5) embargo 1%",
      sections: DESIGN_SECTIONS,
    },
  },
  {
    id: "trn-3b09",
    name: "gbdt_baseline",
    family: "ml",
    arch: "GBDT",
    task: "classification",
    status: "succeeded",
    elapsed: "5.1s",
    ndcg: "0.198",
    detail: {
      why: "涨跌二分类对照组——衡量排序模型相对朴素分类的真增量。",
      data: "equity_cn 5412 标的 · 日频 · 28 因子",
      window: "训练 2019-01 ~ 2023-12 · OOS 留 2024",
      label: "涨跌（fwd_ret_5 > 0）",
      design: "GBDT 二分类作对照，确认排序目标带来的增量是否真实。",
      arch: "GBDT · 400 trees · max_depth 5",
      hparams: "lr 0.05 · early_stopping 40 · purged_kfold(6) embargo 1%",
      sections: DESIGN_SECTIONS,
    },
  },
];

export const HERO_JOB_ID = "trn-7c41";
export const EPOCH_TOTAL = 60;

/** 实时曲线 mock（hero job trn-7c41 的 train/val loss + ndcg，按 epoch 取值）。 */
export interface CurvePoint {
  trainLoss: number;
  valLoss: number;
  ndcg: number;
}

export function curveAt(epoch: number): CurvePoint {
  const e = Math.max(0, Math.min(EPOCH_TOTAL, epoch));
  const t = e / EPOCH_TOTAL;
  return {
    trainLoss: 0.92 * Math.exp(-2.1 * t) + 0.18,
    valLoss: 0.95 * Math.exp(-1.9 * t) + 0.22,
    ndcg: 0.226 * (1 - Math.exp(-2.4 * t)),
  };
}

/** 算力面板 mock（GPU/VRAM/throughput；torch 子进程标注，对齐 M6）。 */
export interface ComputeStat {
  gpuUtil: number;
  vramUsedGb: number;
  vramTotalGb: number;
  throughput: string;
  device: string;
  subprocess: string;
}

export const COMPUTE: ComputeStat = {
  gpuUtil: 87,
  vramUsedGb: 41,
  vramTotalGb: 80,
  throughput: "12.4k samples/s",
  device: "cuda:0 · A100 80G",
  subprocess: "子进程 ✓（DL 走全功率子进程跑 torch，主进程不碰 torch — M6）",
};

/** CV folds mock（Purged k-fold · embargo 1% · 防标签穿越）。 */
export interface CvFold {
  label: string;
  status: "done" | "running" | "pending";
  ndcg: string;
}

export const CV_FOLDS: CvFold[] = [
  { label: "fold 1", status: "done", ndcg: "0.229" },
  { label: "fold 2", status: "done", ndcg: "0.221" },
  { label: "fold 3", status: "running", ndcg: "—" },
  { label: "fold 4", status: "pending", ndcg: "—" },
  { label: "fold 5", status: "pending", ndcg: "—" },
];

/** 训练诊断 mock 对话（诊断 + 追问 chip）。 */
export const ASSISTANT_DIAGNOSIS =
  "tcn_alpha_v1 训练中：val loss 仍在降、与 train 间隙稳定，未见过拟合迹象。NDCG 逼近收敛。";

export const ASSISTANT_CHIPS: string[] = [
  "保持；过拟合迹象出现再 early-stop",
  "收敛后接 walk-forward(8 窗) 再发布",
  "想更快可试 lr warmup + cosine",
];

// ---------------------------------------------------------------------------
// 模型库注册表（registry）
// ---------------------------------------------------------------------------

export interface RegistryModel {
  id: string;
  version: number;
  family: Family;
  task: string;
  stage: Stage | null;
  ndcg: string;
  wf: string;
  lineage: string;
  gist: string;
  archGist: string;
  ioGist: string;
  trained: string;
  /** 是否可发起晋级（dev/staging 可，production/archived/未注册 不可）。 */
  canPromote: boolean;
  note: string;
  /** 源训练 job_id（DRILL-IN 拉真 walk-forward 用；缺=只能回退 mock 逐窗）。 */
  jobId?: string;
}

export const REGISTRY: RegistryModel[] = [
  {
    id: "lgbm_rank_6f",
    version: 2,
    family: "ml",
    task: "lambdarank",
    stage: "staging",
    ndcg: "0.231 ± 0.016",
    wf: "8/8 窗口正",
    lineage: "trn-9a2f · 因子集 fs_core3",
    gist: "排序基线 · 直接优化截面 NDCG",
    archGist: "LightGBM · 800 trees · depth 6",
    ioGist: "入 因子矩阵 [N,28] f32 → 出 排序分 [N,1]",
    trained: "2024-06-18",
    canPromote: true,
    note: "staging 实测中",
    jobId: "trn-9a2f",
  },
  {
    id: "gbdt_baseline",
    version: 1,
    family: "ml",
    task: "classification",
    stage: "dev",
    ndcg: "0.198 ± 0.021",
    wf: "6/8 窗口正",
    lineage: "trn-3b09",
    gist: "涨跌二分类对照组 · 衡量增量",
    archGist: "GBDT · 400 trees · depth 5",
    ioGist: "入 因子矩阵 [N,28] f32 → 出 涨跌概率 [N,1]",
    trained: "2024-06-15",
    canPromote: true,
    note: "对照组",
    jobId: "trn-3b09",
  },
  {
    id: "tcn_alpha_v1",
    version: 1,
    family: "dl",
    task: "regression",
    stage: null,
    ndcg: "训练中…",
    wf: "待跑",
    lineage: "trn-7c41 · TCN",
    gist: "补动量衰减 · 抓跨期时序依赖",
    archGist: "TCN · 6 blocks · 1.8M 参",
    ioGist: "入 时序张量 [N,120,F] f32 → 出 排序分 [N,1]",
    trained: "训练中",
    canPromote: false,
    note: "未注册",
  },
];

/** 晋级门 check（icon + tone + 文案）。 */
export interface GateCheck {
  icon: string;
  tone: "success" | "warning" | "danger";
  text: string;
}

export interface PromoteGate {
  modelId: string;
  from: Stage;
  to: Stage;
  checks: GateCheck[];
  /** to 是 staging/production 时为真 → 须审批门、不可裸翻。 */
  approvalRequired: boolean;
}

/** 晋级提案（dev→staging→production→archived，staging/production 须审批门）。 */
export function buildGate(modelId: string, from: Stage, to: Stage): PromoteGate {
  const toProd = to === "production";
  return {
    modelId,
    from,
    to,
    approvalRequired: to === "staging" || to === "production",
    checks: [
      { icon: "✓", tone: "success", text: "walk-forward / Purged-CV 通过" },
      { icon: "✓", tone: "success", text: "OOS 切片未被探索期触碰（embargo 1%）" },
      toProd
        ? { icon: "○", tone: "warning", text: "缺：staging 实测 ≥ 2 周 + 验证背书（INV-5）" }
        : { icon: "✓", tone: "success", text: "lineage 完整、可追溯（append-only）" },
    ],
  };
}

/** 晋级审批表单字段（对齐后端 422：approver≠creator / reason / risk_restated）。 */
export interface ApproveForm {
  approver: string;
  reason: string;
  riskRestated: boolean;
}

/**
 * 晋级审批前端校验（对齐后端 ApproverEqualsCreator / EmptyReason / risk_restated）。
 * 返回阻止提交的原因数组，空数组表示通过。creator 不可自批（self-approve）。
 */
export function validateApprove(form: ApproveForm, creator: string): string[] {
  const blockers: string[] = [];
  const approver = form.approver.trim();
  if (approver.length === 0) {
    blockers.push("approver 必填（须人工审批，agent 永不自动）");
  } else if (approver === creator.trim()) {
    blockers.push("approver 不可等于 creator（禁止自批 / self-approve）");
  }
  if (form.reason.trim().length === 0) {
    blockers.push("reason 必填（审批理由不可空）");
  }
  if (!form.riskRestated) {
    blockers.push("须勾选 risk_restated（复述风险后方可晋级）");
  }
  return blockers;
}

// ---------------------------------------------------------------------------
// DRILL-IN 模型详情（walk-forward 逐窗 + IO）
// ---------------------------------------------------------------------------

export interface WfWindow {
  w: string;
  seg: string;
  oosExcess: string;
  ndcg: string;
}

export const WALK_FORWARD: Record<string, WfWindow[]> = {
  lgbm_rank_6f: [
    { w: "W1", seg: "2019–20 → 21H1", oosExcess: "+4.2%", ndcg: "0.241" },
    { w: "W2", seg: "2019–21H1 → 21H2", oosExcess: "+3.1%", ndcg: "0.228" },
    { w: "W3", seg: "2019–21 → 22H1", oosExcess: "+1.8%", ndcg: "0.207" },
    { w: "W4", seg: "2019–22H1 → 22H2", oosExcess: "+0.9%", ndcg: "0.196" },
    { w: "W5", seg: "2019–22 → 23H1", oosExcess: "+3.6%", ndcg: "0.233" },
    { w: "W6", seg: "2019–23H1 → 23H2", oosExcess: "+2.4%", ndcg: "0.219" },
    { w: "W7", seg: "2019–23 → 24H1", oosExcess: "+4.0%", ndcg: "0.238" },
    { w: "W8", seg: "2019–24H1 → 24H2", oosExcess: "+2.7%", ndcg: "0.224" },
  ],
  gbdt_baseline: [
    { w: "W1", seg: "2019–20 → 21H1", oosExcess: "+2.1%", ndcg: "0.205" },
    { w: "W2", seg: "2019–21H1 → 21H2", oosExcess: "+1.4%", ndcg: "0.198" },
    { w: "W3", seg: "2019–21 → 22H1", oosExcess: "-0.6%", ndcg: "0.171" },
    { w: "W4", seg: "2019–22H1 → 22H2", oosExcess: "-1.2%", ndcg: "0.166" },
    { w: "W5", seg: "2019–22 → 23H1", oosExcess: "+1.9%", ndcg: "0.202" },
    { w: "W6", seg: "2019–23H1 → 23H2", oosExcess: "+1.1%", ndcg: "0.193" },
    { w: "W7", seg: "2019–23 → 24H1", oosExcess: "+2.3%", ndcg: "0.208" },
    { w: "W8", seg: "2019–24H1 → 24H2", oosExcess: "+0.8%", ndcg: "0.189" },
  ],
  tcn_alpha_v1: [],
};

// ---------------------------------------------------------------------------
// 构建台（build · GraphCanvas 视图模型）
// ---------------------------------------------------------------------------

/** 构建台初始节点（DC bdNodes → NodeView；input→data / linear,gelu→model / head,output→signal/eval）。 */
export const BUILD_NODES: NodeView[] = [
  {
    id: "n1",
    cat: "data",
    title: "Input",
    x: 150,
    y: 24,
    w: 158,
    state: "valid",
    lines: ["features: 28", "x : [N, 28]"],
    ins: [],
    outs: [{ id: "out", name: "x" }],
  },
  {
    id: "n2",
    cat: "model",
    title: "Linear",
    x: 150,
    y: 124,
    w: 158,
    state: "valid",
    lines: ["out: 256", "y = xW + b → [N,256]"],
    ins: [{ id: "in", name: "x" }],
    outs: [{ id: "out", name: "y" }],
  },
  {
    id: "n3",
    cat: "model",
    title: "GELU",
    x: 150,
    y: 224,
    w: 158,
    state: "valid",
    lines: ["激活 · [N,256]"],
    ins: [{ id: "in", name: "x" }],
    outs: [{ id: "out", name: "y" }],
  },
  {
    id: "n4",
    cat: "model",
    title: "Linear",
    x: 150,
    y: 320,
    w: 158,
    state: "valid",
    lines: ["out: 256", "→ [N,256]"],
    ins: [{ id: "in", name: "x" }],
    outs: [{ id: "out", name: "y" }],
  },
  {
    id: "n5",
    cat: "signal",
    title: "Head",
    x: 150,
    y: 420,
    w: 158,
    state: "valid",
    lines: ["out: 1", "score = hW+b → [N,1]"],
    ins: [{ id: "in", name: "x" }],
    outs: [{ id: "out", name: "score" }],
  },
  {
    id: "n6",
    cat: "eval",
    title: "Output",
    x: 150,
    y: 520,
    w: 158,
    state: "valid",
    lines: ["score → 截面排序"],
    ins: [{ id: "in", name: "score" }],
    outs: [],
  },
];

export const BUILD_EDGES: EdgeView[] = [
  { id: "e1", from: { node: "n1", port: "out" }, to: { node: "n2", port: "in" }, compat: "ok" },
  { id: "e2", from: { node: "n2", port: "out" }, to: { node: "n3", port: "in" }, compat: "ok" },
  { id: "e3", from: { node: "n3", port: "out" }, to: { node: "n4", port: "in" }, compat: "ok" },
  { id: "e4", from: { node: "n4", port: "out" }, to: { node: "n5", port: "in" }, compat: "ok" },
  { id: "e5", from: { node: "n5", port: "out" }, to: { node: "n6", port: "in" }, compat: "ok" },
];

/** 组件库 palette 分组（DC：我的模块紫 / 机制青 / 原子 / 训练组件绿）。 */
export interface PaletteItem {
  type: string;
  label: string;
}

export interface PaletteGroup {
  title: string;
  tone: "ghost" | "info" | "neutral" | "success";
  items: PaletteItem[];
}

export const PALETTE: PaletteGroup[] = [
  {
    title: "机制模块（开箱即用 · 青）",
    tone: "info",
    items: [
      { type: "tcn", label: "TCN block" },
      { type: "xsec_attn", label: "截面注意力" },
      { type: "factor_vae", label: "FactorVAE" },
    ],
  },
  {
    title: "原子（io / 层级 / 张量 / 激活 / 输出）",
    tone: "neutral",
    items: [
      { type: "input", label: "Input" },
      { type: "linear", label: "Linear" },
      { type: "conv1d", label: "Conv1d" },
      { type: "gelu", label: "GELU" },
      { type: "dropout", label: "Dropout" },
      { type: "head", label: "Head" },
      { type: "output", label: "Output" },
    ],
  },
  {
    title: "训练 · 优化器 / 损失 / 调度（绿 · 数学定义即注册）",
    tone: "success",
    items: [
      { type: "adamw", label: "AdamW" },
      { type: "lambdarank", label: "LambdaRank" },
      { type: "cosine_warmup", label: "cosine_warmup" },
    ],
  },
];

/** 构建台代码面板 mock（model.py，标注 DL 走子进程，主进程不碰 torch）。 */
export const BUILD_CODE: string[] = [
  "# 由画布结构推导 · DL 编译走全功率子进程跑 torch，主进程不碰 torch（M6）",
  "import torch.nn as nn",
  "",
  "class GraphModel(nn.Module):",
  "    def __init__(self):",
  "        super().__init__()",
  "        self.l1 = nn.Linear(28, 256)",
  "        self.act = nn.GELU()",
  "        self.l2 = nn.Linear(256, 256)",
  "        self.head = nn.Linear(256, 1)",
  "",
  "    def forward(self, x):  # x: [N, 28]",
  "        h = self.act(self.l1(x))",
  "        h = self.l2(h)",
  "        return self.head(h)  # score: [N, 1]",
];

/** 构建台 agent mock 对话。 */
export const BUILD_CHAT_SEED = [
  { role: "user" as const, text: "帮我在 Linear 后加一个 TCN block 抓时序依赖" },
  {
    role: "assistant" as const,
    text: "先确认再动手：拟在 n2(Linear) 后插入 TCN block（膨胀因果卷积），自动接链 + 整理布局。确认后执行。",
  },
];

// ---------------------------------------------------------------------------
// 研究台（research）
// ---------------------------------------------------------------------------

export interface FormulaLine {
  expr: string;
  icon: string;
  tone: "success" | "warning" | "danger";
  note: string;
}

/** FactorVAE forward 推导（候选架构 · 理论判定）。 */
export const RS_FORMULA: FormulaLine[] = [
  { expr: "z = μ_φ(x) + σ_φ(x) ⊙ ε,  ε~N(0,I)", icon: "✓", tone: "success", note: "重参数化可导" },
  { expr: "x̂ = g_θ(z) : ℝ^k → ℝ^28", icon: "✓", tone: "success", note: "维度对齐" },
  { expr: "L = E_q[ log p(x|z) ] − β·KL( q(z|x) ‖ p(z) )", icon: "✓", tone: "success", note: "ELBO 可微" },
  { expr: "p(z) = N(0, I)   ← 高斯先验", icon: "○", tone: "warning", note: "厚尾隐患" },
  { expr: "复杂度 O(N·k·d) /日", icon: "✓", tone: "success", note: "单卡可训" },
];

export const RS_CONCLUSION =
  "FactorVAE 在 A股周频理论成立：维度自洽、ELBO 可微、复杂度可控。唯一隐患是高斯先验 vs 截面收益厚尾——建议把先验/似然换成 Student-t，或在解码端加厚尾噪声。文章观点须先在因子台做 IC + 单调性 + OOS 检验，QUALIFIED 后再入模型（M11）。";

export interface Paper {
  title: string;
  venue: string;
  arxiv: string;
  gist: string;
  transfer: string;
}

export const RS_PAPERS: Paper[] = [
  {
    title: "FactorVAE: Probabilistic Dynamic Factors",
    venue: "AAAI'22",
    arxiv: "arXiv:2112.02744",
    gist: "变分框架抽潜在因子、显式建模噪声，把横截面收益解释为少数动态因子。",
    transfer: "潜因子编码器 + 厚尾先验",
  },
  {
    title: "Temporal Convolutional Networks",
    venue: "—",
    arxiv: "arXiv:1803.01271",
    gist: "膨胀因果卷积，长序列上比 LSTM 更稳更并行，感受野随层指数增长。",
    transfer: "因子时序 backbone",
  },
  {
    title: "Set Transformer",
    venue: "ICML'19",
    arxiv: "arXiv:1810.00825",
    gist: "把样本集合当输入，注意力建模元素间相互作用、置换不变——天然适合每日截面 set。",
    transfer: "截面个股相互作用",
  },
];

export const RS_CHAT_SEED = [
  {
    role: "user" as const,
    text: "我想用 FactorVAE 把噪声因子去掉、抽出潜在因子。这套在 A股周频理论上成立吗？",
  },
  {
    role: "assistant" as const,
    text: "FactorVAE 用变分编码器把横截面收益压到低维潜因子、解码重构。核心是 ELBO = 重构项 − KL。我逐行判定它在你这套上的可行性（见右侧公式工作台）。",
  },
];
