# 给 GPT Pro 的 QuantBT v0.9.7 学术专业性还债 spec briefing

> 用法：贴给**新开**的 GPT Pro 对话（不依赖之前 patch1/patch2 对话上下文）。
> 它会输出 5 条学术技术债的**完整修复实现 spec**，让 Claude 拿到后可直接转成 Python 代码 + Contract test。

---

## 你的角色

你是有 15 年量化 + 资管经验的算法 audit 专家。你**不写代码**，你的任务是输出**可直接转成 Python 代码的实现 spec + 必测 corner case 清单**。

我（QuantBT 项目）即将给"量化算法层"补 5 条学术技术债。我需要你给出：

1. 每条债的**学术原文要求**摘要（书/论文/章节号引用）
2. 当前实现可能的**漏洞场景**（复现步骤）
3. **修复实现 spec**：数据结构 + 函数签名 + 算法步骤 + 关键不变量
4. **Contract test 清单**：至少 5 个必测 corner case，给 pytest 可抄的代码骨架
5. 实现陷阱：论文公式 vs 工程实现的常见踩坑

---

## §0. 项目身份卡（最小上下文）

- **QuantBT** = 单人 + Claude Code AI 协作的全栈量化平台，A股(paper) + 加密(Binance live)
- **代码规模**：后端 Python ~100 文件，前端 React+TS ~40 文件，测试基线 **511 通过**
- **学术路线**：López de Prado《Advances in Financial Machine Learning》2018 + Bailey-LdP《Deflated Sharpe》2014 + WorldQuant Alpha101 (Kakushadze 2016) + Pratt-Prado HRP 2016
- **已落地学术 audit**（contract test 覆盖，不能 regress）：
  - PBO CSCV: S=8 → 70 / S=16 → 12870 完整枚举 + odd-S reject + N≥10 strict
  - DSR: Bailey-LdP 2014 公式 + 偏度/峰度 + Euler 修正 + 浮点 1e-12 防御
  - Purged k-fold: t1 跨 fold 时按 label 时间区间 purge train 样本
- **此次 v0.9.7 要修**：剩 5 条算法层技术债（详见 §3）
- **三个不可动摇约束**：
  - `RunDetailPage.tsx` 冻结（只许加字段/调显示逻辑）
  - A股不接券商（禁 vnpy/easytrader/ths_trader 全部库）
  - Binance no-withdraw 启动校验 + mainnet 二次确认 + follower self-keystore

---

## §1. 当前相关代码位置 + schema 摘要

下面是 5 条债涉及的当前代码状态。Pro 给 spec 时**对照这些 schema 给可 drop-in 的接口**。

### 1.1 Walk-forward（要修 #4）

文件：`app/backend/app/models/purged_cv.py` 当前实现

```python
@dataclass
class FoldSplit:
    train_idx: np.ndarray
    test_idx: np.ndarray
    fold_index: int

def walk_forward(
    n_samples: int,
    train_size: int,
    test_size: int,
    step: int | None = None,
    embargo: int = 0,
) -> Iterator[FoldSplit]:
    """滚动 train/test 窗口。"""
    ...
```

**当前漏洞**（patch1 §G.a #4 / §G.d）：
- 现实现只生成 train/test indices，**调用方可能先全样本 GridSearch 选最优 hyperparam，再 walk-forward 验证**。这是经典 lookahead bias。
- 没有 per-window **train → param selection → test** 三段日志。

### 1.2 因子 AST 算子（要修 #5）

文件：`app/backend/app/factor_factory/expression.py` + `operators.py`

当前 44 个白盒算子（举例）：
- `ts_mean(x, window)`：滚动均值
- `ts_rank(x, window)`：滚动排名
- `cs_rank(x)`：横截面排名
- `delta(x, n)`：x - x.shift(n)
- `corr(x, y, window)`：滚动相关
- ...

**当前漏洞**（patch1 §G.a #5）：
- 没有"shift-invariance"contract test：`ts_op(series, w)[t]` 是否只依赖 `series[≤t]`？
- 如果某算子误用 polars `over()` 的中心化默认，会引入未来函数

### 1.3 FactorRegistry（要修 #6）

文件：`app/backend/app/factor_factory/registry.py`

```python
class FactorRegistry:
    def register(self, factor_id: str, expression: str, version: int) -> None: ...
    def get(self, factor_id: str, version: int | None = None) -> FactorRecord: ...
```

**当前漏洞**（patch1 §G.a #6）：
- factor_id 主键，不绑 dataset_version。**同一 expression 在 A股数据 vs Binance 数据计算结果完全不同**，但 registry 只看 expression hash，会把不同 dataset 上的因子误认为同一个。

