# RULES.project · 本项目铁律【项目级别】· QuantBT

> OS 通用铁律见 `RULES.md`(勿动)。这里只写**本项目**特有的红线。CLAUDE.md 会把新 agent 指到这份。

<!-- 格式·防跑偏 | 结构型(【项目级别】填):固定三块——项目红线 / 致命错误即停工 / 性能·数据标准。
照本项目实际填;OS 通用铁律不写这里(在 RULES.md)。
怎么更新：① 开发者明确给出/指明本项目红线时,加进来;② agent 遇模糊处 → 先问开发者 → 确认是项目规则后才加(agent 不自己定项目红线)。 -->

## 项目红线
- 前端 `frontend-run-detail/src/pages/RunDetailPage.tsx`「收益概述」页**冻结**,只可排版 / 显示逻辑 / 加字段。
- **A股永不实盘**;禁 `import vnpy / easytrader / ths_trader` 等券商网关。
- **安全不变量**(开发不得削弱,产品代码运行时强制):实盘 key 不进 LLM · 杠杆护栏接所有执行路径(含中继/桥,M17) · API key 关提币 + IP 白名单 · 下单 HMAC 防重放。
- **单一源锚点**:身份源 `app/backend/app/lineage/ids.py`(一套 config_hash、一本账),不另造。
- **honest-N 不可手动改小**(防作弊,硬);但试验可自由跑(研究自由)。「不让你藏试验 ≠ 不让你跑试验」。

## 致命错误即停工（对应 RULES.md §5）
look-ahead 泄露 / 未复权价喂回测成交层 / 实盘 key 进 LLM / A股 live 下单 / 杠杆护栏被中继绕过 / **削弱任一安全不变量(下单 HMAC 防重放、提币 IP 白名单等)** —— **出现即停工**。

## 性能 / 数据标准
- 沪深300×10年日频 < 3s · 回测 < 60s · Run 首屏 < 2s。
- 可复现:同码 + 版本 + seed → ±1e-6(**但 LLM 节点取决策级可复现**,R11)。
- 数据质量:每表 ≥5 data tests + dataset_version + checksum。
- 模式安全:A股永不实盘 + 加密 live 显式切换 + 三档风控 + keyring 加密。
