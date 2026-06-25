---
uuid: 872af1762b4840edab8a3805fa8c3a92
title: QRO 模型↔Factor library 完整语义切分——模型本体进 Model Registry/输出进 Signal Contract/因子在 Factor Library（A-QRO-2）
status: in_progress
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
