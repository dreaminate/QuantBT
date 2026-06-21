/**
 * F3 因子台「三纯库 + 暴力遍历挖掘」mock 数据 + 纯判定逻辑层。
 * 规格：dev/research/findings/desk-handoff/factorDeck.md §⑤ + GOAL §3（R16/R17）。
 *
 * 诚实不变量（这些是对抗测试钉的硬约束，逻辑必须可单测）：
 * - R17 两层解耦：DL/ML「本体」（.pt/.pkl/.onnx 等）进【模型注册表】，
 *   只有其「输出」登记为【信号契约】才能进因子库。把本体当因子塞库 = 范畴错误，必拒。
 * - R16 生成/守门解耦：守门指标（IC/IR/DSR/t/PBO…）绝不可进生成器候选的
 *   排序 / fitness。生成器只看「结构多样性」类指标（复杂度/算子覆盖/族多样性）。
 * - 诚实-N：等价公式（normalize 后同形）不重复计入 N_eff —— N_eff ≤ N_total。
 * - 零硬编码色值（全 --desk-* token）；本文件不产 hex。
 */

import type { FactorFamily } from "./factorData";

/* ───────────────────────── 三纯库（算术 / ML / DL）───────────────────────── */

/** 三库枚举：保持纯净，互不混装。 */
export type PureLib = "arith" | "ml" | "dl";

/** 注册物的范畴：决定它能进【因子库】还是只进【模型注册表】。 */
export type ArtifactKind =
  /** 算术表达式：可直接进因子库（本身即信号）。 */
  | "expression"
  /** ML/DL 模型「本体」：只能进模型注册表，禁止当因子塞因子库（范畴错误）。 */
  | "model_body"
  /** ML/DL 模型「输出」登记的信号契约：经契约登记后方可进因子库。 */
  | "signal_contract";

/** 模型本体的产物文件后缀（这些是「本体」，不是信号）。 */
export const MODEL_BODY_EXTS = [".pt", ".pth", ".onnx", ".pkl", ".joblib", ".h5", ".ckpt"] as const;

/** 一条「库内条目」mock 记录。 */
export interface LibArtifact {
  id: string;
  lib: PureLib;
  kind: ArtifactKind;
  title: string;
  /** 产物标识：表达式串 / 模型文件名 / 信号契约 id。 */
  ref: string;
  desc: string;
  fam: FactorFamily;
  /** 仅 signal_contract 有：本体在模型注册表里的引用（两层解耦的「连线」）。 */
  modelRef?: string;
}

/**
 * R17 范畴门：判断某产物是否「允许直接进因子库」。
 * - expression / signal_contract → 允许（信号层）。
 * - model_body → 拒绝（本体层，必须先经信号契约登记输出）。
 */
export function canEnterFactorLib(kind: ArtifactKind): boolean {
  return kind === "expression" || kind === "signal_contract";
}

/** 看 ref 后缀像不像「模型本体文件」（用于拦截把 .pt 直接塞因子库）。 */
export function looksLikeModelBody(ref: string): boolean {
  const lower = ref.trim().toLowerCase();
  return MODEL_BODY_EXTS.some((ext) => lower.endsWith(ext));
}

/** R17 入库守卫的判定结果（UI 拿它决定「允许 / 拒绝 + 理由」）。 */
export interface AdmitResult {
  admitted: boolean;
  /** 拒绝原因（admitted=false 时非空）；为诚实文案，不染绿。 */
  reason: string;
}

/**
 * R17 单一入库守卫：给定产物范畴 + ref，判定能否进因子库。
 * 这是对抗测试①②的核心：
 *  - model_body（含 .pt 后缀）→ 拒（范畴错误）。
 *  - ML/DL 输出未走 signal_contract（仍是 model_body / 裸 ref）→ 拒（未走信号契约）。
 *  - signal_contract / expression → 准入。
 */
export function admitToFactorLib(kind: ArtifactKind, ref: string): AdmitResult {
  if (kind === "model_body") {
    return {
      admitted: false,
      reason: "范畴错误：模型本体（.pt/.pkl…）只能进模型注册表，不能当因子塞因子库（R17）",
    };
  }
  // 防御：即便范畴标成别的，只要 ref 看起来是本体文件，一律拒（双保险）。
  if (kind !== "signal_contract" && looksLikeModelBody(ref)) {
    return {
      admitted: false,
      reason: "ref 指向模型本体文件，须先经『信号契约』登记输出，才能进因子库（R17）",
    };
  }
  return { admitted: true, reason: "" };
}

