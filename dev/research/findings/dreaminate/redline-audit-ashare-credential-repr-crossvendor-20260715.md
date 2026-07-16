# FINDING · 红线审计（A股永不实盘 HOLDS）+ 凭据 repr 泄露三处收口（跨厂商）

- **蒸馏自**：loop 停止条件③期间的非用户门 correctness 活——本地干净切片渐近清零后，选最高杠杆的安全不变量 defense-in-depth 深度审计（≠此前 breadth residual sweep）。
- **证据强度**：中-强。A股 HOLDS = 8 层 choke-point 逐一枚举 + 无 env/config bypass grep + codex 独立复核；repr fix = 对抗测试 + 三处变异门（泄露→翻红）+ 跨厂商 codex skeptic（逮出第 3 处漏网）。非形式化证明，是「当前 HEAD 快照 + 独立双读」级别的信心。
- **适用域**：repr / str / f-string / 容器 repr 泄露向量。**不覆盖** to_dict/asdict/pickle/`__dict__`/debugger 展开属性——那是显式访问边界，非 repr 缺陷（见残余）。

## 动机（为什么做 · 锚定来源）[必填]
安全不变量是两条不松手红线之一（数据泄露 / A股永不实盘）。深度审计问的问题与 breadth sweep 不同：「证明没有代码路径让 A 股单到达 live venue」「证明凭据不经 repr/log 泄露」——通过的测试只证它测到的，不证 bypass 不存在。不做的代价：一条潜伏的 red-line 绕过或凭据泄露向量，后果是灾难级（动钱/数据泄露），且现有测试与 marker sweep 都不覆盖。

## 核心主张（可证伪）[必填]
- **A股**：若某 asset_class 含 equity/cn/a_share/ashare（policy.classify 子串）或 ∈{a_share,equity_cn,stocks_cn,cn_equity}（execution_boundary 精确集），则被 8 层独立 choke-point 中每一层结构性钉在 ≤PAPER tier，无 env/config flag 可解，`a_share_live` 是 IMMUTABLE_EXECUTION_INVARIANTS 不可豁免。**审计判 HOLDS，未找到 concrete bypass。**
- **凭据 repr**：若凭据 dataclass 无 redacting `__repr__`，则 Python 默认 dataclass repr 在 traceback 捕获 locals / debugger / 未来某行日志 / 容器 repr 时渲染全值明文——把「没人 repr 它才安全」的隐式脆弱不变量，收成「构造即安全」的显式门。

## 接线点（本项目 file:line）[必填]
| 文件 | 位置 | 接什么 |
|---|---|---|
| app/backend/app/security/keystore.py | `KeystoreRecord.__repr__`（to_dict 后） | api_key/api_secret → `<redacted>`；`__str__ = __repr__` |
| app/backend/app/execution/binance_client.py | `BinanceCredentials.__repr__`（from_record 后） | 同上 |
| app/backend/app/execution/binance_ws.py | `WSStreamerState.__repr__` | listen_key（WS user-data bearer）→ `<redacted>`；运维诊断字段仍可见；空 key 渲染 `''`（保留「是否已取 key」诊断信号不泄露） |
| app/backend/app/llm/credential_pool.py:123 | `MaterializedCredential.__repr__`（既有约定） | 复用来源：`api_key=<redacted>` + `__str__=__repr__` |

A股 HOLDS 的 8 层 choke-point（证据留档）：policy.classify（单一分类源）→ OrderGuard.place_order → copy_trade.follower_tier 硬编码 "crypto" → StrategyGoal validator → execution_boundary 7 处精确集拦截 → IMMUTABLE_EXECUTION_INVARIANTS["a_share_live"] 不可豁免 → paper/desk.attempt_live_order 抛 AShareLiveForbidden→HTTP403 → 无 FORCE_LIVE/SKIP_GATE/BYPASS env（全仓 grep 空）。

## §5 对抗测试要点（种已知 bug，门必抓）[必填]
1. 种坏门：把某凭据对象 `__repr__` 改回泄露全值 → `test_credential_repr_redaction.py` 对应用例翻红（三处 KeystoreRecord/BinanceCredentials/WSStreamerState 各自变异均已实测 red-then-revert）。
2. 容器 repr 向量（现实日志最常见泄露路径）：`repr([rec])` / `repr({"k": rec})` 必不含明文——单独用例覆盖。
3. 真数据仍可门后访问（打码只在 repr，不动 .api_key / to_dict 加密存储路径）——用例断言，防「打码打过头把功能打坏」。

## 复用 [按需]
`MaterializedCredential.__repr__`（llm/credential_pool.py:123-127）已是本仓 vetted 约定；三处收口按同一形态实现，非重造。

