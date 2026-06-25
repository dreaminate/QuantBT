---
uuid: 36f88f6b97ca4a4f980fb162f9d76009
title: 模型 artifact 安全完整门——producer-run + hash 绑定 + allowlist + safetensors（C-MODELGOV-1 full）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: model-governance
source: goal
source_ref: GOAL §15（artifact 安全·外来 pickle 默认 block）+ 施工图 LINE-C W1 + 止血 commit 7311c6b
depends_on: []
---

# 模型 artifact 安全完整门（C-MODELGOV-1 full）

## Scope [必填]
中心已做【止血】（commit 7311c6b：`training/lib.py` RestrictedUnpickler blocklist + torch weights_only=True + 8 对抗测试）。本卡做【完整门】（GOAL §15「外来 pickle 默认 block」真兑现）：① 外来 `.pkl/.joblib` 默认拒、不进 unpickle ② 仅 producer-run + artifact hash 命中的【系统自产】artifact 才许 legacy pickle ③ legacy pickle 用 **allowlist**（非 blocklist：只放 sklearn/numpy/scipy/lightgbm/xgboost/pandas/collections）④ DL 迁 safetensors + JSON config，`.pt` 仅过渡。

## 文件领地（owner·并发隔离）
`models/` `models/safe_load.py`(新) `training/lib.py`(扩展已止血) `training/lib.py`/`models/dl/trainer.py`(safetensors 保存) `security/`(hash 信任门)。**LINE-C·不与 B/E/G 在飞卡交叠**。

## 接线点（file:line·实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| `app/backend/app/training/lib.py` | `_RestrictedUnpickler`(已建) | blocklist→allowlist + 加 producer-run/hash 信任门 |
| `app/backend/app/models/dl/trainer.py:203` | 保存 ckpt | safetensors + JSON config（`.pt` 过渡保留） |
| 新 `app/backend/app/models/safe_load.py` | — | 统一安全加载入口（trust 检查 + allowlist + hash） |
| `app/backend/app/security/` | — | artifact hash 注册/校验（producer-run 绑定） |

## 对抗测试设计（种坏门必抓）[必填]
1. **allowlist**：种 allowlist 外的模块（含 codex 列的 operator.methodcaller/functools/types/marshal/pydoc gadget）→ 必拒；合法 sklearn/lightgbm/xgboost 模型照常加载。
2. **信任门**：外来路径（非 producer-run/hash 不匹配）的 .pkl → 默认拒（不 unpickle）；hash 篡改 → 拒。
3. **safetensors**：DL 模型存/取走 safetensors round-trip 等价；`.pt` weights_only=True 仍守。
4. 复用止血的 8 对抗测试不破。

## 复用 [按需]
止血的 `_RestrictedUnpickler`（升 allowlist）· `lineage/ids.py` content_hash（artifact hash 绑定·**不另造**）· `security/keystore` 模式。

## 红线 [按需]
外来 pickle 默认 block（§15 致命）· 绝不静默回落 weights_only=False · 单一身份源 ids.py 做 hash · 扩展不替换。

## 非目标 [按需]
不重做止血已堵的直球 RCE；不改训练算法、只改加载/保存安全层。

## 完成记录（2026-06-26·第一波整合 land·中心 orchestrator）
- 实现 commit `15b06d2`（分支 `wave1/w1-artifact-trust`·deep-opus 隔离 worktree）→ 中心 merge `3191b44`。
- 新 `training/artifact_trust.py`（ArtifactTrustStore append-only 链 + TrustPolicy + DL safe loading + safetensors loader）+ `lib.py` 扩展（止血 `_RestrictedUnpickler` 一行未删·`_AllowlistUnpickler` 继承=白名单先过 + blocklist 防御纵深·load_model/predict_with 加 `trust=` keyword·DL 走 load_dl_checkpoint·torch weights_only=True no-fallback）。复用 lineage.ids.content_hash 单一身份源。
- 对抗：`test_artifact_trust_gate.py` 20 passed·MUT#1-4 全抓（未登记拒 / 白名单非黑名单 / DL no-fallback / 正路径不误伤）。中心亲审 lib.py 安全 diff（红线零裸危险加载·grep 实证）。
- **诚实状态 🟡（机制完整+验证齐·生产未激活）**：本卡建机制（allowlist + 信任门 + safetensors loader）；但 ① producer 侧落盘（`models/training.py`/`models/dl/trainer.py`）未接 register() ② 默认 enforce=False（翻则破基线·须先做①）③ safetensors 未入 requirements（importorskip 兜）。三项 = **follow-on P2**。止血部分仍 always-on（✅）。
