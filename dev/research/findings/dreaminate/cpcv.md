# FINDING · R4 CPCV（Combinatorial Purged Cross-Validation）多路径回测

- **蒸馏自**:GOAL §4「CPCV '更强默认' 双轨 walk-forward（R4）」+ 决策 R4=B + 并行双脑（codex xhigh 独立推导，确认 φ 恒等 + 路径重建 + 修正 purge 逐段/PBO 红线/embargo 语义）。
- **证据强度**:强 —— 出自 López de Prado 2018《AFML》Ch.12；φ=C(N−1,k−1) 双计数可证；扩展已有 `models/purged_cv.py`（purged k-fold + embargo + walk_forward 已建并测）。
- **适用域**:中低频、时序标签可定义 t1（label 结束时间）。**关键诚实边界（R4=B）**：CPCV **仅合成(Heston)环境占优、真实市场未确立** → 作 walk-forward 的**双轨稳健性证据**、**绝不**自动判「CPCV 赢」；WF=部署形态证据、CPCV=路径稳健性证据，分歧时并陈不替用户拍。

## 核心主张（可证伪）[必填]

**如果**把 N 个时间连续 group 中每次选 k 个作 test（C(N,k) 组合，train 经 purge+embargo），**则**可重组出
**φ=C(N−1,k−1)=k·C(N,k)/N** 条「各覆盖全时间线一次」的回测路径 → 给单策略一个 OOS 性能**分布**（非单点），
暴露过拟合方差；**而** purge 按每个 test group 区间逐段剔除标签重叠 train（无泄露），embargo 剔 test 后窗。
**命门红线**：φ 条路径**绝不冒充 φ 个策略**喂 PBO（单策略 PBO 恒 N/A）；多路径分布喂 DSR 取保守分位。

### 数学（公式 + 推导）

**组合与路径数**（双计数证明）：
$$S=\binom{N}{k}\ \text{组合};\quad \text{每 group 在 test 出现}\ \binom{N-1}{k-1}\ \text{次}$$
按组合计 (group,combo) 出现 = k·C(N,k)；按 group 计 = N·φ ⇒ **φ = k·C(N,k)/N = C(N−1,k−1)**。
（k·C(N,k) 必被 N 整除——可作不变量。）边界：k=1 ⇒ φ=C(N−1,0)=1（退化单条 purged k-fold OOS 路径）；k=2 ⇒ φ=N−1。

**路径重建**（最易错，用 `path_matrix` 无歧义实现）：
固定组合的字典序 `combos = list(combinations(range(N), k))`；
$$\text{path\_matrix}[g, p] = \text{第 }p\text{ 次把 group }g\text{ 放进 test 的 combo\_id}\quad(\text{shape }N\times\varphi)$$
第 p 列即第 p 条路径：路径 p 上 group g 的 OOS 预测取自组合 `path_matrix[g,p]`，按 group 时间序拼接。
**Golden case** N=4,k=2（combos 01,02,03,12,13,23 = id 0..5）：
```
path_matrix = [[0,1,2],   # g0 ∈ 01,02,03
               [0,3,4],   # g1 ∈ 01,12,13
               [1,3,5],   # g2 ∈ 02,12,23
               [2,4,5]]   # g3 ∈ 03,13,23
```
按 (combo,group) occurrence 分配，**不要求**每条路径由若干「完整 combo」拼成（N/k 非整时本就不成立）。

**Purge（防泄露，沿用 purged_cv 的 t1 区间口径，但逐 test group 段判）**：
train 样本 i 的事件区间 [t0_i,t1_i] 与**任一** test group 的并集区间 [t0_j,t1_j] 重叠即剔：
$$\text{剔除 iff}\quad \exists j:\ t0_i\le t1_j\ \wedge\ t1_i\ge t0_j$$
**必须逐 test group 段判、绝不用全局 min(test)..max(test) 合成大区间**（多个非连续 test group 会误删中间合法 train）。

**Embargo（AFML 语义=test 后）**：每个 test group 结束后 embargo 窗内样本不进 train（末组越界自然截断）。
**诚实标注**：此 embargo 语义（test 后）与 `purged_kfold` 的两侧 embargo 不同 → CPCV k=1 与 purged_kfold **结构等价**（φ=1、N 组各测一次）但**不声称字节等价**（embargo 口径已先定、写进测试）。

### 喂 PBO/DSR（命门 · 路径数≠策略数）
- **Sharpe 分布**：输出 path_sharpe 的 min/q05/q25/median/q75/q95/max + frac≤0（**绝不压成漂亮单点**）。
- **DSR**：逐路径算 DSR，gate 取 **q05 或 min** 作保守 DSR（不取均值/最优）。
- **PBO 红线**：CScV-PBO 的列必须是 **distinct strategy/config**；单策略即便 φ≥10 路径，**PBO 恒 N/A**——绝不用路径数凑策略数（范畴错误，类比 §5 rolling-PSR≠DSR）。多策略时可对每 path_id 跑 PBO、报 PBO 分布取 q95/max（PBO 越高越坏）。

