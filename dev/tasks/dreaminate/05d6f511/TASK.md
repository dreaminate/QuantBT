---
uuid: 05d6f5110c9d4a6d9cafc37f97905198
title: 单人 self-approve 仅非真钱通道(冷却+留痕)，真钱硬双人
status: todo
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P2
area: approval
source: interaction
source_ref: 2026-06-20 回测全流程审计 workflow + D-SELFAPPROVE + GOAL §5
depends_on: []
---

# 单人 self-approve 仅非真钱通道(冷却+留痕)，真钱硬双人

## Scope [必填]
为单人 + 非真钱场景(回测/paper/testnet/A股模拟)提供诚实的 self-approve 通道:强制 cooling-off(二次确认 + 冷却期)+ 审计如实标 `self_approved=true`(绝不伪装双控)。CRYPTO_LIVE 真钱**绝对保留硬双人 approver≠creator**,self-approve 永不触及真钱。冷却时长 / 上线模式(staging/production)放客户端让用户自设。

## 上下文 / 动机 [按需]
审计:`approver≠creator` 实现扎实,但代码自承"单机本地非组织独立、非防恶意"(R7 同源);单人用户想上非真钱线被卡死 → 逼用小号假身份(更糟)。self-approve = 诚实降级非绕门(D-SELFAPPROVE)。

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| app/backend/app/approval/gate.py | 170-171 approver≠creator | 按场景分级,真钱不变 |
| app/backend/app/approval/gate.py | 51-53 诚实限界 | self-approve 须诚实标注 |
| app/backend/app/approval/channels.py | 13-29 超时 + SLA | 冷却期接线 |
| app/backend/app/main.py | 468-527 审批端点 | 加 self-approve 分支 + 场景判定 |
| 客户端 | 冷却时长 / 上线模式 | 用户自设(staging/production) |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. 真钱仍硬双人:CRYPTO_LIVE self-approve → 必拒;种"真钱走 self-approve" → 必抓(致命,§5)。
2. 诚实标注:self-approve 通过的卡审计必含 `self_approved=true`;种"self-approve 伪装双控" → 抓。
3. 冷却生效:未过冷却期 / 缺二次确认 self-approve → 拒。

## 复用 [按需]
`approval/gate.py` 三要件框架;`channels.py` 超时机制。

## 红线 [按需]
§5——真钱审批双控绝不松动;self-approve 是诚实降级非绕门;决策已落 D-SELFAPPROVE(留痕)。

## 非目标 [按需]
不触碰 OrderGuard 真钱硬墙;不为真钱开任何单人捷径;因子血统门归 T-034。

## Open Questions（已决 3/3）[按需]
- [已决] 引入 self-approve(D-SELFAPPROVE):非真钱单人降级放、真钱硬锁。
- [已决] 边界:仅 paper/testnet/A股模拟可 self-approve,CRYPTO_LIVE 硬双人。
- [已决] 冷却 = 二次确认 + 冷却期;时长与 staging/production 上线模式放客户端用户自设。

## 验收一句话 [必填]
种"真钱走 self-approve / self-approve 伪装双控 / 未过冷却即批" → 门必抓;非真钱单人可冷却+留痕自批;不破基线。
