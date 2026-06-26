"""Document Intelligence 抽取层的【对抗式】测试（GOAL §6 续·建在摄入安全栈之上）。

按卡的 4 条可证伪验收逐条种【已知坏门】（MUT = malicious-under-test）证明拦得住、且正路径不误伤：

  #1 EvidenceSpan 缺 source doc / version / parser run / block / 位置追溯（孤儿）→ 拒。
  #2 ExtractedStrategySpec / ExtractedModelClaim 未标「抽取自文档·未验证」（缺证据 / 标 validated /
     缺 disclosure）→ 拒（抽取≠已验证·不假绿灯）。
  #3 抽取【经 sandbox】OfflineDocumentParser（no-network + 页数限额）——抽取器联网 / 页炸弹 → 拒。
  #4 ExtractionRun 落账可 replay（内容寻址·同输入命中存量·哈希链可对账）·正路径不误伤。

外加 span-support 抗伪造核心：reader（untrusted）声称的引文【对回源 block 复算】，伪造 → challenged、
不进 confirmatory（GOAL §6）。所有网络 MUT【绝不真发网络】——no-network 门在 socket 层 fail-closed。
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from app.documents.extraction import (
    EXTRACTED_DISCLOSURE,
    EXTRACTED_UNVERIFIED,
    BlockPosition,
    DocumentBlock,
    DocumentExtractionError,
    EvidenceSpan,
    ExtractedModelClaim,
    ExtractedStrategySpec,
    ExtractionLedger,
    ExtractionRun,
    FormulaArtifact,
    RawBlock,
    ReaderProposal,
    SandboxedBlockExtractor,
    SpanSupportVerification,
    StubBlockExtractor,
    confirmatory_ready,
    run_extraction,
    verify_span_support,
)
from app.documents.intake import LicenseRecord, DocumentVault, intake_document
from app.documents.safety import DocumentIntakeError
from app.documents.sandbox import ParsedDocument
from app.lineage.ids import HASH_LEN, content_hash

# ── 共用夹具 ────────────────────────────────────────────────────────────────────
SID, DVID = "src-aaaa", "ver-bbbb"
CSHA = "f" * 64

_DOC_TEXT = (
    b"# Cross-Sectional Momentum\n\n"
    b"We buy the top decile of stocks by trailing 12-month return and short the bottom decile,"
    b" rebalancing monthly with equal weights.\n\n"
    b"| bucket | weight |\n| top decile | +1 |\n| bottom decile | -1 |\n\n"
    b"The reported in-sample Sharpe ratio is $1.8$ before costs.\n\n"
    b"[1] Jegadeesh and Titman 1993, Returns to Buying Winners and Selling Losers.\n"
)


def _para_block(blocks: tuple[DocumentBlock, ...]) -> DocumentBlock:
    return next(b for b in blocks if "top decile" in b.text and b.block_type == "paragraph")


def _run(reader=None, ledger=None, data: bytes = _DOC_TEXT):
    return run_extraction(
        data=data,
        declared_format="text",
        source_id=SID,
        doc_version_id=DVID,
        content_sha256=CSHA,
        reader=reader,
        ledger=ledger,
    )


def _genuine_span(block: DocumentBlock) -> EvidenceSpan:
    return EvidenceSpan.from_block(block, parser_confidence=0.9)


# ── MUT 抽取器（种坏门：解析 / 切块时联网 · 页炸弹） ──────────────────────────────
class _NetInParseExtractor:
    name = "mut-net-parse"
    version = "v0"

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        socket.create_connection(("8.8.8.8", 53), timeout=1)  # 应被 no-network 拦
        return ParsedDocument(1, self.name, declared_format)

    def extract_blocks(self, data: bytes, *, declared_format: str):
        return ()


class _NetInExtractBlocksExtractor:
    name = "mut-net-blocks"
    version = "v0"

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        return ParsedDocument(1, self.name, declared_format)

    def extract_blocks(self, data: bytes, *, declared_format: str):
        s = socket.socket()
        try:
            s.connect(("8.8.8.8", 53))  # 裸 socket 直连 → 应被 no-network 拦
        finally:
            s.close()
        return ()


class _PageBombExtractor:
    name = "mut-pagebomb"
    version = "v0"

    def __init__(self, n_pages: int) -> None:
        self._n = n_pages

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        return ParsedDocument(self._n, self.name, declared_format)

    def extract_blocks(self, data: bytes, *, declared_format: str):
        return ()


class _BadProductExtractor:
    """种坏门：extract_blocks 产出非 RawBlock（绕 schema）→ 编排须拒。"""

    name = "mut-bad-product"
    version = "v0"

    def parse(self, data: bytes, *, declared_format: str) -> ParsedDocument:
        return ParsedDocument(1, self.name, declared_format)

    def extract_blocks(self, data: bytes, *, declared_format: str):
        return ({"not": "a RawBlock"},)


# ════ 验收 #1 · EvidenceSpan 缺追溯（孤儿）→ 拒 ═══════════════════════════════════
def _span_kwargs(**override):
    base = dict(
        span_id="x",
        source_id=SID,
        doc_version_id=DVID,
        parser_run_id="prun",
        block_id="blk",
        position=BlockPosition(char_span=(0, 3)),
        quoted_excerpt_hash=content_hash("abc"),
        parser_confidence=0.5,
        quoted_excerpt="abc",
    )
    base.update(override)
    return base


@pytest.mark.parametrize("missing", ["source_id", "doc_version_id", "parser_run_id", "block_id"])
def test_evidence_span_missing_traceability_key_refused(missing: str):
    """种坏门：EvidenceSpan 缺任一追溯键（source/version/parser_run/block）→ 孤儿 → 必拒。"""
    with pytest.raises(DocumentExtractionError):
        EvidenceSpan(**_span_kwargs(**{missing: "   "}))  # 空白 = 视同缺


def test_evidence_span_missing_excerpt_hash_refused():
    with pytest.raises(DocumentExtractionError):
        EvidenceSpan(**_span_kwargs(quoted_excerpt_hash="", quoted_excerpt=""))


def test_evidence_span_no_position_locator_refused():
    """种坏门：position 无任何定位器（page/bbox/section/char_span 全缺）→ 无法追溯回原文 → 拒。"""
    with pytest.raises(DocumentExtractionError):
        BlockPosition()  # 全缺 → BlockPosition.__post_init__ 即拒


def test_evidence_span_confidence_out_of_range_refused():
    with pytest.raises(DocumentExtractionError):
        EvidenceSpan(**_span_kwargs(parser_confidence=1.5))
    with pytest.raises(DocumentExtractionError):
        EvidenceSpan(**_span_kwargs(parser_confidence=-0.1))


def test_evidence_span_excerpt_hash_inconsistent_refused():
    """种坏门：存了引文却配不匹配的哈希（引文/哈希自相矛盾）→ 拒。"""
    with pytest.raises(DocumentExtractionError):
        EvidenceSpan(**_span_kwargs(quoted_excerpt="abc", quoted_excerpt_hash=content_hash("DIFFERENT")))


def test_evidence_span_create_and_from_block_have_full_traceability():
    """正路径：from_block 建的 span 追溯键全在场、span_id 16 位、整块引文哈希自洽。"""
    res = _run()
    span = _genuine_span(_para_block(res.blocks))
    assert span.source_id == SID and span.doc_version_id == DVID
    assert span.parser_run_id == res.parser_run_id and span.block_id
    assert len(span.span_id) == HASH_LEN
    assert span.position.char_span is not None
    assert content_hash(span.quoted_excerpt) == span.quoted_excerpt_hash


# ════ 验收 #2 · 抽取声明未标「未验证」→ 拒 ════════════════════════════════════════
def test_extracted_strategyspec_without_evidence_refused():
    """种坏门：ExtractedStrategySpec 无 EvidenceSpan（evidence_refs 空）→ 拒（GOAL §6）。"""
    with pytest.raises(DocumentExtractionError):
        ExtractedStrategySpec.create(
            extraction_run_id="r", source_id=SID, doc_version_id=DVID,
            title="t", summary="s", evidence_refs=[],
        )


def test_extracted_strategyspec_empty_ref_refused():
    with pytest.raises(DocumentExtractionError):
        ExtractedStrategySpec.create(
            extraction_run_id="r", source_id=SID, doc_version_id=DVID,
            title="t", summary="s", evidence_refs=["  "],
        )


@pytest.mark.parametrize("bad_status", ["validated", "proof_backed", "production_ready", "supported", ""])
def test_extracted_strategyspec_non_unverified_status_refused(bad_status: str):
    """种坏门：抽取层把声明标成非 extracted_unverified（假绿灯）→ 拒（抽取≠已验证）。"""
    with pytest.raises(DocumentExtractionError):
        ExtractedStrategySpec(
            spec_id="x", extraction_run_id="r", source_id=SID, doc_version_id=DVID,
            title="t", summary="s", evidence_refs=("span1",),
            verification_status=bad_status, disclosure=EXTRACTED_DISCLOSURE,
        )


def test_extracted_strategyspec_missing_disclosure_marker_refused():
    """种坏门：抽掉「未验证」诚实 marker（静默升格）→ 拒。"""
    with pytest.raises(DocumentExtractionError):
        ExtractedStrategySpec(
            spec_id="x", extraction_run_id="r", source_id=SID, doc_version_id=DVID,
            title="t", summary="s", evidence_refs=("span1",),
            verification_status=EXTRACTED_UNVERIFIED, disclosure="this strategy is great",
        )


@pytest.mark.parametrize("bad_status", ["validated", "production_ready"])
def test_extracted_modelclaim_non_unverified_status_refused(bad_status: str):
    with pytest.raises(DocumentExtractionError):
        ExtractedModelClaim(
            claim_id="x", extraction_run_id="r", source_id=SID, doc_version_id=DVID,
            claim_text="Sharpe 1.8", evidence_refs=("span1",),
            verification_status=bad_status, disclosure=EXTRACTED_DISCLOSURE,
        )


def test_extracted_modelclaim_without_evidence_refused():
    with pytest.raises(DocumentExtractionError):
        ExtractedModelClaim.create(
            extraction_run_id="r", source_id=SID, doc_version_id=DVID,
            claim_text="Sharpe 1.8", evidence_refs=[],
        )


def test_extracted_claims_default_marks_unverified():
    """正路径：create 出的声明默认硬标 extracted_unverified + 含「未验证」诚实 disclosure。"""
    spec = ExtractedStrategySpec.create(
        extraction_run_id="r", source_id=SID, doc_version_id=DVID,
        title="Momentum", summary="buy top decile", evidence_refs=["span1"],
    )
    claim = ExtractedModelClaim.create(
        extraction_run_id="r", source_id=SID, doc_version_id=DVID,
        claim_text="Sharpe 1.8", evidence_refs=["span1"],
    )
    assert spec.verification_status == EXTRACTED_UNVERIFIED == claim.verification_status
    assert "未验证" in spec.disclosure and "未验证" in claim.disclosure
    # 不得自带 proof-backed / production-ready 之类绿灯措辞。
    for word in ("proof-backed", "production-ready", "evidence-sufficient"):
        assert word not in spec.disclosure.replace("不得展示为 proof-backed / evidence-sufficient / production-ready", "")


# ════ 验收 #3 · 抽取经 sandbox（no-network + 页数限额）不绕安全门 ═══════════════════
def test_extraction_blocks_network_in_parse():
    """种坏门：抽取器 parse 内联网 → no-network 沙箱拦下（DocumentIntakeError）。"""
    sx = SandboxedBlockExtractor(_NetInParseExtractor())
    with pytest.raises(DocumentIntakeError):
        sx.extract(_DOC_TEXT, declared_format="text", source_id=SID, doc_version_id=DVID, content_sha256=CSHA)


def test_extraction_blocks_network_in_extract_blocks():
    """种坏门：抽取器 extract_blocks 内裸 socket 外联 → no-network 沙箱拦下。"""
    sx = SandboxedBlockExtractor(_NetInExtractBlocksExtractor())
    with pytest.raises(DocumentIntakeError):
        sx.extract(_DOC_TEXT, declared_format="text", source_id=SID, doc_version_id=DVID, content_sha256=CSHA)


def test_extraction_page_bomb_refused():
    """种坏门：抽取器报超限页数（页炸弹）→ check_pages 限额门拒。"""
    sx = SandboxedBlockExtractor(_PageBombExtractor(10_000_000))
    with pytest.raises(DocumentIntakeError):
        sx.extract(_DOC_TEXT, declared_format="text", source_id=SID, doc_version_id=DVID, content_sha256=CSHA)


def test_extraction_rejects_non_rawblock_product():
    """种坏门：抽取器产出非 RawBlock（绕 schema 约束）→ 拒。"""
    sx = SandboxedBlockExtractor(_BadProductExtractor())
    with pytest.raises(DocumentExtractionError):
        sx.extract(_DOC_TEXT, declared_format="text", source_id=SID, doc_version_id=DVID, content_sha256=CSHA)


def test_stub_binary_does_not_fabricate_blocks():
    """诚实：二进制格式（pdf）stub 不伪造块（真结构抽取须真解析库·用户选型）。"""
    sx = SandboxedBlockExtractor(StubBlockExtractor())
    products = sx.extract(b"%PDF-1.4 ...", declared_format="pdf", source_id=SID, doc_version_id=DVID, content_sha256=CSHA)
    assert products.blocks == ()  # 不伪造
    assert "follow-on" in products.parsed.extraction_note  # 诚实留白


def test_extraction_goes_through_sandbox_with_real_blocks():
    """正路径：真文本经沙箱 → 切出真 block（含 doc-relative char_span）·过 no-network + 限额门不误伤。"""
    sx = SandboxedBlockExtractor(StubBlockExtractor())
    products = sx.extract(_DOC_TEXT, declared_format="text", source_id=SID, doc_version_id=DVID, content_sha256=CSHA)
    assert len(products.blocks) >= 4
    para = _para_block(products.blocks)
    s, e = para.position.char_span  # doc-relative：切回原文须命中块文本
    assert _DOC_TEXT.decode()[s:e] == para.text
    assert {b.block_type for b in products.blocks} >= {"heading", "paragraph", "table", "formula", "reference"}


# ════ span-support 抗伪造 + confirmatory 门（GOAL §6） ════════════════════════════
def test_span_support_genuine_supported():
    res = _run()
    span = verify_span_support(_genuine_span(_para_block(res.blocks)), {b.block_id: b for b in res.blocks})
    assert span.support.status == "supported"


def test_span_support_fabricated_excerpt_challenged():
    """种坏门：reader 声称某 char_span 处引文 = X，实则不符 → challenged（抓伪造）。"""
    res = _run()
    block = _para_block(res.blocks)
    fake = EvidenceSpan.create(
        source_id=SID, doc_version_id=DVID, parser_run_id=res.parser_run_id, block_id=block.block_id,
        position=BlockPosition(char_span=(0, 12)), quoted_excerpt="SELL EVERYTHING", parser_confidence=0.99,
    )
    checked = verify_span_support(fake, {b.block_id: b for b in res.blocks})
    assert checked.support.status == "challenged"


def test_span_support_dangling_block_challenged():
    """种坏门：span 引一个本次抽取没产的 block_id（悬挂）→ challenged（不可复算）。"""
    res = _run()
    span = EvidenceSpan.create(
        source_id=SID, doc_version_id=DVID, parser_run_id=res.parser_run_id, block_id="nonexistent-block",
        position=BlockPosition(char_span=(0, 3)), quoted_excerpt="abc", parser_confidence=0.5,
    )
    checked = verify_span_support(span, {b.block_id: b for b in res.blocks})
    assert checked.support.status == "challenged"


def test_span_support_cross_doc_block_challenged():
    """种坏门：span 的 doc_version/parser_run 与所引 block 不一致（跨文档伪造）→ challenged。"""
    res = _run()
    block = _para_block(res.blocks)
    span = EvidenceSpan.create(
        source_id=SID, doc_version_id="OTHER-DOC", parser_run_id=res.parser_run_id, block_id=block.block_id,
        position=BlockPosition(char_span=(0, len(block.text))), quoted_excerpt=block.text, parser_confidence=0.9,
    )
    checked = verify_span_support(span, {b.block_id: b for b in res.blocks})
    assert checked.support.status == "challenged"


def test_confirmatory_requires_all_spans_supported():
    """GOAL §6：任一引用 span 未过 span-support → 声明不进 confirmatory（保守·不假绿灯）。"""
    res = _run()
    block = _para_block(res.blocks)
    good = verify_span_support(_genuine_span(block), {b.block_id: b for b in res.blocks})
    bad = verify_span_support(
        EvidenceSpan.create(
            source_id=SID, doc_version_id=DVID, parser_run_id=res.parser_run_id, block_id=block.block_id,
            position=BlockPosition(char_span=(0, 5)), quoted_excerpt="WRONG", parser_confidence=0.5,
        ),
        {b.block_id: b for b in res.blocks},
    )
    spans = {good.span_id: good, bad.span_id: bad}
    assert confirmatory_ready([good.span_id], spans) is True
    assert confirmatory_ready([good.span_id, bad.span_id], spans) is False
    assert confirmatory_ready([], spans) is False


# ════ 验收 #4 · ExtractionRun 落账可 replay · 哈希链对账 · 不混 honest-N ═══════════
def test_extraction_run_content_addressed_replay(tmp_path: Path):
    """同输入 → 同 run_id；二次抽取命中存量（不重复落账）= replay 幂等。"""
    led = ExtractionLedger(tmp_path / "ext" / "runs.jsonl")
    r1 = _run(ledger=led)
    r2 = _run(ledger=led)
    assert r1.run.run_id == r2.run.run_id
    assert r1.recorded is True and r2.recorded is False  # 二次 = hit
    assert led.get(r1.run.run_id) is not None
    assert len(led.list_runs()) == 1  # append-only 但内容寻址幂等 → 只一条


def test_extraction_run_replay_after_reopen(tmp_path: Path):
    """落账持久：重开 ledger（新进程语义）后同输入仍命中存量。"""
    p = tmp_path / "ext" / "runs.jsonl"
    r1 = _run(ledger=ExtractionLedger(p))
    r2 = _run(ledger=ExtractionLedger(p))  # 重开
    assert r2.recorded is False and r2.run.run_id == r1.run.run_id


def test_extraction_ledger_chain_detects_tamper(tmp_path: Path):
    """落账哈希链可对账：事后篡改记录 → verify_chain 揪出（诚实：只防篡改）。"""
    p = tmp_path / "ext" / "runs.jsonl"
    led = ExtractionLedger(p)
    _run(ledger=led)
    assert led.verify_chain()[0] is True
    raw = p.read_text(encoding="utf-8")
    p.write_text(raw.replace("\"parser_name\":", "\"parser_name\":\"X\",\"_x\":", 1) if "parser_name" in raw else raw.replace(SID, "tampered", 1))
    intact, issues = ExtractionLedger(p).verify_chain()
    assert intact is False and issues


def test_extraction_run_excludes_outputs_from_run_id():
    """replay 锚点：run_id 只由【输入】定（doc/version/content/parser_run/抽取器身份），不含产物 id / 时间戳。"""
    a = ExtractionRun.create(
        source_id=SID, doc_version_id=DVID, content_sha256=CSHA, parser_run_id="pr",
        parser_name="p", extractor_name="e", extractor_version="v0", block_ids=["b1"],
    )
    b = ExtractionRun.create(
        source_id=SID, doc_version_id=DVID, content_sha256=CSHA, parser_run_id="pr",
        parser_name="p", extractor_name="e", extractor_version="v0", block_ids=["b1", "b2", "b3"],
    )
    assert a.run_id == b.run_id  # 产物列表不同但输入同 → 同 run_id


def test_extraction_ledger_is_separate_from_honest_n():
    """红线：ExtractionRun 落账走文档侧独立账，绝不是 honest-N 试验账（不虚高 honest-N）。"""
    from app.lineage.ledger import Ledger as HonestNLedger

    assert ExtractionLedger is not HonestNLedger
    assert not issubclass(ExtractionLedger, HonestNLedger)
    # ExtractionRun 无 config_hash / strategy_goal_ref（不是试验计数单元）。
    fields = ExtractionRun.create(
        source_id=SID, doc_version_id=DVID, content_sha256=CSHA, parser_run_id="pr",
        parser_name="p", extractor_name="e", extractor_version="v0",
    ).to_payload()
    assert "config_hash" not in fields and "strategy_goal_ref" not in fields


# ════ 解析产物 typed · 公式非数学产物 · 端到端正路径 ══════════════════════════════
def test_typed_artifacts_link_back_to_blocks():
    """table/formula/reference 产物各自 linked by block_id·可追溯回 source/version/parser_run。"""
    res = _run()
    for art in (*res.tables, *res.formulas, *res.references):
        assert art.source_id == SID and art.doc_version_id == DVID
        assert art.parser_run_id == res.parser_run_id
        assert any(b.block_id == art.block_id for b in res.blocks)


def test_formula_artifact_is_not_mathematical():
    """红线：FormulaArtifact = 文档里公式的原样记录，【不是】经验证的 MathematicalArtifact（不强造）。"""
    res = _run()
    assert res.formulas, "测试文本含 $1.8$ 公式块"
    f: FormulaArtifact = res.formulas[0]
    assert "未经数学验证" in f.note and "非 MathematicalArtifact" in f.note
    # 不带数学产物字段（适用域 / 推导 / 反例 / 验证计划）。
    for math_field in ("applicability", "derivation", "proof_sketch", "counterexamples", "failure_conditions"):
        assert not hasattr(f, math_field)


def test_run_extraction_end_to_end_positive_path():
    """正路径不误伤：真文本 → 真 block → 真引文 span（supported）→ 合法未验证 spec → run 落账。"""
    class _Reader:
        def read(self, blocks, *, source_id, doc_version_id, parser_run_id):
            para = _para_block(blocks)
            span = EvidenceSpan.from_block(para, parser_confidence=0.9)
            spec = ExtractedStrategySpec.create(
                extraction_run_id="pending", source_id=source_id, doc_version_id=doc_version_id,
                title="Cross-Sectional Momentum", summary="buy top decile / short bottom decile",
                evidence_refs=[span.span_id],
            )
            claim = ExtractedModelClaim.create(
                extraction_run_id="pending", source_id=source_id, doc_version_id=doc_version_id,
                claim_text="in-sample Sharpe 1.8 before costs", evidence_refs=[span.span_id],
            )
            return ReaderProposal(evidence_spans=(span,), strategy_specs=(spec,), model_claims=(claim,))

    res = _run(reader=_Reader())
    assert len(res.evidence_spans) == 1 and res.evidence_spans[0].support.status == "supported"
    assert res.strategy_specs[0].verification_status == EXTRACTED_UNVERIFIED
    assert res.confirmatory_ready_spec_ids() == (res.strategy_specs[0].spec_id,)
    # run 记录了全部产物 id（可审计 / replay）。
    assert res.run.evidence_span_ids and res.run.strategy_spec_ids and res.run.model_claim_ids


def test_run_extraction_rejects_dangling_evidence_ref():
    """种坏门：reader 的声明引一个本次没产出的 span_id（悬挂 / 伪造引用）→ 编排拒。"""
    class _BadReader:
        def read(self, blocks, *, source_id, doc_version_id, parser_run_id):
            span = EvidenceSpan.from_block(_para_block(blocks), parser_confidence=0.9)
            spec = ExtractedStrategySpec.create(
                extraction_run_id="pending", source_id=source_id, doc_version_id=doc_version_id,
                title="t", summary="s", evidence_refs=["span-that-does-not-exist"],
            )
            return ReaderProposal(evidence_spans=(span,), strategy_specs=(spec,))

    with pytest.raises(DocumentExtractionError):
        _run(reader=_BadReader())


# ════ 与摄入安全栈集成（复用 intake 的 ids·建在其上·不另造身份） ═══════════════════
def test_extraction_layers_on_top_of_intake(tmp_path: Path):
    """集成：先经摄入安全门入金库，再以 intake 给的 source_id/doc_version_id/content_sha256 抽取。

    证明抽取层【建在】摄入安全栈之上、复用其身份（不另造），且抽取读的是隔离副本字节。
    """
    vault = DocumentVault(tmp_path / "vault")
    lic = LicenseRecord(license="CC-BY-4.0", rights_holder="arXiv", source_url="https://arxiv.org/abs/x")
    intake = intake_document(vault=vault, filename="paper.txt", license=lic, data=_DOC_TEXT, origin="local")
    quarantine_bytes = Path(intake.quarantine_path).read_bytes()  # 抽取只读隔离副本

    led = ExtractionLedger(tmp_path / "ext" / "runs.jsonl")
    res = run_extraction(
        data=quarantine_bytes, declared_format=intake.version.declared_format,
        source_id=intake.source.source_id, doc_version_id=intake.version.doc_version_id,
        content_sha256=intake.version.content_sha256, ledger=led,
    )
    assert res.blocks  # 真文本切出块
    assert res.run.source_id == intake.source.source_id
    assert res.run.content_sha256 == intake.version.content_sha256
    assert led.verify_chain()[0] is True
