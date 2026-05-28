"""v0.8.6 · Mode 2 RAG hybrid retrieval (BM25 + recency + run context)。

patch1 §D.c 设计：
- top_k = 4 (glossary 最多 3 + run summary 最多 1)
- retrieval_score = 0.55 * bm25_norm + 0.35 * cosine_norm + 0.10 * recency_boost
- v0.8.6 简化：cosine 部分用关键词重合度替代 (无需 embedding 服务)

输出格式直接给 build_mode2_prompt(rag_context=...)。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from ..glossary import GlossaryRegistry, GlossaryTerm


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+|[一-鿿]")


def _tokenize(s: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(s)]


def _bm25_score(query_tokens: list[str], doc_tokens: list[str], avg_dl: float = 100.0) -> float:
    """简化 BM25：k1=1.5, b=0.75，IDF 用常数 1（小语料无需精确 IDF）。"""
    if not query_tokens or not doc_tokens:
        return 0.0
    dl = len(doc_tokens)
    k1, b = 1.5, 0.75
    tf: dict[str, int] = {}
    for t in doc_tokens:
        tf[t] = tf.get(t, 0) + 1
    score = 0.0
    for q in query_tokens:
        f = tf.get(q, 0)
        if f == 0:
            continue
        score += (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / avg_dl))
    return score


def _keyword_overlap(query_tokens: list[str], doc_tokens: list[str]) -> float:
    """简化 cosine：query 与 doc 的 token 集合 Jaccard."""
    if not query_tokens or not doc_tokens:
        return 0.0
    q = set(query_tokens)
    d = set(doc_tokens)
    inter = len(q & d)
    union = len(q | d)
    return inter / union if union else 0.0


@dataclass
class RagHit:
    kind: str   # "glossary" | "run_context"
    slug: str
    title: str
    snippet: str
    score: float


def retrieve(
    query: str,
    *,
    glossary: GlossaryRegistry,
    run_context: dict[str, Any] | None = None,
    top_k_glossary: int = 3,
    top_k_run: int = 1,
) -> list[RagHit]:
    """检索 glossary + run summary，按 hybrid score 排序。"""

    q_tokens = _tokenize(query)
    if not q_tokens:
        return []

    # 1. glossary 检索
    glossary_scored: list[tuple[float, GlossaryTerm]] = []
    for t in glossary:
        # 拼 doc：display + L1 + L2 + aliases
        doc = " ".join([
            t.frontmatter.display,
            " ".join(t.aliases),
            t.l1,
            t.l2,
        ])
        d_tokens = _tokenize(doc)
        bm = _bm25_score(q_tokens, d_tokens)
        # 归一化 BM25 到 0-1
        bm_norm = min(bm / 8.0, 1.0)
        overlap = _keyword_overlap(q_tokens, d_tokens)
        # recency 对 glossary 不适用，给 0
        score = 0.55 * bm_norm + 0.35 * overlap + 0.10 * 0.0
        if score > 0.05:
            glossary_scored.append((score, t))

    glossary_scored.sort(key=lambda x: -x[0])
    top_glossary = glossary_scored[:top_k_glossary]

    hits: list[RagHit] = []
    for score, t in top_glossary:
        snippet = t.l1 + "\n" + (t.l2[:300] if t.l2 else "")
        hits.append(RagHit(
            kind="glossary",
            slug=t.slug,
            title=t.frontmatter.display,
            snippet=snippet,
            score=score,
        ))

    # 2. run context
    if run_context and top_k_run > 0:
        # run_context 是 dict，转字符串后做关键词命中
        rc_text = " ".join(f"{k}={v}" for k, v in run_context.items() if v is not None)
        rc_tokens = _tokenize(rc_text)
        bm = _bm25_score(q_tokens, rc_tokens, avg_dl=50.0)
        if bm > 0.5:
            hits.append(RagHit(
                kind="run_context",
                slug=f"run_{run_context.get('run_id', 'unknown')}",
                title="当前 active_run 指标",
                snippet=rc_text[:400],
                score=0.55 * min(bm / 5.0, 1.0),
            ))

    return hits


def format_rag_context(hits: list[RagHit]) -> str:
    """RAG hits → MODE2_SYSTEM_PROMPT_ZH 的 {rag_context} slot。"""
    if not hits:
        return "(无 RAG 命中。请提示用户提供更具体的指标名或上下文。)"
    parts = []
    for h in hits:
        parts.append(f"[{h.kind}: {h.title} · slug={h.slug}]\n{h.snippet}")
    return "\n\n".join(parts)


def format_run_context(run_data: dict[str, Any] | None) -> str:
    """run context → {run_context} slot。"""
    if not run_data:
        return "(无 active run 上下文)"
    keys_priority = [
        "run_id", "strategy_name", "market", "frequency",
        "sharpe", "sharpe_ratio", "pbo", "dsr", "deflated_sharpe",
        "max_drawdown", "alpha", "beta", "information_ratio",
        "ic_ir", "turnover", "trust_level",
    ]
    lines = []
    for k in keys_priority:
        if k in run_data and run_data[k] is not None:
            lines.append(f"  {k}: {run_data[k]}")
    return "\n".join(lines) if lines else "(active_run 无可识别指标字段)"


__all__ = ["RagHit", "format_rag_context", "format_run_context", "retrieve"]
