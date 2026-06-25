import { useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import { authFetch, getStoredUser } from "../lib/auth";

/**
 * v0.9.0 · /pricing 三档订阅 (patch2 §A.c 价格锚定)
 * v1.0.5 · 接入 /api/billing/me + /upgrade_request (Stripe scaffold)
 *
 * Community ¥0 / Learn ¥49 / Live Pro ¥149。
 */

interface MySubscription {
  user_id: string;
  plan: string;
  billing_cycle: string;
  status: string;
  current_period_end_utc: string | null;
}

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
      "RunDetail ⓘ 字段 + 诊断建议",
      "诊断台每日 20 次",
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
      "IDE 代码生成 · 真实模型调用，每月 100 次",
      "私域 copy-trade follower beta (waitlist)",
    ],
    anchor: "年付是 BigQuant 旗舰 ¥5499 的 27%；月付是聚宽 SVIP ¥378 的 39%",
    level: "L5-L7",
    cta_label: "申请 Live Pro waitlist",
    cta_href: "/register?plan=live_pro",
  },
];

export function PricingPage() {
  const navigate = useNavigate();
  const user = getStoredUser();
  const [sub, setSub] = useState<MySubscription | null>(null);
  const [annual, setAnnual] = useState(false);
  const [requesting, setRequesting] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    authFetch("/api/billing/me")
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => j && setSub(j))
      .catch(() => {});
  }, [user?.user_id]);

  async function handleUpgrade(planId: string) {
    if (!user) {
      navigate(`/login?next=/pricing`);
      return;
    }
    setRequesting(planId);
    try {
      const r = await authFetch("/api/billing/upgrade_request", {
        method: "POST",
        body: JSON.stringify({
          plan: planId,
          billing_cycle: annual ? "annual" : "monthly",
        }),
      });
      const j = await r.json();
      if (!r.ok) {
        alert(`升级失败: ${j.detail || r.status}`);
        return;
      }
      if (j.status === "downgraded") {
        alert("已切回 Community 免费档");
        setSub({ ...(sub || ({} as MySubscription)), plan: "community", status: "active" } as MySubscription);
        return;
      }
      if (j.checkout_url) {
        // scaffold: 真 Stripe 时此处 window.location = j.checkout_url
        const proceed = confirm(
          `进入 Stripe 结账? (scaffold 阶段不会真扣款)\n\nplan=${j.plan}\ncycle=${j.billing_cycle}\ncheckout_url=${j.checkout_url}`,
        );
        if (proceed) {
          window.location.href = j.checkout_url;
        }
      }
    } finally {
      setRequesting(null);
    }
  }

  return (
    <>
      <div className="cc-page-header">
        <div>
          <h1 className="cc-page-title">{"// 价格"}</h1>
          <div className="cc-soft">
            QuantBT 不是收益机器。三档订阅对应不同的研究、验证和运行权限。先跑通流程，再看证据是否支持策略进入下一步。
          </div>
          {sub && (
            <div style={{ marginTop: 8, fontSize: 13 }}>
              当前订阅: <b>{sub.plan}</b>{" "}
              <span className="cc-chip cc-chip--ok" style={{ marginLeft: 4 }}>
                {sub.status}
              </span>
              {sub.current_period_end_utc && (
                <span className="cc-soft" style={{ marginLeft: 8 }}>
                  下次续费 {sub.current_period_end_utc.slice(0, 10)}
                </span>
              )}
            </div>
          )}
          <label className="cc-row" style={{ gap: 6, marginTop: 8, fontSize: 13 }}>
            <input type="checkbox" checked={annual} onChange={(e) => setAnnual(e.target.checked)} />
            <span>按年付费 (省 15%)</span>
          </label>
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
              {sub?.plan === t.id ? (
                <button
                  type="button"
                  className="cc-btn cc-btn--ghost"
                  disabled
                  style={{ display: "block", width: "100%", textAlign: "center" }}
                >
                  ✓ 当前订阅
                </button>
              ) : (
                <button
                  type="button"
                  className="cc-btn cc-btn--accent"
                  disabled={requesting === t.id}
                  onClick={() => handleUpgrade(t.id)}
                  style={{ display: "block", width: "100%", textAlign: "center" }}
                >
                  {requesting === t.id ? "处理中..." : t.id === "community" ? "切回免费档" : t.cta_label}
                </button>
              )}
              <div className="cc-dim" style={{ fontSize: 10, marginTop: 6, textAlign: "center" }}>
                权限层级 {t.level}
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="cc-card" style={{ marginTop: 24, padding: 16 }}>
        <div className="cc-section-title">不上 Live Pro 我能做什么？</div>
        <div className="cc-soft" style={{ fontSize: 13 }}>
          Community 和 Learn 已经覆盖完整研究流程：拉数据 → 写因子 → 跑回测 → 看 PBO/DSR/MaxDD →
          诊断台复盘 → 改一个变量 → 重新跑 → 社区分享。Live Pro 只是把这个研究流程的产出，
          通过 SafeKey + testnet + live ladder 接到 Binance 小资金实盘。<strong>
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
