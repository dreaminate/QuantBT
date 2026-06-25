---
uuid: 872af1762b4840edab8a3805fa8c3a92
title: QRO 模型↔Factor library 完整语义切分——模型本体进 Model Registry/输出进 Signal Contract/因子在 Factor Library（A-QRO-2）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P1
area: qro
source: goal
source_ref: GOAL §1 语义边界(行 154-157:模型本体进 Model Registry·模型输出进 Signal Contract·因子在 Factor Library·策略通过 StrategyBook)+§9 因子/模型/信号/策略边界(三纯库·守门器解耦)；A-QRO-1(f19c5c19)done 卡残余:A-QRO-2 完整语义切分
depends_on: [f19c5c192f4a44cc95fd159ea04d94e5]
---

# QRO 模型↔Factor library 完整语义切分（A-QRO-2）

## Scope [必填·先读 GOAL §1 行154-157+§9]
A-QRO-1（f19c5c19）已建 QRO 信封 + 状态六轴 + 结构门「模型本体塞进 Factor library→拒」。本卡完整兑现 §1 语义边界：① **模型本体进 Model Registry**（ML/DL 本体·非 Factor）② **模型输出进 Signal Contract**（Forecast→Signal·typed contract）③ **因子在 Factor Library 创建管理**（算术/expression/mining 纯库·非模型）④ **策略通过 StrategyBook 表达**。在 QRO 层 enforce 每类资产的归属库 + 跨类误放→拒（§9 可证伪验收「模型文件作为因子入库→拒」「Signal 未绑定 Signal Contract→拒」）。**读 GOAL §9 三纯库边界 + 守门器解耦（守门指标不进 generator fitness）。**

## 领地（只动·扩展不替换）
扩 `app/backend/app/qro/`（envelope 加 model/factor/signal 库归属断言·不改 A-QRO-1 已建结构）。**读只读** models/(Model Registry)、factor_factory/(Factor Library)、signals/(Signal Contract)、strategy/(StrategyBook) 的现有契约（判归属·不改它们）。**绝不碰** main.py、A-QRO-1 已建核心结构（扩展不替换）、其他在飞线(compiler/execution/portfolio)。

## 可证伪验收（种坏门必抓·§1/§9）
1. 模型本体（ML/DL）作为因子入 Factor Library → 拒（A-QRO-1 已有·本卡完整化·MUT 放过→红）。
2. 模型输出（Forecast）未绑 Signal Contract 进信号层 → 拒（§9）。
3. 因子（算术/expression）误放进 Model Registry → 拒；策略本体误放进 Factor/Model → 拒。
4. 守门指标（DSR/PBO/IC gate）进入 generator fitness → 拒（§9 generator/gatekeeper 解耦）。
5. 正路径：各类资产正确归属库·跨库 typed 引用（策略引 factor id/model id）放行不误伤。

## 红线 [按需]
单一身份源 ids.py 不另造·扩展不替换(A-QRO-1 结构不改)·语义边界不混·守门器解耦·先读 GOAL §1/§9 再动手·撞 decisions 未覆盖岔路停报中心。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不改 Model Registry/Factor Library/Signal Contract/StrategyBook 现有实现（只在 QRO 层判归属）；不建前端。本卡只 QRO 层语义切分门。

## 收尾结果（done）
**实装（扩展不替换·只动 qro/ + 新增测试文件）**：在 A-QRO-1 信封/状态六轴/四命门之上**扩**三道库归属断言，每道**复用单一源**（RULES §1）、重依赖懒导入（同 admit_factor_qro 范式）：
- `assert_signal_contract_bound(qro)`（验收②）——Forecast/Signal 进信号层必须绑定 Signal Contract（model_ref 回指真本体[复用 `signal_contract.looks_like_model_body`] / 显式契约 id / lineage 回指 任一）；裸预测=孤儿信号→拒。
- `admit_model_qro(...)`（验收①反门/③a）——与 admit_factor_qro 对称：family∉{ml,dl}→拒、body_ref 非本体文件（算术 expression）→拒（复用 `looks_like_model_body`，不另造本体判定）。
- `assert_generator_fitness_clean(keys)`（验收④守门器解耦）——守门指标进 generator fitness→拒；判定**复用** `factor_factory.mining.is_gate_metric_key`（GATE_METRIC_KEYWORDS 单一黑名单、与前端镜像），QRO 层零第二黑名单。

**改动文件**：`app/backend/app/qro/envelope.py`（+3 门 + import Iterable + __all__）、`app/backend/app/qro/__init__.py`（barrel 扩 3 导出）、新增 `app/backend/tests/test_qro_semantic_boundary.py`（67 对抗测试）。**未碰** main.py / A-QRO-1 核心 / models/factor/signal/strategy 实现。

**验证（scoped·🟡 全量由中心跑）**：
- scoped `test_qro_envelope.py + test_qro_semantic_boundary.py` = **116 passed**（A-QRO-1 49 + 本卡 67，未破 A-QRO-1 基线）。
- **MUT 实证（种坏门必抓）**：三门各打成「常开破门」→ 对抗套 **30 failed**（②4 红/③a 3 红/④ 23 红）、正路径 37 仍绿（破门精确归因）；复原后 **116 passed**、无 MUT-TEMP 残留。
- collect-only 全量 = **2257 collected**（= 基线 ~2190 + 本卡 67，无采集错=基线完好）。
- 端到端经 barrel：3 正路径准入 / 3 误放（expr→model_reg、gate-metric→fitness、unbound-forecast）皆拒。

**验收逐条**：①模型本体→因子库拒（全 7 后缀+kind+对象级+收编卡 完整化）✅ ②Forecast 未绑契约→拒 ✅ ③a 因子→Model Registry 拒 / ③b 策略→Factor/Model 拒（assert_library_membership）✅ ④守门指标→generator fitness 拒（复用 mining 单一源）✅ ⑤各类正确归属+策略跨库引 factor/model id 放行不误伤 ✅。

**诚实残余/限界**：① 本门判**声明/结构级**归属（QRO 层关口），不证明无泄露——泄露/血统在 `signal_contract.SignalContractRegistry` 单一源已管，QRO 不重算（避免双源）。② 全量后端套件**未由本线跑**（只 scoped+collect-only）；中心整合跑全量+review+land。③ 无新公式→未造 MathematicalArtifact（守红线）。④ 拍板项：GOAL §1/§9 契约已覆盖本卡全部岔路，**无未决项需停报**。
