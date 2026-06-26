"""§16 Mock 诚实 —— silent mock fallback / template false success 检查原语（发版门禁的新建件）。

GOAL §16「Mock 诚实」+ 致命错误 + §0 可证伪验收对「假成功」立了硬规矩，但全仓【尚无】
可核查的落地门（grep `silent_mock` / `template_response` / `fallback_reason` 全空）。本模块就补这块：
把一个产出结果的执行块的【诚实声明】建成 `ExecutionBlock`，再用纯逻辑门逐条核查 ——

  §16 行 2004-2008（Mock 诚实）+ 行 2025（致命：生产结果走 mock fallback）+ §0 行 54
  （任一生产结果走 silent mock fallback → 拒）落成 5 条规则：

    R1 mock 块必挂标识        mode=mock 而 mock_marked=False           → 拒（silent mock）
    R2 fallback 必显原因      mode=fallback 而 fallback_reason 空        → 拒（silent fallback）
    R3 live 块须用 live source mode=live 而 live_source_ref 空           → 拒
    R4 template 不冒充生产成功 mode=template 而 result_grade=production   → 拒（template false success）
    R5 生产结果不走非 live    result_grade=production 且 mode∈{mock,fallback,template} → 拒（致命）

R1/R2/R4 正对卡「可证伪验收①」的三个子例（未挂标识 / fallback 无原因 / template 标 production
success）；R5 兜「生产结果走 mock fallback」这条致命错误。

种坏门必抓（RULES §2）：`tests/test_release_gate.py` 对每条规则各种一个坏块、断言【必拒】；
补回标识 / 原因 / 改非生产等级即【必绿】。把任一规则改弱（放过 silent mock / 放过 template 假成功）
立刻让对应断言转红 —— 门不是纸做的。

诚实限界（不号称做到的 · 设计极限不会再改）：
- 门核查的是【声明的诚实标识】是否齐全自洽，**不**能识破「谎报 mode」——一个真 mock 块把自己
  声明成 mode=live + 伪造 live_source_ref，门无从察觉（那需运行时插桩，不在本门承诺内）。门给的
  硬保证是：**任何被声明为 mock/fallback/template 的块，都不可能在不被拒的情况下喂出一个生产成功**。
- `mode` / `result_grade` 在构造时即对合法集校验、非法值 raise ——杜绝用 typo（mode="mok"）让块
  绕过分类静默放行（fail-closed at construction）。
"""

from __future__ import annotations

from dataclasses import dataclass

# ── 执行块模式（§16 Mock 诚实词汇表）──────────────────────────────────────────
MODE_LIVE = "live"          # 真实 live source
MODE_MOCK = "mock"          # 合成 / 假数据（须挂标识）
MODE_FALLBACK = "fallback"  # 降级路径（须显原因）
MODE_TEMPLATE = "template"  # 模板 / 占位响应（不得冒充生产成功）
EXECUTION_MODES = frozenset({MODE_LIVE, MODE_MOCK, MODE_FALLBACK, MODE_TEMPLATE})

# 非 live 模式：这些块的产出绝不能落到生产/晋级结果里（§16 致命）。
NON_LIVE_MODES = frozenset({MODE_MOCK, MODE_FALLBACK, MODE_TEMPLATE})

# ── 结果等级（这块的产出被当作什么强度消费）──────────────────────────────────
GRADE_PRODUCTION = "production"   # 进生产 / 晋级路径——危险等级
GRADE_PAPER = "paper"
GRADE_EXPLORATORY = "exploratory"
GRADE_DRAFT = "draft"
GRADE_NONE = "none"               # 未被消费成任何对外结果
RESULT_GRADES = frozenset(
    {GRADE_PRODUCTION, GRADE_PAPER, GRADE_EXPLORATORY, GRADE_DRAFT, GRADE_NONE}
)
# 生产/晋级等级：源自非 live 块即撞 §16 致命「生产结果走 mock fallback」。
PRODUCTION_GRADES = frozenset({GRADE_PRODUCTION})

# ── 违规码（测试据此精确断言抓到哪条·非泛绿）───────────────────────────────────
MOCK_UNMARKED = "mock_unmarked"
FALLBACK_NO_REASON = "fallback_no_reason"
LIVE_NO_SOURCE = "live_no_source"
TEMPLATE_FALSE_SUCCESS = "template_false_success"
PRODUCTION_VIA_NON_LIVE = "production_via_non_live"


class MockHonestyError(ValueError):
    """ExecutionBlock 声明非法（mode / result_grade 不在合法集）——构造期 fail-closed。"""


