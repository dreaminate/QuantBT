"""Agent OS 脊柱 02 · LLM record/replay + 受控翻译层（T-016）。

受控翻译层（LLM 只产受 schema 约束对象、不持决策权）+ 不可变 fixture record/replay
（HMAC 完整性 + 内容寻址 cache key）。LLM 是触手、确定性脊柱是骨架，本包是二者间防伪/可回放硬接口。
"""

from __future__ import annotations

from .fixture import FixtureKey, LLMFixture, ModelPin, is_alias_model_id
from .recording_client import RecordingLLMClient
from .repro import PASS_CARET_K_CAVEAT, ReproLevel, pass_caret_k
from .store import FixtureConflict, FixtureStore, IntegrityError, ReplayMiss
from .translation import ControlledTranslator, TranslationResult

__all__ = [
    "ControlledTranslator",
    "FixtureConflict",
    "FixtureKey",
    "FixtureStore",
    "IntegrityError",
    "LLMFixture",
    "ModelPin",
    "PASS_CARET_K_CAVEAT",
    "RecordingLLMClient",
    "ReplayMiss",
    "ReproLevel",
    "TranslationResult",
    "is_alias_model_id",
    "pass_caret_k",
]
