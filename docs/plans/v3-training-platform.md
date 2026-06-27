# v3 · 训练台（ML + DL + TensorBoard）设计蓝图

> 目标（用户原话）：软件内置 xgboost / TFT 等 ML 与 DL 模型训练能力 —— 用户与 Agent 对话输入"用哪些字段"，Agent 写代码导入**训练台**开训；**深度模型接 TensorBoard**，**非深度模型训练结束自动画图评价**，画图风格仿**回测详情页**（不止三联图，可单图）。
>
> 决策记录（2026-05-30，用户拍板）：
> 1. **打包姿态 = 全量内置一个大安装包**（torch + tensorboard 进核心，体积 GB 级换 DL 开箱即用）。
> 2. **本轮范围 = ML + DL + TensorBoard 全做**。
> 3. **不可破的底线（Agent 自加）**：确定性 demo 路径**不依赖 GPU** —— DL 的 demo 用小数据 + 少 epoch 跑 CPU、固定 seed，保住北极星"陌生人装了就能跑"。

> **v3.1 重构（2026-05-30 第二轮纠偏，用户拍板）**：上面"结构化 ModelSpec 调度器"的框架跑偏了，按以下修正：
> 1. **独立「模型中心」模块**：和数据中心并入主应用那样，做成主 app 一等区块（不是独立 SPA）。内含 **训练台** + **模型库**（训练好的 model 作一等资产，可浏览/复用）。
> 2. **训练台本质 = 跑代码**：agent+用户对话 → 生成训练脚本 → **当全功率本地进程跑**。模型目录退化成"积木/模板库"，`family` 字段只作标签，**不再是 ML/DL 执行调度开关**。
> 3. **ML/DL 不硬分**：都是代码；一段脚本里可 sklearn+xgboost+torch 混用。
> 4. **任意模型自由组合、任意数量**；**已训练 model 的输出可作新训练的输入**（`predict_with` 模型级联）。
> 5. **代码执行权限 = 本机全权（Jupyter 式）**：本地优先产品、用户自己机器，不设沙箱限制 —— GPU(CUDA/MPS)+联网+读本地数据湖+任意 import+模型自由组合。云端若开多租户再单独容器化。
> 6. **真用 GPU**：设备自动选 `cuda(NVIDIA) → mps(Apple 芯片) → cpu(Intel Mac/无 GPU)`。Mac 只有 Apple 芯片(M 系)能 GPU 训练(MPS)，Intel Mac 仅 CPU，任何 Mac 都无 CUDA。
> 7. **打包按平台分发**：CUDA torch 与 MPS torch 是不同 wheel，装不进同一包 → Win/Linux 安装包打 CUDA 版、macOS 安装包打 MPS 版（条件分支）。
>
> **执行模型澄清**："不是全进子进程" = 不是把它当受限沙箱。每次训练 = 独立进程跑脚本（这才能真吃满 GPU、可 kill、不卡 web 服务、躲开 torch 的 OpenMP 崩溃），ML 轻量结构化训练仍走进程内 `train_model`。主进程**永不 import torch**。
>
> **已落地并测试（686 passed）**：`models/catalog.py`(6 卡)、xgboost 接入、`training/`(runner 全功率进程 + lib `emit/pick_device/predict_with` + codegen + service 统一执行 + M12 登记 + emit 协议)、`models/dl/lstm_template.py`(真 torch LSTM，学习曲线+checkpoint+设备选择)、模型组合(输出→输入)。⏳ 待做：TFT 模板、ML 评价图、TensorBoard、Agent 上下文、模型中心前端、按平台打包。

---

## 0. 现状基线（开工前核对，已验证）

