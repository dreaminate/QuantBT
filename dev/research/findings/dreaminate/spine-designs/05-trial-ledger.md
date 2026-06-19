# 05 · R1/R8 内容寻址试验账本(honest-N + memoize 同一本) + N_eff 收益相关聚类
> 脊柱 build-ready 设计 · 接 R1–R29 决策 · 含 file:line 接线 + 对抗式测试 · Opus 4.8

---

## 1. 职责与边界（接哪些 R 决策，本部件负责/不负责什么）

### 1.1 一句话定位
一本 **append-only、内容寻址（content-addressed）的试验账本**，让 `config_hash → {result, returns_ref, metrics, ts}` 既是 **memoize 缓存**（R8：命中即返、不重跑、省 compute）又是 **honest-N 计数器**（R1：每个 distinct config 计一次试验）——**同一本账**。在「晋级到可下注 confirmatory 结论」的那一道关卡（= IDE run promote），用累计的 **N_eff（收益序列相关聚类，防换等价写法绕过）** 把现在**从不被调用**的 `eval/dsr.py + eval/pbo.py + eval/bootstrap.py` 真正接进去，要求 **三支证据同向 + 通缩区间** 才放行。

### 1.2 接的 R 决策
| 决策 | 本部件如何兑现 |
|---|---|
| **R1=C honest-N** | 探索（IDE 跑沙箱 run）自由、不挡；只有 `promote`（晋级 confirmatory）时强制把当前 `research_theme` 累计 N_eff 喂进守门器。探索期只记账不裁决。 |
| **R8 / R1 同一本账** | `config_hash = hash(因子AST规范化 + params + universe + dataset_version + freq + label)`；命中 → 返缓存 `result`（**不重跑**）+ 该 distinct hash 已在账上（不重复计 N，但**计入** distinct 计数）。memoize 与 honest-N 物理同表。 |
| **R2 多证据三角** | gate 同时算 DSR(区间) + PBO + bootstrap CI，**三支同向正**才 GREEN；任一强负 RED；分歧 YELLOW + 证据包。绝不单点裁决，红绿灯可下钻暴露 N_eff/聚类/适用域空洞。 |
| **R5 守门器自身模型风险明示** | gate 输出固定附 `model_risk_disclosure`：DSR 是「标度修正，非修复低估，只与诚实 N 一样诚实」；N_eff 聚类是可博弈旋钮，输出区间非单点。 |
| **R6 / R7** | 措辞锚 NIST「有效挑战」概念但**不宣称合规、不宣称组织独立**；左侧账本是「防自欺非防恶意」，独立验证由异模型/异种子的 verifier agent 提供（本部件给出可复算工件，不自称组织独立）。 |
| **R11 重放** | gate 输入全部读已落盘工件（returns/result.json），**不重跑** LLM；`returns_ref` 指向不可变快照。 |
| **R12 OOS 约定非强制** | 留出集/OOS 切片是「约定 + 触碰留痕」，不是访问控制；本部件只对「N 不可手动改小」做硬约束（防作弊），OOS 隔离诚实标注「防自欺非防恶意」。 |
| **P2 假设卡不挡探索** | 探索性 run 标 `exploratory`，不要求假设卡、不进 gate；只有 promote 到 confirmatory 才冻结假设并跑 gate。 |
| **管太宽分界** | 研究侧：N 只计数 + 显示通缩真相，**随便跑**（研究自由）；硬锁只有一条——**N 不可被手动改小 / 换等价写法洗掉**（防作弊）。 |

### 1.3 负责
- 内容寻址 hash 规约（含 AST 规范化，使「等价但表达式不同」→ **不同** hash → 新 trial；「同一表达式跑两次」→ **同** hash → 命中缓存不重复计 N）。
- append-only 账本读写（复用现有 JSONL `_JsonlStore` 模式）。
- N_observed（distinct config 计数）+ N_eff（收益相关聚类，报区间）。
- 把 dsr/pbo/bootstrap 接进 promote 关卡，产出多证据三角裁决 + 通缩区间 + 披露。
- 给 `eval/dsr.py` 增 `var_sr_hat` 入参（False Strategy Theorem 的横截面方差 V）。

### 1.4 **不**负责（明确划界，防越权）
- **不**实现 ONC 真聚类的全部 SOTA（dossier §7：ONC 缺独立复现、超参敏感）——只做「层次聚类 + 报敏感性区间 + 锁定口径」的保守版，且**明示是下界/可博弈旋钮**。
- **不**捕获 LLM 单次推理内隐式假设（研究开放问题 §8.2，物理不可观测）——`N_observed` 明确标注为**真值下界**。
- **不**碰交易成本/容量/拥挤（那是另一脊柱部件）；gate 只管统计显著性，并在披露里写明「过闸 ≠ 会赚钱」。
- **不**改前端 RunDetailPage「收益概述」既有逻辑（冻结）；只新增 gate 证据包字段供下钻页消费。
- **不**做 Harvey-Liu haircut 与 DSR 叠加（dossier §7 双重计数风险）——二者只取其一，本期只用 DSR 侧 N_eff 通缩。

