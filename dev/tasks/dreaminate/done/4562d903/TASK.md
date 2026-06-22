---
uuid: 4562d90381fd488798d9e6b03c1e1438
title: Model台后端接线 — JobDetail/IoSpec/walkforward/promote字段/图codegen/研究判定
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: backend
source: interaction
source_ref: 2026-06-21 epic cfb0fea9 拆分（Claude Design handoff DC→React）
depends_on: [b2682edc2c3b4170a28df7baf150a4ed]
---

# Model台后端接线 — JobDetail/IoSpec/walkforward/promote字段/图codegen/研究判定

## Scope [必填]
为 Model 台四子台补齐后端缺口端点与字段（JobDetail 富文档持久化+暴露、ModelCard IoSpec 单一来源、walk-forward 逐窗端点、promote gate 字段贯通 approver/reason/risk_restated、构建台图→nn.Module codegen 经子进程 harness、研究台理论判定+论文/文章 LLM 提炼端点）；**不做** 任何前端 React 实装（属本 epic 其它卡）、不改 promote/approve 已有门逻辑本身（只把已强制的字段透传上去）、不做构建台任意图全集 codegen（见 Open Questions，本卡只做子集）。

## 上下文 / 动机 [按需]
设计稿四子台（作业台/模型库/构建台/研究台）的治理元素与 dev/RULES + GOAL 高度对齐，是 load-bearing 部分。理解材料 `/tmp/qbt-modelDeck.md` §⑤/§⑦ 已盘清「设计稿要 vs 后端有」：promote 审批门字段（approver≠creator/reason/risk_restated）后端 `approve_promotion` 已**全量强制**（`app/backend/app/main.py:529`、`app/backend/app/experiments/store.py:260`），本卡只需保字段贯通、补缺口端点。M6「主进程不碰 torch」是构建台 codegen 的硬约束——任意图编译/训练必须落 `runner.run_code()` 子进程（`app/backend/app/training/runner.py:41` 已 `subprocess.run([sys.executable,...])`），主进程只做 AST 拼装、不 `import torch`。研究台 LLM 严格止于「提炼数学/可证伪假设」，产出强制导向因子台 IC 检验（M11），**绝不**直出投资结论（R7 措辞红线）。依赖 M1 b2682edc（前端骨架/路由就位后这些端点才有消费方）。

## 接线点（file:line，实现时复核）[必填]

| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/training/store.py` | `TrainingJob` L30-50（`to_dict` L49） | 扩展 dataclass 加 `detail: dict` 字段（why/data/window/label/design/arch/hparams + sections + io_spec），`to_dict` 透传；提交时从 request 持久化进 `<job_id>/` JSONL（沿用 append-only latest-wins） |
| `app/backend/app/main.py` | `training_job` L766、`training_job_eval` L774 | 新增 `GET /api/training/jobs/{id}/walkforward` 端点（逐窗：训练段/测试段/OOS超额/NDCG），从 artifact 读 result.json 的 fold/walk 明细；`to_dict` 已带 detail 自动暴露 |
| `app/backend/app/models/card_loader.py` | `ModelCard` L31-50、`parse_model_card` L99-118、`to_dict` L60 | frontmatter 加可选 `io_spec`（in_groups/out_groups/in_pre/out_note），dataclass 加 `io_spec` 字段、parse 解析、`to_dict`/`to_detail` 暴露（单一来源：dashboard/registry/canvas io 节点共用） |
| `app/backend/app/main.py` | `promote_model` L481-526、`approve_promotion_gate` L529-540 | **不改逻辑**，复核 approve 已强制 approver/reason/risk_restated（`ApproverEqualsCreator/EmptyReason` L538）；只确保 Model 台 registry 端点把 gate 的缺口清单/字段需求透传给前端 |
| `app/backend/app/training/codegen.py` | `spec_to_code` L34、`_dl_code` L65 | 新增 `graph_to_code(graph: dict)`：bdNodes/bdEdges 拓扑排序→形状推断→拼 `nn.Module` 源文本（**纯字符串拼装，主进程不 import torch**） |
| `app/backend/app/main.py` | `training_codegen` L752-758（POST /api/training/codegen） | 扩展接受图 JSON（payload 带 `graph` 走 `graph_to_code`，否则旧 `spec_to_code`，向后兼容不破坏既有 spec 路径） |
| `app/backend/app/training/runner.py` | `run_code` L41-78（`subprocess.run([sys.executable...])` L66） | 图→代码的编译/训练复用此子进程 harness（图 codegen 产物落临时脚本→子进程跑，绝不主进程编译 torch） |
| `app/backend/app/main.py` | 训练路由段尾（≈L893 后） | 新增研究台端点：`POST /api/research/feasibility`（图理论判定：维度自洽/梯度可传/√d_k/复杂度→checks+结论，纯数学、无 torch）、`POST /api/research/distill`（论文→数学 / 文章→可证伪假设，LLM 提炼，输出强制带「须先因子台 IC 检验」导流，不出投资结论） |
| `app/backend/app/training/agent_context.py` | `model_choices_block` L24 起 | 研究台/构建台 agent system_prompt 复用「卡内约束 + 先确认再动手」措辞，提炼端点 prompt 显式禁「下投资结论」 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 种「approve 用 `approver == created_by`（同人自批）」→ 门必抓：`POST /gates/{id}/approve` 返 422 `ApproverEqualsCreator`（`store.py:260` 已强制，本卡测它透传不被绕过）。变异要杀：把 approve 端点 `approver` 默认成 `created_by` 或吞掉 `ApproverEqualsCreator` 异常 → 测试必红（INV-5 晋级 approver≠creator + 验证背书）。
2. 种「`graph_to_code` 在主进程直接 `import torch` 编译/实例化 nn.Module 校验形状」→ 门必抓：单测断言 codegen 模块导入链不引入 torch（`sys.modules` 无 torch / 静态扫无 `import torch`），编译/训练只经 `runner.run_code` 子进程。变异要杀：把形状校验改成主进程 `torch.zeros(...)` 实跑 → 测试必红（M6 主进程不碰 torch）。
3. 种「研究台 `/api/research/distill` 论文/文章提炼后直接返回『该因子可信/可买入/已排除过拟合/建议建仓』类投资结论」→ 门必抓：测试对提炼输出做禁词扫描（命中「可信/安全/排除过拟合/保证/建议买入/直接入模」即拒），并断言输出必含「须先在因子台做 IC+单调性+OOS 检验（M11）」导流字段。变异要杀：去掉禁词过滤或去掉因子台导流 → 测试必红（R7 措辞红线 + M11 因子生命周期门）。
4. 种「promote staging/production 缺 `reason` 空串」→ 门必抓：approve 返 422 `EmptyReason`（`store.py` 强制），字段透传不被默认值填平。
5. 种「JobDetail / IoSpec 字段在 `to_dict` 被吞（前端拿不到 io_spec/walk-forward）」→ 门必抓：序列化测试断言 `to_dict()` 含 detail.io_spec 与 walkforward 端点返逐窗非空（防字段静默丢失）。

## 复用 [按需]
- 晋级门机制全量复用：`MODEL_REGISTRY.promote/approve_promotion`（`store.py:275/260`）、`ApprovalGateService`、`GateRejection.gap_list`、`main.py:481-550` 四端点——本卡**只透传字段、不重写门**。
- 子进程 harness 复用 `runner.run_code`（`runner.py:41`，已注入 PYTHONPATH + torch/OMP/MPS 安全环境）。
- JobDetail 持久化沿用 M12 append-only + latest-wins JSONL 模式（`store.py` 头注释）。
- IoSpec 走 ModelCard frontmatter（仿现有 param_schema/pros/cons 解析，`card_loader.py:99`）。
- codegen 拼装复用 `spec_to_code/_dl_code`（`codegen.py:34/65`）的字符串模板路径。

## 红线 [按需]
- 主进程绝不 `import torch` / 实例化 nn.Module 跑形状校验——图 codegen 是纯 AST/字符串拼装，编译训练唯经子进程（M6）。
- promote/approve 字段透传不得削弱已有门：approver≠creator / reason 非空 / risk_restated / 血统门（confirmatory `can_touch_final_oos`、非 confirmatory 走真钱 409）一条不松（INV-5 / T-019 / D-T024）。
- 研究台 LLM 只提炼数学/可证伪假设，输出措辞禁「可信/安全/排除过拟合/保证」，强制导向因子台 IC 检验（R7 + M11）；不导向直接实盘/真钱晋级。
- 弱点字段（walk-forward 逐窗 OOS 超额、CV、blineage）默认随接口返回、不染绿、不折叠藏（R25，呈现层属前端卡，但字段本身后端须诚实给全）。

## 非目标 [按需]
- 不做任何前端 React 组件/页面（属 epic cfb0fea9 其它卡）。
- 不做构建台「任意图」全集 codegen（仅做 Open Questions 选定子集）。
- 不做 TensorBoard HISTOGRAMS/GRAPHS/HPARAMS 真实 event 写入（现有 tensorboard 端点 `main.py:866/885` 之外的扩展另卡）。
- 不做训练 pause/暂停端点（设计稿有 ⏸，后端缺，另卡）。
- 不改 promote/approve 门的判定逻辑本身（只透传字段）。

## Open Questions（已决 D/总）[按需]
1. [已决] 构建台图→nn.Module codegen 本卡先做子集 (a) 仅线性链(input→linear/conv1d/lstm→head→output，无分支无嵌套，覆盖 90% 树/序列模型、形状推断闭合、风险最低)；(b)分支、(c)机制嵌套留后续里程碑。本卡只产前端「图→代码字符串」预览(mock codegen)，子进程真编译训练入作业台属后续卡(保 M6 主进程不碰 torch)。— leader 2026-06-21 工程决

## 验收一句话 [必填]
种「同人自批 promote / 主进程编译 torch / 研究台直出投资结论」三种坏 → 对应门必抓（422 ApproverEqualsCreator、torch 不入主进程导入链、提炼输出禁词+强制因子台导流），且 JobDetail/IoSpec/walk-forward 字段经 to_dict 全量诚实暴露、不破现有 training/models/experiments 测试基线。
