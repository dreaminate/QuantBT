---
uuid:            # 全 32 位 hex 无连字符;生成:python -c "import uuid;print(uuid.uuid4().hex)"(或直接 os.py mint 全自动)
title:
status: todo     # todo | in_progress | done
owner: wait      # wait(在 pool) | <developer_id>;须 == 所在文件夹(validate 校验一致;os.py assign 两处同改)
assigned_by:     # 分配者 developer_id(leader/admin);pool 中留空
review_status: 0 # 被分配者 self-review:0 未过目 | 1 已过目/确认
priority: P1     # P0 最高 … P3 最低
area:            # 功能域 slug,须已在 ../_areas.md 注册(语法 ^[a-z0-9_-]+(/[a-z0-9_-]+)?$;validate 校验)
source:          # research | goal | interaction(三晋升源出身)
source_ref:      # 溯源句柄:finding 路径 / GOAL §x / 对话
goal_section:    # 服务 GOAL 哪个子系统节(如 §3);build_trace.py 据此聚合覆盖,可空
done_at:         # 落档日期 YYYY-MM-DD(os.py done 自动填;归档按它分季)
depends_on: []   # 上游卡 uuid 列表(全 32 位)= DAG 的边;os.py mint --depends-on 可用 uuid8 前缀自动解析
---
<!-- 【开发os级别·模板】勿改本文件(来自 Multi-Dev-Os)。
     造卡:推荐 `python dev/scripts/os.py mint "<标题>" --area <slug>`(uuid/目录/本注释清理全自动);
     手工造则:复制到 tasks/pool/{uuid8}/TASK.md、填 frontmatter、**删本注释块**。
     ⚠️ 本注释必须在 frontmatter **之后**——放在 `---` 之前会让整个 frontmatter 解析归零(validate 报「uuid 非法」)。
     id 规则:文件夹名 = uuid 前 8 位 hex;依赖/引用一律锚全 32 位 uuid(前缀可变、uuid 不变)。
     归属由所在文件夹编码:tasks/pool/=未分配(owner: wait);tasks/{developer_id}/=已分配;tasks/{developer_id}/done/=落档。
     分配/落档/land 只 leader/admin 能做(见 TEAM.md)。
     脚手架非枷锁:[必填]不能省;[按需]用得上才留,别为填而填。 -->

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

## Open Questions [按需]
<进实现前必须全部决完。需拍板的逐条标**规范标签** [需拍板](待) / [已决](已拍)——**只认这两个名、别用变体**,
且标签必须在行首列表项(`- [需拍板 ...]`),散文里提到标签字面量不算。**计数不落盘**:board/DEVMAP 展示时
从标签现算;validate 守「标签规范 + in_progress 时 [需拍板]=0」。非拍板的开口(留 hook / 归后续)不标。>

## 验收一句话 [必填]
<种什么坏 → 门必抓;不破坏现有测试基线>