---

## 2. 现有代码现状（file:line：有什么、缺什么、哪里是 dossier 点名的洞）

> 路径相对 `/Users/wzy/Work/01_Projects/QuantBT/app/backend/app/`，行号已实际核对。

### 2.1 守门器已存在但**从不被 run 路径调用**（dossier 点名的核心洞）
- `eval/dsr.py:41` `deflated_sharpe_ratio(returns, n_trials, periods_per_year)` — 已实现，但**入参只有 n_trials，缺 var_sr_hat（横截面方差 V）**；`_expected_max_sr` (`eval/dsr.py:33`) 用极值近似 `√(2 ln n) − γ/√(2 ln n)`，未带 V → False Strategy Theorem 的 V 项缺失。
- `eval/pbo.py:58` `cscv_pbo(returns_matrix, s_blocks, max_combinations, *, min_n_strategies, enumerate_all, strict)` — 已实现，含 `PBOConfigError` (`:54`)、`lambda_logit_mean`/`enumerated_full` 审计字段 (`:25-27`)。完整可用。
- `eval/bootstrap.py:23` `bootstrap_sharpe_ci(returns, n_boot, confidence, periods_per_year, seed)` — 已实现。**注意：是 iid 重抽（`:37` `rng.choice`），dossier §6 点名 iid 会低估方差** → 本部件须改/包一层 block bootstrap（见 §4）。
- **验证「从不被调用」**：`grep deflated_sharpe_ratio|cscv_pbo|bootstrap_sharpe_ci` 全仓非 test 命中仅在 `eval/` 自身 + `eval/__init__.py` 导出。`main.py` 对 dsr/pbo **零调用**。
- **半死的下游**：`eval/risk_summary.py:103` `_rule_dsr` 会 `_read(metrics, "dsr", ...)`，`:87` `_rule_pbo` 读 `pbo` — 但**没有任何代码把 dsr/pbo 写进 metrics**，所以这两条规则永远拿 `None` → 永远不触发。`risk_summary.py:248` 已有 `has_dsr` 判断走 `insufficient_data`，证明「dsr 缺失」是常态。**这就是洞：守门器有，规则有，但中间的「计算并注入 metrics」一环缺失。**

### 2.2 promote 关卡 = 唯一的「晋级 confirmatory」入口（gate 应挂这里）
- `ide/promote.py:52` `promote_ide_run(*, ide_run_id, owner_username, strategy_name, strategy_code, result, record_name, run_root)` — 把 IDE 沙箱 emit_result 提升为正式 Run。
  - `:67-73` 校验 `equity_curve`（≥2 点）。
  - `:87` `metrics = _compute_metrics(rows)` — 算 sharpe/sortino/maxdd/alpha/beta，**但不算 dsr/pbo/bootstrap**。
  - `:106` 写 `run.json`，`:99` `"metrics": metrics`。
  - `rows` 每行含 `net_return` (`:160`)，即**收益序列已在手**，可直接喂守门器。
- `main.py:2161` `@app.post("/api/ide/runs/{run_id}/promote")` → `ide_promote_run` — REST 入口，`:2192` 调 `promote_ide_run`。
- `main.py:2127` `@app.get("/api/ide/runs/{run_id}/risk_preview")` → `ide_run_risk_preview` — 只读预览，`:2156` 调 `compute_risk_summary(metrics_combined)`。**这里 metrics_combined 里没有 dsr/pbo**（`:2150` 的平铺白名单含 `"pbo","dsr"` 但 result 里根本没有）。

### 2.3 账本可复用的基建
- `experiments/store.py:80` `_JsonlStore`（`:88` append + `:92` read_all，`:100` 容忍坏行）— **直接复用为账本的 append-only 落盘层**。
- `experiments/store.py:106` `ExperimentStore` / `:124` `RunStore` — 同目录 `data/experiments/*.jsonl` 模式可照搬。
- `main.py:91` `RUN_STORE = RunStore(DATA_ROOT / "experiments")` — 账本可挂 `DATA_ROOT / "experiments" / "trial_ledger.jsonl"`。
- `paths.py:9` `DATA_ROOT`、`paths.py:10` `RUN_ROOT`。

### 2.4 config_hash 的 AST 锚点（防换等价写法）
- `factor_factory/expression.py:55` `parse_expression(formula) -> ast.AST` — 已有 Python AST 解析；`:131` `ast.unparse` 已被用于规范化内层公式。**可复用 `ast.parse` + `ast.dump` 做 AST 规范化 hash**（去掉空格/括号差异，但**保留语义差异** → 等价改写仍同 hash？见 §7 开放问题：AST 规范化只挡「空格/冗余括号」级别的同义，挡不住 `a*2` vs `a+a`，故 N_eff 收益聚类是第二道防线）。
- `factor_factory/registry.py:27` `Factor`（factor_id/formula/version/params）— config_hash 的 params 来源。