### 1.4 DatasetVersion（要修 #7）

文件：`app/backend/app/data_quality.py`（DatasetRegistry）

```python
class DatasetVersion:
    dataset_id: str
    version: str  # 字符串，自由命名
    created_at: str
    files: list[str]  # 现在没 hash
```

**当前漏洞**（patch1 §G.a #7）：
- 同一 `version_id` 可以被重写（连接 connector 重新拉一次数据），文件 hash 没记录。**复现一次过去的 run 时无法确认数据是否真的没变**。

### 1.5 HRP（要修 #15）

文件：`app/backend/app/portfolio/hrp.py` (Pratt-Prado 2016 实现)

```python
def optimize_hrp(
    returns: pl.DataFrame,
    *,
    linkage_method: str = "single",
    distance_metric: str = "correlation",
) -> dict[str, float]:
    """returns 是 T×N，返 {symbol: weight}。"""
```

**当前漏洞**（patch1 §G.a #15）：
- 10 个高相关资产（corr ≈ 0.99）时距离矩阵接近退化，cluster tree 不稳定，权重可能 NaN 或极端集中。
- 没有 fallback 到 risk_parity 的逻辑。

---

## §2. patch1 §G.d 学术 audit 表（你要严格对齐）

下面是已建立的学术 contract，你的修复 spec 必须**保留**这些约束：

| 学术要求 | 阻断标准 |
|---|---|
| PBO CSCV S 必须偶数，组合数 = C(S, S/2) | S=8→70, S=16→12870；strict 模式 odd-S raise |
| PBO 输入是 multi-strategy matrix, N≥10 | N<10 strict raise |
| DSR 考虑 selection bias + 偏度峰度 + Euler 修正 | naive Sharpe 等价 → 拒绝 |
| Purged CV 按 label 事件跨度 purge | train/test label overlap > 0 → 阻断 |
| Triple Barrier 含 profit/stop/vertical | vertical 缺失 → 阻断 |
| Meta-label 基于 primary side | 缺 side 仍生成 → 阻断 |
| HRP 基于距离矩阵 + 层次聚类 + 递归二分 | 未生成 cluster tree → 阻断 |
| Alpha 必须白盒可表达 | 内置因子无 expression → 不能进 marketplace |
| Walk-forward 反 GridSearch | per-window selection log 缺失 → 阻断 ← **本次重点** |

---

## §3. 你要输出的 5 条债的修复 spec

### §3.1 Walk-forward 被当 GridSearch 外壳（patch1 §G.a #4）

请输出：

**a. 学术原文要求**（López de Prado 2018 §11.5 / §7.5）
- Walk-forward 的本质是什么？
- 为什么"先全样本 GridSearch 再 walk-forward 验证"破坏 OOS？
- "Combinatorial Purged Cross-Validation"（CPCV）作为升级版的简短介绍（不要求实现，只是上下文）

**b. 当前实现的漏洞复现场景**
- 给一个 50 行 Python 伪代码：用户**误用** walk_forward()，先全样本选参再分窗
- 给一个 50 行：用户**正确用法**

**c. 修复实现 spec**（数据结构 + 函数签名 + 算法步骤）

数据结构（Python type hint）：
```python
@dataclass
class ParamCandidate:
    params: dict[str, Any]
    params_hash: str  # canonical json hash

@dataclass
class WindowSelectionLog:
    fold_index: int
    train_start: int       # index
    train_end: int
    test_start: int
    test_end: int
    candidates_evaluated: list[ParamCandidate]
    candidate_train_metrics: list[float]  # 与 candidates 同长
    selected_params_hash: str
    selected_train_metric: float
    test_metric: float

@dataclass
class WalkForwardReport:
    windows: list[WindowSelectionLog]
    aggregate_oos_sharpe: float
    deterministic: bool   # 是否所有 window 都给完整 selection log
```

函数签名：
```python
def run_walk_forward(
    *,
    X: pd.DataFrame,
    y: pd.Series,
    times: pd.Series,
    param_grid: list[dict[str, Any]],
    evaluator: Callable[[dict, pd.DataFrame, pd.Series], float],
    train_size: int,
    test_size: int,
    embargo: int = 0,
) -> WalkForwardReport: ...
```

请给完整算法步骤（≥7 步），含 per-window 内：
1. 切 train fold
2. 对 param_grid 每一项**只在 train 内** evaluate (CV 或 train-only metric)
3. 选 selected_params
4. 在 test fold 计算 oos metric
5. 写 WindowSelectionLog（含所有 candidate train metric，便于 audit）
6. ...

**d. Contract test ≥ 5 个**（给 pytest 代码骨架）