@dataclass(frozen=True)
class ExecutionBlock:
    """一个产出结果的执行块的【诚实声明】（§16 Mock 诚实核查单元）。

    `mode` 说这块的数据/响应来路（live/mock/fallback/template）；`result_grade` 说它的产出被当作
    什么强度消费（production = 进生产/晋级）。诚实标识三件套：mock 的 `mock_marked`、live 的
    `live_source_ref`、fallback 的 `fallback_reason`。门按 mode 核对对应标识是否齐全（见模块 R1-R5）。

    哪些块要登记：**数据/响应来路对 mock 诚实有意义的块**。纯计算块（不取数据、不调外部）无须列入。
    一旦声明 mode=live，即【断言】这块消费了 live source，故必须 `live_source_ref` 指名（R3）。
    """

    block_id: str
    mode: str
    result_grade: str = GRADE_NONE
    mock_marked: bool = False        # mode=mock 时：是否挂了「这是 mock」标识
    live_source_ref: str = ""        # mode=live 时：真实数据源引用
    fallback_reason: str = ""        # mode=fallback 时：降级原因（空=silent fallback）
    note: str = ""

    def __post_init__(self) -> None:
        # fail-closed：非法 mode / grade 在构造即拒，杜绝 typo 让块绕过分类静默放行。
        if self.mode not in EXECUTION_MODES:
            raise MockHonestyError(
                f"mode 非法：{self.mode!r} ∉ {sorted(EXECUTION_MODES)}（防 typo 绕过 mock 诚实门）"
            )
        if self.result_grade not in RESULT_GRADES:
            raise MockHonestyError(
                f"result_grade 非法：{self.result_grade!r} ∉ {sorted(RESULT_GRADES)}"
            )

    @property
    def is_production(self) -> bool:
        return self.result_grade in PRODUCTION_GRADES


@dataclass(frozen=True)
class BlockViolation:
    """一个执行块的一条 mock 诚实违规（block_id + 违规码 + 诚实说明）。"""

    block_id: str
    code: str
    reason: str


def check_execution_block(block: ExecutionBlock) -> tuple[BlockViolation, ...]:
    """对单个执行块跑 R1-R5，返回它触发的全部违规（空 = 这块诚实）。

    一块可同时触发多条（如 silent mock 又喂生产 → R1+R5）——全列出，不短路（缺陷面要完整）。
    """

    out: list[BlockViolation] = []
    bid = block.block_id or "<anonymous>"

    # R1 mock 块必挂标识（§16：mock block 必挂标识）。
    if block.mode == MODE_MOCK and not block.mock_marked:
        out.append(BlockViolation(
            bid, MOCK_UNMARKED,
            "mock 块未挂标识（mock_marked=False）→ 拒（§16：mock block 必挂标识·silent mock）",
        ))

    # R2 fallback 必显原因（§16：fallback 显示 fallback 原因；§0：silent mock fallback → 拒）。
    if block.mode == MODE_FALLBACK and not block.fallback_reason.strip():
        out.append(BlockViolation(
            bid, FALLBACK_NO_REASON,
            "fallback 块未显原因（fallback_reason 空）→ 拒（§16：fallback 须显原因·silent fallback）",
        ))

    # R3 live 块须用 live source（§16：live block 使用 live source）。
    if block.mode == MODE_LIVE and not block.live_source_ref.strip():
        out.append(BlockViolation(
            bid, LIVE_NO_SOURCE,
            "live 块未声明 live_source_ref → 拒（§16：live block 须使用 live source）",
        ))

    # R4 template 不冒充生产成功（§16：template response 不生成 production success / no template false success）。
    if block.mode == MODE_TEMPLATE and block.is_production:
        out.append(BlockViolation(
            bid, TEMPLATE_FALSE_SUCCESS,
            "template response 标 production success → 拒（§16：template 不生成 production success）",
        ))

    # R5 生产结果不走非 live（§16 致命：生产结果走 mock fallback；§0：生产结果走 silent mock fallback → 拒）。
    if block.is_production and block.mode in NON_LIVE_MODES:
        out.append(BlockViolation(
            bid, PRODUCTION_VIA_NON_LIVE,
            f"生产结果走 {block.mode} 块 → 拒（§16 致命：生产结果走 mock fallback；只 live source 可喂生产）",
        ))

    return tuple(out)


def check_execution_blocks(blocks: tuple[ExecutionBlock, ...]) -> tuple[BlockViolation, ...]:
    """对一组执行块跑 mock 诚实核查，汇总全部违规（保序）。"""

    out: list[BlockViolation] = []
    for b in blocks:
        out.extend(check_execution_block(b))
    return tuple(out)


__all__ = [
    "MODE_LIVE",
    "MODE_MOCK",
    "MODE_FALLBACK",
    "MODE_TEMPLATE",
    "EXECUTION_MODES",
    "NON_LIVE_MODES",
    "GRADE_PRODUCTION",
    "GRADE_PAPER",
    "GRADE_EXPLORATORY",
    "GRADE_DRAFT",
    "GRADE_NONE",
    "RESULT_GRADES",
    "PRODUCTION_GRADES",
    "MOCK_UNMARKED",
    "FALLBACK_NO_REASON",
    "LIVE_NO_SOURCE",
    "TEMPLATE_FALSE_SUCCESS",
    "PRODUCTION_VIA_NON_LIVE",
    "MockHonestyError",
    "ExecutionBlock",
    "BlockViolation",
    "check_execution_block",
    "check_execution_blocks",
]
