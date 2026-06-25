---
uuid: 25247eb4d21f43ec89249d1de7a86328
title: confirmatory 计算路径强制 PIT/注册数据门——无 PIT 语义数据进 confirmatory→拒（B-PIT-CONFIRMATORY）
status: done
owner: dreaminate
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
RAG-vs-注册调查（wf_748975d3）实证：PIT/注册机制**建好但主计算路径绕过**。本卡建 **confirmatory 边界门**：标 confirmatory 的回测/验证/冻结 run，其数据**必须**带 PIT(known_at) + 注册身份(dataset_version)，否则拒（exploratory 不卡·只 confirmatory 强制·合成 sample demo 照跑）。

## 可证伪验收（种坏门必抓）
1. 无 known_at(PIT) 数据喂 confirmatory → 拒（MUT 放过→红）。2. 无 dataset_version 注册身份进 confirmatory 冻结/promote → 拒。3. exploratory/合成 sample/无 registry → 不受影响。4. confirmatory 用注册+PIT → 正常不误伤。

---

## 完成记录（2026-06-26 · deep-opus 任务线 · 隔离 worktree·中心整合 land）

### 第一步实证结论（先实证再定门落点）
**① 代码哪里区分 exploratory vs confirmatory**
- `hypothesis/card.py`：`Layer = exploratory|secondary|confirmatory`；`store.py:freeze()` 只对 `layer=="confirmatory"` 卡放行（line 107），冻结时已强制 `frozen_oos.dataset_version` **非空**（line 113-114）——但只查「字段非空」，**不查它是否真注册、是否带 known_at**。
- `experiments/store.py`：`Run.layer` 字段存在，但注释明写「store 层不强制校验（不破坏既有 Run）」（line 60-64）——**未强制**。
- `lineage/ledger.py`：`LedgerStage = exploratory|confirmatory`。
- `eval/gate_runner.py:evaluate_overfit_gate`：`record=True` 时**无条件**盖 `stage="confirmatory"` 账本条目（line 131）。→ **这是 confirmatory 记账的单一漏斗**（`record=False`=preview 不记账=探索口径）。

**② confirmatory run 数据入口**
- 单一漏斗 = `evaluate_overfit_gate(record=True)`：所有 confirmatory 回测/组合/IDE-promote 记账都汇此（caller：`ide/promote.py:_run_overfit_gate` record=True、`portfolio/gate.py:gate_portfolio`→`main.py:promote_portfolio` record=True；`main.py:risk_preview` record=False 不算）。它只收 `dataset_version: str`（**默认 `"unknown"`**）+ returns。
- 第二入口 = `hypothesis/store.py:freeze()` 的 `frozen_oos.dataset_version`（confirmatory 卡冻结/一次性 OOS）。

**③ 现状是否真无 PIT 也能进 confirmatory：是（确认漏洞）。** `dataset_version` 默认 `"unknown"`、无 registry 反查、无 known_at 校验 → 无 PIT/未注册数据可径直记成 confirmatory 并计入 honest-N。grep 全仓**无任何等价门**（`无 PIT`/`require_pit`/`confirmatory.*known_at` 等零命中）→ **非 already-enforced，确为新建**（诚实）。

### 门落点（扩展不替换·复用单一源·绝不碰 main.py）
- **新建** `app/backend/app/eval/confirmatory_data_gate.py`：`check_confirmatory_data()`（纯校验返 verdict 不 raise）/ `require_confirmatory_data()`（拒则 raise `ConfirmatoryDataRejected`）。拒条件（enforce 且 registry 在场）：dataset_version 占位(`unknown`/空) → 拒（§16 line2028）｜未在 `DatasetRegistry` 注册 → 拒｜已注册但 `known_at_utc`/`effective_at_utc` 均空 → 拒（§16 line1759/§6 line1112）。**复用 `data_quality.DatasetRegistry` 单一源**（注册身份+known_at+lineage_id），绝不另造第二本。
- `data_quality.py`：加 `DatasetRegistry.find_version(version_id)` 单点反查（additive）。
- `eval/gate_runner.py:evaluate_overfit_gate`：加 `registry`/`enforce_confirmatory_pit` 参数；`record=True` 时在【入账前】校验，拒则 raise 且**绝不落账**（append-only 一本账不可撤·防无 PIT confirmatory 污染 honest-N）。**`registry=None`→不触发**（向后兼容）。
- `hypothesis/store.py:freeze()`：加 `registry` 参数；接 registry 时 `frozen_oos.dataset_version` 必过同一门（保 FreezeRejected 契约）。
- `portfolio/gate.py`/`ide/promote.py`：加 `registry` 参数透传（additive·默认 None）——供**中心**在 main.py 调用点接 `DATASET_REGISTRY` 激活（端点本卡不碰）。

改动文件：`eval/confirmatory_data_gate.py`(新) `eval/gate_runner.py` `data_quality.py` `hypothesis/store.py` `portfolio/gate.py` `ide/promote.py` + `tests/test_confirmatory_pit_gate.py`(新)。**未碰** main.py / `factor_factory/panel_source.py`(合成 demo) / qro·graph·llm。