/** 三库分区 mock 条目（每库纯净：算术只装 expression；ML/DL 装本体 + 其信号契约）。 */
export const LIB_ARTIFACTS: LibArtifact[] = [
  // ── 算术暴力遍历库：纯表达式，本身即信号 ──
  {
    id: "arith_vol_adj_mom",
    lib: "arith",
    kind: "expression",
    title: "波动调整动量",
    ref: "ts_pct_change(close,20) / ts_std(ts_pct_change(close,1),20)",
    desc: "暴力遍历产出、守门通过的算术表达式。本身即信号，直接入因子库。",
    fam: "动量",
  },
  {
    id: "arith_pv_corr",
    lib: "arith",
    kind: "expression",
    title: "价量相关",
    ref: "ts_corr(close,volume,20)",
    desc: "20 日滚动价量相关，遍历挖掘命中的量价结构。",
    fam: "量价",
  },
  // ── ML 库：本体（.pkl/.joblib）进模型注册表；输出走信号契约入因子库 ──
  {
    id: "ml_gbdt_body",
    lib: "ml",
    kind: "model_body",
    title: "GBDT 截面打分模型",
    ref: "gbdt_xs_rank_v3.pkl",
    desc: "LightGBM 截面 rank 模型『本体』。登记在模型注册表，禁止直接当因子。",
    fam: "量价",
  },
  {
    id: "ml_gbdt_signal",
    lib: "ml",
    kind: "signal_contract",
    title: "GBDT 打分信号",
    ref: "sig::ml_gbdt_xs_score",
    desc: "上面 GBDT 本体的『预测输出』经信号契约登记 → 才作为信号进因子库。",
    fam: "量价",
    modelRef: "gbdt_xs_rank_v3.pkl",
  },
  // ── DL 库：本体（.pt/.onnx）进模型注册表；输出走信号契约入因子库 ──
  {
    id: "dl_tcn_body",
    lib: "dl",
    kind: "model_body",
    title: "TCN 序列预测模型",
    ref: "tcn_seq_alpha_v2.pt",
    desc: "时序卷积网络『本体』(.pt)。范畴上是模型不是因子，仅进模型注册表。",
    fam: "动量",
  },
  {
    id: "dl_tcn_signal",
    lib: "dl",
    kind: "signal_contract",
    title: "TCN 预测信号",
    ref: "sig::dl_tcn_seq_pred",
    desc: "TCN 本体的『预测序列』经信号契约登记 → 作为信号进因子库（OOF + purge + embargo 在策略层）。",
    fam: "动量",
    modelRef: "tcn_seq_alpha_v2.pt",
  },
];

/** 库元信息（标题 / 副标 / 该库产物允许进因子库的方式）。 */
export const LIB_META: Record<
  PureLib,
  { glyph: string; name: string; sub: string; entry: string }
> = {
  arith: {
    glyph: "∑",
    name: "算术暴力遍历库",
    sub: "纯表达式 · DSL 计算图",
    entry: "表达式本身即信号 → 守门通过直接入因子库",
  },
  ml: {
    glyph: "◭",
    name: "ML 库",
    sub: "GBDT / 线性 / 树模型",
    entry: "本体进模型注册表 · 仅『输出信号』经契约入因子库",
  },
  dl: {
    glyph: "⊛",
    name: "DL 库",
    sub: "TCN / Transformer / GRU",
    entry: "本体进模型注册表 · 仅『输出信号』经契约入因子库",
  },
};

/* ─────────────────────── 暴力遍历挖掘（生成 / 守门解耦）─────────────────────── */

/** 生成器配置（只决定「生成什么」，绝不含守门指标）。 */
export interface GeneratorConfig {
  /** 参与遍历的算子组（结构维度）。 */
  ops: string[];
  /** 参与遍历的字段。 */
  fields: string[];
  /** 最大嵌套深度（复杂度上限）。 */
  maxDepth: number;
  /** 窗口候选集。 */
  windows: number[];
}

