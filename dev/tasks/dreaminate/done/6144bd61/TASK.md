---
uuid: 6144bd614e874b1491dc5271fbff8116
title: artifact 信任门生产激活——producer 落盘接 register + 翻 enforce + safetensors 入依赖（C-MODELGOV-1 activate）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: model-governance
source: goal
source_ref: GOAL §15 + 36f88f6b 完成记录诚实残余（机制完整·生产未激活）
depends_on: [36f88f6b97ca4a4f980fb162f9d76009]
---

# artifact 信任门生产激活（C-MODELGOV-1 activate）

## Scope [必填]
36f88f6b 已建完整信任门机制（allowlist + producer-run/hash 门 + safetensors loader·20 对抗测试·🟡 生产未激活）。本卡接活生产：① producer 落盘处接 `register()` ② service 组合消费侧翻 enforce ③ safetensors 入 requirements。**先做①再翻②（否则破基线）**。

## 领地（只动这些·扩展不替换）
`models/training.py`、`models/dl/trainer.py`、`training/service.py`、`requirements.txt`、`training/artifact_trust.py`（仅加 producer 便利方法·**不改门语义**）+ 新增 `tests/test_artifact_trust_activation.py`（端到端对抗验证·additive）。**未碰** `main.py`、`training/lib.py`（机制只调用）、`artifact_trust.py` 的门语义、其他线领地。

## 完成记录（2026-06-26·deep-opus 隔离 worktree·分支 `wave3/w1-artifact-activate`）

### 改动文件
| 文件 | 改什么（扩展不替换） |
|---|---|
| `app/training/artifact_trust.py` | **仅加 producer 便利**：`TRUST_STORE_DIRNAME="_artifact_trust"` 常量 + `store_under(data_root)` 便利构造器（落点单一源）+ `__all__`。门语义（`TrustPolicy`/`assert_ok`/`resolve_policy`/`ArtifactTrustStore` 方法）**一字未动**（diff 实证）。 |
| `app/models/training.py` | `train_model` pickle.dump 落 `model.pkl` 后接 `store_under(artifact_dir.parent).register(producer_run="ml_train:<job>", producer_kind="ml_train")`（①·ML producer）。函数内惰性 import 避 `app.models`↔`app.training` 包级环。 |
| `app/models/dl/trainer.py` | `train_dl` torch.save 落 `model.pt` 后接 `store_under(job_dir.parent).register(producer_kind="dl_train")`（①·DL producer·**子进程**写共享 on-disk JSONL）。`.pt` 消费仍 `weights_only=True` no-fallback（未碰·验收#3）。 |
| `app/training/service.py` | `_apply_input_models` 组合消费侧传 `trust=TrustPolicy(store=store_under(self._root), enforce=self._trust_enforce)`（③）。构造参数 `trust_enforce: bool=_TRUST_ENFORCE_DEFAULT(=True)` → **单点可逆**。 |
| `requirements.txt` | 加 `safetensors>=0.4`（②·安全 DL loader 依赖；本机实测已装 0.8）。 |
| `tests/test_artifact_trust_activation.py`（新） | 8 端到端对抗测试（经真 service / 真 train_model / 真 train_dl，非仅 store 单测）。 |

