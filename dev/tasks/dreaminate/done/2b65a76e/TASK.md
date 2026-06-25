---
uuid: 2b65a76ed78d45fab9bdd4ede1a31e01
title: artifact 完整信任门 W1——producer-run + hash binding + 白名单 + safe tensors（C-MODELGOV-1 full）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: model-governance
source: goal
source_ref: GOAL §15（artifact 安全·producer-run + hash binding / safe tensors）+ 源 spec pool 卡 36f88f6b97ca4a4f980fb162f9d76009 + 止血 commit（lib.py:24-149）
depends_on: []
---

# artifact 完整信任门 W1（C-MODELGOV-1 full）

## Scope [必填]
把 artifact 安全从【止血】（`training/lib.py` 的 `_RestrictedUnpickler` blocklist + `torch.load(weights_only=True)`）做成【完整信任门】：① `ArtifactTrustStore` 绑定 full-sha256 → producer-run（外来/未登记/被改一字节 → 拒）② pickle 类【白名单】（非黑名单，可信库根之外的新类默认拒）③ DL 走 safe tensors + JSON config，`.pt` 仅 `weights_only=True` 且**绝不静默回落 `weights_only=False`**。**只做加载/安全层**，不改训练算法。**不做**：产出侧 producer 接 `register()`、默认翻 enforce、`requirements.txt` 加 safetensors（产出侧 `app/models/*` 在领地外 → follow-on）。

## 接线点（实现已复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/training/lib.py` | `_safe_pickle_load` 后 | 加 `_AllowlistUnpickler`(继承止血 blocklist)+ `_allowlist_pickle_load`（白名单·验收 #2） |
| `app/backend/app/training/lib.py` | `load_model` / `predict_with` / `_predict_dl` | 加 keyword-only `trust=` + 路由信任门（默认 None=向后兼容） |
| 新 `app/backend/app/training/artifact_trust.py` | — | `ArtifactTrustStore`(append-only JSONL + prev_hash 链) + `TrustPolicy` + DL 安全加载(safe tensors/weights_only no-fallback) |
| 复用 `app/backend/app/lineage/ids.py` | `content_hash` | artifact content_id（单一身份源·**不另造哈希**；安全绑定键用完整 256-bit sha256） |

## 对抗测试设计（种坏门必抓）[必填]
1. **信任门**：未登记 / hash 不命中 / 被改一字节的 artifact 喂 `load_model`/`predict_with`（enforce）→ 必 raise。
2. **白名单非黑名单**：良性新类（`decimal.Decimal`，blocklist 抓不到）root 不在白名单 → 仍拒。
3. **DL no-fallback**：`.pt` 含非安全类型 → 显式 raise，绝不回落 `weights_only=False`（同文件 `weights_only=False` 本可加载 → 证明刻意拒非被迫）；safetensors 缺包/缺 JSON → 拒不回落 pickle。
4. **正路径不误伤**：登记的真实 sklearn/lightgbm/.pt → enforce 正常加载 + 预测；默认（无 trust）= 止血行为不变。

## 复用 [按需]
止血 `_RestrictedUnpickler`/`_safe_pickle_load`（保留·被 `_AllowlistUnpickler` 继承）· `lineage/ids.py` `content_hash`（artifact 身份·不另造）· 沿用 `lineage/ledger.py` 的 append-only JSONL + prev_hash 链设计。

## 红线 [按需]
外来 pickle/torch.load 不安全加载即停 · 绝不静默回落 `weights_only=False` · 单一身份源 `ids.py` · 扩展不替换（止血一行不删）· honest-N `Ledger` 不被污染（信任登记自有存储，不混进试验计数）。

## 非目标 [按需]
不重做止血已堵的直球 RCE；不改训练算法、不动产出侧 producer（`app/models/training.py` / `app/models/dl/trainer.py`，领地外）；不动 `service.py` 模型组合调用。

## Open Questions（已决 3/3）[按需]
- [已决] **默认 `enforce=False`**：产出侧 producer 未接 `register()`（领地外），默认硬开会误伤所有现存 artifact、破基线。致命红线（不安全反序列化）由 always-on safe-loader 无条件守；信任门是其上的【来源】门，enforce 时开。机制完整 + 对抗验证齐，**激活（producer 接线 + 默认翻 enforce）= follow-on**。
- [已决] **信任登记不写 honest-N `Ledger`**：那本账按 (config_hash, strategy_goal_ref) 计 honest_n，混入 artifact 登记会污染试验计数。故自有 append-only 存储，只复用 `ids.content_hash` 身份函数。
- [已决] **安全绑定键用完整 256-bit sha256**，不用 `content_hash` 的 16 位截断（64-bit 抗碰撞不足以当安全白名单键）；`content_hash` 仅作索引/展示 id（复用单一身份源）。

## 验收一句话 [必填]
种「未登记/被改 artifact 喂 load / 良性新类绕白名单 / DL 非安全类型静默降级」→ 门必抓；登记的真实 sklearn/lightgbm/.pt 正常加载；默认路径止血行为不变、不破基线。