| 维度 | 现状 |
|---|---|
| 已有模型 | `app/backend/app/models/training.py` 仅 `lgbm / sklearn_logreg / sklearn_rf`；干净的 orchestrator：`ModelSpec → _make_model → CV 循环 → TrainResult(oos/fold metrics + feature_importance + artifact)` |
| 已装库 | lightgbm、scikit-learn、scipy、**xgboost 3.2.0(已装)**；torch/tensorboard/pytorch-forecasting **缺** |
| 执行层 | 只有 IDE 沙箱(CPU 15s / 墙钟 30s / 禁网 / 禁子进程)——**扛不住训练**，训练台必须是独立长任务执行层 |
| 实验追踪 | M12 `experiments/store.py`：Experiment/Run/ModelVersion JSONL append-only + lineage + stage 提升 —— **训练任务直接登记到这里** |
| 调度 | M13 `dag/`：百行 DAG + 重试/超时/SLA —— 训练任务可挂 DAG 做定时重训 |
| 字段 | v2 `field_catalog/`：字段宇宙 + 受控词典 —— **"输入哪些字段"的落点** |
| Agent 写码 | M18 `ide/ai_context.py build_ai_context` 喂 connector/factor/operator —— **缺模型目录 + 训练台 API** |
| 画图 | RunDetail 用 ECharts(`echarts-for-react`) + `/api/runs/{id}/series?series=X` 命名序列 + 一套 JQ 风格 token；`RunDetailPage.tsx` 1533 行 **§M15 冻结** |

平台：本机 Python 3.13 / arm64 / macOS。

---

## 1. 架构总图

```
              ┌─────────────── 对话/字段输入 ───────────────┐
用户 ── chat ─→ Agent(M14) ──(field_catalog 字段宇宙 + 模型目录 catalog)──┐
              └ slot-fill: 选 feature_cols / label / model / 超参 ───────┘
                                   │ Agent 写训练脚本(emit_train 协议)
                                   ▼
                      ┌──────────  训练台执行层  ──────────┐
                      │  TrainingService (长任务 runner)    │
                      │   ├─ ML 路径  → train_model()        │  ← 复用现有 orchestrator
                      │   └─ DL 路径  → torch epoch 循环     │  ← 新增
                      │  登记 M12 experiments + 落 artifact  │
                      └──────┬───────────────────┬──────────┘
                  ML 训练结束 │                   │ DL 训练中/后
                             ▼                   ▼
              评价 series 接口            SummaryWriter 日志 → tensorboard 子进程(反代)
                  │                                   │
                  ▼                                   ▼
        前端【训练台页】  ── ML 任务: 评价图(ECharts, 仿 RunDetail 风格, 单图为主)
                          └ DL 任务: TensorBoard tab(iframe)
```

**两族殊途同归**：模型产出预测后，都能流回现有回测/归因管线 → RunDetail 风格图。TensorBoard 只负责 DL 的**训练过程**监控。

---

## 2. 模块落点（遵循 schema → service → API → 前端）

