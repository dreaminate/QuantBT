"""M6+ · 模型目录（训练台单一事实源）。

**source of truth = `docs/model_cards/*.md`**（markdown + frontmatter，仿 Glossary，
可手工/GPT-Pro 续填）。本模块从 card_loader 加载成 MODEL_CATALOG，并提供查询 API。

- Agent 的 ai_context 注入它 → LLM 只能在这些卡片里选模型；
- 前端训练台据它渲染模型下拉 + 超参表单 + 卡片(优缺点/调参)；
- 训练台执行层据它校验 spec.model + 是否需要 DL 栈 + 是否 runnable。

模型是否"可训练(runnable)"由代码模板决定（ML: training._make_model；DL:
dl/architectures），与卡片解耦：卡片可收录尚无模板的模型（runnable: false）。
"""

from __future__ import annotations

from typing import Any, Literal

from .card_loader import (
    DEFAULT_CARDS_DIR,
    ModelCard,
    load_model_cards_dir,
    validate_cards_dir,
    write_model_card,
)

ModelFamily = Literal["ml", "dl"]
CatalogTask = Literal["classification", "regression", "lambdarank", "forecasting"]

# 从 markdown 卡片加载（进程启动一次）
MODEL_CATALOG: dict[str, ModelCard] = load_model_cards_dir(DEFAULT_CARDS_DIR)


def reload_catalog() -> dict[str, ModelCard]:
    """重新从磁盘加载卡片（新增/编辑卡片后调用，如 agent 加入新模型卡）。

    **原地 clear()+update()** 而非 rebind：models/__init__.py 等做了
    `from .catalog import MODEL_CATALOG` 持有同一 dict 对象的引用；rebind 会让那些
    再导出名指向旧 dict（看不到新卡）。原地更新让所有持有者立即一致。
    """
    fresh = load_model_cards_dir(DEFAULT_CARDS_DIR)
    MODEL_CATALOG.clear()
    MODEL_CATALOG.update(fresh)
    return MODEL_CATALOG


def get_model_card(key: str) -> ModelCard:
    if key not in MODEL_CATALOG:
        raise KeyError(f"未知模型 key: {key}（可用: {sorted(MODEL_CATALOG)}）")
    return MODEL_CATALOG[key]


def list_model_cards(
    *,
    family: ModelFamily | None = None,
    task: str | None = None,
    available_only: bool = False,
) -> list[ModelCard]:
    out = list(MODEL_CATALOG.values())
    if family is not None:
        out = [c for c in out if c.family == family]
    if task is not None:
        out = [c for c in out if task in c.tasks]
    if available_only:
        out = [c for c in out if c.is_available()]
    return out


def model_catalog_summary(**kwargs: Any) -> list[dict[str, Any]]:
    """供 REST / Agent ai_context 的 JSON 友好视图（不含长正文）。"""
    return [c.to_dict() for c in list_model_cards(**kwargs)]


def is_dl_model(key: str) -> bool:
    return get_model_card(key).family == "dl"


def add_model_card(info: dict[str, Any]) -> ModelCard:
    """Agent/用户搜到新模型 → 补全信息后落一张新卡片并热加载入目录。

    新卡默认 runnable=False（仅收录文档；要可训练需另加代码模板）。这是
    『agent 只能在卡内做，除非用户让它搜新模型加卡』的落点。
    """
    write_model_card(info)
    reload_catalog()
    return get_model_card(info["key"])


def runnable_models() -> list[str]:
    """当前真正可训练的模型 key（卡片 runnable=True 且依赖已装）。"""
    return [c.key for c in MODEL_CATALOG.values() if c.is_available()]


__all__ = [
    "CatalogTask",
    "MODEL_CATALOG",
    "ModelCard",
    "ModelFamily",
    "add_model_card",
    "get_model_card",
    "is_dl_model",
    "list_model_cards",
    "model_catalog_summary",
    "reload_catalog",
    "runnable_models",
    "validate_cards_dir",
]