### 2.5 缺什么（本部件要新建/补的）
1. `experiments/trial_ledger.py` — **新文件**：`config_hash` 规约 + `TrialLedger`（append-only + memoize + honest-N）+ N_eff 聚类。
2. `eval/dsr.py` — **改签名**：`deflated_sharpe_ratio(..., var_sr_hat=None)`。
3. `eval/bootstrap.py` — **加 block bootstrap**：`bootstrap_sharpe_ci(..., block_size=None)`（保留序列相关）。
4. `eval/overfit_gate.py` — **新文件**：多证据三角 gate（DSR 区间 + PBO + bootstrap CI → verdict + 通缩区间 + 披露）。
5. `ide/promote.py` — **接线**：promote 前调 ledger 记账 + gate，把 dsr/pbo/bootstrap 注入 `metrics` 并把 `gate_verdict` 写进 run.json。
6. `main.py` — **接线**：`risk_preview` 与 `promote` 经 gate；新增只读账本/N_eff 端点。

---

## 3. 目标设计（schema/Pydantic 草图 + 模块布局 + 状态机）

### 3.1 内容寻址 config_hash 规约
```python
# experiments/trial_ledger.py
import ast, hashlib, json

CONFIG_HASH_VERSION = "v1"   # 口径版本，进 hash；改口径 = 新命名空间，不污染旧账

def normalize_factor_ast(formula: str) -> str:
    """AST 规范化：去空格/冗余括号/字面量格式差异，但保留语义结构。
    a + b  和  a+b  → 同; a*2 和 a+a → 不同 (这是设计选择，见 §7)。"""
    try:
        node = ast.parse(formula, mode="eval").body   # 复用 expression.py 的解析约定
        return ast.dump(node, annotate_fields=False)   # 结构化 dump，稳定可复现
    except SyntaxError:
        return f"__raw__:{formula.strip()}"            # 非表达式策略：退化为去空白原文

def config_hash(
    *, factor_formula: str, params: dict, universe: str,
    dataset_version: str, freq: str, label: str,
) -> str:
    payload = {
        "v": CONFIG_HASH_VERSION,
        "ast": normalize_factor_ast(factor_formula),
        "params": _canon(params),          # 排序 + 浮点规范化
        "universe": universe.strip().lower(),
        "dataset_version": dataset_version.strip().lower(),
        "freq": freq.strip().lower(),
        "label": label.strip().lower(),
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return "cfg_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]
```
**铁律**：换 universe / freq / dataset_version / label / 等价但 AST 不同的公式 → **新 hash → 新 trial**（dossier §7：朴素计数器会被这些维度绕过；本设计把它们全进 hash）。

### 3.2 账本 schema（append-only，memoize 与 honest-N 同一本）
```python
@dataclass
class TrialRecord:
    config_hash: str                 # 主键 = 内容寻址
    research_theme_id: str           # 按因子族/主题累计 N，非按 session（防换 session 重置）
    result: dict                     # memoize 命中即返的回测结果（不重跑）
    returns_ref: str                 # 指向不可变收益快照路径 (R11：读工件不重跑)
    metrics: dict                    # sharpe/maxdd/... (含 gate 注入的 dsr/pbo 后回写)
    asset_class: str                 # a_share | crypto (DSR 偏峰/T 按此分资产)
    stage: Literal["exploratory", "confirmatory"]   # P2：探索不挡，仅 confirmatory 过 gate
    created_by: Literal["human", "agent"]
    created_at_utc: str
    # —— 不可静默改小 (R1 硬约束) ——
    superseded_by: str | None = None # 软删除指针；物理行永不删 → "洗掉失败试验"必留痕
    audit_reason: str = ""
    # —— 诚实标注 ——
    n_observed_is_lower_bound: bool = True   # 永远 True：LLM 隐式试验不可埋点 (§8.2)
```

落盘行（append-only JSONL）：每次 record / supersede / gate 回写 metrics 都 **append 新行**，读时取同 `config_hash` 的**最后一行**为当前态（复用 `store.py` 的 latest-wins 模式 `:118`）。

### 3.3 N_observed / N_eff
```python
def n_observed(theme_id) -> int:
    """distinct, 非 superseded 的 config_hash 数。= honest-N 名义计数 (真值下界)。"""

def n_eff(theme_id, *, linkage="average", corr_threshold=0.7, locked=True) -> NEffResult:
    """收益序列相关聚类簇数 = 有效独立试验数。
    防换等价公式绕过：两个公式 AST 不同 (→ 不同 config_hash → N_observed 各 +1),
    但收益序列高度相关 → 聚到同簇 → N_eff 不重复膨胀。
    dossier §7：聚类是可博弈旋钮 → 报区间 [low, high]，口径锁定，明示是启发式。"""
    return NEffResult(
        point=k, low=k_conservative, high=k_optimistic,
        n_observed=N, method=f"hierarchical/{linkage}@{corr_threshold}",
        is_heuristic=True, gameable_knob=True,
    )
```
`n_eff_low`（簇更少、N_eff 更小）→ 通缩**不足**端；`n_eff_high`（簇更多、N_eff 更大）→ 通缩**过度**端。DSR 用两端各算一遍 = 通缩区间。