必测 corner case：
- (1) **GridSearch leak 阻断**：用户外部传"已经全样本最优的 single param" → 应 raise 或 warning
- (2) per-window selection log 完整性：所有 window 必须有 candidates_evaluated 且 ≥ 1
- (3) 各 window 选不同 params 时正确记录
- (4) test fold 不含 train 任何样本（含 embargo）
- (5) deterministic 字段：缺日志时 False
- ...

**e. 工程实现陷阱**（≥4 条）

例：很多用户会传一个已经"在外部跑过 GridSearchCV"的 Pipeline 进来。怎么从签名层面阻断？

---

### §3.2 因子 AST 算子 lookahead 防御（patch1 §G.a #5）

请输出：

**a. 学术原文**（Kakushadze 2016 + Lopez de Prado 2018 §3）
- 时序算子的"causal"要求（output[t] 只能依赖 input[≤t]）
- polars `over()` / pandas `rolling().mean()` 的默认中心化陷阱

**b. 漏洞复现**
- 构造单调递增序列 `x = [1, 2, 3, ..., 100]`
- 期望 `ts_mean(x, 5)[t]` 严格 <= `x[t]`，因为窗口在 t-4..t
- 如果实现误用 center=True，输出会 > x[t]，**lookahead 暴露**

**c. 修复实现 spec**

提供一个泛化 contract test runner：
```python
def assert_shift_invariant(op_fn: Callable, op_name: str, *, window: int = 5) -> None:
    """
    对任意 ts_/cs_ 算子 op_fn(series, window) 做 shift-invariance 检查：
      1. 构造 series_extended = series ++ [future values]
      2. ts_op(series_extended)[:len(series)] 必须 == ts_op(series)
    """
```

要求每个 ts_/cs_ 算子在测试套件中跑这个 assert。

**d. Contract test ≥ 6 个**
- ts_mean 单调序列：output[t] <= max(input[0..t])
- ts_rank 末尾值修改不影响中间值
- cs_rank 不依赖时间序
- delta(x, n) 等价于 x[t] - x[t-n] 严格
- 拼接 future 验证 ≥ 4 个 ts 算子
- polars over() chain 测试（cs_op(ts_op(x)) 双阶段 eval）

**e. 实现陷阱**：polars 双 `over()` chain 在某些版本返 all-null 的问题（v0.7 已修但要保持）。

---

### §3.3 FactorRegistry 绑 dataset_version（patch1 §G.a #6）

请输出：

**a. 概念**：为什么 factor 必须绑数据？

举例：`ts_mean(close, 20)` 在 A股 hs300 vs Binance perpetual 计算的是**完全不同的两个时间序列**。如果 registry 只看 expression hash，会把这两个误认为同一因子，导致 IC 衰减分析、生命周期评估全错。

**b. 修复实现 spec**

新 schema：
```python
@dataclass
class FactorBinding:
    factor_id: str
    expression: str
    dataset_id: str
    dataset_version: str   # 必填
    universe_snapshot_id: str | None  # 若 dataset 多 universe
    
    @property
    def composite_key(self) -> str:
        return f"{self.factor_id}::{self.dataset_id}::{self.dataset_version}"
```

API 改动：
- `register(factor_id, expression, dataset_id, dataset_version)` 必填 dataset_version
- `get(factor_id, dataset_version)` 没 dataset_version 时返 latest 但 warn
- `list_bindings()` 列出该 factor 在哪些 dataset 上 registered

**c. Contract test ≥ 5 个**
- 同 expression 在两 dataset_version 注册 → 两个独立 entry
- get 时缺 dataset_version 给 warning
- 删 dataset_version 时级联清理 factor binding
- ...

**d. 实现陷阱**

数据库 migration：现有 factor_registry.json 已经有数据，新 schema 要兼容。给 migration 步骤。

---

### §3.4 dataset_version 内容不可变（patch1 §G.a #7）

请输出：

**a. 概念**：复现性的最小硬约束

López de Prado 2018 §1 反复强调："Same dataset_version + same code → same result，否则全是错觉。"

**b. 修复实现 spec**

```python
@dataclass
class DatasetManifest:
    dataset_id: str
    version: str
    files: list[FileEntry]
    created_at_utc: str

@dataclass
class FileEntry:
    relative_path: str
    sha256: str       # 必填，文件内容 SHA-256
    size_bytes: int
    row_count: int | None
```

API:
- `create_version(dataset_id, files)` → 计算每文件 sha256，写 manifest
- `verify_version(dataset_id, version)` → 重算 sha256 vs manifest，不匹配 raise
- `register_version` 时如同 version_id 存在，新 files hash 必须**完全匹配**否则 raise

