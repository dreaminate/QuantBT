"""Verifier · 部件12 验证官（异模型一致性检查，产 verdict_id）。

R7 真分离：生成方自报值 vs 验证官【异模型/异种子/异切片】重算值逐项对账。
- 任一数值符号翻转或超容差 → **verdict=blocked（不取均值，异模型不一致即 BLOCK）**。
- 声明缺对应重算（未能复算）→ 该项 unverified → 至少 concern（未验证不当 pass）。
- 独立性【度量】（06 §7-4）：model_differs 为假 → 独立性未确立 → 即便数值全合也降为 concern
  （验证官与生成方共用同一模型，可能共享盲点；self-preference 是熟悉度非身份）。
verdict_id = content-addressed（同输入 → 同 id，可复算）。LLM 调用走部件11/01 record/replay，
replay_ref 指向不可变 fixture（重放读它不重跑 LLM）。
"""

from __future__ import annotations

import math
import unicodedata
from typing import Any, Mapping

from ..lineage.ids import canonical_json
from .schema import (
    DISCLOSURE,
    ClaimCheck,
    Independence,
    Verdict,
    VerdictRecord,
    VerifierError,
    compute_verdict_id,
)

# 相对+绝对容差：|a-b| <= atol + rtol*|claimed|。档位选择非物理常数（裁决文案明示）。
DEFAULT_RTOL = 1e-6
DEFAULT_ATOL = 1e-9


def _norm_model(m: Any) -> str:
    """模型标识归一（NFC + 去空白 + casefold），与 approval/gate.py 的 approver≠creator 自审防护一致。

    复核 #2：'gpt-4' / 'GPT-4 ' / ' gpt-4' 是同一模型——大小写/空白/Unicode 拼写差不得伪装成异模型。
    """

    return unicodedata.normalize("NFC", str(m)).strip().casefold()


def _norm_value(x: Any) -> str:
    """种子/切片归一（NFC + 去空白，保留大小写——dataset 版本号大小写可能有意义）。"""

    return unicodedata.normalize("NFC", str(x)).strip()


def _classify(claimed: float | None, recomputed: float | None, *, rtol: float, atol: float) -> tuple[ClaimCheck, bool]:
    """对账单项 → (ClaimCheck, is_blocking)。is_blocking=True 表示符号翻转/超容差（→ blocked）。"""

    # 复核 #5：任一【存在】侧自报 NaN/Inf 即不可验证的垃圾值 → mismatch/blocking，
    # 必须先于 None 短路判断（否则 claims={x:nan}/recomputed 缺 → 落 unverified → 只 concern，漏 BLOCK）。
    present = [x for x in (claimed, recomputed) if x is not None]
    if any(isinstance(x, float) and (math.isnan(x) or math.isinf(x)) for x in present):
        return ClaimCheck(key="", claimed=claimed, recomputed=recomputed,
                          abs_diff=None, within_tol=False, status="mismatch"), True
    if claimed is None or recomputed is None:
        # 一边缺值（且非 NaN/Inf）：无法对账 → unverified（非 blocking，但触发 concern）。
        return ClaimCheck(key="", claimed=claimed, recomputed=recomputed,
                          abs_diff=None, within_tol=False, status="unverified"), False
    diff = abs(claimed - recomputed)
    within = diff <= atol + rtol * abs(claimed)
    # 符号翻转单列（结论方向相反比数值小差更危险）。0 不算翻转。
    sign_flip = (claimed > 0 > recomputed) or (claimed < 0 < recomputed)
    if sign_flip:
        status = "sign_flip"
    elif within:
        status = "match"
    else:
        status = "mismatch"
    blocking = status in ("mismatch", "sign_flip")
    return ClaimCheck(key="", claimed=claimed, recomputed=recomputed,
                      abs_diff=diff, within_tol=within, status=status), blocking


