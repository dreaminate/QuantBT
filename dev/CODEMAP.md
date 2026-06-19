# CODEMAP · 项目代码结构（不含 dev/ 开发台）

> **干嘛**：项目真实代码在哪、各文件夹装什么,给 agent 导航。**`dev/` 是开发台(过程/计划),不在此图**——本图只画「项目本身」。
> **怎么更新**：代码结构变了(加/删/重命名模块)就同步本图;**只记结构与职责、不记实现细节**(实现看代码 + `tasks/{developer_id}/done/`)。

## 仓库根
| 路径 | 装什么 |
|---|---|
| `app/` | **代码主体**(backend + 前端 + desktop) |
| `dev/` | 开发 OS（**本图不画**） |
| `docs/` | 产品文档(`glossary` / `model_cards` / `plans` / `releases` / `notebooks` / `images`) |
| `config/` · `data/` · `models/` · `var/` · `workspace/` | 配置 / 数据 / 模型产物 / 运行时 / 工作区 |
| `deploy/` · `docker-compose.yml` · `scripts/` | 部署 / 编排 / 脚本 |
| `examples/` | 示例策略 |
| 根 `CLAUDE.md` · `README.md` · `pytest.ini` · `package.json` | 入口路由 / 说明 / 测试配置 / 前端依赖 |

## app/backend/app（后端代码主体）
**治理脊柱（A 簇 · 机构级 Agent OS，T-012~T-022）**
| 模块 | 职责 |
|---|---|
| `lineage/` | 单一身份源 `ids.py`(config_hash/node_id) + 一本账 `ledger.py`(honest-N+memoize) |
| `dag/` | 确定性内核 `kernel.py`(durable / effectful HALT) + engine + effect_ledger + artifact_store |
| `eval/` | 多证据三角 gate(overfit_gate / n_eff / dsr / pbo / bootstrap) |
| `hypothesis/` | 可证伪假设卡(card / gate / falsifiability / store) |
| `security/` | 安全门 gate(policy deny-by-default / nonce 防重放 / broker JIT-key / enforcer OrderGuard) |
| `approval/` | 审批门 + promote 状态机(approver≠creator / 硬限额 fail-closed) |
| `verification/` | 验证官(异模型一致性,产 content-addressed verdict_id) |
| `agent/` | Agent 工作台 + LLM record/replay(replay 不打真 API / 受控翻译门) |
| `copy_trade/` | 跟单中继(`executor` + `gate_binding`,relay 必经 OrderGuard) |
| `execution/` | 执行(`leased_binance`:lease-唯一-key,真 key 只在门后物化) |

**功能平台（M1–M21）**
| 模块 | 职责 |
|---|---|
| `datasets/` · `data_backfill/` · `data_hash/` · `field_catalog/` · `connectors/` · `tushare_quant1/` | 数据层(多源接入 / 补数 / 校验 / 字段目录) |
| `factor_factory/` · `labels/` | 因子库 / 标签(三重障碍) |
| `signals/` · `portfolio/` | 信号融合 / 组合(HRP/ERC/NCO) |
| `training/` · `models/` · `regime/` | 训练台 / 模型注册 / regime |
| `risk/` · `monitor/` · `paper/` · `trading/` | 风控 / 监控 / paper / 交易执行 |
| `experiments/` · `ide/` · `universe/` | 实验注册表 / IDE / 资产池 |

**支撑 / 外围**
| 模块 | 职责 |
|---|---|
| `auth/` · `billing/` · `community/` · `sharing/` | 账号 / 计费 / 社区 / 分享 |
| `glossary/` · `observability/` · `events/` · `backend/` | 术语 / 可观测(Sentry,见 experience) / 事件 / 后端基建 |

## 前端 / 桌面 / 测试
| 路径 | 装什么 |
|---|---|
| `app/frontend/` | 主前端 |
| `app/frontend-run-detail/` | RunDetailPage「收益概述」（**冻结**,见 `RULES.project`） |
| `app/desktop/`(src-tauri) | 桌面壳 |
| `app/backend/tests/` | 后端测试(`cd app/backend && python -m pytest`) |

> 治理脊柱模块职责取自 done 卡 T-012~T-022;**非脊柱模块为结构性归类,权威以代码为准**。
