"""解析沙箱 —— 外来文档只在 no-network 边界内、由【离线】解析器解析（GOAL §6 parser sandbox）。

设计要点（安全优先）：
  - 沙箱入口签名【只收 `data: bytes` + `declared_format: str`】，结构上无处塞凭据 —— 兑现红线
    「实盘 key 绝不进解析器」（解析器拿不到 keystore / secrets / 带 key 的 env）。
  - 解析全程跑在 `safety.no_network()` 内：解析器任何 socket 外联尝试 → `DocumentIntakeError`
    （no-network parser 红线）。
  - 解析后过页数限额门（页炸弹 DoS）。

解析库选型 = 用户拍（PDF / OOXML 真解析库各有取舍与攻击面）。本卡【不接真解析库】，只立沙箱
边界 + 抽象协议 + 离线 stub。真解析库接线、EvidenceSpan / DocumentBlock / 结构化抽取 = 明确
标注的 follow-on（TASK 非目标）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from .safety import DocumentIntakeError, IntakeLimits, check_pages, no_network


@dataclass(frozen=True)
class ParsedDocument:
    """解析沙箱产物（第一切片：只到页数 + 诚实标注，不含结构化抽取）。

    `n_pages` 喂限额门（页炸弹）。`extraction_note` 诚实声明：DocumentBlock / TableArtifact /
    EvidenceSpan / ExtractedStrategySpec 等结构化抽取是 follow-on，本切片【不】产出。
    """

    n_pages: int
    parser_name: str
    declared_format: str
    extraction_note: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class OfflineDocumentParser(Protocol):
    """离线解析器协议：只吃 bytes + 格式 token，产 ParsedDocument。绝不联网、绝不执行嵌入内容。

    真 PDF / OOXML 解析库（用户拍）实现本协议后由 `SafeDocumentParser` 包进 no-network 沙箱。
    """

    name: str

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument: ...


class StubOfflineParser:
    """默认占位解析器：纯离线、不执行任何嵌入内容，只做【安全·有界】页数启发，供限额门有值可校。

    诚实：这【不是】真解析库。它不抽 text / table / formula / evidence（那是 follow-on）。页数为
    byte 级启发估算（PDF 数 `/Type/Page` 标记；其余按换页符 / 单页）——仅用于驱动页炸弹限额门，
    不声称精确。接真解析库（用户选型）后本 stub 退役。
    """

    name = "stub-offline-v0"

    # 启发扫描上限（再保险一层：即便 size 门放过，也不在本 stub 里无界扫描）。
    _MAX_SCAN_BYTES = 16 * 1024 * 1024

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        head = data[: self._MAX_SCAN_BYTES]
        warnings: list[str] = []
        if len(data) > self._MAX_SCAN_BYTES:
            warnings.append(
                f"stub 仅扫描前 {self._MAX_SCAN_BYTES} 字节估页数（启发上界，非精确）"
            )

        if declared_format == "pdf":
            # PDF 页对象标记：/Type /Page（排除 /Type /Pages 目录节点）。
            n_pages = max(1, head.count(b"/Type/Page") + head.count(b"/Type /Page"))
        else:
            # 文本 / 其它：按换页符（\x0c）估页，至少 1 页。
            n_pages = max(1, head.count(b"\x0c") + 1)

        return ParsedDocument(
            n_pages=n_pages,
            parser_name=self.name,
            declared_format=declared_format,
            extraction_note=(
                "stub 离线解析器：只立摄入安全边界 + 估页数；结构化抽取"
                "（DocumentBlock / EvidenceSpan / ExtractedStrategySpec）= follow-on，本切片未产出。"
            ),
            warnings=tuple(warnings),
        )


class SafeDocumentParser:
    """把任意 `OfflineDocumentParser` 包进 no-network 沙箱 + 页数限额门。

    `parse` 全程在 `no_network()` 内跑 —— 解析器若试图联网（外部实体 / 远程资源 / 外泄）→
    `DocumentIntakeError`（no-network 红线）。解析返回后过 `check_pages` 限额门（页炸弹）。
    """

    def __init__(
        self,
        parser: OfflineDocumentParser | None = None,
        *,
        limits: IntakeLimits | None = None,
    ) -> None:
        self._parser: OfflineDocumentParser = parser or StubOfflineParser()
        self._limits = limits or IntakeLimits()

    @property
    def parser_name(self) -> str:
        return self._parser.name

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        """在 no-network 沙箱内解析外来字节；联网尝试 → 拒；页数超限 → 拒。"""
        with no_network():
            parsed = self._parser.parse(data, declared_format=declared_format)
        if not isinstance(parsed, ParsedDocument):
            raise DocumentIntakeError(
                f"解析器 {self._parser.name!r} 返回非 ParsedDocument（{type(parsed)!r}）→ 拒"
                "（沙箱只接受 schema 受约束产物）。"
            )
        check_pages(parsed.n_pages, self._limits)
        return parsed


__all__ = [
    "OfflineDocumentParser",
    "ParsedDocument",
    "SafeDocumentParser",
    "StubOfflineParser",
]