**c. Contract test ≥ 5 个**
- 新 version 写入后再读 manifest hash 一致
- 同 version_id 不同 hash 文件覆盖 → raise
- verify_version 重算 sha256 → 通过
- 文件被外部修改后 verify 应 raise
- 多文件 dataset hash 顺序无关（按 path 排序）

**d. 实现陷阱**：parquet 文件元数据（compression / sort order）可能影响 hash 但内容相同。spec 推荐策略。

---

### §3.5 HRP 协方差奇异 fallback（patch1 §G.a #15）

请输出：

**a. 学术原文**（Prado-Pratt 2016 / López de Prado 2018 §16）
- HRP 三步：(1) correlation → distance → linkage tree；(2) quasi-diagonalization；(3) recursive bisection 分配权重
- 协方差矩阵接近奇异时（高相关资产 / N > T） linkage tree 不稳定

**b. 漏洞复现**

```python
# 10 个资产，corr=0.99 几乎完全相关
returns = generate_high_corr_returns(n_assets=10, corr=0.99, days=252)
weights = optimize_hrp(returns)
# 当前: 权重可能 NaN / 集中在 1-2 个资产
```

**c. 修复实现 spec**

3 段防御：

**(1) 检测奇异性**：
```python
def _is_near_singular(cov: np.ndarray, threshold: float = 1e-6) -> bool:
    eigvals = np.linalg.eigvalsh(cov)
    return bool(np.min(eigvals) < threshold * np.max(eigvals))
```

**(2) Fallback 策略**（≥3 条，按优先级）：
- 协方差 shrinkage（Ledoit-Wolf）后重试 HRP
- 极端时降级 risk_parity（仅用 diagonal vol）
- 最坏 equal_weight + warning

**(3) 返回结构升级**：
```python
@dataclass
class HRPResult:
    weights: dict[str, float]
    fallback_used: Literal["hrp", "hrp_shrunk", "risk_parity", "equal_weight"]
    singularity_detected: bool
    cluster_tree_serialized: str  # JSON, 便于复现
```

**d. Contract test ≥ 6 个**
- 10 个 corr=0.99 资产 → fallback_used != "hrp"，无 NaN
- 5 个 corr=0.3 资产 → fallback_used == "hrp" 正常
- 协方差为对角阵 → 等价 risk_parity
- 权重 sum=1，所有 ≥ 0
- cluster_tree_serialized 可重新构造
- 单资产输入 → 100% 权重

**e. 实现陷阱**：scipy.cluster.hierarchy.linkage 在 NaN 输入会无声 crash 或返空。

---

## §4. 通用输出格式要求

每条独立一节（§3.1 - §3.5），每节硬性结构：

```markdown
## §3.X 名称（patch1 §G.a #Y）

### a. 学术原文要求
（300-500 字，必须含论文/书章节引用）

### b. 当前漏洞复现
（≤80 行 Python 伪代码，可直接 pytest）

### c. 修复实现 spec
（数据结构 + 函数签名 + 算法步骤，500-1000 字）

### d. Contract test 清单
（5-6 个，每个含 pytest 函数骨架 + 期望 assert）

### e. 工程实现陷阱
（4+ 条，论文 vs 实际代码常踩坑）
```

整版总字数 ≥ **5500**。每节 800-1200 字。

---

## §5. 通用约束（patch1 风格延续）

- **不许 emoji**
- **不许营销话术**（强大/前沿/划时代）
- **数字必须有学术出处**（如"PBO < 0.3" 必带 "Bailey-LdP 2014" 等）
- **不许编 API**（QuantBT 当前栈：FastAPI + Polars + DuckDB + scipy + numpy + LightGBM；scipy.cluster.hierarchy / numpy.linalg.eigvalsh / hashlib.sha256 等都 OK；其他库要先 check）
- **不许 "未来扩展"** 这种话；只给 v0.9.7 范围内要做的
- **每节末尾给 TL;DR for this section** 3-5 条 bullet

---

## §6. 我（用户）使用流程

1. 把本文件 [docs/strategy/_PROMPT_FOR_GPT_PRO_ACADEMIC_AUDIT.md](docs/strategy/_PROMPT_FOR_GPT_PRO_ACADEMIC_AUDIT.md) **整段**贴给新 GPT Pro 对话
2. 它输出 5 节 spec
3. 我把它的输出存为 `docs/strategy/gpt_pro_academic_audit_v0.9.7.md`
4. Claude 拿到后：
   - 把 §3.x.c 修复 spec 转成 Python 代码
   - 把 §3.x.d Contract test 转成 `tests/test_academic_audit_v2.py`
   - 跑 pytest 全过后 commit v0.9.7
   - 量化专业性硬约束 100% 落地，CI 阻断不绕过

GO.
