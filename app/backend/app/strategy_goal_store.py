"""DS-2 · StrategyGoal 持久化 + 从对话意图建真 goal_id（D-DELIVERY-SLICE · blocker #2）。

陌生人「对话生成策略」要真成立：`strategy_goal.create` 不再回显 args，而是把意图校验成
StrategyGoal（pydantic + cost_model 按 asset_class dispatch）→ 落库 → 产可下游引用的 **goal_id**
（被 DS-1 `backtest.run` 消费）。

两条入口（复用单一源，不另写解析）：
  · 结构化 args（LLM tool-call 给 asset_class/objective/...）→ 补 cost_model/evaluation_window 默认后校验。
  · 自然语言（description/text）→ `StrategyGoalSlotFiller` 补全（无 LLM 也能走通）。
§3 诚实：缺 asset_class 且无自然语言 → 返 needs_slots（不伪造空目标、不产假 id）。

goal_id 内容寻址（复用 lineage.ids.content_hash 单一身份源）→ 同目标同 id、幂等。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .agent.slot_filling import StrategyGoalSlotFiller
from .lineage.ids import content_hash
from .strategy_goal import StrategyGoal, _coerce_cost_model


def _goal_id(goal: StrategyGoal) -> str:
    return f"goal_{content_hash([goal.name, goal.asset_class, goal.objective, goal.horizon])[:10]}"


def _complete_goal_dict(args: dict[str, Any]) -> dict[str, Any]:
    """结构化 args 补 StrategyGoal 必填默认（cost_model/evaluation_window/name），让 chat 不必逐项给。

    cost_model={} → `_coerce_cost_model` 按 asset_class 建对应默认 CostModel 子类（全字段默认）。
    """
    out = dict(args)
    ac = out.get("asset_class")
    if not out.get("cost_model"):
        out["cost_model"] = {}  # _coerce_cost_model 据 asset_class dispatch 成默认 EquityCost/CryptoPerpCost/...
    if not out.get("evaluation_window"):
        out["evaluation_window"] = {"backtest_start": "2018-01-01", "backtest_end": "2025-12-31"}
    if not out.get("name"):
        out["name"] = f"{ac}_{out.get('horizon', 'daily')}"
    return out


class StrategyGoalStore:
    """StrategyGoal 落库（YAML round-trip 复用既有 save_yaml/from_yaml，不另造序列化）。"""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._filler = StrategyGoalSlotFiller()

    def _path(self, goal_id: str) -> Path:
        return self._root / f"{goal_id}.yaml"

    def create(self, goal: StrategyGoal) -> str:
        goal_id = _goal_id(goal)
        self._root.mkdir(parents=True, exist_ok=True)
        goal.save_yaml(self._path(goal_id))
        return goal_id

    def get(self, goal_id: str) -> StrategyGoal:
        p = self._path(goal_id)
        if not p.exists():
            raise FileNotFoundError(goal_id)
        return StrategyGoal.from_yaml(p)

    def list_ids(self) -> list[str]:
        if not self._root.exists():
            return []
        return sorted(p.stem for p in self._root.glob("*.yaml"))

    def create_from_args(self, args: dict[str, Any]) -> dict[str, Any]:
        """对话意图 → 真 goal_id（strategy_goal.create handler 的真体，替代旧回显 lambda）。"""

        if not isinstance(args, dict):
            return {"error": "strategy_goal.create 需要 dict 参数"}
        name = args.get("name")
        text = (
            args.get("description") or args.get("text") or args.get("goal")
            or args.get("query") or args.get("prompt") or ""
        )
        try:
            if args.get("asset_class"):
                goal = StrategyGoal.model_validate(_coerce_cost_model(_complete_goal_dict(args)))
            elif text:
                goal = self._filler.fill(str(text), name=name)
            else:
                return {
                    "error": "立目标需 asset_class（或自然语言描述 description）——缺槽位，先补全再 create",
                    "needs_slots": ["asset_class | description"],
                }
        except ValidationError as exc:
            return {
                "error": f"StrategyGoal 校验失败: {[e.get('msg') for e in exc.errors()[:3]]}",
                "needs_slots": sorted({str(e.get("loc", ["?"])[0]) for e in exc.errors()}),
            }
        goal_id = self.create(goal)
        return {
            "strategy_goal_id": goal_id,
            "name": goal.name,
            "asset_class": goal.asset_class,
            "objective": goal.objective,
            "horizon": goal.horizon,
            "benchmark": goal.benchmark,
            "note": "StrategyGoal 已校验落库（cost_model 按 asset_class dispatch）；goal_id 可被 backtest.run 消费。",
        }


__all__ = ["StrategyGoalStore"]
