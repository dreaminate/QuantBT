"""Document Intelligence 摄入安全栈（GOAL §6·外来文档 = RCE-adjacent 攻击面·安全优先第一切片）。

外来文档（PDF / 文章 / 论文）= 与外来 pickle 同级攻击面（可 RCE / SSRF / DoS）。本包先把
【摄入安全边界】立死，结构化抽取（EvidenceSpan / DocumentBlock / ExtractedStrategySpec）= follow-on。

  - `safety`  —— 纯·无副作用安全门：mime/magic（伪装扩展名）、URL allowlist（SSRF）、
                no-network（解析器禁联网）、size/page/compression 限额（zip bomb / DoS）。
  - `sandbox` —— 解析沙箱：把离线解析器包进 no-network 边界 + 页数限额；真解析库 = 用户拍（stub）。
  - `intake`  —— 对象（SourceDocument / DocumentVersion / LicenseRecord）+ 内容寻址金库
                （raw vault → quarantine → append-only registry）+ fail-closed 编排。
"""

from __future__ import annotations

from .intake import (
    DocumentRegistry,
    DocumentVault,
    DocumentVersion,
    IntakePolicy,
    IntakeResult,
    LicenseRecord,
    SourceDocument,
    intake_document,
    vault_under,
)
from .safety import (
    DocumentIntakeError,
    IntakeLimits,
    assert_mime_matches_extension,
    assert_url_allowed,
    check_pages,
    check_size,
    inspect_archive_safety,
    no_network,
    sniff_format,
)
from .sandbox import (
    OfflineDocumentParser,
    ParsedDocument,
    SafeDocumentParser,
    StubOfflineParser,
)

__all__ = [
    "DocumentIntakeError",
    "DocumentRegistry",
    "DocumentVault",
    "DocumentVersion",
    "IntakeLimits",
    "IntakePolicy",
    "IntakeResult",
    "LicenseRecord",
    "OfflineDocumentParser",
    "ParsedDocument",
    "SafeDocumentParser",
    "SourceDocument",
    "StubOfflineParser",
    "assert_mime_matches_extension",
    "assert_url_allowed",
    "check_pages",
    "check_size",
    "inspect_archive_safety",
    "intake_document",
    "no_network",
    "sniff_format",
    "vault_under",
]