### 3.4 多证据三角 gate
```python
# eval/overfit_gate.py
@dataclass
class GateVerdict:
    color: Literal["green", "yellow", "red", "insufficient_evidence"]
    dsr_optimistic: float            # 用 n_eff_low (V_low) → 通缩不足
    dsr_conservative: float          # 用 n_eff_high (V_high) → 通缩过度
    pbo: float
    bootstrap_ci: tuple[float, float]
    all_agree_positive: bool
    n_observed: int
    n_eff: dict                      # {point, low, high}
    reason: str
    # R5 守门器自身模型风险明示 (固定附带，不可关)
    model_risk_disclosure: list[str]
    # R7/R12 措辞 (裁决永远说"证据充分/不足"，不说"可信/安全")
    verdict_phrasing: str

def run_overfit_gate(returns, *, theme_id, asset_class, returns_matrix, ledger) -> GateVerdict:
    T = len(returns)
    min_T = 504 if asset_class == "a_share" else 252
    if T < min_T:                                  # §短样本边界：T 不足判"证据不足"非虚假红绿
        return _insufficient(T, min_T)
    neff = ledger.n_eff(theme_id)
    var_low, var_high = _var_sr_interval(returns_matrix)   # False Strategy Theorem 的 V
    dsr_opt  = deflated_sharpe_ratio(returns, n_trials=neff.low,  var_sr_hat=var_low)
    dsr_cons = deflated_sharpe_ratio(returns, n_trials=neff.high, var_sr_hat=var_high)
    pbo = cscv_pbo(returns_matrix, s_blocks=8, strict=False).pbo
    ci = bootstrap_sharpe_ci(returns, block_size=_auto_block(T)).to_tuple()
    agree = (dsr_cons >= 0.5) and (pbo <= 0.5) and (ci[0] > 0)   # 三支同向正
    color = "green" if agree else ("red" if _any_strong_neg(...) else "yellow")
    return GateVerdict(color=color, ..., model_risk_disclosure=_DISCLOSURE)

_DISCLOSURE = [
    "DSR 是显著性阈值的标度修正(studentize)，不是修复夏普被低估；它只与你诚实提交的 N 一样诚实。",
    "N_eff 用收益相关聚类估计，是启发式、对超参敏感、可被低报放水；这里报区间不报单点。",
    "N_observed 是真值下界：agent 单次推理内的隐式试验无法计入。",
    "本闸门只管统计显著性，未计交易成本/容量/拥挤；过闸 ≠ 会赚钱，regime 漂移才是中低频 OOS 失效主因。",
]
```

### 3.5 状态机（promote 时的判定流）
```
[IDE run ok] --promote--> 计算 config_hash
    |
    ├─ 命中账本 (同 hash 已存在且非 superseded)
    │     → 返缓存 result + metrics (不重跑, R8 省 compute)
    │     → N_observed 不 +1 (已在账); gate 用账上 metrics
    │
    └─ 未命中
          → append TrialRecord(stage=confirmatory)  [N_observed +1]
          → run_overfit_gate(returns, theme_id, ...)
          → append 回写 metrics(含 dsr/pbo/bootstrap) + gate_verdict
                |
                ├ green  → promote 放行, run.json 带 gate_verdict
                ├ yellow → promote 放行但标 caution, 证据包下钻
                ├ red    → 仍落 run (探索留痕) 但 run.json verdict=red, 前端禁推下一关卡
                └ insufficient_evidence → 落 run, 判"证据不足", 不给红绿
```
**N 不可手动改小**：没有任何 API 能减少 `n_observed`；「删失败试验」只能 `supersede`（append 软删行，原行物理保留）→ N 计数仍含被 supersede 的（或显式标注「已 supersede N」，但**不能归零**）。

### 3.6 模块布局
```
experiments/trial_ledger.py   [新] config_hash + TrialLedger + n_observed/n_eff
eval/dsr.py                   [改] +var_sr_hat 入参 (False Strategy Theorem)
eval/bootstrap.py             [改] +block_size (序列相关 block bootstrap)
eval/overfit_gate.py          [新] 多证据三角 + 通缩区间 + 披露
ide/promote.py                [接] promote 前记账 + gate, 注入 metrics + gate_verdict
main.py                       [接] risk_preview/promote 经 gate; 新增只读账本端点
```

---

## 4. 代码接线点（逐条 file:line：改哪行/在哪加新文件/动了哪个函数签名）

