---
uuid: 64717fe601994e5999f1bf5c787d3aff
title: paper provider 真回放捆绑样本——替换确定性合成游走（§3 增强）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: paper
source: goal-gap
source_ref: 2026-06-23 DS-4 leader §3 复审残余 · 真样本回放
depends_on: [cfb7d950a05f401784ac6063fcc73419]
---

# paper provider 真回放捆绑样本

## Scope [必填]
DS-4 的 `ReplayBarProvider` 现喂 content_hash 派生的**确定性合成游走**（已诚实标 `deterministic_sim_walk`、非假绿）。增强：让 crypto 市场的 paper run **真回放 DS-1 捆绑的 BTC 样本**（`data/samples/crypto/BTCUSDT_1d.csv` 真 close 序列）——更「能信」（陌生人晋级的真回测策略在 paper 跑真历史 bars）。须连带修 `seed_positions` 的 entry_price 耦合（现硬编 100 匹配合成 base，换真价 ~16000-47000 需用样本首价反推 qty/entry，否则 P&L 失真）。无样本的市场（A股 token-gated）保留合成兜底、标签诚实区分。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么 |
|---|---|---|
| app/backend/app/paper/replay_provider.py | ReplayBarProvider.__post_init__ + seed_positions | crypto 读真样本 close 序列 + entry_price 用样本首价；无样本→合成兜底（标签区分 bundled_sample_replay / deterministic_sim_walk） |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. crypto paper run → series = 真 BTC 样本 close（断言序列前几值=样本真值，非合成 100 起）；source=bundled_sample_replay。
2. entry_price 用样本首价 → P&L 合理（非 300x 失真）；无样本市场→合成兜底 + source=deterministic_sim_walk。

## 验收一句话 [必填]
crypto paper 真回放 BTC 样本 bars（source 诚实）、P&L 不失真；无样本市场合成兜底标签区分；不破基线。

## 完成记录（2026-06-24 · deliver-final）
- commit `45b0f19`：crypto paper 读真 BTC 样本 close 序列（`data/samples/crypto/BTCUSDT_1d.csv`，source=`bundled_sample_replay`），entry_price 用样本首价反推 qty 防 P&L 失真；无样本市场（A股）合成兜底标 `deterministic_sim_walk`；混源诚实复合标。复用 `sample_data` 单一源、未另造路径。
- 对抗测试 +7（含变异自检：entry_price 改回 base=100 → 3 测转红，证非套套逻辑）；focus 151 passed；全量后端 1357 passed / 0 failed。
- 诚实残余：length=64 截断（真样本 516 行回放前 64，幂等取舍）；A股真样本待 `TUSHARE_TOKEN`（未来卡，本卡范围纪律内不做多市场样本扩展）。
## 完成记录
- `ReplayBarProvider` now tries `data/samples/crypto/<symbol>_1d.csv` first, including normalized symbols such as `BTC-USDT -> BTCUSDT_1d.csv`.
- Added source labels:
  - `bundled_sample_replay` for all-symbol bundled sample replay.
  - `deterministic_sim_walk` when no bundled sample exists.
  - `mixed_bundled_sample_and_deterministic_sim_walk` when one run mixes both.
- Sample bars keep the caller symbol in returned bars, so paper positions/orders still match `BTC-USDT` style symbols.
- `seed_positions()` now uses provider first price for entry price and quantity sizing; BTC sample starts at `47704.35`, so a 50k notional seed no longer uses the old hard-coded 100 entry.
- Empty `simulate=False` runs remain red: no provider, `bars_fed=0`, no fake equity.
- Validation:
  - `python -m pytest app/backend/tests/test_paper_desk_api.py app/backend/tests/test_paper_scheduler.py app/backend/tests/test_delivery_slice_e2e.py -q` -> 37 passed / 2 warnings.
  - `python -m compileall -q app/backend/app/paper/replay_provider.py app/backend/app/paper/desk.py app/backend/app/paper/__init__.py` -> PASS.
  - `python -m pytest app/backend/tests/test_agent_business_tools_a4.py app/backend/tests/test_ds1_run_id_spine.py app/backend/tests/test_paper_desk_api.py -q` -> 63 passed / 2 warnings.
  - `cd app/backend && python -m pytest -q` -> 1567 passed / 13 skipped / 283 warnings.

## 边界
- This is still a local bundled-sample replay provider, not a realtime exchange connector and not testnet/live data.
- A股 live rejection is unchanged.
- Symbols without bundled samples still use deterministic synthetic fallback, with the source label exposed.
