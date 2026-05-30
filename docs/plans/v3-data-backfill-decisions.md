# v3 · 本地数据补充（backfill）· 决策总结

> 目标（用户原话）：把本地数据补充一下 —— 我提供的 Tushare 能拉到的**所有 A股数据**都拉，
> **加密数据也全部**拉；若 zip 包需要拼接就补充相关逻辑，让它**和 API 一样丝滑**。有问题自行决策。

本文件 = 我代你做的决策记录。机器已建好 + 单测 10 个通过 + **真实小样本端到端验证通过**。

---

## 1. 诚实边界（重要）

"拉全部 A股 + 全部加密"是 **GB~TB 级、受 Tushare 2000 积分限流、数小时~数天**的长任务。
我在会话内**无法**把全量下载完（时间/限流/磁盘）。因此我交付的是：

- ✅ **完整可断点续传的拉取 + zip 拼接管线**（你要的"补充逻辑、像 API 丝滑"）
- ✅ **真实网络小样本验证**（证明端到端真能跑通，非纸上谈兵）
- ✅ **一条命令触发全量**（你按需后台跑，进度可见、可中断续传）

全量下载 = 由你用下面的 CLI 触发的运维操作，不是代码缺失。

## 2. 真实验证结果（本会话实测）

| 源 | 验证 | 结果 |
|---|---|---|
| Tushare（你的 token） | `build_token_pool` + `stock_basic` + `daily` 小样本（真实网络） | ✅ token 生效、**全 A股 5850 只**、daily 拉取 6000 行落地、`read_tushare` 丝滑读出 OHLCV |
| Binance Vision | 逻辑 4 单测（月+日 zip 拼接/缺口/续传/丝滑读，注入 fetch） | ✅ 单测全过；⚠️ 真实下载在本机国内直连 `data.binance.vision` **超时（需代理/VPN）**——非逻辑问题 |

> token 取自 `~/.quantbt/secrets.yaml` 的 `tushare.token`，**全程不打印/不入日志/不入 git**（构建 TokenPool 时用 `_mask_token` 掩码）。
> Binance Vision 国内直连受限：跑全量前需配置代理（`HTTPS_PROXY` 环境变量），或在可直连环境运行 CLI。

## 3. 关键决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | 新建 `app/backend/app/data_backfill/{binance,tushare}.py` 独立编排层 | 与现有 connector/vision_pull 解耦；专做"全量 + 拼接 + 续传" |
| D2 | **Binance 月 zip 打底 + 当月日 zip 收尾** | Vision 有 monthly（全历史请求数少 ~12/年）与 daily；月+日组合最省请求又能到最新 |
| D3 | **拼接 = 按 open_time 去重 + 排序 + 缺口检测 → 连续 parquet** | "像 API 一样丝滑"：`read_klines` 返回与 REST /klines 同列连续序列，上层无感 |
| D4 | **断点续传 = 跳过已存在 parquet** | 全量可中断重跑；增量只补缺的 |
| D5 | 下载/调用**可注入**（`fetch` / `call` 回调） | 单测无需联网；真实用 requests / TokenPool |
| D6 | Tushare 复用现有 `TokenPool`（限流 + 多 token + 用量统计） | 不重造轮子；2000 积分限流由它兜底 |
| D7 | A股接口取**主流全集 19 个**（行情/基础/资金/财务/指数） | "能拉到的所有"——日周月线/复权/每日指标/资金流/三大报表/财务指标/分红/预告/股东数等 |

## 4. 怎么用（统一 CLI，像 API 一样读）

```bash
# 加密：全市场月+日 zip → 连续 parquet（断点续传）
python scripts/backfill.py binance --market um --intervals 1d,1h --start 2020-01-01
python scripts/backfill.py binance --market spot --intervals 1d
python scripts/backfill.py binance --symbols BTCUSDT,ETHUSDT --intervals 1d,4h,1h

# A股：全接口 × 全标的（token 自 secrets.yaml）
python scripts/backfill.py tushare
python scripts/backfill.py tushare --symbols 000001.SZ,600000.SH   # 指定标的

# 全都拉
python scripts/backfill.py all
```

读取（和调 API 一样丝滑，无需关心 zip/拼接）：
```python
from app.data_backfill.binance import read_klines
from app.data_backfill.tushare import read_tushare
df = read_klines("BTCUSDT", "1d", market="um", data_root=Path("data/lake"))
inc = read_tushare("income", data_root=Path("data/lake"), ts_code="000001.SZ")
```

## 5. 全量成本提示（你触发前心里有数）

- **A股**：5850 标的 × 19 接口 ≈ 10 万+ 次调用；2000 积分限流下约**数小时**；落盘约 GB 级。
- **加密**：全 symbol(数百~上千) × 多 interval × 数据类型；月 zip 打底仍是**数 GB~数十 GB**、数小时下载。
- 建议：先按需子集（如先 `--symbols` 主流标的 / `--intervals 1d`），再逐步全量；断点续传可分多次。

## 6. 新增/改动文件

- `app/backend/app/data_backfill/__init__.py`
- `app/backend/app/data_backfill/binance.py`（月+日 zip 拼接 + 缺口检测 + 丝滑读 + 全量编排 + 续传）
- `app/backend/app/data_backfill/tushare.py`（19 接口全集 + 全标的遍历 + 续传 + 丝滑读 + TokenPool 接入）
- `scripts/backfill.py`（统一 CLI：binance / tushare / all）
- `app/backend/tests/test_data_backfill.py`（10 测试，注入 fetch/call 无网络）

## 7. 留待（非阻塞）

- 全量真实下载（你按 CLI 触发；长任务）。
- 可选：把 backfill 触发/进度做成 REST + 前端数据中心一个按钮（当前是 CLI；读取已"丝滑"）。
- 可选：Binance 资金费率/持仓量等非 kline 数据类型扩进同一拼接框架（vision 注册表已含，补 spec 即可）。