| # | 模块 | 路径 | 职责 |
|---|---|---|---|
| 2 | 模型目录 | `models/catalog.py` | `ModelFamily(ml/dl)` + `ModelCard`(name/family/支持task/超参默认+schema/needs_dl/描述)。注册 lgbm/sklearn×2/xgboost(ML) + tft/lstm(DL)。单一事实源，供 Agent + 前端 + 校验。 |
| 3 | ML 扩展 | `models/training.py` | `ModelKind += "xgboost"`；`_make_model` 加 XGB{Classifier,Regressor,Ranker}（固定 `random_state`/`n_jobs`）。`feature_importances_` 已兼容现有重要度归集。 |
| 4 | 训练台执行层 | `training/service.py` `training/emit.py` `training/store.py` | `TrainingJob` 状态机(queued→running→succeeded/failed)；后台线程跑(非沙箱)；登记 M12；落 `data/training_runs/<id>/`(spec.json/metrics.json/curves.json/model.pkl 或 .pt/eval_series.json)。`emit_train` 协议：Agent 脚本回吐结构化结果。 |
| 5 | DL 训练路径 | `models/dl/{tft,lstm,trainer}.py` | **纯 torch 自写**(不引 pytorch-forecasting，避 py3.13/pandas2.3/numpy2 依赖地狱，且符合本仓"自写不引重库"传统)。统一 epoch 循环 → train/val loss 曲线 + checkpoint → 收敛到 `TrainResult`。`importorskip("torch")` 容错。 |
| 6 | TensorBoard | `training/tensorboard.py` | DL trainer 写 `SummaryWriter(logdir)`；按需启动 `tensorboard --logdir --port` 子进程；FastAPI 反代 `/api/training/jobs/{id}/tensorboard/*` → :端口（部署侧 nginx/Caddy 同样反代）；端口分配 + 启停生命周期。 |
| 7 | 评价图 | 后端 `eval/model_eval.py` + 前端 `components/charts/`(共享风格) + `pages/training/TrainingEvalView.tsx` | 抽 RunDetail ECharts 风格 token 成共享组件；ML 训练后算评价序列(**特征重要度 / ROC-PR / 学习曲线 / 预测-实际散点 / 残差 / 分fold IC**)；`/api/training/jobs/{id}/series?name=X`；前端新视图（单图为主）。**0 行改 RunDetailPage.tsx**。 |
| 8 | Agent 扩展 | `ide/ai_context.py` + `agent/tool_schema.py` | `build_ai_context` 注入模型目录 + 字段宇宙 + 训练台 schema；新增 `training.create_job/status/list` agent 工具。 |
| 9 | 前端训练台 | `pages/training/TrainingPage.tsx` + `api.ts` | 选字段(field_catalog)/选模型(catalog)/超参表单/开训/任务列表与状态/ML 看评价图/DL 看 TensorBoard。 |
| 10 | 收口 | `requirements.txt` + `deploy/quantbt-backend.spec` + GOAL + MEMORY | 写依赖 + 打包 collect + 全量测试绿 + 文档回写。 |

---

## 3. 关键契约

### 3.1 ModelCard（catalog 的元素）
```python
@dataclass(frozen=True)
class ModelCard:
    key: str                 # "xgboost" / "tft" ...
    family: Literal["ml","dl"]
    display_name: str
    tasks: tuple[str,...]    # classification/regression/lambdarank/forecasting
    needs_dl: bool           # True → 需 torch；前端标"重模块"
    default_params: dict
    param_schema: dict       # 给前端渲染超参表单 + Agent slot-fill
    description: str
    tensorboard: bool        # True → 训练时出 TB tab
```

### 3.2 emit_train 协议（Agent 生成脚本 → 训练台）
训练脚本最后一行打印 `__QUANTBT_TRAIN__ <json>`（仿 IDE `emit_result`）：
```json
{"oos_metrics":{...},"fold_metrics":[...],"curves":{"train_loss":[...],"val_loss":[...]},
 "feature_importance":{...},"artifact":"model.pt","tensorboard_logdir":"tb/"}
```
主进程解析 → 落盘 → 登记 M12 → 训练台可见。

### 3.3 TrainResult（已存在，DL 复用同契约）
DL 路径产 `TrainResult`，额外把 `curves`（学习曲线）与 `tensorboard_logdir` 放进 metrics/附属，保证前端两族走同一数据形状。

---

## 4. 评价图清单（ML 轨，仿回测详情页风格，单图为主）

| 图 | 类型 | 任务 | 数据源 |
|---|---|---|---|
| 特征重要度 | 横向 bar | 全部 | `feature_importance` |
| 学习曲线 | 折线(train/val) | 全部 | `curves` |
| ROC / PR 曲线 | 折线 | 分类 | OOS proba |
| 混淆矩阵 | 热力 | 分类 | OOS pred |
| 预测-实际散点 | 散点+45°线 | 回归 | OOS pred/true |
| 残差图 | 散点 | 回归 | OOS resid |
| 分 fold IC / 指标 | bar | 全部 | `fold_metrics` |