class Verifier:
    """异模型验证官。无状态；产 VerdictRecord（不落盘——落盘交 VerdictStore）。"""

    def __init__(self, *, rtol: float = DEFAULT_RTOL, atol: float = DEFAULT_ATOL) -> None:
        self._rtol = rtol
        self._atol = atol

    def reconcile(
        self,
        *,
        target_ref: str,
        claims: Mapping[str, float],
        recomputed: Mapping[str, float],
        generator_model: str,
        checker_model: str,
        generator_seed: Any = None,
        checker_seed: Any = None,
        generator_slice: str | None = None,
        checker_slice: str | None = None,
        replay_ref: str | None = None,
        notes: str = "",
        created_at_utc: str = "",
    ) -> VerdictRecord:
        """对生成方自报 `claims` 做异模型 `recomputed` 对账，产权威 verdict_id。"""

        if not target_ref:
            raise VerifierError("target_ref 不可空（验证官须知道复核的是谁）")
        if not generator_model or not checker_model:
            raise VerifierError("generator_model / checker_model 都必填（独立性须被度量，不能假定）")
        if not claims and not recomputed:
            raise VerifierError("无任何可对账的数值声明")

        keys = sorted(set(claims) | set(recomputed))
        checks: list[ClaimCheck] = []
        any_blocking = False
        any_unverified = False
        for k in keys:
            row, blocking = _classify(claims.get(k), recomputed.get(k), rtol=self._rtol, atol=self._atol)
            row = ClaimCheck(key=k, claimed=row.claimed, recomputed=row.recomputed,
                             abs_diff=row.abs_diff, within_tol=row.within_tol, status=row.status)
            checks.append(row)
            any_blocking = any_blocking or blocking
            any_unverified = any_unverified or (row.status == "unverified")

        independence = self._measure_independence(
            generator_model, checker_model, generator_seed, checker_seed,
            generator_slice, checker_slice,
        )

        # 裁决：异模型不一致即 BLOCK（最高优先，不被独立性洗白也不取均值）。
        if any_blocking:
            verdict: Verdict = "blocked"
        elif any_unverified:
            verdict = "concern"        # 有声明未能复算 → 存疑，未验证不当 pass
        elif not independence.established:
            verdict = "concern"        # 数值全合但独立性未确立（同模型）→ 06 §7-4 降级，不给 consistent
        else:
            verdict = "consistent"

        auto_note = self._verdict_note(verdict, checks, independence)
        full_notes = (notes + " " + auto_note).strip() if notes else auto_note

        verdict_id = compute_verdict_id(
            target_ref=target_ref, generator_model=generator_model, checker_model=checker_model,
            verdict=verdict, consistency_check=checks, independence=independence, replay_ref=replay_ref,
        )
        return VerdictRecord(
            verdict_id=verdict_id,
            target_ref=target_ref,
            generator_model=generator_model,
            checker_model=checker_model,
            verdict=verdict,
            consistency_check=checks,
            independence=independence,
            disclosure=DISCLOSURE,
            replay_ref=replay_ref,
            notes=full_notes,
            created_at_utc=created_at_utc,
        )

    def reconcile_decision(
        self,
        *,
        target_ref: str,
        generator_decision: str,
        checker_decision: str,
        generator_model: str,
        checker_model: str,
        replay_ref: str | None = None,
        notes: str = "",
        created_at_utc: str = "",
        **independence_kw: Any,
    ) -> VerdictRecord:
        """离散决策（非数值）一致性：决策不同 → blocked。用于 LLM 决策级复核。"""

        # 编码成一个伪数值键（相等=0/0，不等用哨兵触发 sign_flip → blocking）。
        g = canonical_json(generator_decision)
        c = canonical_json(checker_decision)
        same = g == c
        return self.reconcile(
            target_ref=target_ref,
            claims={"decision_eq": 1.0},
            recomputed={"decision_eq": 1.0 if same else -1.0},
            generator_model=generator_model,
            checker_model=checker_model,
            replay_ref=replay_ref,
            notes=(notes + f" [decision g={generator_decision!r} c={checker_decision!r}]").strip(),
            created_at_utc=created_at_utc,
            **independence_kw,
        )

    @staticmethod
    def _measure_independence(gen_model, chk_model, gen_seed, chk_seed, gen_slice, chk_slice) -> Independence:
        # 复核 #2/#4：归一后比较——大小写/空白/Unicode 拼写差不得把同模型伪装成异模型（独立性须度量非假定）。
        model_differs = _norm_model(gen_model) != _norm_model(chk_model)
        seed_differs = gen_seed is not None and chk_seed is not None and _norm_value(gen_seed) != _norm_value(chk_seed)
        slice_differs = bool(gen_slice) and bool(chk_slice) and _norm_value(gen_slice) != _norm_value(chk_slice)
        axes = int(model_differs) + int(seed_differs) + int(slice_differs)
        established = model_differs   # 最低门槛：异模型；同模型 → 独立性未确立
        if not model_differs:
            note = ("独立性未确立：验证官与生成方共用同一模型，可能共享低困惑度盲点"
                    "（self-preference 是熟悉度非身份）；此为同源复算，非组织独立。")
        else:
            note = f"独立性已度量：异模型{'/异种子' if seed_differs else ''}{'/异切片' if slice_differs else ''}（axes={axes}）。"
        return Independence(model_differs, seed_differs, slice_differs, axes, established, note)

    @staticmethod
    def _verdict_note(verdict: Verdict, checks: list[ClaimCheck], independence: Independence) -> str:
        bad = [c.key for c in checks if c.status in ("mismatch", "sign_flip")]
        unv = [c.key for c in checks if c.status == "unverified"]
        if verdict == "blocked":
            return f"异模型不一致(不取均值)：{bad}；{independence.note}"
        if verdict == "concern":
            if unv:
                return f"存疑：{unv} 未能复算（未验证不当 pass）；{independence.note}"
            return f"存疑：数值在容差内但{independence.note}"
        return f"证据一致（容差内且{independence.note}）。"


__all__ = ["Verifier", "DEFAULT_RTOL", "DEFAULT_ATOL"]
