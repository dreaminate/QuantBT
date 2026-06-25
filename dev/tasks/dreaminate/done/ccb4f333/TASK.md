---
uuid: ccb4f33319c641d49c783a41e6b9d39b
title: artifact enforce 覆盖自由代码子进程路——submit_code/train_now_code 子进程也过信任门（§15 残余①）
status: done
owner: dreaminate
assigned_by: dreaminate
review_status: 0
priority: P2
area: model-governance
source: goal
source_ref: GOAL §15(external pickle blocked by default·全路径)；W1 done 卡 6144bd61 诚实残余①：结构化 spec 路已 enforce·自由代码子进程路(submit_code)子进程默认策略 enforce=False 未覆盖
depends_on: [6144bd614e874b1491dc5271fbff8116]
---

# artifact enforce 覆盖自由代码子进程路（§15 残余①）

## Scope [必填·先读 GOAL §15]
W1（6144bd61）已让结构化 spec 路（ML/DL 组合）enforce 默认开（external pickle blocked by default）。残余①：**自由代码训练子进程路**（`submit_code`/`train_now_code`·codegen 渲染用户代码→子进程跑）若子进程内用户代码自调 `predict_with`/`load_model`，**子进程默认 TrustPolicy enforce=False**（未在子进程 configure_default_trust）→ 该路 §15 未兑现。本卡：子进程启动期 configure enforce（继承主进程信任 store + enforce 默认开），使自由代码路加载 artifact 也过信任门。

## 完成记录（2026-06-26·deep-opus 隔离 worktree·分支 `wave5/w1-subprocess-enforce`·基于 origin/main 前五波已 land）

### 第一步·子进程路实证结论（先实证再定注入点）
1. **`run_code` 唯一调用方 = `service._run_code`**（grep 全仓实证）：两入口 `_resolve_result` line 320（自由代码 `code is not None`）+ line 324（DL spec `spec_to_code`）。无第三方调用方 → service 级透传 env 即覆盖全部 scoped 子进程路。
2. **子进程启动 = `runner.run_code`**：落 `train_script.py` → `subprocess.run([sys.executable, script], cwd=job_dir, env=...)`。env 注入 `PYTHONPATH`（含 backend root·让子进程 `import app.*`）+ `QUANTBT_JOB_DIR`；service 另加 `QUANTBT_PANEL_PATH`。**子进程是独立解释器进程，全功率（GPU/网络/本地数据湖），与主进程隔离**。
3. **子进程默认 TrustPolicy 来源 = `artifact_trust._DEFAULT_POLICY`**（模块级 `TrustPolicy(enforce=False)`）。`resolve_policy(None)` → 取 `_DEFAULT_POLICY`。grep 实证 **`configure_default_trust` 全仓零调用** → 任一子进程的进程级默认策略**恒 enforce=False**（残余① 根因，实证坐实）。
4. **codegen header 注入覆盖不到自由代码路**：codegen `_HEADER` import `predict_with`，但 `submit_code(name, code, panel)` 的 `code` 是 **RAW 用户代码、不经 codegen 渲染**（`_resolve_result` line 319-320 直接 `_run_code(code, ...)`）。故「codegen 脚本头注入」**只覆盖结构化 DL spec 路、漏自由代码路**（正是残余①命门）→ 注入点必须在 **runner/service 级**（包住所有子进程执行，无论 codegen 渲染还是 raw 用户码）。
5. **信任 store 落点·跨进程同源**：`store_under(root)` = `<root>/_artifact_trust/artifact_trust.jsonl`（W1 落点单一源）。`service._root` = training_runs root（`store.py:job_dir` = `<root>/<job_id>`）。子进程经 `QUANTBT_TRUST_ROOT=str(self._root)` → `store_under(QUANTBT_TRUST_ROOT)` 与主进程消费侧 `store_under(self._root)` 解析到**同一** on-disk JSONL（append-only·跨进程共享）。