### 4.1 `eval/dsr.py:41` — 改签名加 `var_sr_hat`（False Strategy Theorem）
**现状** `eval/dsr.py:41-63`：`deflated_sharpe_ratio(returns, n_trials, periods_per_year)`，`:60` `expected = _expected_max_sr(n_trials)`，`_expected_max_sr` (`:33`) 只吃 `n_trials`，**无 V**。
**改为**：
```python
def deflated_sharpe_ratio(returns, n_trials, periods_per_year=252, *, var_sr_hat=None):
    # var_sr_hat = 试验间 SR 的横截面方差 V (Bailey-LdP 式(1) 的 √V 项)
    # None → 退化为旧极值近似 (向后兼容现有 6 个 test_eval.py 调用)
```
`_expected_max_sr` (`eval/dsr.py:33`) 改为接受 `var_sr_hat`：
```python
def _expected_max_sr(n_trials, var_sr_hat=None):
    z = math.sqrt(2*math.log(n_trials))
    base = z - euler/z                         # 旧行为 (V=1 归一化隐含)
    if var_sr_hat is None: return base
    # E[max] ≈ √V·[(1-γ)·Φ⁻¹(1-1/N) + γ·Φ⁻¹(1-1/(Ne))]  (式(1))
    return math.sqrt(var_sr_hat) * ((1-euler)*norm.ppf(1-1/n_trials) + euler*norm.ppf(1-1/(n_trials*math.e)))
```
**向后兼容**：`test_eval.py:28,35` 不传 `var_sr_hat` → 走旧分支，现有断言不破。
**文档定位（R5）**：`dsr.py` 模块 docstring (`:1-12`) 追加一句：「DSR 是阈值标度修正，非修复 SR 低估；只与诚实 N 一样诚实。」

### 4.2 `eval/bootstrap.py:23` — 加 `block_size`（保留序列相关）
**现状** `eval/bootstrap.py:37` `sample = rng.choice(arr, size=arr.size, replace=True)` = **iid 重抽**（dossier §6 点名低估方差）。
**改为**加 `block_size: int | None = None` 入参：`None` → 旧 iid（向后兼容 `test_eval.py:42`）；给值 → moving-block 重抽（抽连续块拼接），保留自相关。新增 `BootstrapCI.method` 字段标注 `"iid"|"block"`。

### 4.3 `experiments/trial_ledger.py` — 新文件
复用 `experiments/store.py:80` `_JsonlStore` 模式（import 或照搬）。落盘 `DATA_ROOT/experiments/trial_ledger.jsonl`。实现 §3.1–3.3 的 `config_hash` / `TrialLedger.record` / `memoize_get` / `n_observed` / `n_eff`。**关键：`n_eff` 的 `linkage`/`corr_threshold` 口径写死为模块常量 + 进 `config_hash` 不相关的独立 `NEFF_CONFIG_VERSION`，锁定不可由请求参数改（防放水）。**

### 4.4 `eval/overfit_gate.py` — 新文件
实现 §3.4 `run_overfit_gate` + `GateVerdict`。import `eval.dsr/pbo/bootstrap` + `experiments.trial_ledger`。**这是把三个从不被调用的守门器真正接起来的中枢。**

### 4.5 `ide/promote.py:52` — 接线（gate 挂这里，核心）
**在 `:87` `metrics = _compute_metrics(rows)` 之后、`:89` 组 manifest 之前**插入：
```python
# —— 05 脊柱：内容寻址记账 + 多证据三角 gate ——
from ..experiments.trial_ledger import TrialLedger, config_hash
from ..eval.overfit_gate import run_overfit_gate
ledger = TrialLedger(run_root.parent / "trial_ledger.jsonl")   # 与 RUN_STORE 同根
chash = config_hash(
    factor_formula=result.get("metadata", {}).get("factor_formula", strategy_code[:2000]),
    params=result.get("metadata", {}).get("params", {}),
    universe=metadata.get("universe", "default"),
    dataset_version=result.get("metadata", {}).get("dataset_version", "unknown"),
    freq=metadata["frequency"], label=result.get("metadata", {}).get("label", "fwd_ret"),
)
cached = ledger.memoize_get(chash)
if cached is not None:                       # R8：命中即返不重跑
    return PromotedRun(run_id=cached["run_id"], run_dir=Path(cached["run_dir"]), metrics=cached["metrics"])
theme_id = result.get("metadata", {}).get("research_theme_id", strategy_name)
returns = [r["net_return"] or 0.0 for r in rows]          # 收益序列已在手 (:160)
ledger.record(config_hash=chash, theme_id=theme_id, returns=returns, stage="confirmatory", ...)
verdict = run_overfit_gate(returns, theme_id=theme_id, asset_class=_asset_of(metadata), ledger=ledger)
metrics["dsr"] = verdict.dsr_conservative      # 注入 → 让 risk_summary.py:103 _rule_dsr 真正生效
metrics["pbo"] = verdict.pbo
metrics["bootstrap_sharpe_lower"] = verdict.bootstrap_ci[0]
ledger.write_metrics(chash, metrics, verdict.to_dict())   # append 回写
```
manifest (`:99`) 增 `"gate_verdict": verdict.to_dict()`。**`returns_matrix`**（PBO 需要 N 列策略）由 `ledger` 拿同 `theme_id` 历史 trial 的 `returns_ref` 拼成矩阵（< min_n_strategies 时 PBO 返 NaN，gate 据此走 yellow/insufficient）。
**函数签名不变**（仍 `promote_ide_run(*, ide_run_id, ...)`），只增内部逻辑 → 不破 `main.py:2192` 调用方。

