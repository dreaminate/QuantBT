---
uuid: d2c5e8f3a91b4c6d8e2f7a3b9c1d4e05
title: §16 发版门 advisory-first 接进 promote 路径（D-RELEASE-ADVISORY·中心串行·LINE-E）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: release-gate
source: goal-gap
source_ref: GOAL §16 工程标准 release gate（行 1969 起）+ §0；第十波组装器 f2a9c4e1 + 第十一波执行诚实 b7e3d9a1 之后的「接进 promote 端点」最后一步（advisory-first）
depends_on: [f2a9c4e1b8d7460a9c3e1f5b6a2d8e04, b7e3d9a1c4f8460b8d2a6e9f1c5b3a07]
---

# §16 发版门 advisory-first 接进 promote 路径（D-RELEASE-ADVISORY）

## Scope
中心串行活（main.py/promote 中心专属）：把第十波 `release_gate.promote_assembler.evaluate_run_releasable` 接进 `promote_ide_run`——让已建 §16 八门聚合 release gate **真正在 promote 路径上跑**，把裁决落进 run.json 的 `release_verdict`。**advisory-first：只记录、绝不在 promote 时 reject 晋级**（是否硬卡晋级=后续显式 enforce 决策·守不预先削弱方法学也不破基线）。

## 完成纪要（done · 第十二波 · 中心串行 · 自跑全量 land）
**改（+1 文件 additive·扩展不替换）**：
- `app/backend/app/ide/promote.py`：`promote_ide_run` 写 run.json 前加防御式 advisory——惰性 import `evaluate_run_releasable(manifest)` → `manifest["release_verdict"] = .to_dict()`；try/except 兜底（release 自检任何异常落 `available:False` 诚实标·绝不破 promote 主流程）。默认开（每个 promoted run 都带 release_verdict）。
- 新测试 `app/backend/tests/test_promote_release_advisory.py`（5 例）。

**对抗 + advisory 不变量守门（5 例）**：① promote 后 run.json 必含 release_verdict（gate 真在 promote 跑）② 弱标签裸 run §16 硬门全过 ok=True（不误伤正路径）③ **模板基线冒充→§16 裁 ok=False（mock 诚实门 R4/R5）且记录，但 promote 仍成功落盘**（advisory 核心：只记录不 reject）④ 既有 manifest 键不丢（additive）⑤ release_verdict JSON-safe。
**MUT 三态（in-place Edit·非 git checkout）**：把 advisory 改成洗白（恒 ok=True 不真跑门）→ 模板基线测试转红（`assert True is False`·证 advisory 真跑门非桩）→ 手工复原 → 5 passed。

**测试**：scoped `5 passed in 0.19s`；**全量批次 2675 passed / 13 skipped / 0 failed / 116s**（基线 2683 + 5·collect 2688 精确吻合·flake 未触发）+ validate PASS。**改 promote_ide_run（众多 promote 测试共用）零回归** = advisory 真 additive 非破坏。

**意义（推进 §16/§0）**：已建 release gate（§16 八门聚合）此前无生产调用方 → 第十波组装器 → 第十一波执行诚实落账 → 本波 advisory 接进 promote。**至此 §16 发版门真在 promote 路径上跑**：每个 promoted run 携带可追溯 release_verdict（是否可发版 + 缺什么 + 模板冒充被 R4/R5 抓）。

**红线合规**：advisory 只记录不 reject（不预先削弱·不破基线）·防御式不破 promote·复用 evaluate_release 零重写·扩展不替换·未碰 main.py 端点（promote_ide_run 是 promote 数据产出 chokepoint·非 main.py 路由）/release_gate 内部/组装器内部/approval。no 假绿灯（MUT 证门有牙·异常落诚实标）。

**诚实残余 / follow-on**：
- **enforce（硬卡晋级）**：本波只 advisory（记录 release_verdict）。是否在 promote/晋级端点据 release_verdict 硬拒不可发版 run = 后续显式决策（需先把 dataset/LLM/IDE 直接 promote 路径的证据补齐·否则误拒合法 run）·摆代价待定。
- run.json 证据续补：dataset_versions+checksum / LLMCallRecord / IDE 沙箱直接 promote 路径 execution_blocks（KNOWN_RUN_GAPS·续 follow-on）。
- main.py 可加 `GET /api/runs/{run_id}/release_check` 只读端点暴露 release_verdict 给前端（follow-on·非本波）。
