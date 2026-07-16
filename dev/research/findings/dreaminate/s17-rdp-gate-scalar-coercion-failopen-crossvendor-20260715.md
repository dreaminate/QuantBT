# FINDING · §17 RDP 门 scalar/coercion fail-open 系统性收口（跨厂商多轮）

- **蒸馏自**：loop ③ 期间 §17 advisory-first 切片被跨厂商 codex 判 NOT SOUND，复审逮出**底层 canonical §17 RDP 门存在既有 fail-open**——比 advisory feature 本身更高杠杆的 correctness 缺口。pivot 去收这个门。
- **证据强度**：中-强。每一面都**动态复现**（validate_rdp ok=True on 畸形输入）+ 对抗测试 + 变异门（neuter→red→restore→green）。跨厂商 codex 多轮独立探针逐层揭深。非形式化证明，是「当前 HEAD 快照 + 独立双读 + 动态探针」级信心。
- **适用域**：§17 RDP 门（`delivery.validate_rdp` / `section17_rdp_check`）对**畸形标量/容器/空白/非 str 输入**的 fail-closed。**不覆盖** forged in-memory 实例（`object.__new__` 绕 `__post_init__`）——属另一威胁模型（需进程内恶意码），构造期校验够不着（登记为诚实残余）。

## 动机（为什么做 · 锚定来源）[必填]
安全/诚实不变量之一 = 不假绿灯（RULES §3）。§17 门是「研究交付是否完整可信」的诚实闸。若门能被畸形输入洗成 `ok=True`，则「门过了」这个权威信号本身失真——正是 GOAL 命门「监管对齐/一致性校验不可绕过」在门这一层的体现。不做的代价：一份畸形/半残 RDP 冒充完整交付通过门，且既有测试与 marker 都不覆盖这些边界。

## 核心主张（可证伪）[必填]
canonical §17 门原本在**多个输入面**把畸形值 char-split / str-coerce / len()-only 成「非空」→ 门2(dataset/ingestion)、门3(residual) whitewash 成 `validate_rdp.ok=True`。收口 = 每个输入面构造/装配即 fail-closed（raise），诚实路径保真。**逐面动态复现过 whitewash，逐面修后动态复现 fail-closed。**

## 接线点（本项目 file:line · 7 面）[必填]
| # | 面 | 洞 | 修 |
|---|---|---|---|
| 1 | `research_os/rdp.py` `_ref_sequence`（`__post_init__` string-ref 循环） | `tuple("skill")` char-split 逐字符假多重 | 拒 bare str/bytes/bytearray |
| 2 | 同上 | dict/generator/memoryview/set `tuple()` mis-expand | 只接受 list/tuple 容器 |
| 3 | 同上 | 非 str 元素绕门 isinstance-str | 每元素必 str |
| 4 | 同上（round-2b 补） | **空白元素** `("",)`/`("   ",)` 过门3 `len()` | 每元素必 `.strip()` 非空；零内容用空 tuple |
| 5 | `delivery/aggregator.py` | 构造前 `tuple(unverified_residual)` char-split 标量 | residual/known_limitations 原样透传→`__post_init__` 守 |
| 6 | `research_os/rdp.py` `DatasetVersionRef` | `from_dict` str-coerce 嵌套 dict + **普通构造器无 __post_init__**（dict 字段→门2 `.strip()` 崩 AttributeError） | `from_dict` 拒非 str + **加 `__post_init__`** 普通构造器同守 |
| 7 | `main.py` `_rdp_manifest_from_payload` | HTTP 序列字段 `_rdp_tuple` `str(v)` 洗白 + **9 标量文本字段** `str(raw.get(x) or "")` str-coerce dict/list | `_rdp_tuple` 拒标量/映射/非 str 元素 + 新 `_rdp_str` 守 9 文本字段；端点 except 扩 `(ValueError,TypeError)`→422 |

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
`tests/test_rdp_scalar_ref_failclosed.py`（96 passed）：全 39 string-ref 字段 bare-str + dict/generator/memoryview/set + 非 str 元素 + 空白元素 + aggregator 标量 + `DatasetVersionRef` 普通构造器非 str + `_rdp_str` dict/list + **真实 POST 422**（TestClient 打 `/api/research-os/rdp/manifests` 8 种畸形 payload）+ **精确门2/门3 隔离断言**（非只整体 False）+ 诚实路径不误伤。**变异三轮**（`_ref_sequence` 容器/元素 guard·`_rdp_tuple`+`from_dict`·面A/B/C guard）neuter→red→restore→green 手验。

## 未验证残余（诚实）[必填]
- **forged in-memory 实例**：`object.__new__(RDPManifest)` 直设 char-split 字段绕 `__post_init__` → 门仍可能过。属「进程内已有恶意码」威胁模型，构造期校验够不着；门级启发式（「疑似逐字符」）脆弱易误伤。**登记为诚实边界残余**（4+3 可达输入面已全闭）。跨厂商 codex round-2b 同意这是合理边界（见下方 arc）。
- **门2 defensive-reject**：面6 修后门2 不再收到 dict（构造期已拒），但门2 本身对「若真收到非 str」仍 `.strip()`——由构造期 guard 前置防护，非门自身 shape defense。
- **cross-vendor 轮次**：codex round-3 verdict 待回（本 finding land 时据实填）。

## → 拆成的任务 [必填]
| uuid8 | 验收一句话 | 优先级 | 依赖 |
|---|---|---|---|
| —（无新卡） | 7 面收口随本 finding 直接 land（product + 96 测 + 跨厂商 codex SOUND）；forged-instance 残余登记不阻塞 | — | — |