### 注入点决策（实证后定·扩展不替换）
- **runner 级 trust-bootstrap launcher（env-gated）+ service 透传 env**。
- **为何不选 codegen header**：覆盖不到自由代码 raw 路（实证 #4）——效果**不等价**，不是真选项。
- **为何 `runpy.run_path(run_name="__main__")` 而非 prepend preamble**：用户/生成脚本可能 `from __future__ import ...`（必须置顶），prepend 会破置顶约束；runpy 把真脚本当独立 `__main__` 跑，**一字不改用户码**（`__future__`/`if __name__`/`sys.argv[0]` 均保持原义）。
- **职责切分（架构和谐）**：service 拥有「信任根 + enforce 值」（W1 既有 `self._root`/`self._trust_enforce`），runner 拥有「子进程启动」→ service 决策、runner 机制。
- **env-gated 向后兼容**：未注入 `QUANTBT_TRUST_ROOT` → runner 逐字原行为（直接跑 `train_script.py`），既有 `run_code` 直接调用方（含 runner 单测）一字不受影响。
- **主进程全局零污染**：`configure_default_trust` **只在子进程**（隔离·随进程消亡）；主进程 `_DEFAULT_POLICY` 一字不翻 → W1 决策3（不全局翻·避跨消费点 `backtest_bridge` 误伤 + 跨测试污染）**完整保持**。这正是子进程方案优于「主进程全局翻」之处：子进程隔离使全局 configure 安全。

### 改动文件（扩展不替换·3 文件）
| 文件 | 改什么 |
|---|---|
| `app/training/runner.py` | 加模块级 `_TRUST_BOOTSTRAP` launcher 字符串（启动期 `configure_default_trust(store=store_under(QUANTBT_TRUST_ROOT), enforce=QUANTBT_TRUST_ENFORCE)` 后 `runpy.run_path(QUANTBT_USER_SCRIPT, run_name="__main__")`）；`run_code` 内 **env-gated**：`env.get("QUANTBT_TRUST_ROOT")` 才写 launcher 并 target 它（否则 entry 仍 `train_script.py`）。`script_path` 仍指用户脚本（调试保真）。 |
| `app/training/service.py` | `_run_code` 的 `env_extra` 加 `QUANTBT_TRUST_ROOT=str(self._root)` + `QUANTBT_TRUST_ENFORCE="1"/"0"`（继承 `self._trust_enforce`·W1 单点可逆开关）。 |
| `tests/test_artifact_trust_subprocess_enforce.py`（新） | 6 端到端对抗测试（经真 `TrainingService.train_now_code` → runner 子进程）。 |

**未碰**：`main.py`、`artifact_trust.py`（门语义·零改·`store_under`/`configure_default_trust`/`TrustPolicy` 仅调用）、`training/lib.py`（机制·零改）、`codegen.py`、其他在飞线（compiler/monitor）。`git diff --name-only` 实证仅上 3 文件。

### 验证（scoped·实跑·非假绿灯·`KMP_DUPLICATE_LIB_OK=TRUE QUANTBT_FORCE_DEVICE=cpu`）
- **新对抗 `tests/test_artifact_trust_subprocess_enforce.py`：6 passed in 17.54s**。覆盖：直证子进程默认策略 enforce=True+绑同源 store（+opt-out 继承 enforce=False）；① 外来未登记 .pkl 子进程内被拒（job failed·ArtifactTrustError）；MUT 配对 opt-out 外来照常加载；② 已登记自产 artifact 子进程内放行不误伤；③ 子进程 store 与主进程同源（跨进程登记可见）。
- **既有受影响 9 文件：129 passed**（test_training_runner 28+ / test_artifact_trust_activation 8 / test_artifact_trust_gate 20 / test_training_pit_wiring / test_dl_trainer_fixes 9 / test_training_service / test_training_api / test_training_pit_service_activate / test_backtest_bridge / test_model_cards）。自由代码 + DL spec 子进程路现跑在 launcher 下，**基线未破**。
- **`pytest --collect-only`：2138 → 2144**（= 基线 2138 + 新 6·无 import 错）。
- **MUT 定点反向 edit（绝不 git checkout·改完 re-edit 还原·实测）**：
  - **MUT-1**（runner launcher 强 `enforce=False`·模拟「子进程不 configure」）→ `test_subprocess_default_policy_is_enforced` + `test_subprocess_freecode_external_pkl_refused` **FAIL**（后者 `assert 'succeeded' == 'failed'`：外来 .pkl 被加载 = 残余① 漏洞复现）。坏门被抓 → 还原。
  - **MUT-2**（service 抽掉 `QUANTBT_TRUST_ROOT` 透传·模拟「上游不接线」）→ 上 2 + `test_subprocess_store_same_source_as_main` **3 FAIL**（端到端 wiring 失效）。坏门被抓 → 还原。
  - 还原后 `grep MUT` 源码零残留、6 passed。