### 关键设计决策（工程取舍·留痕）
1. **落点单一源 = `<root>/_artifact_trust`，靠 `dir.parent` 收敛、零 env / 零 codegen 改**：service 的 job 落 `<root>/<job_id>/`（`store.job_dir`），runner 注入 `QUANTBT_JOB_DIR=<root>/<job_id>`（runner.py:61）。故 producer 的 `artifact_dir.parent`/`job_dir.parent`（=`<root>`）与消费侧 `self._root` 解析到**同一** JSONL。**DL 子进程登记 → 主进程消费**跨进程一致（on-disk append-only JSONL·实测 `is_trusted` True）。
2. **register 在 producer 落盘处（非 service 层）**：覆盖 in-process ML + subprocess DL + 任何 codegen 路径，与卡 ① 字面一致；`producer_run` 用 job 目录名（=job_id·provenance 锚），ML/DL 对称、不为 DL 走子进程多塞 run_id 管线。
3. **enforce 用「service 传 `trust=`」而非全局 `configure_default_trust`**（卡 ③ 二选一）：
   - 唯一在我领地的主进程消费点 = `_apply_input_models`，显式绑 `self._root` 的账 → **正确 store 绑定**（无全局 last-wins 错店 bug）。
   - **绝不**全局翻：`backtest_bridge.py:126`（主进程 `predict_with(trust=None)`·主 endpoint 调）在我领地外，全局翻会**跨领地误伤** + 构造 service 即变异 `_DEFAULT_POLICY` 会**跨测试污染全量**（不可控、我又跑不了全量）。契合「provide pipeline not impose」+ 最小爆炸面。
4. **safetensors：入 requirements + 保留 `.pt` 输出（卡 ② 明列「或保留 .pt 但登记」）**，**不**切 DL 输出格式。理由：`test_dl_trainer_fixes:162`/`test_model_cards:173` 硬断言 `model.pt` 存在、`backtest_bridge:164` 只 auto-find `model.pkl/.pt`（不认 `.safetensors`）、M12 path 依赖——切格式破基线。DL §15 安全已由「登记门 + `weights_only=True` no-fallback」兑现（`.pt` 加载本就安全），safetensors-**输出**是边际 at-rest 硬化、非安全关键 → 诚实标为 follow-on（避基线风险）。

### 验证（scoped·实跑·非假绿灯）
- **新对抗 `tests/test_artifact_trust_activation.py`：8 passed**（`KMP_DUPLICATE_LIB_OK=TRUE QUANTBT_FORCE_DEVICE=cpu`）。覆盖：① ML/DL producer 落盘即登记（含 DL 跨进程 `is_trusted`）② enforce 默认 ON 组合**已登记**模型（xgboost→lgbm 走白名单·DL→ML 跨进程）全链不破 ③ 组合**外来/未登记** .pkl → job `failed`·`ArtifactTrustError`（端到端）+ 篡改一字节 → 拒 ④ `trust_enforce=False` opt-in → 外来经止血 blocklist 照常加载 ⑤ `store_under` 落点单一源。
- **既有受影响 11 文件：131 passed in 73.7s**（`test_artifact_trust_gate` wave-1 机制 20·`test_training_runner`/`test_dl_trainer_fixes` 组合现跑在 enforce 下·`test_models`/`test_model_catalog`/`test_model_cards`/`test_cpcv_oos_distribution` 直调 producer 登记副作用·`test_training_service`/`test_backtest_bridge`/`test_training_pit_service_activate`）。**基线未破**。
- **`pytest --collect-only`：1900 collected**（= 基线 1892 + 新 8·无 import 错·包级环已惰性 import 解）。
- **MUT 定点反向 edit（绝不 git checkout·改完 re-edit 还原·实测）**：
  - **MUT-1**（ML register 落错店 `artifact_dir.parent/MUT_BOGUS`）→ `test_ml_producer_registers_artifact_on_save` + `test_service_compose_registered...` **FAIL**（后者正是「① 不彻底 → enforce 拒掉合法自产 → 破基线」场景·`ArtifactTrustError`）。坏门被抓 → 还原 → 复跑 8 passed。
  - **MUT-2**（`_apply_input_models` 强 `enforce=False`）→ `test_service_compose_external_pkl_refused_end_to_end` + `..._tampered_...` **FAIL**（外来/篡改 artifact 误加载、job succeeded）。坏门被抓 → 还原。
  - 还原后 `grep MUT` 零残留、8 passed。