/**
 * 生成器允许的「排序键」（fitness 维度）——只看结构，绝不含任何守门指标。
 * 守门指标（IC/IR/DSR/t/PBO/Sharpe…）出现在这里即违反 R16，对抗测试②会抓。
 */
export type GenSortKey = "complexity" | "op_coverage" | "family_diversity" | "novelty";

export const GEN_SORT_KEYS: { value: GenSortKey; label: string }[] = [
  { value: "complexity", label: "结构复杂度" },
  { value: "op_coverage", label: "算子覆盖" },
  { value: "family_diversity", label: "族多样性" },
  { value: "novelty", label: "结构新颖度" },
];

/**
 * 守门指标关键词黑名单（R16）：这些绝不可作为生成器的排序 / fitness 维度。
 * UI 在把任意键塞进生成器排序前，必须先过 assertGenSortKeyClean。
 */
export const GATE_METRIC_KEYWORDS = [
  "ic",
  "ir",
  "dsr",
  "sharpe",
  "pbo",
  "cscv",
  "t_stat",
  "tstat",
  "t-stat",
  "pnl",
  "return",
  "alpha",
  "ret",
] as const;

/** 某个排序键是否「污染」了守门指标（命中黑名单关键词）。 */
export function isGateMetricKey(key: string): boolean {
  const k = key.toLowerCase().replace(/[\s_-]/g, "");
  return GATE_METRIC_KEYWORDS.some((m) => k.includes(m.replace(/[\s_-]/g, "")));
}

/**
 * R16 解耦守卫：断言生成器排序键里没有任何守门指标。
 * 命中即抛 —— 对抗测试②「守门指标进 fitness 排序 → 抓」靠它。
 */
export function assertGenSortKeyClean(key: string): void {
  if (isGateMetricKey(key)) {
    throw new Error(
      `R16 解耦门：守门指标『${key}』不可进生成器候选排序/fitness —— 生成器只看结构多样性，守门在独立后置环节`,
    );
  }
}

/** 单个遍历候选（生成器产出；只带结构属性，无任何守门指标）。 */
export interface MiningCandidate {
  id: string;
  expr: string;
  fam: FactorFamily;
  /** 结构复杂度（嵌套深度 + 算子数），生成器排序用。 */
  complexity: number;
  /** 用到的算子数（结构维度）。 */
  opCount: number;
  /** 结构新颖度 0..1（与已入库结构的距离），生成器排序用。 */
  novelty: number;
}

/**
 * 守门结果（生成与守门解耦后，独立后置环节算出）。
 * 这里才有 IC/IR/DSR；它是「评判」不是「生成排序」。
 */
export interface GateResult {
  candidateId: string;
  ic: number;
  ir: number;
  dsr: number;
  /** 是否通过守门（诚实门槛，不达标不染绿）。 */
  passed: boolean;
  /** 未通过原因（passed=false 时非空）。 */
  note: string;
}

/**
 * 等价公式归一化：把空白、外层冗余括号、大小写抹平，用于诚实-N 去重。
 * 等价（normalize 后同形）的公式只能计 1 次 N_eff。
 */
export function normalizeExpr(expr: string): string {
  let s = expr.replace(/\s+/g, "").toLowerCase();
  // 去掉整体最外层成对冗余括号（如 "(a+b)" → "a+b"），可重复剥离。
  // 仅当首字符 '(' 与其匹配的 ')' 正好是末字符时才剥。
  for (;;) {
    if (s.length < 2 || s[0] !== "(" || s[s.length - 1] !== ")") break;
    let depth = 0;
    let wraps = true;
    for (let i = 0; i < s.length; i++) {
      if (s[i] === "(") depth++;
      else if (s[i] === ")") depth--;
      if (depth === 0 && i < s.length - 1) {
        wraps = false;
        break;
      }
    }
    if (!wraps) break;
    s = s.slice(1, -1);
  }
  return s;
}

/**
 * 诚实-N 计数：在候选公式集合里数「不同结构」的个数（N_eff）。
 * 等价公式（normalize 后同形）只计一次 —— 防止靠等价改写灌水 N。
 * 返回 { total, nEff }；不变量恒有 nEff ≤ total。
 */
