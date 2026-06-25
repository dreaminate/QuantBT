# W4 · D-RDP-1 — Research Delivery Package schema + manifest + 拒绝门

- **uuid**: 0e7bbc13
- **LINE**: LINE-E（交付信任·北极星总闸）
- **GOAL ref**: §17 交付标准（2033-2076，开放格式 RDP）
- **depends_on**: 无（greenfield · `app/backend/app/delivery/` 全仓 0 hit）；消费已建对象（DatasetVersion/artifact hash/honest-N/Verifier verdict 等已在 main）
- **mint/assign**: leader dreaminate · 2026-06-26 第一波
- **review_status**: 1 · **待拍板**: 0

## 现状（实证）
`app/backend/app/delivery/` 不存在（greenfield）。§17 定义正式研究交付 = 开放格式 Research Delivery Package，含 ~25 字段 manifest（manifest / 研究命题 / Research Graph / 数据·PIT 语义 / DatasetVersion·IngestionSkill / LLMCallRecord·replay / TheorySpec·Binding·ConsistencyCheck / MethodologyChoiceRecord·ResponsibilityDisclosure / 因子·模型·信号·StrategyBook 版本 / 代码·环境·hash·seed / reproducibility command / source refs / artifact hash / environment lock / 测试·对抗测试 / 回测·训练·验证 run / honest-N / 成本·执行假设 / 归因 / 已知限制 / 未验证残余 / Verifier verdict / Approval·promotion / Deployment·monitor·rollback·retire 清单）。

## 领地（greenfield · 零交叠）
- 新 `app/backend/app/delivery/`：`rdp.py`（schema dataclass + manifest 序列化为开放格式 JSON）+ `rdp_gate.py`（4 条拒绝门）
- **只读引用**已建对象的字段（不改它们）：DatasetVersion(`data_hash`)、artifact hash(`lineage/ids.py`)、honest-N(`lineage/ledger`)、Verifier verdict、Approval。**复用 `lineage/ids.py` 不另造身份。**

## 可证伪验收（§17 四条拒绝门·种坏门必抓）
1. RDP 缺 manifest / artifact hash / reproducibility command → **拒**（对抗：去掉任一 → assemble/validate raise；MUT 放过 → 测试红）。
2. RDP 缺 DatasetVersion 或 IngestionSkill 引用 → 拒。
3. RDP 缺「未验证残余」字段 → 拒（这是诚实闸：未声明残余即不可信）。
4. 晋级资产无法追溯到 RDP → 拒（promotion 须带 RDP ref）。
本卡先落 **schema + 序列化 + 4 拒绝门 + 对抗测试**；接进真实 promote 路径作 follow-on（mint P2，本卡不强求端到端，但拒绝门须真能拒）。

## 红线
复用 `lineage/ids.py` 单一身份源；开放格式（JSON·可第三方解析·绝不私有二进制）；不假绿灯（缺字段真拒，不静默填默认）；扩展不替换。

## 完成协议（opus → 中心）
- 只动 greenfield `delivery/` + 写 `dev/tasks/dreaminate/done/0e7bbc13/TASK.md`，**绝不碰** dev/state.md / log.md / board.md / GOAL.md / tasks/pool/ / 已建对象文件。
- `cd app/backend && python -m pytest tests/<新测试> -v` 跑绿、不破基线。
- commit + push 分支 `wave1/w4-rdp-schema`。
- 回报：分支名 / 新建文件 / 真测试汇总行 / 4 拒绝门对抗测试 / 开放格式证据 / 拍板项命中 / 诚实残余（端到端接线 follow-on 标清）。
- 无新公式 → 不强造 MathematicalArtifact；重点 §17 契约 correctness + 拒绝门对抗测试。
