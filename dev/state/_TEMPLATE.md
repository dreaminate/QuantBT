<!-- 【开发os级别·模板】勿改本文件。开新机/新身份:复制到 state/{developer_id}/state.md,删本行再填。
     state = 你名下的现状 gap(对照 ../GOAL.md 终态量)。boot 第 2 步读它。
     **文件类型:重生型** —— 每次 land 后按当前现状**整篇重写**,不追加、不堆块(历史在 git)。
     ⚠️ 「上次刷新」「本会话续接」这类跨会话快照**禁止写进本文件**——那是 state/{id}/frontier.md 的职责
     (模板 _TEMPLATE.frontier.md;validate_dev 抓 state 里的续接块堆叠)。体量守 ~30K 内,超限 validate WARN。
     ✅ 行的「证据」格必填可指认证据(防假绿灯,RULES §3 🟡≠✅)。表头「状态/证据」别改名,validate_dev 靠它认。 -->
# STATE · <developer_id> 现状（对照 GOAL 的 gap · 重生型）

> 现状 gap,对照 `../GOAL.md` 终态量。**🟡 未验证 ≠ ✅ 已验证** —— 只有挂得出可指认证据(file:line / 测试名 passed / 带口径的指标)的才标 ✅,空泛即假绿灯。
> 重生型:land 后整篇重写为当前快照;会话叙事进 `log/`,续接现场进 `frontier.md`,都别堆在这。

## 进行中
<这一轮在干的卡 uuid8 + 一句进展;别写终态(终态在 GOAL),只写"到哪了"。>

## 状态表（确定的才标 ✅,证据必挂）
| 子系统/能力 | 状态 | 证据 |
|---|---|---|
| <对应 GOAL 哪节> | 🟡 | <在干/没验:留卡 uuid 或空> |
| <对应 GOAL 哪节> | ⬜ | <没动> |

<!-- ✅ 行示例(确定了再这么写,证据必须可指认):
| 登录闸 | ✅ | auth/session.py:42 · test_login passed · 覆盖 12/12 |
-->

## 下一步
<最近 1–3 步;细节在 board/{你}/board.md 的卡,这里只点方向。>
