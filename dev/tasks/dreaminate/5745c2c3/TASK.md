# W3 · B-VERSION-1 — 数据写时强约束 dataset_version/checksum→拒

- **uuid**: 5745c2c3
- **LINE**: LINE-B（数据 PIT 脊柱）
- **GOAL ref**: §11 数据层；§17 RDP「缺 DatasetVersion 引用→拒」上游
- **depends_on**: 不可变门已就绪（`data_hash/dataset_hash.py` `write_manifest` 同 version 不同 hash→raise / `verify_version()` 重算核对 / FactorBinding 三元组主键）
- **mint/assign**: leader dreaminate · 2026-06-26 第一波
- **review_status**: 1 · **待拍板**: 0

## 现状（实证 · 先实证再动手）
不可变门**已建**（dataset_hash.py:136-152 同 version 内容变即 raise）。但 `connectors/base.py` FetchResult 只是「便于 data_quality.py 登记 dataset_version」=**advisory**，看不到写路径**强制**缺 dataset_version/checksum→拒。**本卡真 gap = 把已建不可变门接进实际 ingest 写路径，缺 dataset_version/checksum 的写入直接拒**（不是重建不可变门）。

## 第一步（opus 必做）
先 grep 实证：数据落库/登记的真实写入入口在哪（`data_quality.py` register? `connectors/base.py` persist? `ide/promote.py`?），现状是 gate 还是 advisory。把实证结论写进 done 卡，再定最小接线点。**若实证发现已是强制 gate → 诚实标 already-enforced 并补一条对抗测试钉死、不假装新建。**

## 领地（只动这些 · 扩展不替换）
- `app/backend/app/data_hash/dataset_hash.py`（如需扩约束）
- `app/backend/app/connectors/base.py`（FetchResult 写时校验）
- 数据登记入口（`data_quality.py` 或实证确认的写路径单点）
- **复用** `lineage/ids.py` content_hash（绝不另造哈希）；**绝不碰** `field_catalog/`（W2 领地）

## 可证伪验收（种坏门必抓）
1. 缺 dataset_version 的写入/登记 → 拒（对抗：构造无 version 的 FetchResult 喂写路径 → 必 raise；MUT 去掉校验 → 漏过 → 测试红）。
2. 缺 checksum / checksum 不匹配 manifest → 拒（对抗：篡改 checksum → verify 失败 → 拒）。
3. 合法 version+checksum → 正常写入（正路径不误伤·向后兼容）。

## 红线
复用 `lineage/ids.py`；扩展不替换（不可变门不删）；向后兼容（合法写入字节不变）；不碰 field_catalog。

## 完成协议（opus → 中心）
- 只动上列领地 + 写 `dev/tasks/dreaminate/done/5745c2c3/TASK.md`（含写路径实证结论），**绝不碰** dev/state.md / log.md / board.md / GOAL.md / tasks/pool/。
- `cd app/backend && python -m pytest tests/<新测试> -v` 跑绿、不破基线。
- commit + push 分支 `wave1/w3-dataset-write-gate`。
- 回报：分支名 / 改动文件 / 写路径实证结论 / 真测试汇总行 / 对抗测试 / 红线合规 / 拍板项命中 / 诚实残余。
- 无新公式 → 不强造 MathematicalArtifact；重点 correctness（数据完整性）+ 对抗测试。