### 🟡 enforce-默认-翻开 状态（诚实标注·中心特别叮嘱）
- **「enforce 默认翻开」已实现**：`_TRUST_ENFORCE_DEFAULT=True`，`TrainingService` 默认构造即在组合消费侧 enforce；① producer 已全接 register（ML in-process + DL subprocess·实测登记）→ 默认 ON 不误伤自产模型（131 affected + 8 new 绿为证）。
- **仅 scoped 验证·待中心全量验证**：本卡**只跑得了 scoped**（碰过的组合消费 + producer 路径），**绝不声称 enforce 默认全量安全**。`_apply_input_models` 是我领地唯一主进程消费点；其他主进程消费点（`backtest_bridge.predict_with(trust=None)` 等·领地外）**未**被本卡 enforce（我刻意不全局翻·见决策3）。
- **若全量有未登记 producer 路径破** → 中心**单点回退 opt-in**：`TrainingService(trust_enforce=False)`（无需改门 / 改 producer / 改 lib）。
- **未覆盖 producer 路径风险（诚实披露）**：自由代码训练（`submit_code`/`train_now_code`）子进程内用户代码若自调 `predict_with` 加载 artifact，子进程默认策略 enforce=False（未在子进程 configure）→ 该路**不**enforce。本卡领地（4 文件）未覆盖子进程消费 enforce（须 codegen/runner 改·领地外）→ 列 follow-on。结构化 spec 路（ML/DL）的组合在主进程 `_apply_input_models` 完成、已 enforce，无此洞。

### 拍板项命中（profile 松紧·点名）
**enforce 默认 ON 算 profile 松紧拍板**：默认翻开后，组合 `input_models` 只许**本系统自产·已登记**模型；外来/跨 service-root 未登记 artifact 被拒（= §15 安全本意，但**改变行为**：原经 blocklist 加载）。松紧（默认 ON vs opt-in）= 用户/中心那摊（「provide pipeline not impose」）——本卡守 correctness/安全不变量、给**单点可逆开关**（`trust_enforce`），代价摆明、由中心整合点拍。app 内单一 `TRAINING_SERVICE`（main.py:1265·单 root）→ 自产模型恒在同账，默认 ON 不破正常组合。

### 红线合规（逐条）
- ✅ 外来 pickle/torch.load 不安全加载即停：外来/未登记 artifact 端到端被拒（MUT-2 证有齿）。
- ✅ 绝不静默回落 `weights_only=False`：`.pt` 走 `load_torch_checkpoint`（未碰·wave-1 always-on）。
- ✅ 复用 `lineage.ids.content_hash`：`store_under` 经 `ArtifactTrustStore` 复用，零另造哈希族。
- ✅ 扩展不替换：止血/门机制一行未删；artifact_trust 仅加便利、门语义零改（diff 实证）；producer 登记是 additive；`_apply_input_models` 仅加 `trust=`。
- ✅ enforce 翻开前 producer 必全接：① ML+DL producer 落盘即登记（先于 ② 翻 enforce）·实测自产模型 enforce 下绿。
- 🟡 数学：无新公式 → 不造 MathematicalArtifact（卡明示·重点 §15 安全 correctness + 对抗）。

### 诚实残余（follow-on·非本卡兑现）
1. **enforce-默认 全量验证 = 中心整合点**（本卡只 scoped·见上 🟡）。
2. **safetensors 输出**（DL 切 `.safetensors`+JSON 旁车）未做（保留 `.pt`·避破 `model.pt` 断言/backtest auto-find/M12）→ follow-on（须连带改 backtest_bridge auto-find + M12·跨领地）。loader 已 ready、依赖已入。
3. **自由代码子进程消费 enforce** 未覆盖（须 codegen/runner 改·领地外·见 🟡）。
4. **全局 `configure_default_trust` 未翻**（决策3·避跨领地/跨测试污染）；如要 `backtest_bridge` 等领地外消费点也 enforce，是中心整合决策。
