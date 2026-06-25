# W2 · B-PIT-1 — 训练管线消费 PIT 点查（堵 look-ahead）

- **uuid**: fe46991c
- **LINE**: LINE-B（数据 PIT 脊柱）
- **GOAL ref**: §11 数据层 / R28 双时态 PIT；look-ahead 泄露红线
- **depends_on**: PIT API 已就绪（`field_catalog/catalog.py:197 load_panel(as_of_known=...)` + `universe/resolver.py` as-of 双轴）
- **mint/assign**: leader dreaminate · 2026-06-26 第一波
- **review_status**: 1 · **待拍板**: 0

## 现状（实证）
`app/backend/app/training/codegen.py:25` 生成的训练脚本里 `panel = pd.read_parquet(os.environ["QUANTBT_PANEL_PATH"])` —— 裸读全量 parquet，**不经 PIT as-of 边界**。`load_panel(as_of_known=...)`（catalog.py:197）已实现按 known_at 双时态点查，但训练管线零消费 = 死接线（数学对、训练侧用不上）。

## 领地（只动这些 · 扩展不替换）
- `app/backend/app/training/codegen.py`（panel 加载段 + 把 as_of_known 透传进生成脚本）
- **只读消费** `field_catalog/catalog.py::load_panel` / `universe/resolver.py`（不改这俩 = LINE-B owner 单一源）
- 注意：codegen 生成的是**训练脚本字符串**，须把 as_of_known 沿 codegen→生成脚本→load_panel 串通

## 可证伪验收（种坏门必抓）
1. 给定 as_of_known，训练只见「截至该 known_at 已知」的行（对抗：构造一条 known_at 晚于 as_of_known 的未来行 → 训练 panel 必不含它；MUT 还原裸 read_parquet → 该行泄露进训练 → 测试红）。
2. as_of_known=None / 列缺失 → 逐字现状不变（向后兼容·additive）。
3. 绝不用全量 read_parquet 旁路（对抗：断言生成脚本不再含裸 `pd.read_parquet(PANEL_PATH)` 无 as-of 守卫的路径，或等价点查证明）。

## 红线
look-ahead 泄露/未复权价喂成交层即停；复用 field_catalog 单一 PIT 源不另造；扩展不替换；向后兼容默认不变。

## 完成协议（opus → 中心）
- 只动上列领地 + 写 `dev/tasks/dreaminate/done/fe46991c/TASK.md`，**绝不碰** dev/state.md / log.md / board.md / GOAL.md / tasks/pool/。
- `cd app/backend && python -m pytest tests/<新测试> -v` 跑绿、不破基线。
- commit + push 分支 `wave1/w2-pit-wiring`。
- 回报：分支名 / 改动文件 / 真测试汇总行 / 对抗测试（泄露 MUT 必抓）/ 红线合规 / 拍板项命中 / 诚实残余。
- 无新公式 → 不强造 MathematicalArtifact；重点 correctness（无前视）+ 对抗测试。
