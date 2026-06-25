---
uuid: 25247eb4d21f43ec89249d1de7a86328
title: confirmatory 计算路径强制 PIT/注册数据门——无 PIT 语义数据进 confirmatory→拒（B-PIT-CONFIRMATORY）
status: todo
owner: wait
assigned_by: dreaminate
review_status: 0
priority: P1
area: data-pit
source: goal
source_ref: GOAL §16 line1759「无 PIT 语义的数据进入 confirmatory validation→拒」+ §6 line1112「estimator 未绑定 data timing/PIT→拒」+ §16 line2028 数据缺 dataset_version/checksum/lineage=致命；RAG 调查 wf_748975d3 实证「注册机制建好但主计算路径绕过」
depends_on: [e01bf12fcac34eadb1bd048e218cbe45, 6a8752abcc324ec18cbfa910e1e78376, 0430cd78e7a944db83f3644451fd42ae]
---

# confirmatory 计算路径强制 PIT/注册数据门（B-PIT-CONFIRMATORY）

## Scope [必填]
RAG-vs-注册调查（wf_748975d3）实证：PIT/注册机制**建好但主计算路径绕过**——`factor_factory/panel_source.py` 因子评测走合成 sample、`training/service.py` panel 由调用方外部塞、`codegen.py` 读外部 parquet，都可不带 known_at/dataset_version。GOAL §16/§6 明令「无 PIT 语义数据进 confirmatory→拒」「estimator 未绑定 PIT→拒」。本卡建**confirmatory 边界门**：标 confirmatory 的回测/训练/验证 run，其数据**必须**带 PIT(known_at) + 注册身份(dataset_version)，否则拒（exploratory 不卡·只 confirmatory 强制）。

## 第一步（opus 必做·先实证）
grep 实证：① 代码里哪里区分 exploratory vs confirmatory（confirmatory freeze §8 line1389 / hypothesis card layer / promote 路径）② confirmatory run 的数据入口在哪 ③ 现状是否真无 PIT 也能进 confirmatory。结论写 done 卡再定门落点。**合成 sample 仅 demo/exploratory 不强制注册（不管太宽）；真数据进 confirmatory 才强制。**

## 领地（实证后定·扩展不替换）
confirmatory 边界判定处（hypothesis/promote 层）+ 数据入口校验。复用 field_catalog.load_panel(as_of_known) + data_quality 注册身份 + lineage。**绝不碰** main.py（中心独占）、合成 sample 的 demo 路（exploratory 不卡）。

## 可证伪验收（种坏门必抓·GOAL §16/§6）
1. 无 known_at(PIT) 语义的数据喂 confirmatory 回测/验证 → 拒（对抗：构造无 known_at panel 标 confirmatory→必 raise；MUT 放过→红）。
2. 无 dataset_version 注册身份的数据进 confirmatory promote → 拒（§16 致命·晋级资产可追溯）。
3. exploratory 路径不受影响（合成 sample 探索照跑·不管太宽）。
4. confirmatory 用注册+PIT 数据 → 正常（正路径不误伤）。

## 红线 [按需]
look-ahead 泄露即停（confirmatory 用 non-PIT=前视）· 复用 field_catalog/data_quality 单一源不另造 · 扩展不替换 · exploratory 不强制（不管太宽·合成 demo 照跑）· 未复权价喂成交层即停。

## 非目标 [按需]
不强制 exploratory/合成 sample 注册（那是 demo·管太宽）；不重建 PIT/注册机制（已建·只加 confirmatory 门）。
