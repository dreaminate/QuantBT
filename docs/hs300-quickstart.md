# HS300 性能证据链 · 5 分钟 Quickstart

用你自己的真实 Tushare 数据把 GOAL §16「沪深300×10年日频读取 <3s」性能门合法转绿。
前提:tushare.pro 账户 ≥2000 积分;macOS(系统 Keychain)或带 libsecret 的 Linux 图形会话。

> 语义先讲清:本链产出的是**读性能基准面**(as-of 当期 300 成分×十年,带幸存者选择,
> metadata 已标 `research_use=forbidden_confirmatory`)——不是无偏研究 universe,别拿去回测选股。
> `operator_attested` 是**你本机的完整性背书**(经跨厂商 dual-model 复核流程),不是 Tushare
> 官方签名或第三方审计。诚实边界详见 `dev/research/findings/dreaminate/hs300-chain-evidence-20260714.md`。

```bash
# 0. 录入 Tushare token(交互输入,不回显、不进 shell 历史)
python scripts/hs300_onboard.py store-token

# 1. 生成 provenance 签名 key(只打印 sha256 指纹;指纹就是要 pin 的 verification_key_sha256)
python scripts/hs300_onboard.py keygen

# 2. 拉取十年数据(~700 次 API 调用,180 次/分限速,4-6 分钟;中断直接重跑续拉)
python scripts/hs300_onboard.py pull --staging-dir data/.cache/tushare_hs300_raw

# 3. 自检(12 项门逐项诊断;不过会给出每项 fail 明细)
python scripts/hs300_onboard.py preflight --staging-dir data/.cache/tushare_hs300_raw

# 4. 组链签名(DatasetVersion + 不可变 manifest + 签名 universe/receipt)
python scripts/hs300_onboard.py build \
  --staging-dir data/.cache/tushare_hs300_raw \
  --registry-path data/datasets/registry.jsonl \
  --panel-path data/datasets/lake/hs300_daily_10y_readbench_cohort/panel.parquet \
  --out-dir data/datasets/provenance/hs300_daily_10y_readbench_cohort

# 5. 跑性能探针——build 输出末尾已打印整条 bench 命令,直接复制运行
#    (measured=true + observed < 3.0 即真数据转绿)
```

## 转绿的最后一道门(设计如此,不是 bug)

跑完 1-5 后 bench 仍会报 `out-of-band production authority root` GAP——**除非** harness
(`app/backend/tests/benchmark/perf_harness.py` 的 `_HS300_PINNED_AUTHORITY_ROOTS`)里
pin 了与你 keygen 指纹一致的 authority root。这一步故意要求**经复核的代码改动**:
CLI/环境变量/receipt 都加不进信任根,防止任何人自签自绿。仓库当前 pin 的是
`quantbt-hs300-operator-root-v1`(attestation 依据见该文件注释);要用你自己的 key,
按仓库流程走跨厂商 dual-model 复核后替换/追加 root 并同步演化对应对抗测试。

## 常见失败

| 症状 | 原因与修法 |
|---|---|
| `keyring 无 'tushare'` | 先跑第 0 步 store-token(别用 keygen——那是生成随机签名 key 的) |
| pull 报「每分钟最多访问」 | 限流:等 1 分钟重跑,幂等续拉不丢进度 |
| pull 报「没有权限」 | 积分档不够,确认 ≥2000 积分 |
| preflight `since_listing_coverage` fail | 数据缺口超 20%:先重跑 pull 补全;真实成分自上市覆盖率最差约 0.87,正常数据不会挂 |
| bench `signature mismatch` | build 和 bench 用的 key 不同名,或签名件被手工改过:重跑 build |
| 换了 --start/--end 后数据不对 | staging 目录绑定单一窗口:换窗口必须换 --staging-dir 新目录 |
