# 研究台 · active（在研线程）

<!-- 【开发os级别】勿改 · clone 自 Multi-Dev-Os。具体线程用 _TEMPLATE.md 造。 -->

> 正在深挖的研究主题,**一线程一目录**(per-dev)。镜像 `../../tasks/{developer_id}/`——研究也有「在做」态。

## 结构
```
active/{developer_id}/<topic-slug>/
  ├ NOTES.md      工作日志（滚动，最新在上）
  └ （数据 / 草图 / 引用随手放）
```

## 生命周期
来自 `../ideas/` 的想法 → 这里深挖(读论文、做小实验、画架构) → 蒸馏成 build-ready 设计落 `../findings/{developer_id}/` → mint uuid 入 `../../tasks/pool/`。

## 纪律
- **不挡**:在研期 informal,不要求严格验收。
- 蒸馏出 finding、立成任务时才进 Goal Loop 对抗测试门。
- 线程蒸馏完 → 把产出落 `../findings/`,本目录可归档或删。
- 模板见 `_TEMPLATE.md`。
