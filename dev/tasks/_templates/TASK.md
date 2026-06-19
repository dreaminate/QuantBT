<!-- 【开发os级别·模板】勿改本文件(来自 Multi-Dev-Os)。
     造卡(三晋升源:research/goal/interaction → mint)：复制到 tasks/pool/{uuid8}/TASK.md、填 frontmatter.uuid=新 32位hex、删本注释再填。
     id 规则：文件夹名 = uuid4 前 8 位 hex；frontmatter.uuid = 全 32 位 hex(无连字符)；**依赖/引用一律锚全 32 位 uuid**(前缀可变、uuid 不变)。
     归属由所在文件夹编码：tasks/pool/=未分配(owner: wait)；tasks/{developer_id}/=已分配；tasks/{developer_id}/done/=落档。
     分配/落档/land 只 leader/admin 能做(见 TEAM.md)；冻结历史卡保留 legacy T-xxx id(validate 兼容,不重 mint)。
     脚手架非枷锁：[必填]不能省；[按需]用得上才留,别为填而填。 -->
---
uuid:            # 全 32 位 hex 无连字符(稳定身份,永不变；文件夹名取前 8 位)
title:
status: todo     # todo | in_progress | done
owner: wait      # wait(在 pool) | <developer_id>；须 == 所在文件夹(validate 校验一致)
assigned_by:     # 分配者 developer_id(leader/admin)；pool 中留空
review_status: 0 # 被分配者 self-review：0 未过目 | 1 已过目/确认
priority: P1     # P0..P3
area:            # 功能域(给 dev-map 按功能查),如 auth / 数据 / api
source:          # research | goal | interaction(三晋升源出身)
source_ref:      # 溯源句柄：finding 路径 / GOAL §x / 对话
depends_on: []   # 上游卡 uuid 列表(全 32 位)= DAG 的边；锚 uuid 不锚前缀
---

# <title>

## Scope [必填]
<单一能力单元,1 句「做什么 + 不做什么」>

## 上下文 / 动机 [按需]
<为什么现在做,链到 finding / gap>

## 接线点（file:line，实现时复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| <path> | <行/符号> | <接什么线> |

## 对抗测试设计（种已知 bug，门必抓）[必填]
1. <名>:种 <已知的坏> → 门必 <抓的表现>(含变异要杀的点)

## 复用 [按需]
<现有可复用的 file:符号,别重造>

## 红线 [按需]
<相关 RULES.project 红线 / 致命错误>

## 非目标 [按需]
<明确不做什么,防 scope 蔓延>

## Open Questions（已决 {已决}/{总}）[按需]
<进实现前必须全部决完。需拍板的逐条标**规范标签** [需拍板](待) / [已决](已拍)——**只认这两个名、别用变体**(标签漂→计数连锁错)。**计数器 `已决 D/总` 由 `python dev/scripts/build_card_counters.py` 从标签派生写回、人别手敲**(validate 核对标签规范+计数);**已决=总(如 4/4)才可进实现**(满格=完成,直觉化)。非拍板的开口(留 hook / 归后续 / 实现时定)不标、不计入。>

## 验收一句话 [必填]
<种什么坏 → 门必抓;不破坏现有测试基线>
