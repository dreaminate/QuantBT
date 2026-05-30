"""模型卡加载器（markdown + frontmatter，仿 Glossary 体系）。

source of truth = `docs/model_cards/<key>.md`：
- YAML frontmatter：结构化字段（key/family/tasks/param_schema/pros/cons/...）
- 正文：## L1 定位 / ## L2 优缺点+适用 / ## L3 调参+数据要求 / ## L4 保存本体+评价图

catalog.py 从这里加载成 MODEL_CATALOG。模型是否"可训练(runnable)"由代码模板决定
（ML: training._make_model；DL: dl/architectures），与卡片解耦：卡片可收录尚无模板的模型。
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# docs/model_cards 相对仓库根（app/backend/app/models/card_loader.py → parents[4] = repo root）
DEFAULT_CARDS_DIR = Path(__file__).resolve().parents[4] / "docs" / "model_cards"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


class ModelCardError(Exception):
    """卡片 frontmatter / 结构错误。"""


@dataclass(frozen=True)
class ModelCard:
    key: str
    family: str  # ml / dl（标签，非执行开关）
    display_name: str
    tasks: tuple[str, ...]
    description: str
    pros: tuple[str, ...] = ()
    cons: tuple[str, ...] = ()
    tuning_tip: str = ""
    default_params: dict[str, Any] = field(default_factory=dict)
    param_schema: dict[str, dict[str, Any]] = field(default_factory=dict)
    needs_dl: bool = False
    tensorboard: bool = False
    requires_import: str | None = None
    runnable: bool = True  # 是否已有训练模板
    compute: str = "cpu"  # cpu / gpu
    persistence: str = ""  # 保存本体说明
    related: tuple[str, ...] = ()
    body: str = ""  # L1-L4 正文（详情页用）

    def is_available(self) -> bool:
        """所需后端库是否已安装。runnable=False 的卡片永远视作不可训练。"""
        if not self.runnable:
            return False
        if not self.requires_import:
            return True
        return importlib.util.find_spec(self.requires_import) is not None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tasks"] = list(self.tasks)
        d["pros"] = list(self.pros)
        d["cons"] = list(self.cons)
        d["related"] = list(self.related)
        d["available"] = self.is_available()
        d.pop("body", None)  # 列表视图不带长正文
        return d

    def to_detail(self) -> dict[str, Any]:
        d = self.to_dict()
        d["body"] = self.body
        return d


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ModelCardError("缺少 YAML frontmatter (--- ... ---)")
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ModelCardError(f"frontmatter YAML 解析失败: {exc}") from exc
    if not isinstance(fm, dict):
        raise ModelCardError("frontmatter 必须是 dict")
    return fm, m.group(2)


def parse_model_card(path: Path) -> ModelCard:
    fm, body = _split_frontmatter(path.read_text(encoding="utf-8"))
    required = {"key", "family", "display_name", "tasks", "description"}
    missing = required - fm.keys()
    if missing:
        raise ModelCardError(f"{path.name} frontmatter 缺字段: {sorted(missing)}")
    if fm["key"] != path.stem:
        raise ModelCardError(f"{path.name}: key={fm['key']!r} ≠ 文件名 {path.stem!r}")
    if fm["family"] not in ("ml", "dl"):
        raise ModelCardError(f"{path.name}: family 必须是 ml/dl")
    return ModelCard(
        key=fm["key"],
        family=fm["family"],
        display_name=fm["display_name"],
        tasks=tuple(fm["tasks"]),
        description=fm["description"],
        pros=tuple(fm.get("pros") or ()),
        cons=tuple(fm.get("cons") or ()),
        tuning_tip=fm.get("tuning_tip", ""),
        default_params=dict(fm.get("default_params") or {}),
        param_schema=dict(fm.get("param_schema") or {}),
        needs_dl=bool(fm.get("needs_dl", fm["family"] == "dl")),
        tensorboard=bool(fm.get("tensorboard", False)),
        requires_import=fm.get("requires_import"),
        runnable=bool(fm.get("runnable", True)),
        compute=fm.get("compute", "cpu"),
        persistence=fm.get("persistence", ""),
        related=tuple(fm.get("related") or ()),
        body=body.strip(),
    )


def load_model_cards_dir(directory: Path | None = None) -> dict[str, ModelCard]:
    """加载目录下所有非下划线 .md → {key: ModelCard}。目录缺失返回空 dict（不崩）。"""
    directory = directory or DEFAULT_CARDS_DIR
    out: dict[str, ModelCard] = {}
    if not directory.exists():
        return out
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("_"):
            continue
        card = parse_model_card(path)
        if card.key in out:
            raise ModelCardError(f"重复 key: {card.key}")
        out[card.key] = card
    return out


def render_card_md(fm: dict[str, Any], body: str = "") -> str:
    """frontmatter dict (+可选正文) → 卡片 markdown 文本。"""
    front = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False, width=100)
    if not body:
        pros = "\n".join(f"- {x}" for x in (fm.get("pros") or [])) or "- （待补）"
        cons = "\n".join(f"- {x}" for x in (fm.get("cons") or [])) or "- （待补）"
        runnable_line = "✅ 已实现训练模板。" if fm.get("runnable") else "🟡 卡片已收录；训练模板排队中（在 dl/architectures 或 _make_model 加实现即可跑）。"
        body = (
            f"## L1 · 定位\n{fm.get('description','')}\n\n"
            f"## L2 · 优缺点 & 适用\n**✅ 优点**\n{pros}\n\n**⚠️ 缺点**\n{cons}\n\n"
            f"## L3 · 调参 & 数据要求\n{fm.get('tuning_tip','（待补）')}\n\n"
            f"## L4 · 保存本体 & 评价\n**保存本体**：{fm.get('persistence','')}\n**可训练**：{runnable_line}\n"
        )
    return f"---\n{front}---\n\n{body}"


def write_model_card(info: dict[str, Any], *, directory: Path | None = None, overwrite: bool = False) -> Path:
    """把(agent 搜来的)模型信息落成一张新卡片 .md。

    新卡默认 runnable=False（仅收录文档；让它可训练需另加代码模板）。
    """
    directory = directory or DEFAULT_CARDS_DIR
    directory.mkdir(parents=True, exist_ok=True)
    key = str(info.get("key", "")).strip()
    if not key or not all(c.isalnum() or c == "_" for c in key):
        raise ModelCardError(f"key 必须是 snake_case 英文: {key!r}")
    for req in ("family", "display_name", "tasks", "description"):
        if not info.get(req):
            raise ModelCardError(f"缺字段: {req}")
    if info["family"] not in ("ml", "dl"):
        raise ModelCardError("family 必须是 ml/dl")
    path = directory / f"{key}.md"
    if path.exists() and not overwrite:
        raise ModelCardError(f"卡片已存在: {key}（overwrite=False）")
    fm = {
        "key": key,
        "family": info["family"],
        "display_name": info["display_name"],
        "tasks": list(info["tasks"]),
        "description": info["description"],
        "pros": list(info.get("pros") or []),
        "cons": list(info.get("cons") or []),
        "tuning_tip": info.get("tuning_tip", ""),
        "default_params": dict(info.get("default_params") or {}),
        "param_schema": dict(info.get("param_schema") or {}),
        "needs_dl": bool(info.get("needs_dl", info["family"] == "dl")),
        "tensorboard": bool(info.get("tensorboard", info["family"] == "dl")),
        "requires_import": info.get("requires_import"),
        "runnable": bool(info.get("runnable", False)),  # agent 新增默认仅收录
        "compute": info.get("compute", "gpu" if info["family"] == "dl" else "cpu"),
        "persistence": info.get("persistence", ""),
        "related": list(info.get("related") or []),
        "source": info.get("source", "agent_added"),
    }
    path.write_text(render_card_md(fm, info.get("body", "")), encoding="utf-8")
    return path


def validate_cards_dir(directory: Path | None = None) -> dict[str, Any]:
    directory = directory or DEFAULT_CARDS_DIR
    errors: list[str] = []
    cards: dict[str, ModelCard] = {}
    if not directory.exists():
        return {"ok": False, "count": 0, "errors": [f"目录不存在: {directory}"]}
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("_"):
            continue
        try:
            c = parse_model_card(path)
            cards[c.key] = c
        except ModelCardError as exc:
            errors.append(str(exc))
    # related 闭环
    for c in cards.values():
        for ref in c.related:
            if ref not in cards:
                errors.append(f"{c.key}.related → {ref} (不存在)")
    return {"ok": not errors, "count": len(cards), "errors": errors}


__all__ = [
    "DEFAULT_CARDS_DIR",
    "ModelCard",
    "ModelCardError",
    "load_model_cards_dir",
    "parse_model_card",
    "render_card_md",
    "validate_cards_dir",
    "write_model_card",
]