export function honestNCount(exprs: string[]): { total: number; nEff: number } {
  const seen = new Set<string>();
  for (const e of exprs) seen.add(normalizeExpr(e));
  return { total: exprs.length, nEff: seen.size };
}

/** 默认生成器配置（mock）。 */
export const DEFAULT_GEN_CONFIG: GeneratorConfig = {
  ops: ["ts_mean", "ts_std", "ts_zscore", "ts_corr", "rank", "neg"],
  fields: ["close", "volume", "amount"],
  maxDepth: 3,
  windows: [5, 10, 20, 60],
};

/** 确定性伪随机（与 factorData.nz 同式，保证 SSR/测试稳定）。 */
function lz(i: number): number {
  const x = Math.sin(i * 12.9898 + 3.71) * 43758.5453;
  return x - Math.floor(x);
}

const MINING_FAMS: FactorFamily[] = ["动量", "反转", "波动", "量价", "形态"];

/**
 * mock 候选生成（生成器输出）：确定性、只带结构属性。
 * 含一对「等价公式」（rank(close/ts_mean(close,20)) vs 带冗余括号版），
 * 用来让对抗测试③验证 N_eff 不被等价改写抬高。
 */
export function buildMiningCandidates(): MiningCandidate[] {
  const base: { expr: string; fam: FactorFamily }[] = [
    { expr: "rank(close/ts_mean(close,20))", fam: "动量" },
    // 等价：仅多一层外层括号，normalize 后与上一条同形 → N_eff 不应 +1
    { expr: "(rank(close/ts_mean(close,20)))", fam: "动量" },
    { expr: "neg(ts_zscore(close,20))", fam: "反转" },
    { expr: "ts_corr(close,volume,20)", fam: "量价" },
    { expr: "ts_std(ts_pct_change(close,1),60)", fam: "波动" },
    { expr: "rank(volume/ts_mean(volume,20))", fam: "量价" },
    { expr: "ts_zscore(amount,10)", fam: "量价" },
    { expr: "neg(ts_pct_change(close,5))", fam: "反转" },
  ];
  return base.map((b, i) => {
    const opCount = (b.expr.match(/[a-z_]+\(/g) ?? []).length;
    const depth = Math.max(...cumDepth(b.expr));
    return {
      id: `cand_${i}`,
      expr: b.expr,
      fam: b.fam ?? MINING_FAMS[i % MINING_FAMS.length],
      complexity: depth * 10 + opCount,
      opCount,
      novelty: 0.3 + lz(i * 5 + 2) * 0.6,
    };
  });
}

/** 逐字符括号深度序列（取 max 作嵌套深度）。 */
function cumDepth(expr: string): number[] {
  const out: number[] = [0];
  let d = 0;
  for (const ch of expr) {
    if (ch === "(") d++;
    else if (ch === ")") d = Math.max(0, d - 1);
    out.push(d);
  }
  return out;
}

/**
 * mock 守门评估（独立后置环节）：给候选算 IC/IR/DSR + 诚实门槛裁决。
 * 门槛：|IC|≥0.02 且 IR≥0.5 且 DSR≥0 才 passed（不达标不染绿，R25）。
 */
export function gateEvaluate(cands: MiningCandidate[]): GateResult[] {
  return cands.map((c, i) => {
    const ic = (lz(i * 7 + 1) - 0.42) * 0.09;
    const ir = (lz(i * 7 + 3) - 0.35) * 1.6;
    const dsr = (lz(i * 7 + 5) - 0.45) * 0.8;
    const passed = Math.abs(ic) >= 0.02 && ir >= 0.5 && dsr >= 0;
    let note = "";
    if (!passed) {
      const fails: string[] = [];
      if (Math.abs(ic) < 0.02) fails.push("|IC|<0.02");
      if (ir < 0.5) fails.push("IR<0.5");
      if (dsr < 0) fails.push("DSR<0（去膨胀后失真）");
      note = fails.join(" · ");
    }
    return { candidateId: c.id, ic, ir, dsr, passed, note };
  });
}

/** 守门通过/未过的色（R25：未达标不染绿）。 */
export function gatePassColor(passed: boolean): string {
  return passed ? "var(--desk-success)" : "var(--desk-warning)";
}