### 真测试汇总行（scoped·均带 timeout·凭汇总行判绿）
- `tests/test_confirmatory_pit_gate.py`（新对抗）：**19 passed in 1.15s**（覆盖验收①②③④ + 单点可逆 + 向后兼容）。
- **MUT 种坏门**：把 `ENFORCE_CONFIRMATORY_PIT_DEFAULT` 翻 `False`（退回 advisory）→ 同套 **11 failed / 8 passed**（无 PIT 进 confirmatory 被放过、不再 raise → 红）→ 还原 True 后复跑 **19 passed**。门确真生效、坏门必被抓。
- 受影响基线复跑：`test_gate_wiring + test_portfolio_gate + test_hypothesis_card + test_hypothesis_run_wiring + test_ide_promote + test_data_quality + test_dataset_envelope_lineage` **127 passed in 2.69s**。
- 漏斗集成/端点：`test_funnel_hooks + test_entrypoint_gate_coverage + test_run_verdict_card + test_agent_business_tools_a4 + test_r11_frontend_dispatch_audit + test_verification_verdict` **90 passed in 8.71s**。
- 基线计数：`collect-only` **1900 → 1919**（+19 新增·破 0）。`py_compile` 全过。

### 对抗测试（验收逐条钉死）
- ① 无 known_at 数据标 confirmatory（`record=True`+registry）→ `ConfirmatoryDataRejected` raise **且 `honest_n==0`**（入账前拒·MUT 探针：门坏则数据流进 record_or_hit→honest_n=1→红）。
- ② 占位 `"unknown"` / 未注册 version 进 confirmatory funnel 与假设卡 freeze → 拒。
- ③ exploratory（`record=False`）+ 无 PIT + registry → 不门控；`registry=None` + `record=True` + `"unknown"` → 照常入账（既有 test_gate_wiring/端点口径·不破基线）。
- ④ 注册+PIT 数据 confirmatory → 放行且正常入账（`honest_n 0→1`）/ 假设卡正常冻结（不误伤正路径）。

### 红线合规逐条
- **look-ahead 泄露即停**：本卡正中此红线——无 PIT confirmatory=前视，已建门拒；入账前拒绝防 honest-N 污染。✅
- **复用 field_catalog/data_quality 单一源不另造**：门复用 `DatasetRegistry`（known_at+lineage_id），未建第二本。✅
- **扩展不替换**：75 插入/3 删除（删的 3 行=被扩展的签名行）；全 additive 参数默认 None/默认值，既有调用字节级不变。✅
- **exploratory 不强制（不管太宽·合成 demo 照跑）**：门只在 `record=True`/卡冻结+registry 在场触发；`panel_source.py` 合成路未碰。✅
- **不破基线**：1900→1919 破 0；affected 127 + 集成 90 全绿。✅
- **🟡≠✅**：只跑 scoped、未跑全量，下方残余诚实标。
- 未碰 state/log/board/DEVMAP/GOAL/pool/其他卡/main.py/qro/graph/llm。✅

### 拍板项命中
**无新待拍板岔路。** 关键取舍均被既有边界/决策钉死：① 激活归属——领地「绝不碰 main.py（中心独占）」直接决定：库层 funnel 门=本卡、生产 HTTP 端点接 DATASET_REGISTRY=中心；② default-ON + 单点可逆（`ENFORCE_CONFIRMATORY_PIT_DEFAULT`）沿用 **C-MODELGOV-1 已立范式**（建门+默认开+可逆+独立激活）；③ PIT 定义（`known_at`/`effective_at` 在场）锚 GOAL §11/§16/§6 + 决策 R28=A。无新公式 → 未造 MathematicalArtifact（守红线）。

### 诚实残余（🟡·交中心）
1. **🟡 生产 HTTP 端点未激活**：`main.py` 的 `/api/ide/runs/{id}/promote`、`/api/portfolio/{id}/promote`、`/api/runs/{id}/promote` 尚未把 `DATASET_REGISTRY` 接进 funnel（main.py=中心独占·绝不碰）。**激活动作=中心在这些调用点传 `registry=DATASET_REGISTRY`**（`promote_ide_run`/`gate_portfolio`/`evaluate_overfit_gate` 已备好 `registry` 参数）。库层 funnel 门已强制 + 真 funnel 上对抗钉死——非纸门，但端点层尚未挂。
2. **🟡 enforce 默认 True 待中心全量验证**：本卡只跑 scoped，绝不声称全量绿；中心跑全量后若某未注册生产 confirmatory 路径破基线 → 翻 `ENFORCE_CONFIRMATORY_PIT_DEFAULT=False` 单点回退（无需改门/改调用点）。
3. **诚实限界**：门校验【声明的 dataset_version 身份】是否注册+带 PIT，**不**对 returns 与该数据做逐字节内容绑定（更深 content-addressing 超本门 scope）；它把 confirmatory 数据从「`unknown`/未注册/无 known_at 一律放行」抬到「必须可追溯到注册 PIT 数据集」。训练路的实际 PIT 折叠由 B-PIT-1（e01bf12f/6a8752ab）的 `as_of_known` 消费另行保障，与本门正交互补。
4. commit+push `wave3/confirmatory-pit-gate`（省略 co-author）；review_status=0 待中心复核。