### 4.6 `main.py:2127` `ide_run_risk_preview` — 接线（只读预览也经 gate）
**现状** `:2156` `compute_risk_summary(metrics_combined)`，但 `metrics_combined` 无 dsr/pbo。
**改**：在 `:2156` 前，若 result 含 `equity_curve`，调 `run_overfit_gate` 算出 dsr/pbo 注入 `metrics_combined`，再喂 `compute_risk_summary`。**这样 `risk_summary.py:103 _rule_dsr` / `:87 _rule_pbo` 从「永远拿 None 不触发」变成真生效。** 返回体增 `"gate_verdict"` 给下钻页（不改 RunDetailPage 既有逻辑，只加字段）。

### 4.7 `main.py` — 新增只读账本端点（约 `:2160` 区附近，promote 端点旁）
```python
@app.get("/api/research/themes/{theme_id}/honest_n")   # 暴露 N_observed / N_eff 区间 + 通缩真相
@app.get("/api/research/trials/{config_hash}")          # 单 trial 下钻 (memoize 命中证据)
```
只读、不改写、不能改小 N。供红绿灯一键下钻（R2：暴露有效 N/试验聚类/适用域空洞）。

### 4.8 `eval/__init__.py` — 导出
`eval/__init__.py:5-17` 增 `from .overfit_gate import run_overfit_gate, GateVerdict`。

> **冻结尊重**：以上无一处改 RunDetailPage「收益概述」既有逻辑；只在 run.json / risk_preview 返回体**加字段**（`gate_verdict`），属允许的「加字段」三类改动之一。

---

## 5. 对抗式测试规约（按 TEST_STANDARD：种已知坏→门必抓→断言什么）

> 验收标准：种一个已知的坏，门必须抓住，否则门是纸做的。非覆盖率清单。新增测试文件 `tests/test_trial_ledger.py` + `tests/test_overfit_gate.py`。

### 5.1 ① 种已知坏 → 门必抓

**T1 · 噪声探针（纯随机信号）→ gate 必判过拟合**
种：50 列纯 `N(0,0.01)` 随机收益矩阵（无 alpha），目标列也是噪声。
门：`run_overfit_gate` 必须 **不返 green**（PBO 不显著低 / DSR 保守端 < 0.5 / bootstrap CI 跨零任一成立 → yellow 或 red）。
断言：`verdict.color != "green"` 且 `verdict.all_agree_positive is False`。
（呼应现有 `test_eval.py:46` `test_cscv_pbo_high_for_noise_strategies`，但升级为**整个 gate** 必抓，非单指标。）

**T2 · 泄露探针（塞一个 = 次日收益的特征）→ 短样本/N_eff 门必报警**
种：构造一条 in-sample Sharpe 虚高（收益序列直接抄了「未来」）但 `theme` 里已有 30 个高相关变体的 trial。
门：N_eff 聚类必须把这 30 个变体聚成**少数簇**（N_eff << N_observed），DSR 用 `n_eff` 而非 `n_observed=30` → 通缩区间须随 N_eff 抬升；且 gate 披露里必须出现「N_observed 是下界」。
断言：`n_eff.point < n_observed` 且 `dsr_conservative < dsr_optimistic`（通缩区间非退化）。

**T3 · 已知真信号探针（必须通过，抓误杀）**
种：一列真有持续 alpha（`loc=0.001`）、`theme` 内只有少数独立 trial、T 充足（≥504）的收益。
门：gate **必须能 green**（不被一刀切保守主义误杀真实弱信号，对齐 R 决策「不因单用户砍治理但也别错杀」）。
断言：`verdict.color == "green"` 且三支同向正。

**T4 · 短样本探针 → 判「证据不足」而非虚假红绿**
种：a_share，T=300 < min_T=504。
门：gate 必须返 `insufficient_evidence`，**不**给 green/red。
断言：`verdict.color == "insufficient_evidence"` 且 `"证据不足" in verdict.reason`，且**没有**输出一个会被误读为「修复后的好夏普」的单点数字。

### 5.2 ② 变形测试（不变量）

**T5 · 打乱时间 → Sharpe/DSR 必坍塌**
种：真信号收益序列 → `np.random.shuffle`（破坏序列结构）。
门：shuffle 后若 alpha 来自时序结构，Sharpe 应变；**关键不变量**：block bootstrap CI（`block_size` 给值）对 shuffle **比 iid 更敏感**（iid 对 shuffle 不变）→ 证明 block bootstrap 真在用序列信息。
断言：`bootstrap_ci(block).lower` 在 shuffle 前后变化幅度 > `bootstrap_ci(iid).lower` 的变化幅度。

**T6 · 换种子 → DSR 不翻符号 / verdict 不翻色**
种：同收益、`bootstrap seed` 与 `cscv` 采样不同 → 跑两次 gate。
门：verdict 颜色不得翻转（green↔red），DSR 保守端不得跨 0.5 阈值翻转。
断言：`verdict_seed1.color == verdict_seed2.color`（允许 yellow 抖动到边界但不允许 green↔red 翻转）。

**T7 · 加微小成本 → 净 Sharpe 必下降（接成本部件的契约占位）**
种：收益逐期扣 1bp。
门：扣成本后 Sharpe 单调不增；gate 不得因「成本前 green」而对成本后也放行（gate 输入用净收益）。
断言：`sharpe(net) <= sharpe(gross)`，且若净 Sharpe 跌破阈值则 verdict 降级。

