---
uuid: 381b6c1830244df3b552079823f3a471
title: 实盘因子血统门——未过检验因子上真钱线 → 警告+知情确认
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: security-invariant
source: interaction
source_ref: 2026-06-20 用户提出 + D-PROVENANCE + GOAL §2/§5
depends_on: []
---

# 实盘因子血统门——未过检验因子上真钱线 → 警告+知情确认

## Scope [必填]
上真钱线(CRYPTO_LIVE)前,逐一校验策略所用每个因子是否走完治理流程(假设卡→独立验证→审批)。只要有一个未过 → **上线前强制弹窗警告**(列出未过因子)+ **知情确认(acknowledge 留痕)后仍可上**(用户自己的钱与判断,§0.1)。硬透明 + 软决定,非死挡(D-PROVENANCE)。

## 上下文 / 动机 [按需]
用户 2026-06-20 提出:实盘策略里可能混入根本没过整个流程检验的因子,上真钱前必须让用户知情。与 self-approve(T-030)、真钱双人并列的真钱保护,补一道"血统"维度。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/lineage/ | 因子→策略 谱系 | 查策略用到哪些因子 + 各自治理状态 |
| app/backend/app/hypothesis/store.py | 假设卡状态 | 因子是否过假设卡 |
| app/backend/app/verification/ | verdict | 因子是否过独立验证 |
| app/backend/app/approval/gate.py | 70-131 上线审批 | 上真钱线前插血统校验 + 警告 |
| 客户端 | 血统警告弹窗 | 列未过因子 + 知情确认 |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 未过必警告:种"策略含 1 个没过假设卡/验证的因子 → 上真钱线" → 必弹警告列出该因子;种"血统门漏检某因子" → 抓。
2. 知情确认留痕:确认后审计必记 acknowledge(谁/何时/哪些因子);种"确认无留痕" → 抓。
3. 非死挡:全部因子过检验 → 不弹窗正常上;种"血统门误把已过因子拦死" → 抓。

## 复用 [按需]
`lineage/` 谱系、`hypothesis/store.py`、`verification/` verdict 现有状态查询。

## 红线 [按需]
真钱保护(§5);硬透明 + 软决定(D-PROVENANCE / 同 D-T024-FALS 范式),不死挡用户自己的判断。

## 非目标 [按需]
不对非真钱(paper/testnet)强制血统门(探索自由);不死挡(知情确认后可上)。

## 验收一句话 [必填]
种"未过检验因子上真钱线无警告 / 确认无留痕 / 已过因子被误拦" → 门必抓;不破基线。

## 完成记录（2026-06-20）
- **血统门核心机制（安全，D-PROVENANCE）**：新模块 `app/backend/app/provenance.py`——`check_factor_provenance` / `gate_live_promotion(factor_ids, status_lookup, acknowledged)`：逐因子查治理状态，任一未 cleared → 列出 + `requires_acknowledge`；已知情确认 → 放行 + 留痕（硬透明 + 软决定，绝不死挡）；查询异常按未过 fail-safe（绝不当已过）。
- **对抗测试**（`test_provenance_gate.py` 5 passed）：未过因子必警告 / 知情确认放行留痕 / fail-safe 未过 / 全过不误拦探针。
- **残余（端点 + 谱系接线）**：`status_lookup` 注入需接 lineage 谱系（策略→因子）+ hypothesis/store + verification（因子治理状态）；上真钱线端点（safety ladder live / copy_trade live）插 `gate_live_promotion` + 前端血统警告弹窗。核心判定逻辑 + 单测已做实，接线建议拆子卡（需谱系 API）。
