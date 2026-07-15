# worktree / 分支盘点（只列清单 · 删除等用户拍板）

> 生成 2026-07-15。loop 契约明列的「90+ 历史 worktree/分支盘点」。**本文只盘点 + 给建议 + 附用户可自跑命令,不删任何东西**（删除是不可逆动作 = 用户拍板）。数据以生成时 `git worktree list` / `git branch` 实测为准,后续会漂,清理前请重跑核对。

## 总量（实测）
- **worktree**：90 个（含主 checkout `main`）。其中 ~76 个 `agent-<hex>` 临时 agent worktree + ~13 个命名 integration/slice worktree + 主 checkout + 本 loop worktree（`loop-r1-wrapup`，当前 locked，勿删）。
- **本地分支**：113 个。**107 已合并进 main**（安全可删）/ **5 未合并**（需审,可能含未落地工作）/ 1 当前。

## ✅ 5 个未合并分支已逐个核完（2026-07-15，Explore 子代理 + 主 agent 复核）
结论:**1 个有真·未落地工作(已救回)，4 个可安全删**。
| 分支 | 核查结论 | 依据 |
|---|---|---|
| `worktree-autopolish-w1` | **有真·未落地 P0 → 已救回 land main(ee3a2601)** | sandbox posix_spawn/ctypes 逃逸止血从没 land;已按 main 现结构重实现 |
| `wip/uncommitted-closure-20260628` | **可删（是被主动否决的 fake-green，无真工作）** | 它 preserve 的 closure-via-materializer 是作者自标 "fake-green A";main 不仅没收、还在 goal_coverage.py:359/579、main.py 主动加守卫拒绝 goal_closure ref |
| `worktree-agent-a400943bb6777831b`(S13 TRUST) | **可删（producer 已换位重实现）** | build_section13_trust_record 不在 main,但工作已进 promote_assembler.py:854 _assemble_section13(typed dataclass fail-closed)+test_runjson_producers.py:594 覆盖 |
| `worktree-agent-a763a6989385c4c03`(S16 ENGSTD) | **可删（producer 已换位重实现）** | 同上 → promote_assembler.py:898 _assemble_section16 + test_runjson_producers.py:604 |
| `worktree-integration-prodbuilder` | **可删（= a400943+a763 merge，无额外独有码）** | S13+S16 并集,两块均已落地 |

**可选保守动作**:S13/S16 分支各带一份更细的对抗测试(test_s13/s16_producer.py 469/501 行,针对老分支的 bool-序列化-往返威胁模型)。main 用 typed dataclass 设计结构上避开了该威胁(不走 dict 往返)，所以那两份测试对 main 设计largely moot;producer 契约已由 test_runjson_producers.py 测到。若想保留更细 mutation-三态用例,删前可单独摘出(需适配 main 的 _assemble_section1x 设计)。

---

## （历史）5 个未合并分支初盘（已被上表核查结论取代）
| 分支 | 末次提交 | 摘要 | 建议 |
|---|---|---|---|
| `wip/uncommitted-closure-20260628` | 2026-06-28 `cdbded91` | wip: preserve uncommitted closure-via-materializer work for recovery | **审**：显式的「未提交工作抢救」分支,删前确认内容是否已由后续 closure 切片覆盖 |
| `worktree-agent-a400943bb6777831b` | 2026-06-29 `01e3b7a3` | harden(research-os) NC-S13-TRUST-PRODUCER 经 codex 堵 2 洞 | **审**：research-os 加固,确认是否已并入 main 的对应 producer |
| `worktree-agent-a763a6989385c4c03` | 2026-06-29 `9c3ce662` | release-gate NC-S16-ENGSTD-PRODUCER 变异三态计数订正 | **审**：同上,release-gate producer |
| `worktree-autopolish-w1` | 2026-06-25 `92eade4f` | fix(security) ide 沙箱 posix_spawn/ctypes 逃逸止血 | **审·安全相关**：沙箱逃逸止血,确认该 defense-in-depth 是否已在 main 生效,未生效则应先落地再删 |
| `worktree-integration-prodbuilder` | 2026-06-29 `da4e69e0` | Merge branch worktree-agent-a763... into worktree-integration | **审**：集成分支,含上面 a763 的合并 |

## 107 已合并分支（安全可删 —— 内容已在 main）
全部 `git branch --merged main` 命中、内容已进 main。绝大多数是 `worktree-agent-<hex>`（临时 agent 分支）+ 历史 wave/integration 分支。列表长,不逐一列（可 `git branch --merged main` 自查）。

## 命名 worktree（非临时 agent · 可能有历史价值,单独看）
`autopolish-w1 / center-integ / codemap-full-landing / codemap-v2 / delivery-slice / integration-prodbuilder / integration-wave{1,2,3}/-batch3 / math-spine / qb-deliver` —— 这些是有意命名的集成/交付 worktree,删前确认对应分支已合并且无未落地产物。

## 建议清理路径（用户自跑 · 我不执行）
```bash
# 1) 先看清单(重跑核对,数据会漂)
git worktree list
git branch --merged main | grep -v '^\*\| main$'   # 107 个已合并,安全候选
git branch --no-merged main                          # 5 个未合并,先审上表

# 2) 审完 5 个未合并分支后,若确认无需保留:
#    (逐个核实内容已在 main 或确定弃用,再删)
# git branch -D <未合并分支名>

# 3) 已合并分支批量删(可逆性:分支指针删了,commit 仍在 main 历史):
# git branch --merged main | grep -v '^\*\| main$' | xargs -n1 git branch -d

# 4) 清理临时 agent worktree(worktree remove 会删工作目录,不可逆):
# git worktree list | grep 'worktrees/agent-' | awk '{print $1}' | xargs -n1 git worktree remove --force
# git worktree prune   # 清理已失效登记

# ⚠️ 勿删:主 checkout、loop-r1-wrapup(本 loop,locked)、codemap-full-landing(dreaminate/*)
```

## 边界
- **不可逆**：`git worktree remove` 删工作目录、`git branch -D` 删未合并分支指针 → 均需用户拍板,本文只列。
- 已合并分支删指针可逆（commit 在 main 历史,分支名可重建）；未合并分支删 `-D` 后需 reflog 抢救,风险高。
- git stash 栈全 worktree 共享（见根 CLAUDE.md 环境说明）：清理 agent worktree 前确认无你在用的 stash 条目。
