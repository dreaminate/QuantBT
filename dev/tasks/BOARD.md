# 任务台 · BOARD（活跃任务板）

> 完成即把 `active/<id>/` 落档到 `done/<id>/`、本表那行删掉（**主板永不臃肿**）。
> `review_status`: 0=未经用户确认 · 1=用户已确认。任务文件模板见 `_templates/TASK.md`。
> （旧 codex 任务残留 `TASK-0001/` + `index.md` 已归 `_archive/`，仅留档。）
> 完整性自检：`python dev/scripts/validate_dev.py`（BOARD↔done 一致 / 四台齐全 / 无悬空旧路径）。

| id | 标题 | 来源 | 状态 | 优先级 | 依赖 | 验收一句话 |
|----|------|------|------|--------|------|-----------|
| T-001 | 蒸馏 `dev/GOAL.md` 完整最终形态 | 备忘录/四台范式 | ✅ done | P0 | — | 两层相乘终态、剔过渡、每子系统可证伪验收（落档 `done/T-001/`） |
| T-012 | `lineage/ids.py` 单一身份源 | spine 01/03 + S1 | ✅ done | P0 | — | 种重复/NFC/24位/假语义去重 → 门必抓（8 绿） |
| T-013 | lineage 一本账（SQLite WAL + JSONL，honest-N + memoize） | spine 03 + S2/S4 | ✅ done | P0 | T-012 | 种重复 config_hash 不重跑且计 N、N 不可手动改小（落档 `done/T-013/`，25 对抗测试 + 13 变异全杀 + 二轮复核） |
| T-014 | 01 确定性内核（node 身份 / durable / effectful 不可幂等边界） | spine 01 | ✅ done | P0 | T-012,T-013 | 种重发单 → HALT 边界必截断、走对账不重发（落档 `done/T-014/`，25 对抗测试 + 15 变异全杀 + 专项 money-safety 复审无 HIGH；jobs/agent 接线 deferred） |
| T-015 | 05 试验账本算法层 + 多证据三角 gate（接 DSR/PBO/bootstrap 进 run） | spine 05 | ✅ done | P0 | T-013 | 噪声→不绿、泄露→N_eff<<N、接线活性证明（落档 `done/T-015/`，24 对抗测试 + 变异全杀 + 5-lens 复核 10 真发现全修，含 honest_n 兜底通缩 HIGH） |
| T-016 | 02 LLM record/replay + 受控翻译层 | spine 02 | ✅ done | P1 | T-013 | replay 时真 LLM 调 0 次、cache key 不碰撞（落档 `done/T-016/`，30 对抗测试 + 变异全杀 + 5-lens 复核 14 真发现全修，含常量 run_id 撞键 HIGH） |
| T-017 | 04 假设卡（P2 不挡探索） | spine 04 | ✅ done | P1 | T-013 | 空机制卡 confirmatory、探索留空必放行（落档 `done/T-017/`，29 对抗测试 + 变异全杀 + 5-lens 复核 15 真发现全修，含可证伪检测字词门退化 HIGH） |
| T-018 | 06 安全门 deny-by-default + 交易所侧硬墙（gate 组件） | spine 06 | ✅ done | P1 | T-014 | 注入也取不到 key、四路径同判（M17）（落档 `done/T-018/`，23 对抗测试 + 7 变异全杀 + 5-lens 复核 19 真发现：12 在 gate 内修、**7 生产接线 deferred→T-021**） |
| T-021 | 06 安全门【生产接线】：relay 必经 OrderGuard + 默认门模板 + 防重放 + fail-closed | spine 06 §4/§7 | ✅ done | P1 | T-018 | INV-2/M17 生产强制（落档 `done/T-021/`，16 对抗测试 + 8 变异全杀 + 5-lens 复核 4 真发现全修；产品决策 D-T021-1/2/3）。🟡 INV-3 lease-唯一-key 通道→T-022 |
| T-022 | 06 安全门 INV-3：venue 只认 lease 签名（移除 self-fetch）+ 生产注入 broker | spine 06 §4 | ✅ done | P2 | T-021 | INV-3 relay 闭合（落档 `done/T-022/`，LeasedBinanceVenue 构造不持 key/真 key 只在门后 S4 物化/has_key 不 fetch；10 对抗测试 + 4 变异全杀 + 5-lens 复核 15→1[LOW]修；既有 venue 零改动 additive） |
| T-019 | 07 审批门 + promote 改带审批门状态机 | spine 07 | ✅ done | P1 | T-013,T-018 | approver≠creator、缺要件拒并返缺口（落档 `done/T-019/`，22 对抗测试 + 5 变异全杀 + 5-lens 复核 17 真发现全修；含生产接线 main.py 端点 + apply_stage 侧门修复 HIGH） |
| T-020 | 部件12 验证官（产 verdict_id，异模型一致性，S3 提前） | S3 | ✅ done | P1 | T-013,T-016 | 异模型不一致即 BLOCK、措辞禁「组织独立」（落档 `done/T-020/`，31 对抗测试 + 10 变异全杀 + 5-lens 复核 18→5 真发现全修；含生产接线 + verdict↔工件绑定 + 防篡改读路径 3 处 HIGH 修复）|
| T-023 | 确定性内核（T-014）接进 jobs/agent 执行路径 | 收口§A | 🟡 pending_review | P0 | T-014,T-013,T-016 | 种重发单/重跑LLM/fork撤单→内核边界必截断走对账不重发（`active/T-023/`，4B 待用户过目） |
| T-024 | 可证伪假设卡接进 Run 生命周期（P2 不挡探索） | 收口§A | 🟡 pending_review | P1 | T-017,T-013,T-020 | 空机制当 confirmatory→拒、探索留空→放行、冻结改字段→拒、措辞黑名单 0 hit（`active/T-024/`，4B 待用户过目） |
| T-025 | 真钱执行路径审计 + 急停/kill 控件收尾 | 收口§A | 🟡 pending_review | P1 | T-021,T-022 | 种绕门 place_order→审计必抓、kill 端点无鉴权→403、emergency 真平仓非空 log（`active/T-025/`，4B 待用户过目） |

## 建设顺序（spine/00 §标注②）

第0层 T-012(✅)+T-013(✅)+T-014(✅) → 第1层 T-015(✅) → 第2层 T-016(✅)+T-017(✅) → 第3层 T-018(✅ gate 组件，生产接线→T-021)+T-019(✅)+T-020(✅)。
**脊柱 8 块全建并验证 + 安全门生产接线全链闭合**（T-021 relay 闸门 INV-2/M17/INV-4 生产强制 + T-022 INV-3 key 只在门后物化）。
脊柱 8 块全建并验证（1001 测试绿，已合并 main）。**进入收口阶段（D-CLOSEOUT：1A 混合 / 2B 分两轮 / 3C 最大自驱 / 4B 先看卡）。**

**收口第一波 = 簇A 脊柱收尾**（T-023/T-024/T-025，pending_review，4B 待用户过目卡后开跑）：把已建但 deferred 的内核接活、假设卡接进 Run、真钱路径审计坐实 + 急停控件收尾。第二波起按 1A 混合（C 组合三角 + D 双时态 → B 因子轨 → E/F 交织）。诚实残余：TCB 天花板（本地门=防篡改证据，唯一硬墙在交易所侧）。