## 未验证残余（诚实）[必填]
- **to_dict/asdict/`__dict__`/dataclasses.fields()/pickle 仍返回明文**：这是显式访问边界，非 repr 泄露。KeystoreRecord.to_dict() 是 keyring payload（keystore.py:216）与 Fernet 序列化-前-加密（:311）**必需**，不能打码。无其他无关 caller（codex grep 确认）。
- **debugger / locals 展开属性仍可直接读明文**：repr 打码不防「工具主动展开对象属性」，不可过度声称。framing = defense-in-depth（潜伏、非当前活跃泄露），不是「杜绝一切凭据可见」。
- **WSStreamerState.last_error 若某处把全 listen_key 塞进错误串会经该字段泄露**：本 fix 只打码 listen_key 字段；codex 确认现有代码只打 8 字符前缀（binance_ws.py:217/350-355），故当前无此路径，但属 error-构造侧的独立责任，非 repr 门覆盖。
- **A股 HOLDS 是快照审计非形式化证明**：asset_class token 完备性依赖 AssetClass enum（equity_cn 唯一 CN canonical token）；一个既躲开 classify 子串又躲开精确集的新奇 CN 标识（如 "china_stock"）理论上可绕两层——由 enum 约束缓解，非绝对。
- **BinanceUserDataStream 当前未接线**（状态表已诚实标 unwired 实验原型）：WSStreamerState fix 是潜伏向量的前置收口，非活跃泄露修复。

## → 拆成的任务（mint uuid 入 tasks/pool/）[必填]
| uuid8 | 验收一句话 | 优先级 | 依赖(uuid) |
|---|---|---|---|
| —（无新卡） | 本 finding 的 repr fix 已随审计**直接 land**（product code + 对抗测试 + 跨厂商 codex SOUND），无未决执行项 | — | — |

**跨厂商价值实录**：builder（Claude/standard-opus 审计）+ 我自审只锚定 api_key/api_secret 字段名，**漏掉 listen_key**；verifier（codex/GPT）枚举全部含 secret-ish 字段的 dataclass + 跑独立 `leaks=True` probe，逮出第 3 处 WSStreamerState。同厂商共享盲区，跨厂商 refute——本 session 又一次现证。

---

## 附录·系统性收口全弧（2026-07-15，跨厂商 3 轮到 SOUND）

初版只修 3 处（KeystoreRecord/BinanceCredentials/WSStreamerState.listen_key）；跨厂商 codex 复审逐层揭出**系统性**：

- **codex 第 1 轮 NOT SOUND**：3 处只是冰山，且 WSStreamerState 仍经 `last_error` 间接泄露。
- **穷尽 inventory**（standard-opus runtime-probe 16 候选）定全量=**10 个直接类 + GenericRESTConfig 传递面**：TokenClient.token·ReleaseCandidate.gateway_secret/known_secrets·NodeExecutionContext.token·CapabilityToken.sig(Pydantic)·LLMProviderRecord/LLMGatewayCallRequest.plaintext_credential·_AuthSpec.static_value(Pydantic)。
- **deep-opus 实现**（builder=Claude）：dataclass→`field(repr=False)`、Pydantic v2→`Field(repr=False)`、binance_ws error 串→`_redact_secret` 助手包 6 处 capture 点。原则钉死：**accidental(repr/str/%s/traceback) 必闭；functional(to_dict/model_dump/asdict 供签名/持久化/传输) 是显式访问边界不动**。
- **codex 第 2 轮 NOT SOUND（P1）**：rotation 探针逮 **stale-generation 泄露**——`_redact` 只打码当前 `self._state.listen_key`,但 `create_listen_key` 轮换后老连接 `_on_error`/`_ws_loop` 携【旧】key,当前 key 不匹配 → 旧 key 经 snapshot+audit export 外流（`state_leak/audit_leak=True`）。+P2：`_ws_loop`/`_reconcile_loop` 两 capture 点无变异测。
- **P1 补丁**（我实现）：`self._known_listen_keys` 有界(末 64)追踪历来签发的每个 key；`self._redact(text)=_redact_secrets(text, 历史∪当前)` 对全部已签发 key 打码。6 点统一走 `self._redact`；新增 3 测（stale-rotation 复现 + 两 site 变异牙口），三者变异均 red-then-revert 实证。
- **codex 第 3 轮 SOUND to land**：独立 rotation 探针 `state/snapshot/audit_leak=False`；11 对象 repr 全 PASS；functional 边界(model_dump/asdict)保真；renew 不轮换 key 确认；tuple rebind 线程安全。

**残余（如实登记·非阻塞）**：
- **64-key 上界**：>65 次轮换后最旧 key 会掉出窗漏打码。codex Inference 现生命周期不可达（renew 不轮换·`_ws_loop` 仅 key 空时 create·永不清空）；**待「真正 generation rotation」实现时重估上界**（模块本就是未接线原型）。
- **asdict 面**：`field(repr=False)` 不影响 `asdict`,`onboarding_gateway._json_value(asdict(...))` 仍序列化 plaintext_credential/payload_preview——但受**validation tripwire**（`contains_plaintext_secret`,onboarding_gateway.py:1565/1731/1740）在落盘前拒；codex 探针证 asdict 含 sentinel 但 record_llm_provider() 拒、拒串不回显、无文件生成。属显式边界残余,**非阻塞**（硬化建议：`_json_value` 移到 validation 之后缩短内存明文窗）。
- **overlapping-length secret**：`_redact_secrets` 已改长者优先排序（精确总契约）；真实 listen_key 等长本无重叠。

**产品改动**：9 文件（7 加 repr=False/Field + binance_ws helper/tracking/6 callsite + 3 既有保留）；测试 `test_credential_repr_redaction.py` 8→23（+12 系统对象 +3 P1）。builder=Claude(deep-opus 实现 + 我 P1 补丁)/verifier=codex(GPT) 跨厂商 approver≠creator。