风格统一：复用 `JQ_GRID` 网格线、轴标 `#6b7280 11px`、RunDetail 配色表；深色 shell 适配。

---

## 5. DL 安全 / 北极星底线

- **demo 不依赖 GPU**：DL 样例数据集小、`max_epochs` 默认低、固定 `torch.manual_seed`，CPU 几秒内跑完；真实大训练用户自行加 epoch / 上 GPU(MPS/CUDA)。
- **torch 缺失不崩**：catalog 标 `needs_dl`，DL 相关测试 `importorskip("torch")`；ML 轨与全栈其余功能在无 torch 环境照常 657 测试绿。
- **训练 ≠ 沙箱**：训练台是受信任的本地长任务执行层，**不复用 IDE 30s 沙箱**；Agent 生成的训练脚本经 catalog 白名单模型 + 固定模板，不开放任意代码逃逸面（沙箱仍只管"用户策略代码"）。
- **资源护栏**：训练任务 wallclock 上限 + 并发上限（串行 lock，防同时多 DL 撑爆内存）。

---

## 6. 分阶段路线（本轮 = 全做，但分轨提交、全程测试绿）

- **P-A 基础**：模型目录 catalog + xgboost 接入 + 测试。✅ 本轮
- **P-B 执行层**：TrainingService 长任务 + M12 登记 + emit 协议 + REST。
- **P-C ML 评价图**：评价 series + 共享风格组件 + 训练评价视图。
- **P-D DL 轨**：纯 torch TFT/LSTM + 学习曲线 + checkpoint。
- **P-E TensorBoard**：SummaryWriter + 子进程 + 反代 + iframe。
- **P-F Agent + 前端**：ai_context 模型目录注入 + training.* 工具 + 训练台页。
- **P-G 收口**：依赖/打包 + 全量测试 + GOAL/MEMORY 回写。

每阶段独立可交付、`pytest` 绿、`RunDetailPage.tsx` 0 行变更。

---

## 7. 收尾完成（2026-05-30，"做完" goal）

四项"留待"全部落地，**全量 761 passed / 13 skipped / 0 failed**，前端 tsc + vite build 通过：

| 项 | 落地 | 验证 |
|---|---|---|
| **4 张排队 DL 模板** | `dl/architectures.py` 加 TFT(变量选择+门控残差+多头注意力)/N-BEATS(残差堆叠)/N-HiTS(多尺度池化)/DeepAR(自回归 μ/σ);卡片转 `runnable:true`;codegen 纳入 | 4 架构前向 + 端到端子进程训练(parametrize)真 torch 通过 |
| **ML 评价图** | `eval/model_eval.py`(特征重要度/学习曲线/预测-实际/残差/ROC-AUC/分fold)+ `/api/training/jobs/{id}/eval` + 前端零依赖内联 SVG `components/charts/EvalCharts.tsx`(复用 cc 深色风格)接入训练台任务表 | 后端 6 测试 + tsc/vite 通过;**0 行碰 RunDetailPage.tsx** |
| **TensorBoard** | DL trainer 写 `SummaryWriter` 到 `<job>/tb`;`training/tensorboard.py` 进程管理(端口分配/启停/复用)+ `POST/GET /api/training/jobs/{id}/tensorboard`;前端 DL 任务"↗ TensorBoard"按钮起独立端口直开(本地优先,不做脆弱反代) | 管理器 5 测试 + 真跑 DL job 确认 tb event 落盘 |
| **依赖/按平台打包** | requirements 加 xgboost/catboost/torch/tensorboard(含 CUDA index-url 说明);spec 按平台 collect torch(macOS=MPS / Win-Linux=CUDA,不同 wheel 分别构建) | 全量绿 |

**全 19 张模型卡现均 runnable**(9 ML + 10 DL);DeepAR 当前点预测用 μ 头(σ 头保留供未来区间预测,卡片已注明)。

