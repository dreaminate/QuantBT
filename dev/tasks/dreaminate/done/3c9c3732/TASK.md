---
uuid: 3c9c373209644a9aafca80e186a9759f
title: 补未披露 unauthed 数据泄露端点——copy_trade signals/executions 鉴权+归属 + data export 鉴权（安全审计 pass3 #2/#4）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P1
area: security
source: audit-finding
source_ref: 第三轮安全审计（workflow w5jwdr2ec）#2（copy_trade 端点无鉴权·lev 8）+ #4（data export 无鉴权）
depends_on: []
---

# 补未披露 unauthed 数据泄露端点

## Scope [必填]
第三轮安全审计发现 4 个端点**无任何鉴权**（无 require_user_dependency·无归属过滤）→ 任何匿名调用者可拉数据：
- `/api/copy_trade/signals`（main.py:2858）：全部 master 完整下单意图（标的/方向/量/限价/杠杆/止盈止损/note 自由文本）。
- `/api/copy_trade/executions`（main.py:2864）：跨租户 follower 执行记录。
- `/api/data/export/size` + `/api/data/export`（main.py:1962/1968）：未登录全量拖 DATA_ROOT 研究数据。
邻居端点（ct_master_followers 等）均鉴权+owner-403+keystore 掩码——这几个是**真漏网**（未披露·非 best-effort 声明覆盖）。
hosted 模式（开放 register·North Star=陌生人能信）下=静默数据泄露。

## 安全不变量先行 [必填]
- 读 copy_trade 信号/执行明细**必经身份校验且按归属过滤**：信号下单意图（含 note 可携 PII/策略 IP）只对 owner master
  与其已订阅 follower 可见；execution 只对本人（follower 本人或其所跟 master）可见——绝不向匿名/无关租户回显。
- 数据导出必须鉴权（凭据已由 allowlist 排除[security/secrets/keystore·test_data_export 守]，但研究数据跨用户不可未登录拖走）。

## 治理（护栏·安全不变量·correctness）[必填]
- 纯安全 correctness（数据泄露红线·我不可违背项），不涉用户方法学。单机桌面（登录态）无副作用；hosted 模式essential。
- **扩展不替换**：端点层加 `Depends(require_user_dependency)` + 归属过滤（复用 get_master_by_user/list_subscriptions/list_followers），不动 service/数据模型。
- follower_id/master_id 由服务端按 user.user_id 解析归属校验、**绝不信任 query 自报**。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| main.py ct_list_signals | +鉴权 + scope 到 caller 自家/订阅 master（越权 master_id→403） | additive |
| main.py ct_list_executions | +鉴权 + scope 到 caller 自家 master 的 follower + 自己订阅的 follower（越权 follower_id→403） | additive |
| main.py data_export_size / data_export | +`Depends(require_user_dependency)` | additive |
| tests/test_security_endpoint_auth.py | 新建 3 测试 | 新增 |

## 对抗测试设计（种已知 bug，门必抓）+ 变异 [必填]
1. **匿名门**：4 端点匿名 GET → 401 → MUT（去 Depends）→ 200 红 ✓
2. **跨租户门**：播种 master B + signal，user A（无关）→ signals=[]、越权指 B master_id→403；user B→看到自己 → MUT（退回 list_signals(master_id)）→ A 看到 B 信号红 ✓
3. **executions 跨租户**：无关 user A（无 master/订阅）→ executions=[]。

## 验收一句话 [必填]
copy_trade signals/executions + data export 端点补鉴权+归属过滤（匿名 401·跨租户隔离·越权 403），堵未披露数据泄露；
MUT 双门抓；全量后端 1660 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-ENDPOINT-AUTH）
- **审计驱动（第三轮安全·#2/#4）**：读 main.py 原文复核——4 端点确无 Depends（邻居均有）。区分：未披露真漏洞（先清）vs sandbox 已披露 best-effort 局限（另卡）。
- **实现（additive）**：4 端点加鉴权；copy_trade 按 get_master_by_user/list_subscriptions/list_followers 归属过滤（signals=自家∪订阅 master·executions=自家 master 的 follower∪自己订阅·越权 query 参数 403）；data export 加鉴权。
- **对抗 + 变异**：3 测试（匿名→401·跨租户播种 A 看不到 B+越权 403·executions 无关空集）。MUT（ct_list_signals 退回无鉴权无归属）→ 匿名门(200)+跨租户门(A 看到 B) 双红；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：security 3 passed；**全量后端 1660 passed / 13 skipped / 0 failed / 197s**（基线 1657，净 +3）；data_export 既有测试测函数非端点不受影响。
- **同审计 P0 残（另卡 5bfb5202）**：ide.sandbox posix_spawn/ctypes RCE 逃逸（#1·CRITICAL）+ open/glob 读宿主机文件（#3）——已披露 best-effort 局限·真修=OS 级隔离（infra·deployment-mode=用户拍）·已 prominently 报告用户。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
