---
uuid: 6144bd614e874b1491dc5271fbff8116
title: artifact 信任门生产激活——producer 落盘接 register + 翻 enforce + safetensors 入依赖（C-MODELGOV-1 activate）
status: todo
owner: wait
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
36f88f6b 已建完整信任门机制（allowlist + producer-run/hash 门 + safetensors loader·20 对抗测试·🟡 生产未激活）。本卡把机制接活生产：① producer 落盘处（`models/training.py` pickle.dump / `models/dl/trainer.py` torch.save）落盘后调 `ArtifactTrustStore.register(...)` ② `service.py` predict_with 传 `trust=` 或 `configure_default_trust(enforce=True)` 翻默认 enforce ③ safetensors 入 `requirements.txt`、DL producer 出 `.safetensors`。**先做①再翻②否则破基线**。

## 接线点（实现复核）[必填]
- `app/backend/app/models/training.py`（pickle.dump 后 register）
- `app/backend/app/models/dl/trainer.py`（torch.save 后 register + safetensors）
- `app/backend/app/training/service.py`（predict_with 传 trust / configure_default_trust enforce=True）
- `requirements.txt`（safetensors）

## 对抗验收（种坏门必抓）[必填]
1. enforce 翻开后：未登记 producer artifact 喂 load → 拒（端到端·非仅单测 store）。
2. 翻 enforce 后既有训练→预测全链不破（producer 已登记→正常加载）。
3. safetensors round-trip 等价；.pt 仍 weights_only=True no-fallback。

## 红线 [按需]
外来 pickle/torch.load 不安全加载即停·绝不静默回落 weights_only=False·复用 lineage.ids.content_hash·扩展不替换·翻 enforce 前必先接 producer（不破基线）。
