"""Document Intelligence 摄入安全栈的【对抗式】测试（GOAL §6·外来文档 = RCE-adjacent 攻击面）。

外来文档 = 与外来 pickle 同级攻击面（恶意 PDF/文档可 RCE/SSRF/DoS）。本测对卡的 5 条可证伪验收
逐条种【已知坏门】（MUT = malicious-under-test）证明拦得住，且正路径不误伤：

  #1 mime/magic 与扩展名不符（伪装文档·.pdf 实为可执行 / 别的容器）→ 拒。
  #2 URL 不在 allowlist / 私网（SSRF）→ 拒；解析器尝试联网（no-network）→ 拒。
  #3 超 size / page / compression limit（zip bomb / DoS）→ 拒。
  #4 文档先 quarantine 再 sandbox 解析（绝不直接信任原件路径）→ 隔离真生效。
  #5 source hash + license/rights record 在场（可追溯·合规）。

注：MUT 全程【绝不真发网络】—— no-network 门在 socket 层 fail-closed 拦下，测试离线确定。
"""

from __future__ import annotations

import hashlib
import io
import socket
import urllib.request
import zipfile
from pathlib import Path

import pytest

from app.documents.intake import (
    DocumentRegistry,
    DocumentVault,
    IntakePolicy,
    LicenseRecord,
    intake_document,
)
from app.documents.safety import (
    DocumentIntakeError,
    IntakeLimits,
    assert_mime_matches_extension,
    assert_url_allowed,
    check_size,
    inspect_archive_safety,
    no_network,
    sniff_format,
)
from app.documents.sandbox import (
    ParsedDocument,
    SafeDocumentParser,
    StubOfflineParser,
)
from app.lineage.ids import content_hash

ALLOWLIST = frozenset({"arxiv.org"})


# ── 字节构造助手 ──────────────────────────────────────────────────────────────
def _pdf_bytes(n_pages: int = 1) -> bytes:
    return b"%PDF-1.4\n" + b"/Type/Page\n" * n_pages + b"trailer\n%%EOF\n"


def _docx_bytes(entries: int = 2, payload: bytes = b"<xml>hello</xml>") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", payload)
        for i in range(entries):
            z.writestr(f"word/part{i}.xml", payload)
    return buf.getvalue()


