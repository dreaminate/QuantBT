"""T-032 · 文档对齐回归 —— 防 GOAL/RULES.project 与代码漂移（流程即信任）。

种坏门必抓：GOAL M10 若再标「待接进 run 闸门」（与 T-015 已接矛盾）→ 必抓；
禁裸 place_order 红线若从 RULES.project 丢失 → 必抓。
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app as app_pkg

DEV = Path(app_pkg.__file__).resolve().parent.parents[2] / "dev"
GOAL = DEV / "GOAL.md"
RULESP = DEV / "RULES.project.md"


@pytest.mark.skipif(not GOAL.exists(), reason="dev/ 不在此环境")
def test_goal_m10_no_stale_pending():
    txt = GOAL.read_text(encoding="utf-8")
    assert "待接进 run 闸门" not in txt, "GOAL M10 仍标『待接进 run 闸门』（文档滞后于 T-015 已接）"


@pytest.mark.skipif(not RULESP.exists(), reason="dev/ 不在此环境")
def test_rulesproject_keeps_naked_place_order_redline():
    txt = RULESP.read_text(encoding="utf-8")
    assert "禁裸" in txt and "place_order" in txt, "RULES.project 缺『禁裸 place_order』红线（承接 T-026/T-029）"
