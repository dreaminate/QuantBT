# 喂给 GPT Pro 的提示词（QuantBT Mode 2 词条生成）

把下面整段 prompt 一次性贴到 GPT Pro，让它一次出 5 条；分 6 批生成全 30 条。每批末尾让它**给出可直接保存为 .md 文件**的纯文本。

---

## 提示词正文（贴这整段）

你是 QuantBT 项目的量化术语词条作者。我要构建一个浏览器内置量化教学知识库，给业余~半专业的中文量化爱好者用，每个概念是一个 markdown 文件。本回合请生成 **{BATCH_LIST}** 这 N 条词条（见末尾批次列表）。

### 硬规则（违反任何一条都重来）

1. **每条严格四段**：`## L1 一句话` / `## L2 公式与例子` / `## L3 业界阈值与误区` / `## L4 延伸阅读`。标题原文照搬，**不要改写**。
2. **L1 限 5-15 个中文字**，hover tooltip 用。不许带公式、不许带例子、不许带括号注解。
3. **L2 必须含 KaTeX 公式**（`$$ ... $$`）+ **一个 3-5 行算例**（具体数字代入算出结果）。
4. **L3 必须含**：(a) 阈值参考表格（区间→解读），(b) **至少 3 条**带学术/业界出处的"常见误区"。每条误区单独编号。
5. **L4 必须**：用 `[[other_term_slug]]` 链接 frontmatter `related` 字段里列的所有词条；每个 wiki link 后跟一句话说"和本条的区别在哪"。最后附文献 APA 引用列表。
6. **风格**：
   - 中文为主，英文术语首次出现给括注（如 "夏普比率 (Sharpe Ratio)"）。
   - **不许**任何 emoji。
   - **不许**营销话术（强大/超棒/业界领先/划时代 等都不准）。
   - **不许**编 API（禁止写 "调用 xx.func()"）。
   - 写"SR > 2 警惕过拟合"这种判断必须带文献出处（如 "Lopez de Prado 2018"）。
   - 数字阈值不许凭感觉，必须能追溯到论文/业内共识。
7. **frontmatter** 完全按下面 schema：

```yaml
---
term: <文件名 slug，snake_case 英文，必须与文件名一致>
display: "<中英混排显示名>"
aliases:
  - <用户可能用的别名 1>
  - <用户可能用的别名 2>
  - <中文别名>
level: <beginner | intermediate | advanced>
category: <metric | factor | model | risk | execution | data | portfolio>
formula_latex: "<KaTeX 公式，反斜杠用双反斜杠 \\\\>"
unit: "<自然语言单位，如 '无量纲（年化）' '百分比' '次/年'>"
typical_range: [<下界>, <上界>]    # 业界常见数值范围，无意义则写 null
sources:
  - "<APA 引用 1>"
  - "<APA 引用 2>"
related:
  - <其它 term slug 1>
  - <其它 term slug 2>
---
```

### 输出格式

每条词条用以下分隔包起，方便我脚本提取存为 .md：

```
<<<FILE: <term_slug>.md>>>
---
term: ...
（完整 frontmatter）
---

## L1 一句话
...

## L2 公式与例子
...

## L3 业界阈值与误区
...

## L4 延伸阅读
...
<<<END>>>
```

### 本批要生成的词条（替换 {BATCH_LIST} 为下面对应批次的列表）

**批次 1（核心绩效指标 · 5 条）**:
- `sharpe_ratio` 夏普比率
- `sortino_ratio` 索提诺比率
- `information_ratio` 信息比率
- `max_drawdown` 最大回撤
- `calmar_ratio` 卡玛比率

**批次 2（风险与稳健性 · 5 条）**:
- `volatility` 波动率（年化）
- `alpha` Jensen Alpha
- `beta` 市场 Beta
- `var_cvar` VaR / CVaR
- `tail_risk` 尾部风险

**批次 3（过拟合证伪 · 5 条）**:
- `pbo` 回测过拟合概率 (CSCV)
- `deflated_sharpe` 折减夏普比 (DSR)
- `bootstrap_sharpe_ci` 自助法夏普置信区间
- `purged_kfold` 净化交叉验证
- `embargo` 禁运期 (Embargo)

**批次 4（因子与信号 · 5 条）**:
- `ic` 信息系数 (IC)
- `rank_ic` Rank IC
- `ic_ir` IC 信息率
- `alpha101_concept` WorldQuant Alpha101 体系
- `triple_barrier` 三重障碍标签

**批次 5（组合优化 · 5 条）**:
- `mean_variance` Markowitz 均值方差
- `hrp` 层次风险平价 (HRP)
- `risk_parity` 风险平价
- `kelly_fraction` Kelly 仓位
- `brinson_attribution` Brinson 归因

**批次 6（数据陷阱与执行 · 5 条）**:
- `survivorship_bias` 幸存者偏差
- `look_ahead_bias` 前视偏差
- `slippage` 滑点
- `funding_rate` 资金费率（永续）
- `walk_forward` 滚动样本外测试

---

### 参考样例（已有的 sharpe_ratio.md，你输出格式要完全对齐它）

```
（这里把 docs/glossary/sharpe_ratio.md 完整复制粘贴，让 GPT Pro 看到 ground truth 风格）
```

---

## 我（用户）的使用流程

1. 复制本文件全部内容到 GPT Pro 对话框
2. 把"批次 1"这行替换成你这次要生成的批次（一次只让它做 5 条避免上下文爆）
3. 把"参考样例"那段贴上 [sharpe_ratio.md](sharpe_ratio.md) 全文
4. 让 GPT Pro 出 5 个 `<<<FILE: ...>>>` 块
5. 我把每个 `<<<FILE: xxx.md>>>` 块的内容存为 `docs/glossary/xxx.md`
6. v0.8.4 后端会跑 `scripts/check_glossary.py` 校验 frontmatter + L1/L2/L3/L4 + related 闭环
7. 校验过了 → 提交 → 可以接入 `/api/glossary` endpoint

### 我（Claude）需要等的

等 30 个 .md 文件全到位（或一部分），就可以开 v0.8.4：
- `glossary/loader.py` 加载 + 校验
- `/api/glossary` `/api/glossary/{term}` REST endpoint
- 然后 v0.8.5 把 ⓘ 按钮挂到 RunDetail metrics 卡片 + IDE result_keys chip
