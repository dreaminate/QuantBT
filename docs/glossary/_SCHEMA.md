# Glossary 词条 schema (v0.8.4)

每条概念是 `docs/glossary/<term>.md`，文件名 = term slug（snake_case，英文）。

## YAML frontmatter（必填字段）

```yaml
---
term: sharpe_ratio                  # 文件名 slug，唯一 ID
display: "夏普比率 (Sharpe Ratio)"   # UI 显示用，中英混排
aliases:                            # 用户/LLM 可能用的别名（搜索时命中）
  - sharpe
  - sharpe ratio
  - 夏普
  - 夏普比
level: beginner                     # beginner | intermediate | advanced
category: metric                    # metric | factor | model | risk | execution | data | portfolio
formula_latex: "SR = \\frac{E[R_p - R_f]}{\\sigma_p} \\cdot \\sqrt{T}"   # KaTeX 可渲染
unit: "无量纲（年化）"               # 自然语言单位
typical_range: [-2, 4]              # 业界常见数值范围（用于 RunDetail 给数字配色）
sources:                            # 必填至少 1 条；学术/业界出处
  - "Sharpe (1966) Mutual Fund Performance, J. of Business"
related:                            # 关联其他 term slug（用于"延伸阅读"）
  - sortino_ratio
  - information_ratio
  - deflated_sharpe
---
```

## 正文（必填四段）

正文必须**严格按下面四段**输出（标题用 `## L1` `## L2` `## L3` `## L4`），让前端能定位到对应层级渲染：

```markdown
## L1 一句话
（5-15 字，hover tooltip 用。不要公式不要例子。）

## L2 公式与例子
（KaTeX 公式 + 一个 3-5 行算例。让用户一眼能算。）

## L3 业界阈值与误区
（带数字的判断标准 + 至少 2 条 "常见误区/陷阱"。这是防破产层。）

## L4 延伸阅读
（链接 related term，简述与本条的区别。可附学术文献完整引用。）
```

## 风格约束

1. **中文为主**（用户中文用户），英文术语首次出现给括注。
2. **不许营销话术**：禁说 "强大 / 超棒 / 业界领先"。
3. **数字要给来源**：写 "Sharpe > 2 警惕" 必须带 "(Lopez de Prado, 2018)" 等出处。
4. **不许 emoji**。
5. **L3 至少 2 条误区**，因为这是 mode 2 的灵魂。
6. **不许编 API**：禁止写 "调用 quantbt.sharpe_ratio()"，那是代码层不归词条管。

## 文件命名

- 文件名小写 snake_case，英文：`sharpe_ratio.md`、`purged_kfold.md`
- 不许用中文名做文件名（slug 要 URL-safe）

## 校验

加入仓库前，前端会跑 `scripts/check_glossary.py`（v0.8.4 一起出）校验 frontmatter 必填字段、four-section 完整性、related 是否都指向存在的 term。
