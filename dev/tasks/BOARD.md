# 任务台 · BOARD（活跃任务板）

> 完成即把 `active/<id>/` 落档到 `done/<id>/`、本表那行删掉（**主板永不臃肿**）。
> `review_status`: 0=未经用户确认 · 1=用户已确认。任务文件模板见 `_templates/TASK.md`。
> 完整性自检：`python dev/scripts/validate_dev.py`。
> **本表 = 活跃版**（只列 todo/in_progress，完成即删行）；**全含量版**（含 done，需要时查询）：`python dev/scripts/build_ledger.py`。

<!-- 格式·防跑偏 | 结构型：固定表头列 id | 标题 | 来源 | 状态 | 优先级 | 依赖 | 验收一句话。
本表=活跃版,只列 todo/in_progress；任务完成 → 落档 done/<id>/ 并**删本表那行**（永不臃肿）。
全含量版不手维护——由 build_ledger.py 从 active/+done/ 目录现生成（防第二份账本自己跑偏）。 -->

| id | 标题 | 来源 | 状态 | 优先级 | 依赖 | 验收一句话 |
|----|------|------|------|--------|------|-----------|
| T-023 | 确定性内核（T-014）接进 jobs/agent 执行路径 | 收口§A | todo | P0 | T-014,T-013,T-016 | 种重发单/重跑LLM/fork撤单→内核边界必截断走对账不重发 |
| T-024 | 可证伪假设卡接进 Run 生命周期（P2 不挡探索） | 收口§A | todo | P1 | T-017,T-013,T-020 | 空机制当 confirmatory→拒、探索留空→放行、冻结改字段→拒、措辞黑名单 0 hit |
| T-025 | 真钱执行路径审计 + 急停/kill 控件收尾 + GenericVenue 接活 | 收口§A | todo | P1 | T-021,T-022 | 种绕门 place_order→审计必抓、kill 端点无鉴权→403、emergency 真平仓非空 log、generic venue 接活经门 |

## 建设顺序
脊柱 8 块全建并验证（T-012~T-022，1001 测试绿，已合并 main；**全档见 `done/` + `build_ledger.py`**）。
**进入收口阶段**（`DECISIONS.md` D-CLOSEOUT：1A 价值密度混合 / 2B 分两轮 / 3C 最大自驱 / 4B 先看卡）。
**第一波 = 簇A 脊柱收尾**（T-023/T-024/T-025，**2 岔路已决 D-T024/D-T025**，待用户过目最终卡后开跑）；第二波起按 1A（C 组合三角 + D 双时态 → B 因子轨 → E/F 交织）。
诚实残余：TCB 天花板（本地门=防篡改证据，唯一硬墙在交易所侧）。
