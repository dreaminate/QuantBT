"""训练台 Agent 上下文 —— 约束 agent『只能在模型卡里做』。

注入给训练台对话 agent 的 system prompt：可用模型清单（来自 catalog/模型卡）+
训练库用法 + 硬约束。除非用户让 agent 搜新模型 → 走 add_model_card 加卡后再用。
"""

from __future__ import annotations

from ..models.catalog import list_model_cards

_LIB_DOC = """## 训练库（生成的代码可 import app.training.lib）
- emit(payload)：训练脚本最后一行回吐结果（必须）
- pick_device()：自动选 cuda→mps→cpu
- predict_with(artifact_path, panel, feature_cols)：把已训练模型的输出当新训练的输入特征（模型组合）
- ML 模型走 app.models.training.train_model(ModelSpec(...))；DL 走 app.models.dl.train_dl(arch=...)"""

_CONSTRAINT = """## 硬约束（必须遵守）
1. 你**只能从下面"可用模型"里选**来写训练代码；不得编造目录外的模型。
2. 任意 ML/DL 可自由组合、任意数量；已训练模型的输出可经 predict_with 当作新模型输入。
3. 若用户要一个目录里没有的新模型：先综合用户给的信息，调用 add_model_card 把它**加入模型卡**
   （补全 family/tasks/优缺点/调参/超参 schema），加卡后才能使用。不要绕过卡片直接乱写。"""


def model_choices_block() -> str:
    """可用模型清单（按 ml/dl 分组，标注是否已可训练）。"""
    lines: list[str] = []
    for fam, label in (("ml", "ML（表格/截面）"), ("dl", "DL（时序，需 torch+GPU）")):
        lines.append(f"### {label}")
        for c in list_model_cards(family=fam):  # type: ignore[arg-type]
            flag = "可训练" if c.is_available() else "仅收录(模板排队)"
            tasks = "/".join(c.tasks)
            lines.append(f"- {c.key}（{c.display_name}）· {tasks} · {flag} · {c.description[:40]}")
    return "## 可用模型（只能在这里面选）\n" + "\n".join(lines)


def training_system_prompt(field_universe_block: str = "") -> str:
    parts = [
        "你是 QuantBT 训练台的助手。用户用自然语言描述要训什么，你生成可运行的训练脚本。",
        model_choices_block(),
        _LIB_DOC,
    ]
    if field_universe_block:
        parts.append(field_universe_block)
    parts.append(_CONSTRAINT)
    return "\n\n".join(parts)


__all__ = ["model_choices_block", "training_system_prompt"]