## 完成记录（2026-06-26）

### 改动文件
- **新建** `app/backend/app/training/artifact_trust.py`（信任门机制：`ArtifactTrustStore` / `TrustRecord` / `TrustPolicy` / `artifact_fingerprint` / `load_dl_checkpoint` / `load_torch_checkpoint` / `load_safetensors_artifact` / `configure_default_trust` / `resolve_policy`）。
- **扩展** `app/backend/app/training/lib.py`：止血 `_RestrictedUnpickler` / `_safe_pickle_load` **一行未删**；加 `_AllowlistUnpickler`（继承止血类·白名单）+ `_allowlist_pickle_load`；`load_model` / `predict_with` / `_predict_dl` 加 keyword-only `trust=None`（默认向后兼容）+ 路由信任门；`_predict_dl` 的 `torch.load(weights_only=True)` 迁入 `artifact_trust.load_torch_checkpoint`（weights_only 仍 True，加显式 no-fallback）。
- **新建** `app/backend/tests/test_artifact_trust_gate.py`（20 对抗/正路径测试）。

### 双层门设计（核心张力解法）
- **Layer 1（always-on·守致命红线）**：反序列化安全无条件生效。pickle = 白名单 unpickler（enforce）/ 止血 blocklist（默认），两道并存；DL = `weights_only=True` 绝不回落 + safe tensors 优先。**任何路径都不存在不安全反序列化**。
- **Layer 2（来源门·enforce 时开）**：`full-sha256 → producer-run` 登记绑定，未登记/被改 → 拒。
- **默认 `enforce=False`**：产出侧 producer 接线在领地外，硬开破基线；激活 = follow-on。

### 真测试汇总行（scoped，未跑全量·全量由中心单跑）
- `tests/test_artifact_trust_gate.py`：**20 passed**（本卡新增）。
- 还原后联跑信任门 + 止血基线 + DL 向后兼容：`test_artifact_trust_gate + test_model_artifact_safety + test_dl_trainer_fixes + test_backtest_bridge` = **55 passed**。
- blast-radius（load_model/predict_with 调用方）：`test_training_service + test_training_runner + test_models + test_training_api + test_model_cards` = **51 passed**。
- 止血基线 `test_model_artifact_safety.py` **8 passed**（未破）。

### 对抗测试（每条：种坏门→红→还原→绿）
1. **验收 #1**（未登记拒）：mut `assert_trusted` 不 raise → `test_unregistered_pickle/pt_refused` + `test_tampered_after_register_refused` 3 红（DID NOT RAISE）→ 还原绿。
2. **验收 #2**（白名单非黑名单）：mut `_AllowlistUnpickler.find_class` 跳白名单 → `test_allowlist_refuses_unlisted_benign_class` + `test_enforce_load_applies_allowlist...` 2 红（良性 Decimal 被放行）→ 还原绿。
3. **验收 #3**（no-fallback）：mut `load_torch_checkpoint` except 回落 `weights_only=False` → `test_dl_pt_nonsafe_type_refused_no_silent_fallback` 红（非安全 ckpt 被加载）→ 还原绿。
4. **验收 #4**（正路径不误伤）：mut `assert_trusted` 总 raise → `test_registered_sklearn/lightgbm/pt_loads` 3 红（登记的被误拒）→ 还原绿。

### 红线合规
- 不安全加载即停：`app/` 生产代码零 `weights_only=False`、零裸 `pickle.load`/`torch.load`；唯一 `torch.load` 是 `weights_only=True`。
- 复用 `ids.content_hash`（`test_fingerprint_reuses_content_hash_single_source` 守）；安全键用完整 sha256。
- 扩展不替换：止血代码保留（`grep` 计数 lib.py 14 处 / artifact_trust.py 6 处）。

### 诚实残余（follow-on·均出本卡领地）
- **产出侧 producer 接 `register()`**：`app/models/training.py:236`（pickle.dump）/ `app/models/dl/trainer.py:204`（torch.save）落盘后须调 `ArtifactTrustStore.register(...)`，信任门方在生产生效。
- **默认翻 enforce**：`service.py:353` 模型组合 `predict_with` 传 `trust=`，或 `configure_default_trust(enforce=True)`；需产出侧先接线否则破基线。
- **safe tensors 依赖 + producer 出 .safetensors**：`requirements.txt` 加 `safetensors`（本地已装 0.8.0 验证 happy-path，未入 requirements）；`trainer.py` 改存 `.safetensors + .json`。当前 LIVE DL 仍 `.pt`（已 `weights_only` 硬化）。
- **safetensors happy-path 测试**用 `pytest.importorskip` 门控：本地装了 → 跑绿；中心 env 未装 → skip（不 fail）。
- **登记账末尾截断**：单机 append-only 的已知极限（与 `ledger.py` 同源），需外部公证根除，超本卡范围（已诚实标注）。
