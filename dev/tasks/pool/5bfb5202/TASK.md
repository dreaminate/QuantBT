---
uuid: 5bfb520225c747b0b0c3c214f52e8ecf
title: ⚠P0 ide 策略沙箱 OS 级隔离——堵 posix_spawn/ctypes RCE 逃逸 + open/glob 读宿主机文件（安全审计 pass3 #1/#3）
status: todo
owner: wait
assigned_by:
review_status: 0
priority: P0
area: security
source: audit-finding
source_ref: 第三轮安全审计（workflow w5jwdr2ec）#1（RCE 沙箱逃逸·CRITICAL·lev 9）+ #3（沙箱读宿主机文件·lev 8）
depends_on: []
---

# ⚠P0 ide 策略沙箱 OS 级隔离（RCE 逃逸 + 文件读泄露）

> **⚠ 安全审计 pass3 命中 CRITICAL·已 prominently 报告用户**：`ide/sandbox.py` 用 Python 层 monkey-patch **黑名单**拦
> os.system/popen/subprocess，但 **`os.posix_spawn`/`os.posix_fork`/`ctypes` 未拦**——审计实测 (B) `os.posix_spawn('/bin/sh',...)`
> 与 (D) `ctypes.CDLL(libc).system(...)` 均在沙箱内成功执行 shell（exit 0）=**RCE 沙箱逃逸**；且 `open`/`glob` 未拦→可读宿主机
> keystore_index.json（实盘 key 索引）/auth DB（他人密码哈希）/任意源码（#3）。任何注册用户 POST /api/ide/strategies/{name}/run
> （require_user_dependency 即可达）→ 后端宿主机任意命令执行 + 凭据提取。
>
> **deployment-mode 决定严重度（=用户拍板·provide pipeline not impose）**：
> - **单机桌面/自托管**（Tauri·operator 跑自己代码）：低实影响——**已披露** best-effort（sandbox.py:12 docstring + 前端 banner「仅原型验证·受限沙箱」），可接受。
> - **多租户 hosted**（开放 register 今已 ship·North Star=陌生人能信）：**CRITICAL**——陌生人读走实盘 key 索引/他人哈希并经可绕过的网络层外泄=违 RULES.project『凭据不泄露/实盘 key 不进 LLM』+ §5 数据泄露致命门。

## 数学/安全不变量先行 [必填]
- **隔离不变量**：用户策略代码绝不能在后端宿主机进程命名空间内执行任意 syscall/spawn 进程、绝不能读授权数据子集外的文件。
  进程/文件/网络隔离**必须是 OS 级**（namespace/seccomp/容器/sandbox-exec），**不能依赖 Python 层黑名单**——黑名单图灵完备不可救
  （posix_spawn/ctypes/cffi/mmap+shellcode/openpty 等未列举路径恒可绕）。

## 接线点（file:line，实现复核）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| ide/sandbox.py:170 _run_in (Popen 构造) | OS 级真沙箱包装 | Linux bwrap/nsjail（--read-only 根·--network=none·非 root·drop caps·seccomp）/ macOS sandbox-exec seatbelt profile |
| ide/sandbox.py:170 数据挂载 | 主进程预取本 run 数据放只读 bind-mount | 用户代码无裸 open 能力·只读授权子集 |
| ide/service.py:342 run_user_strategy | 入口前 AST 白名单预检 | 禁 import ctypes/cffi/mmap·禁 Attribute 访问 posix_spawn/posix_fork/_exit/dup2/openpty·禁裸 __import__/eval/exec |
| prod backend.Dockerfile | USER 非 root + 执行主体与持 Fernet master 口令的后端进程隔离 | 独立无凭据执行主体 |

## 短期止血（非终态·明标 best-effort·下迭代可先做）[按需]
sandbox.py prelude 补 `_os.posix_spawn/posix_spawnp/posix_fork=拒绝` + _FORBIDDEN 加 ctypes/cffi/_ctypes/mmap + 入口 AST 预检拒危险 import/attr。
**封住已验证的 posix_spawn/ctypes 向量（defense-in-depth·提高门槛）**，但 docstring 须明标**仍是黑名单非 hardened·不得当终态**（防假绿灯）。

## 对抗测试设计（种已知坏门必抓）[必填]
1. test_sandbox_blocks_posix_spawn：用户代码 os.posix_spawn('/bin/sh',...) → 必被拒/隔离（不得 exit 0 执行）。
2. test_sandbox_blocks_ctypes：ctypes.CDLL(libc).system(...) → 必被拒。
3. test_sandbox_blocks_arbitrary_file_read：open('/etc/hosts')/glob 仓库凭据路径 → 必失败/空。
4. 端点层：任意登录用户经 /api/ide/.../run 不可逃逸（OS 隔离后）。

## 验收一句话 [必填]
用户策略代码在 OS 级真沙箱执行（进程/文件/网络隔离·与凭据进程隔离），posix_spawn/ctypes/open/glob 逃逸均被堵；deployment-mode 由用户拍；种已知逃逸门必抓。

## 上下文 / 动机 [必填]
**已 prominently 报告用户**（2026-06-25·autonomous-loop·第三轮安全审计）。建议在缓解前限该端点仅 admin 或 hosted 模式下线 IDE run，直到 OS 沙箱接入。
此卡是 RULES.project『削弱安全不变量/凭据泄露即停工』范畴，但 deployment-mode（单机 vs hosted）的松紧拍板属用户——故 mint P0 卡 + 报告，不替用户决定部署形态。
