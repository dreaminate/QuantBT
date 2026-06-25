# W1 · C-MODELGOV-1-full — artifact 安全完整信任门

- **uuid**: 2b65a76e
- **LINE**: LINE-G-sec（安全红线）
- **GOAL ref**: §15 模型治理（外来 pickle 默认 block / torch weights_only / producer-run+hash 信任门 / allowlist / safetensors）
- **depends_on**: 止血已 done（`training/lib.py` RestrictedUnpickler + weights_only=True，commit 在 main）
- **mint/assign**: leader dreaminate · 2026-06-26 第一波
- **review_status**: 1（leader 直分）· **待拍板**: 0

## 现状（实证）
`app/backend/app/training/lib.py:24-149` 已止血：`_RestrictedUnpickler`（拦已知 RCE gadget）+ `torch.load(weights_only=True)`。注释自陈完整门未兑现：缺 **producer-run + artifact hash 信任门 + allowlist（非 blocklist）+ DL 走 safetensors + JSON config**。

## 领地（只动这些 · 扩展不替换）
- `app/backend/app/training/lib.py`（`load_model` line 102、`_safe_pickle_load`、torch.load 区）
- 新模块允许：`app/backend/app/training/artifact_trust.py`（producer-run + hash allowlist registry）
- **复用** `lineage/ids.py` 的 content_hash（单一身份源红线·绝不另造哈希）+ ledger（producer-run 记录可复用 append-only）

## 可证伪验收（种坏门必抓）
1. 非系统自产（producer-run 未登记 / hash 不在 allowlist）的 artifact → **拒加载**（对抗：伪造一个未登记 artifact 喂 load_model → 必 raise）。
2. allowlist 是白名单非黑名单（对抗：构造不在白名单的新类 → 拒；只靠 blocklist 会漏新 gadget）。
3. DL artifact 走 safetensors + JSON config，绝不静默回落 weights_only=False（对抗：篡改 ckpt 含非安全类型 → 显式 raise，不静默降级）。
4. 系统自产且 hash 命中 allowlist → 正常加载（正路径不被误伤）。

## 红线
外来 pickle/torch.load 不安全加载即停；绝不静默回落 weights_only=False；复用 `lineage/ids.py`；扩展不替换（止血代码不删）。

## 完成协议（opus → 中心）
- 只动上列领地 + 写自己 `dev/tasks/dreaminate/done/2b65a76e/TASK.md`（落档），**绝不碰** dev/state.md / dev/log.md / dev/board.md / dev/GOAL.md / dev/tasks/pool/（中心整合时统一刷）。
- `cd app/backend && python -m pytest tests/<新测试> -v` 跑绿、不破基线（基线 1734 collected）。
- commit + push 分支 `wave1/w1-artifact-trust` 到 origin（省略 Claude co-author 行）。
- 回报：分支名 / 改动文件 / 真测试汇总行 / 对抗测试列表（种坏门必抓证据）/ 红线合规 / 拍板项命中（无则注明）/ 诚实残余。
- 数学说明：本卡无新公式 → **不强造 MathematicalArtifact**；信任门是安全工程，重点是 correctness + 对抗测试。