## 9. 训练模型 → 回测兼容（2026-05-30，用户提问触发）
训练台产物可直接回测：`training/backtest_bridge.py`
(`backtest_trained_model`/`backtest_job`/`scores_to_weights`)
把 .pkl(ML)/.pt(DL) 模型经 `predict_with → 每日截面 top-N 等权(或多空)权重 → shift(1) 防前视 → 组合日收益 → 净值+指标(sharpe/maxdd/vol/winrate)`。
- REST：`POST /api/training/jobs/{id}/backtest`（默认用 job 的训练数据集+特征）。
- 前端：训练台评价面板加『▶ 回测』按钮，显示指标条。
- demo 训练数据集已补 `close` 价格列（每标的随 label 倾斜的随机游走）。

### 9.1 样本外（OOS）回测（2026-05-30 续，用户追加要求）
默认回测是 **in-sample**（在训练数据上跑，指标偏乐观，仅 sanity check）。补两种样本外：
- **跨数据集 OOS**：`dataset_id` 传**另一个**数据集（模型没训过 → 真·样本外）。两个内置 demo
  共用同一套 `FEATURES`，可互为 OOS；缺特征列 → 明确报错（不让 predict 崩）。
- **时间后段 OOS**：`oos_fraction`（如 0.3）只回测末尾该比例的交易日，返回 `oos_cutoff` 切点。
- 响应带 `is_oos` / `is_cross_dataset` / `oos_cutoff` / `train_dataset`；前端结果区用色块标注
  **in-sample(样本内,黄) vs OOS(样本外,绿)**，并显示是跨数据集还是时间后段 + 天数。
- 前端控件：回测集下拉（训练集 / 其它数据集）+「OOS后段」下拉（全段/后30%/后20%/后50%）。
- **端到端实测（ground-truth JSON 验证）**：in-sample→240天/is_oos=false；oos_fraction 0.3→72天/cutoff=2023-06-18/is_oos=true；跨数据集→crypto/is_cross_dataset=true。
- 测试：`test_backtest_bridge.py` 共 14（原 8 + OOS 6：fraction 切分/校验/跨集特征兼容/特征不匹配报错/REST 跨集/REST 后段）。

### 9.2 严格无泄露 walk-forward（2026-05-30 续，用户追加"补"）
§9.1 的"时间后段 OOS"是**近似**——它只切回测窗口，训练仍用全程数据（模型见过测试期）。本节做成严格：
- 训练请求加 `train_fraction`（如 0.7 = 只用**前** 70% 交易日训练）；`service._execute` 训练前按
  唯一日期分位切前段（ML/DL/代码三路径统一生效）；`_slice_front_dates` 负责切分 + 校验。
- 回测 endpoint：job 有 `train_fraction`、回测同数据集、用户未显式传 `oos_fraction` →
  **自动取互补后段** `oos_fraction = 1 - train_fraction`，响应标 `strict_oos=true`。
- 训练前段与回测后段同一日期分位 → 零重叠、零未来泄露。
- **ground-truth 实测**：train_fraction=0.7 → 训练截止 2023-06-17、OOS 起于 2023-06-18、
  `zero_overlap=true`、OOS 72 天(后30%)、`strict_oos=true`。
- 前端：训练表单加「训练窗口（OOS）」下拉（全程 / 前70%·留后30% / 80% / 50%）；回测徽章区分
  **in-sample(黄) / OOS·严格无泄露(绿) / OOS·时间后段(近似) / OOS·跨数据集**。
- 测试：`test_backtest_bridge.py` 共 **18**（14 + 4：_slice_front_dates 切分/校验、严格零泄露日期断言、REST 自动配对）。
- 全量 **761 passed / 13 skipped / 0 failed**；前端 tsc + vite 通过。
> 说明：此前训练台与回测引擎之间**没有桥**，examples 里是手写胶水；本次补齐一键链路 + OOS（近似 + 严格无泄露）严谨验证。
