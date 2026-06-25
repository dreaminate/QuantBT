---
uuid: 67b4202584534a23b147973d7d48b8ca
title: RDP 接线——接现导出器 6 字段 + 接真 promote 路径 require_valid_rdp（D-RDP-1 wire）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: delivery
source: goal
source_ref: GOAL §17 + 9d593481 完成记录诚实残余（schema+4 门 ✅·接线 🟡）
depends_on: [9d593481fd674978930926f541f2b7b3]
---

# RDP 接线（D-RDP-1 wire）

## Scope [必填]
9d593481 已建 RDP schema + §17 四拒绝门（greenfield `delivery/`·22 对抗测试·🟡 未接线）。本卡接线：
① 现导出器 `run_detail_research_export.py` 的 6 个 run-bundle 字段透传进 `RDPManifest`（扩展不替换·不动 RunDetailPage 收益概述页冻结·只加字段/只加文件）；
② 接真 promote 路径——`approval.gate.ApprovalGateService.approve` / `paper.desk.PaperDeskService.approve_promotion` 翻态前调 `require_valid_rdp(rdp, promotion=claim)`，晋级缺/残缺 RDP 追溯 → 拒。
RDP 聚合器（D-RDP-2·依赖 LINE-A LLMCallRecord + B DatasetVersion）另卡，本卡不做。

## 文件领地（owner·并发隔离）
`run_detail_research_export.py`、`approval/gate.py`、`paper/desk.py`、`delivery/`（扩 `rdp_gate.py` 加接线闸·**不改已建 4 门语义**）。新增 `tests/test_rdp_wire.py`（扩展不替换 `test_rdp_gate.py`）。**未碰** main.py / 前端 RunDetailPage / experiments/store.py / 其他飞线领地。

## 对抗验收（种坏门必抓）[必填]
1. promote 带残缺 RDP（缺 manifest/hash/repro/DatasetVersion/未验证残余）→ 拒晋级（端到端·MUT 放过→红）。
2. 现导出器 6 字段进 RDPManifest 不破 RunDetailPage 冻结（仅加字段/文件）。
3. 缺字段 RDP → verdict blocked/missing，不美化完整交付。

## 红线 [按需]
RunDetailPage 收益概述页冻结 · no template false success · 缺字段诚实标 missing · OrderGuard/promote 门不绕 · 扩展不替换 · 复用 lineage.ids 不另造。

---

## 完成记录（2026-06-26 · deep-opus 任务线 · 隔离 worktree）

### 实现（扩展不替换，6 文件 +165/-2）
- `delivery/rdp_gate.py`：新增接线闸 `require_promotion_rdp(rdp, promotion=None, *, require_rdp=False)`——
  rdp 给出 → 调既有 `require_valid_rdp(rdp, promotion=...)`（门1-3 恒跑·门4 仅当 claim 给出·**4 门语义零改**）；
  rdp=None 时按 `require_rdp` 分流：False（默认·向后兼容）放行 / True 则按「晋级资产无法追溯 RDP → 拒」raise RDPRejected。导出进 `delivery/__init__.py`。
- `approval/gate.py`：`ApprovalGateService.approve` 加 3 个 keyword-only 可选参（`rdp` / `promotion_claim` / `require_rdp`），在 pending 守卫后、**任何 gate mutation 之前**调 `require_promotion_rdp`（fail-closed：残缺 → 不进 approved、不跑 execute_fn、stage 不翻）。默认全 no-op。
- `paper/desk.py`：`PaperDeskService.approve_promotion` 同加 3 参，在 INV-5 四检通过后、`promoted` 翻态前调 `require_promotion_rdp`（残缺 → promoted 不动、门仍 pending）。默认全 no-op。
- `run_detail_research_export.py`：新增 `build_rdp_from_run_bundle(run_id, manifest, *, 6 字段, **rdp_fields)`——把 strategy_py→code_refs/source_file_refs、report_md/log_text→source_file_refs、trades/positions→backtest_run_refs、attribution→attribution 槽诚实投影；门强制项（artifact_hash/repro/dataset_versions/ingestion/未验证残余）只从 manifest+显式 rdp_fields 透传，缺即留空（不补默认）。`export_run_bundle_for_detail` 加可选 `rdp` 参 → 给出则额外写开放格式 `rdp.json`（只加文件，run.json/portfolio.csv 与冻结页计算零变化）。
- id 仍走单一身份源（RDPManifest 内部 `lineage.ids.content_hash`），本卡不另造哈希。

### 真测试汇总行（scoped·带 timeout·凭汇总行判绿）
- `tests/test_rdp_wire.py`（新·15 用例）→ **15 passed in 1.21s**。
- `test_rdp_wire.py + test_rdp_gate.py + test_overview_rows.py` → **40 passed in 0.75s**（接线未破已建 4 门 + 导出器基线）。
- `test_paper_desk_api.py + test_approval_gates.py + test_self_approve.py + test_verification_verdict.py + test_run_verdict_card.py` → **117 passed in 3.50s**（两条 promote 路径基线全绿·默认参 no-op 证不破基线）。
- 全量 `--collect-only` → **1813 tests collected**，零 import 报错（接线未破任一模块加载）。**未跑全量套件**（scoped only）。