### 5.3 ③ 交叉验证（多证据三角无单一承重点）

**T8 · 三支不同向 → 必不放行（无单点承重）**
种：构造 DSR 保守端 > 0.5 但 bootstrap CI 跨零的收益。
门：gate **必须** yellow（不得因 DSR 单支过关就 green）。
断言：`verdict.color == "yellow"` 且 `all_agree_positive is False`。证明 DSR 永不单点裁决（dossier §7 红线）。

**T9 · 独立重算对账（异实现）→ 不一致即 BLOCK**
种：用 `scipy.stats` 独立算同一序列的 skew/kurt 与 DSR 分母，与 `eval/dsr.py:66 _skew`/`:77 _kurt_excess` 对账。
门：两套实现差异 > 1e-6 即测试 FAIL（指向 bug）。
断言：`abs(dsr_ours - dsr_independent) < 1e-6`。

### 5.4 ④ 幂等 / 恢复 / 防绕过（honest-N 的核心硬约束）

**T10 · memoize 幂等：同 config_hash 重跑 → 返缓存不重复计 N（R8）**
种：同一 `config_hash` 调 `promote` 两次。
门：第二次必须**命中缓存返存量**、`n_observed` **不 +2 只 +1**、不重跑 gate。
断言：`ledger.memoize_get(h)` 第二次非 None；`n_observed(theme)` 调用前后差 = 1。

**T11 · 换等价写法绕过 → N_eff 必抓（防作弊，硬）**
种：`a*2` 与 `a+a`（AST 不同 → 2 个 config_hash → N_observed=2）但收益序列**完全相同**。
门：N_eff 聚类必须把二者聚成 **1 簇**（N_eff=1），不让换写法把有效 N 撑大来稀释通缩。
断言：`n_observed == 2` 且 `n_eff.point == 1`。**这是「防换等价公式绕过」的核心断言。**

**T12 · N 不可手动改小（防作弊，硬）**
种：尝试通过任何公开 API（含只读端点、supersede）让 `n_observed` 减少。
门：无 API 能减少 N_observed；`supersede` 只 append 软删行、`n_observed` 含被 supersede 的（或单列「已 supersede」但**不归零**）。
断言：调 supersede 后 `n_observed` 不减；账本文件行数只增不减（append-only）。

**T13 · 崩溃恢复 / 坏行容忍**
种：账本 JSONL 末尾写半行（模拟崩溃中途）。
门：`read_all` 跳过坏行不崩（复用 `store.py:100` 容错），N 计数仍正确。
断言：坏行不致 raise；`n_observed` = 完好行的 distinct 数。

**T14 · 换 session/换 theme 不重置（防跨会话绕过）**
种：同 `research_theme_id`、不同进程/session 各记一次。
门：N 按 `theme_id` 跨 session 累计，不因换 session 归零。
断言：两次 record 后 `n_observed(theme) == 2`（distinct config 时）。

### 5.5 ⑤ 裁决措辞（R7/R12）

**T15 · 措辞断言：永说「证据充分/不足」不说「可信/安全」**
门：`verdict.verdict_phrasing` 与 `reason` 中**不得**出现「可信」「安全」「保证」；**必须**出现「证据充分/不足」式措辞 + 适用域 + 未验证项。
断言：`not any(w in text for w in ["可信","安全","保证"])`，且 `verdict.model_risk_disclosure` 非空且含「只与诚实 N 一样诚实」。

### 5.6 ⑥ 经验网（回测↔paper 对账占位）

**T16 · gate 输出可被下游 risk_summary 消费（接线活性证明）**
门：promote 后 `metrics["dsr"]/["pbo"]` 非 None → `compute_risk_summary` 的 `_rule_dsr`(`risk_summary.py:103`) / `_rule_pbo`(`:87`) **真正触发**（不再永远拿 None）。
断言：种 `dsr=0.1` → `risk_summary.trust_level == "high_risk"` 且 flags 含 `low_dsr_confidence`。**这条直接证明「守门器从死接活」**——dossier 点名的洞被补上。

---

## 6. 与其他脊柱部件的契约（共享 schema 字段约定）

### 6.1 本部件**产出**（其他部件消费）
| 字段 | 类型 | 约定 | 消费方 |
|---|---|---|---|
| `config_hash` | `str` `cfg_<sha256[:24]>` | 内容寻址主键；`hash(AST规范化+params+universe+dataset_version+freq+label+CONFIG_HASH_VERSION)` | run.json、experiment 注册、checkpoint 关联 |
| `gate_verdict` | `dict` | `{color, dsr_optimistic, dsr_conservative, pbo, bootstrap_ci, n_observed, n_eff:{point,low,high}, reason, model_risk_disclosure[], verdict_phrasing}` | RunDetail 下钻页（只加字段，不改既有逻辑）、晋级关卡部件 |
| `n_observed` / `n_eff` | `int` / `{point,low,high}` | N_observed 是真值**下界**；N_eff 是启发式区间，口径锁定版本 `NEFF_CONFIG_VERSION` | 所有「晋级闸门」部件、honest-N 展示 |
| `returns_ref` | `str` (path) | 指向**不可变**收益快照；R11 重放只读此工件不重跑 | OOS 验证部件、verifier agent |
| `stage` | `"exploratory"\|"confirmatory"` | P2：exploratory 不过 gate；confirmatory 才冻结假设跑 gate | 假设卡部件 |