**跨厂商价值实录（多轮收敛·本 session 第 N 次现证）**：
- **R1**（advisory-first 切片复审）：codex 逮出底层门 fail-open（claim6），我独立复现 `validate_rdp ok=True`。
- **R2a**（我 __post_init__ 单点 guard）：codex 判 NOT SOUND——只闭 1 面，systemic 5 面（非 str 容器·aggregator·main HTTP·from_dict·门 shape）。
- **R2b**（我 systemic 4 面 + 70 测）：codex 判 NOT SOUND——再逮 3 类**内容级**兄弟洞（空白元素·DatasetVersionRef 普通构造器·HTTP 标量文本字段）。
- **R3**（我 7 面 + 96 测 + 真实 POST 422）：codex verdict 待回。

**规律**：coercion 修必须闭**整个等价类**（`tuple(x)`·`str({})`·`("",)`·普通构造器 都是「让畸形看起来合法」），不是闭一个代表。同厂商 pre-review 每次都漏更深一层；跨厂商 skeptic 逐轮逼出。builder=Claude(主上下文实现，deep-opus 中途 hang 后我接手)·verifier=codex(GPT，R1/R2a/R2b/R3 独立复验)·approver≠creator。

---

## 附录·ROUNDS 3-6 全弧 + 「pervasive class」结论（2026-07-15 · 需用户拍板 scope）

初版记 R1-R2b（type/content 级）。此后跨厂商 codex 又逐轮逼出**更深同类洗门**，每轮我收、codex 再逮，收敛缓慢——**证明这是一整类 coercion fail-open，不是有界切片**：

- **R3**：`validate_rdp_manifest` 的 `required_text` `str(value)` 洗白 live-部署安全字段（approval/rollback/retire）。修：isinstance-str。
- **R4**：`target_runtime` 只类型检查不枚举闭集（"LIVE"/"live " 跳 live 门）+ 真实 POST 测试假绿（只断 status 不断归因）。修：allowlist + attribution 断言。
- **R5**：`target_runtime` allowlist 派生自**全** RuntimeStatus 枚举（含 suspended/retired 末态→跳门进 runner）+ `PromotionClaim.asset_kind` 无下游校验（gate4 不查 kind）。修：独立四值常量 + gate4 查 asset_kind。
- **R6**：**别名投影层** `RDPManifest.merge()`（rdp.py:339）在 tuple 守卫**之后**对 legacy scalar alias 做 `str()`——dict `deployment_plan`/`monitor_plan` → 伪造非空 ref → validate 零 violation + runner 被调用 1 次收伪造 refs（真 live 门洗白）+ `_build_promotion` 对无 allowlist 的 `asset_ref` str-laundering。修：merge 别名源必 str + `_build_promotion` exact-str + section17 捕获 fail-closed。

**已闭的输入面（~12 个·全 mutation 验·跨厂商逐轮实证）**：`_ref_sequence`(bare/容器/元素/空白)·`aggregate_rdp`·`DatasetVersionRef.from_dict`·`_rdp_tuple`(HTTP 序列)·`_rdp_str`/`_rdp_opt_str`(HTTP 标量文本/optional)·`required_text`(validator)·`residual_attestation`·`target_runtime`(枚举闭集)·gate4 `asset_kind`·`merge()` 别名(deployment/monitor/graph)·`_build_promotion`(promotion exact-str)。

**测试**：`test_rdp_scalar_ref_failclosed.py` 144 passed（7 变异循环·全 red-then-restore）。受影响 69 文件 **1864 passed**。codex R6 实证 R5 两修已闭、逮出 R6 两 blocker（已修）。

### ★ pervasive-class 结论（诚实）
这个「coerce-then-weakly-check」惯用法**遍布**每个边界：构造守卫→聚合→反序列化→HTTP 适配器→validator→枚举 allowlist→晋级适配器→**别名投影/merge 派生层**。每加一道守卫就暴露上/下游另一个 coercion 点。**已闭全部当前已知 safety-adjacent 洗门（live/资金/晋级/§17诚实门）**；但**别名投影层同族剩项**（`cost_execution_assumptions`/`attribution` 等**研究完整性**字段·非 live/资金 red-line·但仍是 §17 门的 不假绿灯 correctness 面）未系统收，且**无法保证已穷尽**——每轮 codex 仍找到新面。

### 待用户拍板（scope/effort · 方法学门槛类）
**问题**：是否继续投入把这一整类 coercion fail-open **穷尽收口**？三选：
- **(a) 系统性穷尽审计**（我做）：grep 每个喂 §17/live 门的 `str()`/coercion 点（别名投影全族 + from_dict legacy + receipt validators + …），在单一 canonical 入口统一校验 + 全覆盖对抗测试矩阵。**代价**：还需多轮 + 大改；**收益**：整类闭合。
- **(b) land 当前实质修 + 登记残余**：所有 **safety-adjacent（live/资金/晋级/§17门）已闭**、跨厂商 6 轮验；剩 non-safety 研究完整性同族边界作 documented residual。**代价**：非 safety 的 correctness 洗门仍在；**收益**：12 个真实 safety 洗门立即收口。
- **(c) 全 park**：整块留分支等专门审计窗口。

**我的推荐**：**(b)**——safety red-line 全闭是硬约束、已达成；研究完整性同族边界是 correctness-非-safety，可作 documented residual 分独立卡跟进，不必阻塞 12 个 safety 修 land。但**方法学松紧是你的事**，摆代价请你拍。