def _zip_bomb_bytes(uncompressed: int = 2_000_000) -> bytes:
    """高压缩比 zip（解压后远大于压缩前）—— zip bomb 核心特征。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.bin", b"A" * uncompressed)  # 极可压缩
    return buf.getvalue()


def _many_entries_zip(entries: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        for i in range(entries):
            z.writestr(f"e{i}.txt", b"x")
    return buf.getvalue()


# magic 前缀（伪装成文档扩展名的真实可执行 / 容器）
_ELF = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 56
_PE = b"MZ\x90\x00" + b"\x00" * 60
_MACHO = b"\xcf\xfa\xed\xfe" + b"\x00" * 60
_SHEBANG = b"#!/bin/sh\nrm -rf /\n" + b"\x00" * 40


def _vault(tmp_path: Path) -> DocumentVault:
    return DocumentVault(tmp_path / "vault")


def _license() -> LicenseRecord:
    return LicenseRecord(license="CC-BY-4.0", rights_holder="arXiv", source_url="https://arxiv.org/abs/x")


# ── MUT 解析器（种坏门：解析器尝试联网 / 页炸弹 / 录证据） ───────────────────────
class _NetParserCreateConnection:
    name = "mut-create-connection"

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        socket.create_connection(("8.8.8.8", 53), timeout=1)  # 应被 no-network 拦下
        return ParsedDocument(1, self.name, declared_format)


class _NetParserUrllib:
    name = "mut-urllib"

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        urllib.request.urlopen("http://example.com", timeout=1)  # getaddrinfo 被拦
        return ParsedDocument(1, self.name, declared_format)


class _NetParserRawSocket:
    name = "mut-raw-socket"

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        s = socket.socket()
        try:
            s.connect(("8.8.8.8", 53))  # 裸 socket 直连 IP 字面，应被拦
        finally:
            s.close()
        return ParsedDocument(1, self.name, declared_format)


class _PageBombParser:
    name = "mut-pagebomb"

    def __init__(self, n_pages: int) -> None:
        self._n = n_pages

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        return ParsedDocument(self._n, self.name, declared_format)


class _RecordingParser:
    name = "recording"

    def __init__(self) -> None:
        self.seen: bytes | None = None

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        self.seen = bytes(data)
        return ParsedDocument(1, self.name, declared_format)


# ══ 验收 #1 · mime/magic 与扩展名不符（伪装文档）→ 拒 ═════════════════════════
@pytest.mark.parametrize(
    "magic, ext",
    [
        (_ELF, ".pdf"), (_PE, ".pdf"), (_MACHO, ".pdf"), (_SHEBANG, ".pdf"),
        (_ELF, ".docx"), (_PE, ".docx"), (_ELF, ".txt"), (_SHEBANG, ".csv"),
    ],
)
def test_disguised_executable_refused(magic: bytes, ext: str):
    """种坏门:声称是文档（.pdf/.docx/.txt/...）实则可执行 / 脚本 → 必拒（RCE 攻击面）。"""
    with pytest.raises(DocumentIntakeError):
        assert_mime_matches_extension(filename=f"evil{ext}", head=magic)


def test_disguised_container_refused():
    """种坏门:.pdf 实为 ZIP（PK），.docx 实为 PDF —— 伪装成别的容器 → 拒。"""
    with pytest.raises(DocumentIntakeError):
        assert_mime_matches_extension(filename="evil.pdf", head=_docx_bytes()[:64])
    with pytest.raises(DocumentIntakeError):
        assert_mime_matches_extension(filename="evil.docx", head=_pdf_bytes()[:64])


def test_binary_magic_ext_with_short_head_refused():
    """fail-closed:binary-magic 扩展名（.pdf）头部太短无法确认魔数 → 拒（不放过未确认外来）。"""
    with pytest.raises(DocumentIntakeError):
        assert_mime_matches_extension(filename="x.pdf", head=b"\x00\x01")


def test_intake_rejects_disguised_executable_pdf(tmp_path: Path):
    """端到端:把伪装成 .pdf 的 ELF 喂 intake_document → 在 mime 门拒，绝不入账。"""
    vault = _vault(tmp_path)
    with pytest.raises(DocumentIntakeError):
        intake_document(vault=vault, filename="paper.pdf", license=_license(), data=_ELF)
    assert vault.registry.list_versions() == []  # 拒 → 绝不信任入账


def test_legit_pdf_and_docx_pass_mime_gate():
    """正路径:真 %PDF- 名 .pdf、真 PK 名 .docx → 过 mime 门（不误伤）。"""
    assert assert_mime_matches_extension(filename="ok.pdf", head=_pdf_bytes()[:64]) == "pdf"
    assert assert_mime_matches_extension(filename="ok.docx", head=_docx_bytes()[:64]) == "zip_ooxml"


def test_sniff_format_tokens():
    assert sniff_format(_pdf_bytes()) == "pdf"
    assert sniff_format(_docx_bytes()) == "zip_ooxml"
    assert sniff_format(_ELF) == "executable_elf"
    assert sniff_format(_PE) == "executable_pe"
    assert sniff_format(b"plain text no magic") == "unknown"


# ══ 验收 #2 · URL allowlist / SSRF + no-network parser → 拒 ═══════════════════
@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # 云元数据 link-local
        "http://127.0.0.1:8000/x",                    # loopback
        "http://10.1.2.3/x",                          # 私网
        "http://192.168.0.1/x",                       # 私网
        "http://[::1]/x",                             # IPv6 loopback
        "http://0.0.0.0/x",                           # unspecified
        "http://100.64.0.1/x",                        # CGNAT
        "file:///etc/passwd",                         # 非 http scheme
        "gopher://evil/x",                            # 非 http scheme
        "data:text/html,<script>",                    # data scheme
        "ftp://arxiv.org/x",                          # 即便 host 允许，scheme 非 http
        "http://localhost/x",                         # 本地指代名
        "http://svc.internal/x",                      # 内网指代名
        "https://evil.com/x",                         # 不在 allowlist
        "https://notarxiv.org/x",                     # 前缀混淆（非子域）
        "https://arxiv.org.evil.com/x",               # 后缀混淆攻击
    ],
)
def test_ssrf_urls_refused(url: str):
    with pytest.raises(DocumentIntakeError):
        assert_url_allowed(url, allowlist=ALLOWLIST)


@pytest.mark.parametrize(
    "url",
    [
        "https://arxiv.org/abs/2401.00001",
        "http://arxiv.org/x",
        "https://export.arxiv.org/abs/x",  # 子域经 .arxiv.org 后缀放行
    ],
)
def test_allowlisted_urls_pass(url: str):
    assert_url_allowed(url, allowlist=ALLOWLIST)  # 不 raise


def test_intake_rejects_disallowed_origin_url(tmp_path: Path):
    """端到端:origin 是未授权 URL（SSRF 面）→ intake 在 URL 门拒。"""
    vault = _vault(tmp_path)
    pol = IntakePolicy(url_allowlist=ALLOWLIST)
    with pytest.raises(DocumentIntakeError):
        intake_document(
            vault=vault, filename="p.pdf", license=_license(), data=_pdf_bytes(),
            origin="http://169.254.169.254/x", policy=pol,
        )
    assert vault.registry.list_versions() == []


@pytest.mark.parametrize("mut", [_NetParserCreateConnection(), _NetParserUrllib(), _NetParserRawSocket()])
def test_no_network_parser_blocks_egress(mut):
    """种坏门:解析器尝试联网（create_connection / urllib / 裸 socket）→ no-network 门拒。"""
    safe = SafeDocumentParser(mut)
    with pytest.raises(DocumentIntakeError):
        safe.parse(_pdf_bytes(), declared_format="pdf")


def test_intake_rejects_network_parser(tmp_path: Path):
    """端到端:把会联网的恶意解析器接进 intake → 在 sandbox 拒，绝不入账。"""
    vault = _vault(tmp_path)
    with pytest.raises(DocumentIntakeError):
        intake_document(
            vault=vault, filename="p.pdf", license=_license(),
            data=_pdf_bytes(), parser=_NetParserCreateConnection(),
        )
    assert vault.registry.list_versions() == []


def test_no_network_restores_globals_after_context():
    """no-network 上下文退出后还原全局 socket，绝不泄漏（try/finally）。"""
    orig_gai, orig_cc = socket.getaddrinfo, socket.create_connection
    orig_connect = socket.socket.connect
    with no_network():
        with pytest.raises(DocumentIntakeError):
            socket.getaddrinfo("example.com", 80)
    assert socket.getaddrinfo is orig_gai
    assert socket.create_connection is orig_cc
    assert socket.socket.connect is orig_connect


def test_offline_parser_works_inside_sandbox():
    """正路径:离线 stub 解析器在 no-network 沙箱内正常工作（不误伤合法离线解析）。"""
    parsed = SafeDocumentParser(StubOfflineParser()).parse(_pdf_bytes(3), declared_format="pdf")
    assert parsed.n_pages == 3
    assert parsed.parser_name == "stub-offline-v0"
    assert "follow-on" in parsed.extraction_note  # 诚实标注抽取为后续


# ══ 验收 #3 · size / page / compression limit（zip bomb / DoS）→ 拒 ════════════
def test_size_limit_refused():
    limits = IntakeLimits(max_bytes=100)
    check_size(100, limits)  # 边界:等于上限放行
    with pytest.raises(DocumentIntakeError):
        check_size(101, limits)


def test_intake_size_limit_refused_inmemory(tmp_path: Path):
    vault = _vault(tmp_path)
    pol = IntakePolicy(limits=IntakeLimits(max_bytes=10))
    with pytest.raises(DocumentIntakeError):
        intake_document(vault=vault, filename="p.pdf", license=_license(), data=_pdf_bytes(5), policy=pol)
    assert vault.registry.list_versions() == []


def test_intake_size_limit_prechecks_path_without_registering(tmp_path: Path):
    """path 入口:stat 预检超限即拒（不先把 DoS 文件读爆内存），绝不入账。"""
    vault = _vault(tmp_path)
    big = tmp_path / "big.pdf"
    big.write_bytes(_pdf_bytes(200))
    pol = IntakePolicy(limits=IntakeLimits(max_bytes=50))
    with pytest.raises(DocumentIntakeError):
        intake_document(vault=vault, filename="big.pdf", license=_license(), path=big, policy=pol)
    assert vault.registry.list_versions() == []


def test_zip_bomb_compression_ratio_refused():
    """种坏门:高压缩比 zip（解压远大于压缩）→ 拒（只读中央目录·绝不解压触发炸弹）。"""
    bomb = _zip_bomb_bytes(2_000_000)
    limits = IntakeLimits(max_compression_ratio=10.0, max_uncompressed_bytes=10**12, max_archive_entries=10**6)
    with pytest.raises(DocumentIntakeError):
        inspect_archive_safety(bomb, limits)


def test_zip_uncompressed_total_refused():
    bomb = _zip_bomb_bytes(2_000_000)
    limits = IntakeLimits(max_compression_ratio=10**6, max_uncompressed_bytes=1000, max_archive_entries=10**6)
    with pytest.raises(DocumentIntakeError):
        inspect_archive_safety(bomb, limits)


def test_zip_too_many_entries_refused():
    z = _many_entries_zip(8)
    limits = IntakeLimits(max_archive_entries=5, max_compression_ratio=10**6, max_uncompressed_bytes=10**12)
    with pytest.raises(DocumentIntakeError):
        inspect_archive_safety(z, limits)


def test_corrupt_zip_refused():
    """fail-closed:声称 zip（PK 头）但中央目录读不开 → 拒（损坏 / 伪装容器不可信）。"""
    with pytest.raises(DocumentIntakeError):
        inspect_archive_safety(b"PK\x03\x04" + b"\x00" * 40, IntakeLimits())


def test_non_zip_skips_archive_gate():
    """非 zip 容器（PDF）不走 archive 门（由 size 门 + sandbox 兜底），不误伤。"""
    inspect_archive_safety(_pdf_bytes(), IntakeLimits())  # 不 raise


def test_intake_zip_bomb_docx_refused(tmp_path: Path):
    """端到端:伪装成 .docx 的 zip bomb（过 mime 门）→ 在 archive 门拒，绝不入账。"""
    vault = _vault(tmp_path)
    pol = IntakePolicy(limits=IntakeLimits(max_compression_ratio=10.0))
    with pytest.raises(DocumentIntakeError):
        intake_document(vault=vault, filename="evil.docx", license=_license(),
                        data=_zip_bomb_bytes(2_000_000), policy=pol)
    assert vault.registry.list_versions() == []


def test_page_bomb_refused():
    """种坏门:解析返回超量页（页炸弹）→ SafeDocumentParser 页数门拒。"""
    limits = IntakeLimits(max_pages=10)
    safe = SafeDocumentParser(_PageBombParser(11), limits=limits)
    with pytest.raises(DocumentIntakeError):
        safe.parse(_pdf_bytes(), declared_format="pdf")


def test_intake_page_bomb_refused(tmp_path: Path):
    vault = _vault(tmp_path)
    pol = IntakePolicy(limits=IntakeLimits(max_pages=3))
    with pytest.raises(DocumentIntakeError):
        intake_document(vault=vault, filename="p.pdf", license=_license(),
                        data=_pdf_bytes(), parser=_PageBombParser(99), policy=pol)
    assert vault.registry.list_versions() == []


# ══ 验收 #4 · quarantine → sandbox 隔离真生效（绝不直接信任原件） ═══════════════
def test_quarantine_then_sandbox_isolation(tmp_path: Path):
    """正路径:文档先落 raw vault（内容寻址）+ quarantine，解析【喂的是隔离副本】而非原件路径。"""
    vault = _vault(tmp_path)
    src = tmp_path / "incoming" / "paper.pdf"
    src.parent.mkdir(parents=True)
    data = _pdf_bytes(2)
    src.write_bytes(data)

    rec = _RecordingParser()
    res = intake_document(vault=vault, filename="paper.pdf", license=_license(), path=src,
                          origin="https://arxiv.org/abs/x",
                          policy=IntakePolicy(url_allowlist=ALLOWLIST), parser=rec)

    sha = hashlib.sha256(data).hexdigest()
    # raw vault:内容寻址落原件（审计「来了什么」）
    raw = vault.raw_dir / sha[:2] / sha
    assert raw.exists() and raw.read_bytes() == data
    # quarantine:隔离副本存在，且【与原件不同路径】（不就地信任）
    q = Path(res.quarantine_path)
    assert q.exists() and q.parent == vault.quarantine_dir and q != src
    assert q.read_bytes() == data
    # 解析器看到的字节 = 隔离副本内容（证明解析喂自 quarantine，非直接信任原件路径）
    assert rec.seen == data
    # 过门后入账
    assert len(vault.registry.list_versions()) == 1


def test_rejected_doc_never_registered(tmp_path: Path):
    """隔离语义:被拒的恶意文档绝不入账（registry 空），原件路径不被破坏。"""
    vault = _vault(tmp_path)
    src = tmp_path / "evil.pdf"
    src.write_bytes(_ELF)
    with pytest.raises(DocumentIntakeError):
        intake_document(vault=vault, filename="evil.pdf", license=_license(), path=src)
    assert vault.registry.list_versions() == []
    assert src.read_bytes() == _ELF  # 原件未被改动


# ══ 验收 #5 · source hash + license/rights record 在场 ════════════════════════
def test_source_hash_and_license_present(tmp_path: Path):
    """正路径:结果带完整 sha256 source hash + license record，且入账记录同样携带。"""
    vault = _vault(tmp_path)
    data = _pdf_bytes(1)
    res = intake_document(vault=vault, filename="p.pdf", license=_license(),
                          data=data, origin="https://arxiv.org/abs/x", title="A Paper",
                          policy=IntakePolicy(url_allowlist=ALLOWLIST))
    full = hashlib.sha256(data).hexdigest()
    assert res.version.content_sha256 == full and len(full) == 64       # 完整 256-bit source hash
    assert res.source.source_hash == full
    assert res.version.license.license == "CC-BY-4.0"                    # license/rights 在场
    assert res.source.license.rights_holder == "arXiv"
    # 入账记录携带 source hash + license（可追溯·合规)
    recs = vault.registry.list_versions()
    assert recs[0]["content_sha256"] == full
    assert recs[0]["license"]["license"] == "CC-BY-4.0"


def test_empty_license_refused():
    """种坏门:空 license（未显式声明许可）→ 拒（绝不静默伪造 / 留空·合规红线）。"""
    with pytest.raises(DocumentIntakeError):
        LicenseRecord(license="")
    with pytest.raises(DocumentIntakeError):
        LicenseRecord(license="   ")


def test_unknown_license_must_be_explicit(tmp_path: Path):
    """许可未知也须【显式】填 'unknown'（可审计的刻意选择），此时摄入放行。"""
    vault = _vault(tmp_path)
    res = intake_document(vault=vault, filename="p.pdf",
                          license=LicenseRecord(license="unknown"), data=_pdf_bytes())
    assert res.version.license.license == "unknown"


# ══ 金库登记账机制:append-only + tamper-evident + 单一身份源 ════════════════════
def test_identity_reuses_content_hash_single_source(tmp_path: Path):
    """单一身份源红线:16 位 id 由 ids.content_hash 产（不另造）；安全键用完整 256-bit sha256。"""
    vault = _vault(tmp_path)
    data = _pdf_bytes(1)
    res = intake_document(vault=vault, filename="p.pdf", license=_license(), data=data)
    full = hashlib.sha256(data).hexdigest()
    assert res.version.content_id == content_hash({"schema": "document-intake-v1", "content_sha256": full})
    assert len(res.version.content_id) == 16
    assert len(res.version.content_sha256) == 64


def test_registry_append_only_chain_and_tamper_detected(tmp_path: Path):
    """登记账 prev_hash 链:正常 → intact；篡改某行 → 检出（防对登记文件事后篡改）。"""
    vault = _vault(tmp_path)
    intake_document(vault=vault, filename="a.pdf", license=_license(), data=_pdf_bytes(1))
    intake_document(vault=vault, filename="b.pdf", license=_license(), data=_pdf_bytes(2))
    ok, issues = vault.registry.verify_chain()
    assert ok, issues

    jsonl = tmp_path / "vault" / "documents.jsonl"
    lines = jsonl.read_text().splitlines()
    import json as _json
    rec0 = _json.loads(lines[0])
    rec0["record"]["license"]["license"] = "TAMPERED"
    lines[0] = _json.dumps(rec0, ensure_ascii=False)
    jsonl.write_text("\n".join(lines) + "\n")
    ok2, issues2 = DocumentRegistry(jsonl).verify_chain()
    assert not ok2 and issues2


def test_raw_vault_content_addressed_idempotent(tmp_path: Path):
    """内容寻址:同内容两次摄入,raw vault 只存一份（幂等·按 sha256 寻址）。"""
    vault = _vault(tmp_path)
    data = _pdf_bytes(1)
    intake_document(vault=vault, filename="p.pdf", license=_license(), data=data)
    intake_document(vault=vault, filename="p2.pdf", license=_license(), data=data)
    sha = hashlib.sha256(data).hexdigest()
    raw = vault.raw_dir / sha[:2] / sha
    assert raw.exists()
    # 两次都入账（版本账 append），但 raw 内容寻址只一份
    assert len(vault.registry.list_versions()) == 2
