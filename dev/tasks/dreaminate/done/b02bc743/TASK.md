---
uuid: b02bc743a65e49fe93ee29c48c14b498
title: ide 沙箱 posix_spawn/ctypes 逃逸止血（defense-in-depth·封审计实测向量·非终态）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 1
priority: P0
area: security
source: audit-finding
source_ref: 第三轮安全审计（workflow w5jwdr2ec）#1 的短期止血部分；P0 卡 5bfb5202 的 defense-in-depth 子项
depends_on: []
---

# ide 沙箱 posix_spawn/ctypes 逃逸止血（defense-in-depth）

## Scope [必填]
P0 卡 5bfb5202 的 RCE 真修=OS 级隔离（infra·deployment-mode 待用户拍）。本卡先做**短期止血**：封审计**实测**的两条
逃逸向量（os.posix_spawn 族 + 用户直接 import ctypes），降低当前暴露面。**明确非终态**：黑名单本质不可救，
真隔离仍待 OS 级（P0 5bfb5202）。

## 安全先行（为何止血有效 + 为何仍非终态 + 为何不整体封 ctypes）[必填]
- **posix_spawn 族**：合法策略不用 os.posix_spawn/posix_fork/forkpty/spawn*——黑名单封禁安全无副作用，封住审计实测向量。
- **ctypes 不可整体封**：numpy/scipy 内部用 ctypes（传递性 import），整体 sys.modules 封会破合法库 → 改用 **AST 预检**
  只拒**用户代码直接** import/`__import__` ctypes/cffi（用户 AST·不进库的内部 import·不误伤）。封审计实测的 `ctypes.CDLL(libc).system` 直接向量。
- **仍非 hardened（不假绿灯）**：getattr/importlib 混淆、mmap+shellcode 等未列举路径仍可绕 → docstring 明标 best-effort·真隔离=OS 级。
  这是 defense-in-depth（封已知向量），**绝不 claim 修好沙箱**。

## 治理（护栏·安全·不假绿灯）[必填]
- 安全红线 correctness（封实测 RCE 向量），与既有 best-effort 黑名单设计一致（补覆盖）。
- **deployment-mode（单机 best-effort 可接受 / hosted 必须 OS 隔离）= 用户拍板**——本止血不替决定部署形态，OS 隔离留 P0 5bfb5202。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 改什么(扩展不替换) |
|---|---|---|
| ide/sandbox.py SANDBOX_PRELUDE | spawnv 后加 posix_spawn/posix_fork/forkpty/spawn* 族封禁循环 | additive |
| ide/sandbox.py | +`_scan_forbidden_imports`（AST 预检 ctypes/cffi/_ctypes·含 __import__ 串）+ run_user_strategy 入口调用 | additive |
| ide/sandbox.py docstring | 诚实标注：已封实测向量但仍非 hardened·真隔离 OS 级（P0 5bfb5202） | doc |
| tests/test_ide.py | +5 测试 | additive |

## 对抗测试设计（种已知坏门必抓）+ 变异 [必填]
1. **posix_spawn 封**：os.posix_spawn('/bin/echo',...) → PermissionError(CAUGHT) → MUT（去 prelude 封禁）→ 真 spawn echo·stdout='x' 无 CAUGHT·红 ✓（实证 RCE 向量真可触发）
2. **posix_fork 封**（平台有则）。
3. **ctypes import 拒**：import ctypes → AST 预检 error 含 ctypes → MUT（去 _scan_forbidden_imports 调用）→ error=None·红 ✓
4. **__import__('ctypes') 串拒**（封绕过）。
5. **不误伤**：import json/math 正常跑（AST 只拒 FFI）。

## 验收一句话 [必填]
封审计实测的 posix_spawn 族（prelude）+ 用户直接 import ctypes（AST 预检）逃逸向量·不误伤合法库·明标非 hardened（真隔离 OS 级待用户拍 P0 5bfb5202）；
MUT-posix/MUT-ctypes 双变异抓（含实证 posix_spawn 真执行）；全量后端 1665 passed / 0 failed。

## 完成记录（2026-06-25 · autonomous-loop / D-SANDBOX-STOPGAP）
- **背景**：第三轮安全审计 #1 实测 os.posix_spawn + ctypes.CDLL 沙箱逃逸 RCE。真修=OS 隔离（P0 5bfb5202·deployment-mode 用户拍）；本卡先止血封实测向量（留着已验证 RCE 向量不止血不负责任）。
- **实现（additive）**：prelude 加 posix_spawn/posix_fork/forkpty/spawn* 族封禁（合法策略不用·安全）；run_user_strategy 入口 AST 预检 `_scan_forbidden_imports`（拒用户直接 import/`__import__` ctypes/cffi·不整体封以免破 numpy）；docstring 诚实标注非终态。
- **对抗 + 变异**：+5 测试。MUT-posix（去 prelude 封禁）→ posix_spawn 真执行 echo（stdout='x' 无 CAUGHT）红=**实证 RCE 向量真实**；MUT-ctypes（去 AST 预检）→ ctypes 不被拒（error=None）红；定点反向 edit 后还原（**绝不 git checkout 带未提交改动**）。
- **验证**：test_ide 27 passed（+5）；**全量后端 1665 passed / 13 skipped / 0 failed / 215s**（基线 1660，净 +5）。首跑机器重载触已知 flaky test_effect_ledger_concurrent_same_key 120s 兜底（隔离 1.16s 绿·改动只碰 sandbox 证非回归·复跑转闲全绿·并发硬化残余非本切片）。
- **P0 5bfb5202 残**：OS 级真隔离（容器/nsjail/seccomp/sandbox-exec·只读挂载·网络命名空间·与凭据进程隔离）+ open/glob 文件读隔离（#3）——待用户 deployment-mode 拍板。
- **本轮 loop「commit 和 push 自动进行」→ 本地 commit + push 分支**（land main 仍仅用户）。