### 消费侧 ① · per-path 模型 OOS 指标分布（2026-06-25 落地·report-only）
`models/training.py::cpcv_oos_metric_distribution`：每条 φ 路径覆盖全样本一次 → 对每路径算模型 OOS 主指标
（regression→**r2**[baseline 0]；二分类→**roc_auc**[baseline 0.5·重组 proba 路径]；多分类/lambdarank/无 proba
→ unsupported_task 诚实）→ 分布 mean/std/**q05**/min/median/max/frac_below_0。
**q05/路径方差 = 过拟合脆弱度**：q05≪mean 或方差大 = OOS 表现高度依赖切分（split-fragile）。复用
`_fit_predict_fold`（从 train_model 抽出·行为不变·与训练同口径）+ cpcv.py 的 cpcv_splits/assemble_cpcv_paths。
**report-only**：不接 gate、不替方法学拍板。判别器命门：强信号→r2 高稳、噪声→r2≈0/负（MUT「预测 misalign」→
强信号 r2 崩到 -0.87→判别器红，证路径重组对齐正确）。
**未落（follow-on·用户方法学）**：② q05 接 promote/overfit gate 的阈值/口径 + ③ Sharpe/DSR 口径需
**prediction→收益转换**（=用户方法学决策，本件用模型自身 r2 避开）+ 分类/排序任务（proba/group 路径重组）。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么(扩展不替换) |
|---|---|---|
| `app/models/cpcv.py` | 新建 | cpcv_splits(返回 list[CPCVSplit],复用 purged_cv 的 t1-purge 口径) + n_cpcv_paths/n_cpcv_combinations + build_path_matrix + assemble_cpcv_paths + cpcv_metric_distribution |
| `app/models/purged_cv.py` | 复用 FoldSplit/t1 purge 思路 | 不改 |
| `app/eval/`（消费侧，按需） | 多路径分布喂 DSR 保守分位 | additive |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. 组合数 ≠ C(N,k) / 路径数 ≠ C(N−1,k−1) / k·C(N,k)%N≠0 → 抓（golden N=4,k=2 path_matrix 逐元素核）。
2. **每条路径覆盖每样本恰一次**（无重无漏）；某路径漏/重 group → 抓。
3. **purge 泄露 sentinel**：去 purge → train 存在与 test 标签区间重叠的样本（种 t1 跨界）→ 门必抓；逐段 vs 全局区间：构造非连续 test group + 中间合法 train，断言全局口径会误删而逐段不误删。
4. **PBO 红线**：单策略 φ 路径喂 PBO 必判 N/A（绝不用路径数当策略数）。
5. C(N,k) 爆炸 → 超 max_combinations 必 raise（绝不静默采样致 φ 公式失效）。
6. 边界拒：N<2 / n_samples<N / k<1 / k≥N / times 未排序 / len(t1)≠len(times) / 某折 train 空。
7. k=1 → φ=1 且全覆盖（结构等价 purged k-fold，不声称字节等价）。
8. DSR 喂法：多路径取 q05/min 保守（种「均值掩盖差路径」→ 保守分位仍暴露）。

## 复用 [按需]
- `app/models/purged_cv.py`：t1 标签重叠 purge 口径、embargo、FoldSplit。
- `app/eval/dsr.py`：逐路径 DSR。`math.comb` 算组合/路径数。

## 未验证残余（诚实）[必填]
- **R4=B caveat**：CPCV 真实市场优越性未确立 → 双轨呈现、不自动判赢（已入 API/文案设计）。
- **CPCV 只隔离索引**：scaler/特征选择/target encoding/调参必须每折内 fit，否则路径重建再对也是把泄露预测拼漂亮（R5 用法 caveat，docstring 披露）。
- **embargo 语义**：定为 AFML test-后；与 purged_kfold 两侧不同（已标注、非 bug）。
- ~~**path-metric→gate 接线**：本切片给分布 + 保守分位 helper；接进 promote gate 的生产路径属后续（建议 mint）。~~ **✅ done（2026-06-25·done 卡 89e7be1e）**：q05 保守分位接进 `run_overfit_gate` + `gate_runner.evaluate_overfit_gate`（promote 生产路径）。**护栏铁律**：默认 `report_only` 绝不改裁决（守不替方法学拍板）；`cpcv_conservative` 用户 opt-in 才 green→yellow advisory；**q05 是多证据三角[PBO/DSR/CI]外第四类弱证据 → 绝不硬 red、绝不升级**（守 R2 单支不承重·路径稳≠策略好·**CPCV 路径绝不喂 cscv_pbo** 跨策略红线）。MUT-A/B/C 三变异验证有牙。**③ 残**：cv_scheme UI 选项 + 双轨 report 不自动判赢 + Sharpe/DSR prediction→收益转换（用户方法学·池卡 861182e6 ③）。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| (本切片) | CPCV splits+路径重建+分布数学对齐理论、φ/覆盖/purge 不变量守门、PBO 红线、爆炸/边界拒、双轨 caveat | P1 | — |
| 89e7be1e ✅done | CPCV q05 保守分位接进 overfit gate（report_only 默认 / cpcv_conservative opt-in·绝不硬 red/不升级·守不替拍板） | P2 | 本切片 |
| f1bd08f2 ✅done | 最后一公里：promote_ide_run 真实路径读 emit cpcv 透传 gate（此前恒 cpcv=None 死接线·审计 #8）→ CPCV 全链端到端贯通至生产晋级 | P2 | 89e7be1e |
| 861182e6 ③ 池卡留 | cv_scheme UI 选项 + 双轨 report 不自动判赢 + Sharpe/DSR prediction→收益转换（用户方法学） | P2 | 89e7be1e |