### 对抗测试（种坏门必抓·MUT 定点反向·绝不 git checkout）
- **promote 缺/残缺 RDP 必拒**：`test_paperdesk_promote_with_incomplete_rdp_rejected`（paper 端到端）+ `test_approvalgate_approve_with_incomplete_rdp_rejected_stage_not_flipped`（model 端·断言 execute_fn 未跑、stage 未翻）。
- **MUT 承重锚（无 checkout）**：`test_paperdesk_promote_rdp_enforcement_is_load_bearing_mut`——同款合规晋级 rdp=None【成功】 vs rdp=残缺【被拒】，差量即闸的承重证据；把 `require_promotion_rdp` 改弱成放行 → 残缺分支转绿 → `pytest.raises(RDPRejected)` 立刻红。
- **require_rdp=True 无 RDP → 拒**（两路径各一）；**张冠李戴**（claim.asset_ref≠RDP）→ 门4 拒；**完整 RDP+匹配 claim → 放行**（证非砖墙·门4 真追溯）。
- **冻结页不破**：`test_overview_row_frozen_schema_unchanged`（OverviewRow == 7 冻结列）+ `test_build_rdp_does_not_touch_overview_rows`（构造 RDP 前后 build_overview_rows 逐行一致·行键恒为冻结集）+ `test_export_emits_rdp_json_additively`（rdp.json 仅追加·run.json 逐字节不变）。
- **残缺 RDP → missing 不美化**：`test_incomplete_rdp_verdict_lists_missing_not_beautified`（validate_rdp 不 ok·missing 含 artifact_hash/repro/dataset_versions/ingestion/未验证残余·reason 含「拒」不含「通过」）。

### 红线合规（逐条）
- **RunDetailPage 收益概述页冻结**：✅ 未碰前端；导出器只加 `build_rdp_from_run_bundle` + 可选 `rdp.json` 文件，`build_overview_rows`/`OverviewRow` 7 列结构零改，对抗断言守。
- no template false success / 缺字段诚实标 missing：✅ 投影不补门强制项，残缺 RDP 经 validate_rdp 据实判 blocked/missing。
- OrderGuard / promote 门不绕：✅ 仅【加】一道 §17 RDP 闸于翻态前，未削弱 INV-5/三要件/A股 live-forbidden 任一既有门（基线 117 绿）。
- 扩展不替换：✅ 全是新增函数 / keyword-only 可选参（默认 no-op），无既有签名破坏、无 4 门语义改动。
- 复用 lineage.ids 不另造：✅ 无新哈希族。
- 安全不变量：✅ 未触实盘 key / 杠杆护栏 / HMAC / 提币白名单；RDP 闸是 fail-closed（残缺 raise·绝不静默放行）。

### 拍板项命中
无新待拍板项。一个【已按规则自决并诚实标注】的取舍见下「诚实残余」——非冲突、不阻塞，留中心/leader 复核口径。

### 诚实残余（🟡 留 follow-on）
1. **强制档默认关（向后兼容取舍·已自决）**：接线默认 `require_rdp=False`——未带 RDP 的既有晋级仍放行（不破基线·两路径 117 基线绿）。§17「任何正式晋级必须追溯 RDP」的【全量强制】需 D-RDP-2 聚合器把真血统装进 RDP 供给 promote 路径后，再把开关常开（或 main.py 路由透传 rdp）。闸已就位 + `require_rdp=True` 分支真能拒（对抗测试守），翻开关即「真·不绕」。**理由**：D-RDP-2 未建时强制开 = promote 路径全砖死且无法产合法 RDP，违「不破基线」。
2. **HTTP 路由层未透传**：`main.py:4695`(/api/paper/.../approve) 与 `:1094`(model promote) 暂未把 `rdp`/`claim` 透传进服务方法（本卡领地**绝不碰 main.py**）。服务层 promote 路径已接线 + 端到端测；经 HTTP 强制 RDP 需一处 main.py 编辑，留 follow-on。
3. **RDP 聚合器（D-RDP-2）另卡**：依赖 LINE-A LLMCallRecord + B DatasetVersion 产真血统；本卡只接线投影，不产真 §17 全量 RDP。
4. **命名对象 typed 化**：LLMCallRecord/ResponsibilityDisclosureRecord/TheorySpec 仍 string ref（承 9d593481 残余③），待类建好收紧。

### land 信息
- 分支：`wave2/w4-rdp-wire`（push `git push origin HEAD:wave2/w4-rdp-wire`·省略 co-author）。
- 改动文件：`app/backend/app/delivery/rdp_gate.py`、`delivery/__init__.py`、`app/approval/gate.py`、`app/paper/desk.py`、`run_detail_research_export.py`、`tests/test_rdp_wire.py`。
- 整合 / 全量 / land 由中心 orchestrator 收口。