### 红线合规（逐条）
- ✅ 外来 pickle/torch.load 不安全加载即停：自由代码子进程内外来/未登记 artifact 端到端被拒（MUT-1/-2 证有齿）。
- ✅ 绝不静默回落 `weights_only=False`：未碰 `lib.py`/`artifact_trust.py` 的 DL 加载（wave-1 always-on no-fallback 原样）。
- ✅ 复用 artifact_trust 不另造：launcher 仅调 `store_under`/`configure_default_trust`/`TrustPolicy`，门语义零改（`git diff` 实证 artifact_trust.py 未在改动列）。
- ✅ 扩展不替换：runner env-gated（未注入逐字原行为）；service 仅加 2 env 键；artifact_trust/lib/codegen/main 零改。
- ✅ 不破基线：129 affected passed + collect 2138→2144（仅 +6·无 import 错）。
- ✅ 主进程零污染：configure 只在子进程（隔离），主进程 `_DEFAULT_POLICY` 一字不翻（W1 决策3 完整保持·测试 autouse `reset_default_trust` 防泄漏）。
- 🟡 数学：无新公式 → 不造 MathematicalArtifact（卡明示·重点 §15 安全 correctness + 对抗）。

### 拍板项命中
**无新拍板项**。enforce 默认 ON 的 profile 松紧 W1（6144bd61）已拍并给单点可逆开关 `trust_enforce`；本卡只把**同一开关**一致延伸到子进程路（`QUANTBT_TRUST_ENFORCE` 继承 `self._trust_enforce`）——`TrainingService(trust_enforce=False)` 即子进程同步回退，无新松紧/correctness/安全决策。注入点取舍（runner vs codegen vs prepend）四面已在领地内解（codegen 覆盖不到自由代码 raw 路→效果不等价→非真分叉；runpy 不破 `__future__`；env-gated 无前后冲突；service/runner 职责切分和谐）→ 唯一真正覆盖残余① 的方案族，无需用户拍板。

### 诚实残余（follow-on·非本卡兑现）
1. **enforce-默认 全量验证 = 中心整合点**：本卡只跑 scoped（碰过的子进程自由代码/DL 路 + 129 affected）。子进程 launcher 对**全部** `_run_code` 调用方生效（free-code + DL spec），中心全量须确认无未登记 producer 路径被子进程 enforce 误伤（与 W1 同一 🟡·单点回退 `trust_enforce=False`）。
2. **safetensors 输出**（W1 残余②）未动：本卡不碰 DL 输出格式。
3. **领地外消费点未 enforce**（W1 残余④）：`backtest_bridge.predict_with(trust=None)` 等主进程领地外消费点仍走主进程默认（enforce=False）；本卡只补自由代码**子进程**路，不全局翻主进程（W1 决策3）。是否令领地外消费点也 enforce = 中心整合决策。
4. **诚实边界（信任门本质）**：本钩子令子进程默认 enforce，但「能写 artifact 且能写信任账的攻击者仍可自登记」的单机局限（artifact_trust.py docstring 已述）原样——本门拦的是**外来/未登记 artifact 直接喂 load**（§15 命门），非绝对安全；需外部公证根除，超出本卡。
