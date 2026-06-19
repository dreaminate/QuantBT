# 研究台 · ideas（创新 / 在研入口）

<!-- 【开发os级别】勿改 · clone 自 Multi-Dev-Os。具体 idea 文件用 _TEMPLATE.md 造。 -->

> 论文研读、原创架构设计、RFC、猜想——**还没成熟到能录成任务**的东西先落这里。
> 研究归研究:这里**不挡、不要求严格验收**(还在想,没立任务)。

## 放什么
- **论文研读笔记**(一篇 / 一主题一个 `.md`)
- **原创架构设计 / RFC**(提案,未拍板)
- **猜想 / 反思**(对既有设计的质疑、待验证的点子)

## 生命周期
```
ideas/{developer_id}/（灵感·RFC·论文笔记）
   ↓ 值得深挖
research/active/{developer_id}/<topic>/（在研线程，带工作日志）
   ↓ 蒸馏成熟、build-ready
research/findings/{developer_id}/（可落地设计 + 对抗测试要点；提取到池时看所有人 findings）
   ↓ mint uuid 入池、leader/admin 分配
tasks/pool/{uuid8}/ → Goal Loop 对抗测试门
```

## 纪律
- 这里**不挡**:informal 阶段不要求验收。**立成任务(开始建)才进 Goal Loop 的对抗测试门**。
- 想法升级为在研线程 → 移/拷到 `../active/{developer_id}/<topic>/`。
- 模板见 `_TEMPLATE.md`。
