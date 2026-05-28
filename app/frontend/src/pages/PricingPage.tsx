import { Link } from "react-router-dom";

/**
 * v0.9.0 · /pricing 三档订阅 (patch2 §A.c 价格锚定)
 *
 * Community ¥0 / Learn ¥49 / Live Pro ¥149。
 * 按"信任阶梯 L0-L7"映射。不收费时点暂用 waitlist 形式（v0.9.x 后真上 stripe）。
 */

interface Tier {
  id: string;
  name: string;
  price_cny_monthly: number;
  price_cny_annual: number | null;
  tagline: string;
  features: string[];
  anchor: string;
  level: "L0-L1" | "L2-L4" | "L5-L7";
  cta_label: string;
  cta_href: string;
}

const TIERS: Tier[] = [
  {
    id: "community",
    name: "Community",
    price_cny_monthly: 0,
    price_cny_annual: null,
    tagline: "入门免费，先证明流程跑通",
    features: [
      "A股 demo 数据 (4 个 ETF 252 日)",
      "加密 sample 数据 (BTC/ETH 永续 365 日)",
      "每日 5 次回测",
      "Glossary 30 条 L1/L2 解释",
      "RunDetail 基础指标 + 风险卡",
      "社区只读 + 浏览复现实验库",
      "不能 Binance live",
    ],
    anchor: "对标 QuantConnect Free / 聚宽免费学习入口",
    level: "L0-L1",
    cta_label: "立即注册",
    cta_href: "/register",
  },
  {
    id: "learn",
    name: "Learn",
    price_cny_monthly: 49,
    price_cny_annual: 499,
    tagline: "学习者主档：把策略跑明白",
    features: [
      "Community 全部",
      "A股 paper trading",
      "加密 paper trading",
      "Glossary 30+ 全 L1-L4 + 独立专页",
      "RunDetail ⓘ 字段 + Coach 主动建议",
      "Mode 2 教练每日 20 次",
      "导出 run JSON/CSV + 数据所有权",
      "策略模板 fork + 复现实验提交",
    ],
    anchor: "年付是 BigQuant 标准版 ¥1099 的 45%；月付是 BigQuant 月折算 53%",
    level: "L2-L4",
    cta_label: "Learn 7 天试用",
    cta_href: "/register?plan=learn",
  },
  {
    id: "live_pro",
    name: "Live Pro",
    price_cny_monthly: 149,
    price_cny_annual: 1499,
    tagline: "实盘档：通过 SafeKey 才能用真钱",
    features: [
      "Learn 全部",
      "Binance testnet 全 12 cell order matrix",
      "SafeKey wizard 强制 no-withdraw + IP 白名单",
      "Fernet AES keyring 加密落盘",
      "Mainnet 二次确认 + 5 级 live ladder",
      "Kill switch + 异常断连保护",
      "IDE 高级 AI 辅助 + 真 LLM 月 100 次",
      "私域 copy-trade follower beta (waitlist)",
    ],
    anchor: "年付是 BigQuant 旗舰 ¥5499 的 27%；月付是聚宽 SVIP ¥378 的 39%",
    level: "L5-L7",
    cta_label: "申请 Live Pro waitlist",
    cta_href: "/register?plan=live_pro",
  },
];

export function PricingPage() {
  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{"// 价格"}</h1>
          <div className="cc-soft">
            QuantBT 不是收益机器。三档订阅，每档对应一段"信任阶梯"。先跑通流程，再看你能不能证明策略有效。
          </div>
        </div>
      </div>

      <div className="cc-grid" style={{ marginTop: 24 }}>
        {TIERS.map((t) => (
          <div
            key={t.id}
            className="cc-card"
            style={{
              padding: 24,
              display: "flex",
              flexDirection: "column",
              minHeight: 540,
              border: t.id === "learn" ? "2px solid var(--cc-accent, #4a9eff)" : undefined,
              position: "relative",
            }}
          >
            {t.id === "learn" && (
              <div
                style={{
                  position: "absolute",
                  top: -10,
                  left: 16,
                  background: "var(--cc-accent, #4a9eff)",
                  color: "#fff",
                  fontSize: 10,
                  padding: "2px 8px",
                  borderRadius: 10,
                }}
              >
                推荐 P0 用户
              </div>
            )}
            <div className="cc-card-title" style={{ fontSize: 20, marginBottom: 4 }}>{t.name}</div>
            <div className="cc-soft" style={{ fontSize: 13, marginBottom: 12 }}>{t.tagline}</div>

            <div style={{ marginBottom: 16 }}>
              <span style={{ fontSize: 32, fontWeight: 600 }}>
                {t.price_cny_monthly === 0 ? "¥0" : `¥${t.price_cny_monthly}`}
              </span>
              <span className="cc-dim" style={{ fontSize: 12 }}>/月</span>
              {t.price_cny_annual && (
                <span className="cc-soft" style={{ fontSize: 11, marginLeft: 8 }}>
                  · 年付 ¥{t.price_cny_annual} (省 {Math.round((1 - t.price_cny_annual / (t.price_cny_monthly * 12)) * 100)}%)
                </span>
              )}
            </div>

            <ul style={{ paddingLeft: 18, margin: 0, fontSize: 13, flex: 1 }}>
              {t.features.map((f) => (
                <li key={f} style={{ marginBottom: 6 }}>{f}</li>
              ))}
            </ul>

            <div style={{ marginTop: 16 }}>
              <div className="cc-dim" style={{ fontSize: 11, marginBottom: 4 }}>价格锚点</div>
              <div className="cc-soft" style={{ fontSize: 11, marginBottom: 12 }}>{t.anchor}</div>
              <Link to={t.cta_href} className="cc-btn cc-btn--accent" style={{ display: "block", textAlign: "center" }}>
                {t.cta_label}
              </Link>
              <div className="cc-dim" style={{ fontSize: 10, marginTop: 6, textAlign: "center" }}>
                信任阶梯 {t.level}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="cc-card" style={{ marginTop: 24, padding: 16 }}>
        <div className="cc-section-title">不上 Live Pro 我能做什么？</div>
        <div className="cc-soft" style={{ fontSize: 13 }}>
          Community 和 Learn 已经覆盖完整研究流程：拉数据 → 写因子 → 跑回测 → 看 PBO/DSR/MaxDD →
          Mode 2 教练复盘 → 改一个变量 → 重新跑 → 社区分享。Live Pro 只是把这个研究流程的产出，
          通过 SafeKey + testnet + live ladder 安全地接到 Binance 小资金实盘。<strong>
            没过 SafeKey 不给 mainnet，这是产品原则不是付费墙。</strong>
        </div>
      </div>

      <div className="cc-card" style={{ marginTop: 12, padding: 16 }}>
        <div className="cc-section-title">为什么不做带单 GMV 抽佣？</div>
        <div className="cc-soft" style={{ fontSize: 13 }}>
          带单收益分成法律和信任成本高（patch2 §A.f 风险表）：跨境交易、follower 亏损纠纷、
          投顾/代客资格。v0.9.x 阶段先把工具卖好。Copy-trade 仅作为
          <strong> follower self-keystore 工具</strong>开放灰度 beta（5 master / 50 follower），
          不做公开排行榜，不承诺收益。
        </div>
      </div>
    </>
  );
}

export default PricingPage;
