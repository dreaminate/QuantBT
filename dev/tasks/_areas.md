<!-- 【项目级别】填:本项目的 area 词表。卡的 frontmatter.area 必须用这里注册过的 slug。
     为什么强约束:area 是 DEVMAP「按功能查」的分组轴——自由文本会长成一卡一域(实测 334 卡 143 个 slug),导航失效。
     slug 语法(validate_dev 强制):^[a-z0-9_-]+(/[a-z0-9_-]+)?$ (小写字母数字-_,至多一层 /)。
     新 area 先在此登记一行再用;validate 对未注册 slug 报 WARN、非法格式报 FAIL。宁可粗(个位数个域),别细。
     注:done 历史卡的 143 个旧 slug 不追溯;本表只管新卡,从粗颗粒重新开始。 -->
# AREAS · QuantBT 功能域词表

| slug | 含义 |
|---|---|
| eval-methodology | 评测方法学(CSCV/PBO/因子生命周期等研究评测口径) |
| research-os | 研究 OS(agent 编排/门/producer 链) |
| backtest | 回测引擎与数据 |
| execution | 执行/交易接入(binance 等) |
| platform | 前后端平台(app/backend + 前端台) |
| governance | 治理脊柱/lineage/审批闸 |
