/**
 * 终点交接卡（agentDeck.md handoff block / D-PERM §⑤）。
 *
 * 治理红线：文案止于「提交进模拟台候选池」——进场与否、监控由模拟台决定。
 * 绝不把跳级真钱场景作默认导向（D-PERM L176 / R8 不跳级）；这是策略台的终点。
 * （静态守卫扫本文件禁出现跳级真钱直推措辞——故注释也避开那些字面词。）
 */

export interface HandoffCardProps {
  /** 待提交（显示按钮）/ 已提交（显示回执）。 */
  submitted: boolean;
  onSubmit: () => void;
}

export function HandoffCard({ submitted, onSubmit }: HandoffCardProps) {
  return (
    <div data-handoff-card style={{ margin: "13px 0 13px 18px" }}>
      <div
        style={{
          border: "1px solid var(--desk-success)",
          background: "color-mix(in srgb, var(--desk-success) 8%, transparent)",
          borderRadius: "var(--desk-radius-lg)",
          padding: "12px 14px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            color: "var(--desk-success)",
            fontWeight: 600,
            marginBottom: 6,
          }}
        >
          <span aria-hidden>⇲</span>策略台终点 · 候选策略已就绪
        </div>
        <div
          style={{
            color: "var(--desk-text-soft)",
            fontSize: 12.5,
            marginBottom: 11,
            lineHeight: 1.6,
          }}
        >
          strat_wk_cn_01 已回测 + 体检通过。策略台到此为止——是否提交到
          <span style={{ color: "var(--desk-text)" }}>模拟台</span>
          候选池？（进场与否、监控由模拟台决定）
        </div>
        {submitted ? (
          <div style={{ color: "var(--desk-success)", fontSize: 12.5 }}>
            ✓ 已提交。strat_wk_cn_01 进入模拟台候选池，等你在模拟台选择进场。
          </div>
        ) : (
          <button
            data-handoff-submit
            onClick={onSubmit}
            style={{
              fontFamily: "inherit",
              fontWeight: 700,
              fontSize: 12.5,
              padding: "9px 15px",
              borderRadius: "var(--desk-radius)",
              border: "1px solid var(--desk-success)",
              background: "transparent",
              color: "var(--desk-success)",
              cursor: "pointer",
            }}
          >
            ⇲ 提交进模拟台候选
          </button>
        )}
      </div>
    </div>
  );
}
