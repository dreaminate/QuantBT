---
uuid: ccb4f33319c641d49c783a41e6b9d39b
title: artifact enforce 覆盖自由代码子进程路——submit_code/train_now_code 子进程也过信任门（§15 残余）
status: in_progress
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: model-governance
source: goal
source_ref: GOAL §15(external pickle blocked by default·全路径)；W1 done 卡 6144bd61 诚实残余①：结构化 spec 路已 enforce·自由代码子进程路(submit_code)子进程默认策略 enforce=False 未覆盖
depends_on: [6144bd614e874b1491dc5271fbff8116]
---

# artifact enforce 覆盖自由代码子进程路（§15 残余）

## Scope [必填·先读 GOAL §15]
W1（6144bd61）已让结构化 spec 路（ML/DL 组合）enforce 默认开（external pickle blocked by default）。残余①：**自由代码训练子进程路**（`submit_code`/`train_now_code`·codegen 渲染用户代码→子进程跑）若子进程内用户代码自调 `predict_with`/`load_model`，**子进程默认 TrustPolicy enforce=False**（未在子进程 configure_default_trust）→ 该路 §15 未兑现。本卡：子进程启动期 configure enforce（继承主进程信任 store + enforce 默认开），使自由代码路加载 artifact 也过信任门。**先实证**子进程 env/启动钩子在哪（codegen runner），定最小注入点。

## 第一步（opus 必做·先实证）
grep 实证 submit_code/train_now_code 子进程启动路径（codegen 渲染→subprocess 跑）、子进程如何拿 trust store（artifact_trust.store_under 落点·跨进程 JSONL 共享）、子进程默认 TrustPolicy 从哪来。结论写 done 卡再定注入点。

## 领地（实证后定·扩展不替换）
training/codegen.py（子进程脚本头注入 configure enforce）或 training/runner/service.py 子进程启动钩子。**复用** artifact_trust（store_under/configure_default_trust·不改门语义）。**绝不碰** main.py、artifact_trust 门语义、training/lib.py 机制、其他在飞线（compiler/monitor）。

## 可证伪验收（种坏门必抓·§15）
1. 自由代码子进程加载未登记/外来 artifact（enforce 下）→ 拒（对抗：子进程跑加载外来 .pkl→必 raise；MUT 子进程不 configure→漏过→红）。
2. 自由代码子进程加载系统自产已登记 artifact → 正常（producer 已接·正路径不误伤）。
3. 子进程信任 store 与主进程同源（跨进程 JSONL 共享·登记可见）。

## 红线 [按需]
外来 pickle/torch.load 不安全加载即停·绝不静默回落 weights_only=False·复用 artifact_trust 不另造·扩展不替换·先读 GOAL §15 再动手。无新公式→不强造 MathematicalArtifact。

## 非目标 [按需]
不改结构化 spec 路（W1 已 enforce）；不改 artifact_trust 门语义；safetensors 输出（另 follow-on）。本卡只补自由代码子进程路 enforce 覆盖。
