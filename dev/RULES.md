# RULES · 开发铁律（不可妥协）

## 0. 哲学
处处最专业最严谨；**绝不因「单用户/低频」砍任何治理**；用户有困难派 agent 辅助，而不是降低标准。

## 1. 复用 + 性能（S4）
- **单一源**：一个身份源 `app/backend/app/lineage/ids.py`、一套 config_hash、一本账——消灭重复实现（复核 §1.2-A 抓出的双产方就是反面）。
- **性能**：SQLite WAL 索引做 source-of-truth（查 config_hash/honest_n 走 O(log n) 不是 O(n) 扫 jsonl）+ append-only JSONL 做防篡改审计镜像 + memoize（命中即跳过重算）+ 有界 N_eff。
- **复用现有**：`experiments/store.py` 的 `_gen_id`/`_JsonlStore`、`data_packages.py:70` 的 `sha256[:16]`、`copy_trade` 幂等范式——不重造轮子。

## 2. 测试验收标准（绝不妥协）
不是覆盖率，是「**种一个已知的坏，门必须抓住，否则门是纸做的**」。每部件配：泄露探针 / 噪声探针 / 变形测试（打乱时间→Sharpe坍塌、加成本→净值降）/ 幂等 / 裁决措辞 / 对账探针。范式见 `app/backend/tests/test_lineage_node_id.py`。

## 3. 诚实纪律（dogfood 产品原则）
- 🟡「声称但未验证」≠ ✅「已建并验证」——`STATE.md` 绝不假绿灯。
- 裁决永远说「证据充分/不足 + 适用域 + 没验证的」，**绝不说「可信/安全」**。
- honest-N **不可手动改小**（防作弊，硬）；但试验**可自由跑**（研究自由，放）。「不让你藏试验 ≠ 不让你跑试验」。

## 4. 工程红线
- 不破坏现有 **763 测试**；改现有文件用「**扩展不替换**」。
- 前端 `RunDetailPage`「收益概述」页**冻结**，只可排版/显示逻辑/加字段。
- git 在 `fullstack` 分支、有未提交改动；**不要 commit 除非用户明说**。
- `DECISIONS.md` **append-only**，`confirmed_by` 锁定后不改既往。

## 5. 致命错误即停工（自原 GOAL §12）
look-ahead 泄露 / 未复权价喂回测成交层 / 实盘 key 进 LLM / A股 live 下单 / 杠杆护栏被中继绕过——**出现即停工**。