### 6.2 本部件**消费**（其他部件产出）
| 字段 | 来源约定 |
|---|---|
| `dataset_version` | 数据平台 v2 的不可变版本号（`data_quality.py`）；进 config_hash → 换数据源必新 trial |
| `universe` / `freq` / `label` | 策略 metadata；进 config_hash |
| `research_theme_id` | 因子族/主题维度（非 session）；N 按它累计 |
| `idempotency_key` | 与 `config_hash` 对齐：promote 用 `config_hash` 做幂等键 → 同 config 重 promote 返存量（呼应 §8 M17 跟单幂等教训） |
| `checkpoint_id` | 崩溃恢复：账本 append-only 自带恢复点，无需额外 checkpoint，最后一行即最新态 |

### 6.3 不变量（跨部件强约束）
- **N 单调不减**：任何部件都不能让 `n_observed` 减小。
- **memoize 与 honest-N 同源**：同一 `config_hash` 既是缓存键又是计数单元，不存在「缓存命中但不计 N」或「计 N 但不缓存」的分裂。
- **gate 永不单点**：消费方不得只取 `dsr_conservative` 当唯一裁决；必须读 `all_agree_positive`。

---

## 7. 开放问题 / 风险（落地前必答）

1. **AST 规范化的语义深度边界**（dossier §8.4 + R8 核心）：`ast.dump` 只挡「空格/冗余括号」级同义，挡不住 `a*2`↔`a+a`、`rank(x)`↔`rank(x+0)` 这类语义等价但 AST 不同的改写。设计上**故意**让它们成不同 config_hash（各计 N），靠 **N_eff 收益聚类**做第二道防线把它们聚回一簇。但若两公式在某数据切片上**收益恰好不相关**（小样本噪声），聚类会漏聚 → N_eff 虚高 → 通缩不足。**必答**：是否对「AST 距离近 + 收益相关」做双信号聚类，而非纯收益相关？本期默认纯收益聚类 + 明示这是下界。

2. **N_eff 鸡生蛋循环**（research 15 §8.1 / dossier §8）：N_eff 聚类需跨策略相关阵，而相关阵需这些策略**同期回测**才能估。本设计用「同 theme 历史 trial 的 returns_ref 拼矩阵」近似，但早期 trial 少时 PBO/聚类统计功效低。**必答**：trial 数 < min_n_strategies(10) 时，gate 走 yellow 还是 insufficient？本期定 yellow + 披露「样本不足以做 PBO」。

3. **PBO 的 returns_matrix 从哪来**：promote 时只有**本策略**一列收益，PBO 需 N 列。本设计从账本同 theme 拼历史列——但历史列可能 universe/freq 不同（不可比）。**必答**：是否只拼**同 universe+freq** 的历史列？应是，否则 PBO 把苹果和橘子混算。落地需在 `ledger.returns_matrix(theme, universe, freq)` 加过滤。

4. **加密短样本 DSR 失效**（dossier §7 + research 15 §8）：crypto 山寨/早期 Binance T 极小 + 肥尾 + 幸存者偏差，DSR 渐近正态近似失效。本设计 `min_T` 对 crypto 设 252，但 252 可能仍不够。**必答**：crypto 是否直接禁用 DSR 单点、只做定性警示？建议是，但需产品确认。

5. **var_sr_hat（V）怎么估**：False Strategy Theorem 的 V = 试验间 SR 横截面方差，需多个 trial 的 SR。早期 trial 少时 V 估计噪声大 → DSR 区间不可靠。**必答**：V 不可估时退化为旧极值近似（V 隐含=1）是否会系统性低估通缩？是 → 须在披露里写「V 未独立估计，通缩可能不足」。

6. **不可变契约 vs agent 自主迭代的治理悖论**（research 14 §8.6）：agent 看到 gate 红/黄/绿反馈必然对闸门隐式过拟合。本部件无法独力解（需 verifier agent 异模型）。**必答**：是否对 agent 隐藏 gate 细节只给「证据不足，换思路」？超出本部件范围，标为跨部件依赖。

7. **research_theme_id 的归属**：谁定义 theme 边界？若用户把每个策略当独立 theme，N 永远=1，honest-N 形同虚设。**必答**：theme_id 是否由 agent 按 AST/经济假设自动聚类分配，而非用户自填？本期允许 metadata 自填 + 标注「自填 theme 会低估 N」，长期需 agent 托管。

8. **bootstrap block_size 是新自由度**（research 15 §8.2）：`_auto_block(T)` 选 √T 是任意的，本身是未记账的 garden-of-forking-paths。**必答**：是否把 block_size 也锁定进 `NEFF_CONFIG_VERSION` 口径（不可调）？本期定锁定 √T + 报对 block_size 的敏感性。
