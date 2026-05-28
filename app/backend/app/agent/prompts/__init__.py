"""v0.8.6 起 · Mode 2 教学型 agent prompt 模板库。

v0.8.4 Day 6 落 baseline prompt (mode2_teaching) 但不接 SSE；
v0.8.6 接入多轮 chat + conversation 持久化 + RAG glossary。
"""

from .mode2_teaching import MODE2_SYSTEM_PROMPT_ZH, build_mode2_prompt

__all__ = ["MODE2_SYSTEM_PROMPT_ZH", "build_mode2_prompt"]
