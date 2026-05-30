# v3 · 模型卡体系 · 决策总结

> 目标（用户原话）：因为我们"本质是跑代码"的结构，ML/DL 想写哪个写哪个 —— 直接把主流量化
> ML/DL 模型的**模型卡**写出来（优点/缺点/怎么调参/训练好后保存 model 本体一整套）；**Agent 只能
> 在这些模型卡里做**，除非用户让 Agent 搜新模型，则 Agent 综合用户信息拿到新 model、补全信息后
> **加入模型卡**。有问题自行决策。

本文件 = 我代你做的决策记录。全部任务做完、全量测试 **761 passed / 13 skipped** 通过（含后续"做完"goal 的 4 DL 模板 + 评价图 + TensorBoard + 训练→回测桥 + OOS 严格无泄露）。

---

## 1. 关键决策

| # | 决策 | 理由 |
|---|---|---|
| D1 | **卡片 = markdown + frontmatter**，放 `docs/model_cards/<key>.md`，仿 Glossary | 你选的方案 2；内容可手工/GPT-Pro 续填，与教学层一致 |
| D2 | **catalog 从 md 加载**（`models/card_loader.py` → `models/catalog.py`），不再硬编码 | md 即 single source of truth；改卡=改 md，热加载 `reload_catalog()` |
| D3 | **两层卡片**：①模型类型卡（算法说明书，静态）②已训练模型护照（M12 ModelRegistry，每次训练一张） | 你说的"每个模型有卡片"+"训练好保存 model 本体"是两件事 |
| D4 | **runnable 与卡片解耦**：卡片可收录尚无训练模板的模型（`runnable: false`） | 让你"想写哪个写哪个"——先收录文档，模板可后补 |
| D5 | **DL 用通用训练 harness + 架构注册**：加一个 DL 模型 = 加一个 `nn.Module` | 避免每个模型一套模板；`dl/trainer.py` + `dl/architectures.py` |
| D6 | **Agent 约束**：`training/agent_context.py` 注入"只能在卡内选"+ 新模型走 `add_model_card` | 落实"agent 只能在卡里做，除非搜新模型加卡" |
| D7 | **新模型默认 runnable=false**：agent 加卡=补全文档；要可训练需另加代码模板 | 不让 agent 自动生成不可信的训练实现；卡片先行、安全 |

---

## 2. 已写的模型卡（19 张，`docs/model_cards/`）

**ML（9，全部可训练）**：`lgbm` `xgboost` `catboost` `sklearn_rf` `extra_trees` `sklearn_logreg` `ridge` `lasso` `elastic_net`

**DL（10，全部可训练）**：`lstm` `gru` `alstm` `mlp` `tcn` `transformer` `tft` `nbeats` `nhits` `deepar`
（"做完"goal 已补齐 tft/nbeats/nhits/deepar 的纯 torch 模板，全部 `runnable:true`）

每张卡含 frontmatter（key/family/tasks/param_schema/pros/cons/tuning_tip/persistence/...）+ 正文
**L1 定位 / L2 优缺点+适用 / L3 调参表+数据要求 / L4 保存本体+评价图**。

> 这些卡片由 `scripts/gen_model_cards.py` 一次性 bootstrap（集中数据→渲染 md）；之后 md 即源，
> 可直接编辑或让 GPT-Pro 按统一格式续填 4 张排队模型的训练模板细节。

## 3. "保存 model 本体"体系

- ML → `model.pkl`（pickle/joblib），reload→`.predict`；护照记库版本防跨版本失败。
- DL → `model.pt`（state_dict + arch config），reload 按 config 重建网络再 load。
- 每次训练落 `data/training_runs/<job_id>/`（spec.json/result.json/model.*）+ 登记 M12（Run+ModelVersion，含血缘）。
- 组合：`predict_with(artifact, panel, feature_cols)` 把已训练模型输出当新训练输入（任意 ML/DL、任意数量）。

## 4. 新模型加卡流程（agent 搜新模型）

```
用户："去搜一个 TabNet 加进来"
 → agent 综合资料 → POST /api/training/models 或 catalog.add_model_card({key,family,tasks,描述,优缺点,调参,param_schema})
 → 写 docs/model_cards/tabnet.md（runnable:false）→ reload_catalog() → 训练台/agent 立即可见
 → 要可训练：在 dl/architectures.py 加一个 nn.Module（DL）或 _make_model 加分支（ML），改 runnable:true
```

## 5. 新增/改动文件

- `app/backend/app/models/card_loader.py`（卡片 loader + 校验 + 写卡）
- `app/backend/app/models/catalog.py`（改为 md 加载 + add_model_card/reload/runnable_models）
- `app/backend/app/models/training.py`（_make_model 加 catboost/extra_trees/ridge/lasso/elastic_net）
- `app/backend/app/models/dl/{trainer,architectures}.py`（通用 harness + 6 架构；删旧 lstm_template）
- `app/backend/app/training/{codegen,agent_context}.py`（DL 走 train_dl(arch=) + agent 约束）
- `docs/model_cards/*.md`（19 张）、`scripts/gen_model_cards.py`
- REST：`/api/training/models`（GET 列表 / POST 加卡）、`/api/training/models/{key}`（详情）、`/api/training/agent_context`
- 测试：`test_model_cards.py`（+16）、`test_model_catalog.py`、`test_training_*`

## 6. 留待（非阻塞）

- 4 张排队 DL（tft/nbeats/nhits/deepar）的 torch 训练模板（卡片已就位，加架构即可跑）。
- 前端：训练台右栏接"对话 agent"面板（约束上下文已就绪，差 UI 接线）。
- 模型护照 UI（模型库页已列版本/血缘，可再补 feature_cols/库版本展示）。
