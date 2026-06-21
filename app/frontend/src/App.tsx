import { Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import { RunDetailPage } from "./pages/RunDetailPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/community/LoginPage";
import { CommunityFeedPage } from "./pages/community/CommunityFeedPage";
import { SharedStrategiesPage } from "./pages/community/SharedStrategiesPage";
import { UserProfilePage } from "./pages/community/UserProfilePage";
import { CopyTradePage } from "./pages/community/CopyTradePage";
import { GlossaryIndexPage } from "./pages/community/GlossaryIndexPage";
import { GlossaryDetailPage } from "./pages/community/GlossaryDetailPage";
import { FunnelDashboardPage } from "./pages/FunnelDashboardPage";
import { PricingPage } from "./pages/PricingPage";
import SettingsSecurityPage from "./pages/SettingsSecurityPage";
import { Shell } from "./components/shell/Shell";
// DC→React 暗色台（DeskShell 全屏，绕 cc Shell）—— epic cfb0fea9
import { StrategyConsolePage } from "./pages/StrategyConsolePage";
import { FactorDeskPage } from "./pages/workshop/factor/FactorDeskPage";
import { ModelDeskPage } from "./pages/models/ModelDeskPage";
import { PaperDeskPage } from "./pages/workshop/PaperDeskPage";
import { AgentWorkbenchPage } from "./pages/workshop/agent-workbench/AgentWorkbenchPage";
import { OverviewDeskPage } from "./pages/overview/OverviewDeskPage";

/**
 * 路由策略（导航收口后 · 单一 Workshop 顶 tab + 6 个全屏台）：
 * - `/runs/:runId` RunDetailPage 是 GOAL §M15 冻结的 jq-* 旧 SPA：完全跳过 cc-* shell。唯一冻结例外。
 * - desk 台（总览/策略/因子/Model/模拟/Agent）是 DeskShell 全屏、自带顶栏 + 台切换器，跳过 cc Shell。
 * - 其它路由（Home / 社区 / 设置 / 定价）统一用 cc Shell。
 * - 旧的分散页（回测列表/对比/数据/策略索引/工坊/IDE/教练/模板/交易/实验/训练/旧Agent）已搬进对应台，
 *   其旧路由统一【重定向】到新台落点（防外部直链 404）；旧 Agent 对话页 /agent 已退役并入 Agent台。
 */

const DESK_PREFIXES = ["/overview", "/strategy", "/factors", "/models", "/paper", "/agent-workbench"];

/** /compare 旧链重定向到总览台·对比分析子标签，保留 run_ids 等 query（防丢上下文）。 */
function CompareRedirect() {
  const [params] = useSearchParams();
  const q = params.toString();
  return <Navigate to={`/overview?view=compare${q ? `&${q}` : ""}`} replace />;
}

export default function App() {
  const location = useLocation();
  const isFrozenRunDetail = /^\/runs\/[^/]+$/.test(location.pathname);

  if (isFrozenRunDetail) {
    return (
      <div className="jq-app">
        <main className="jq-main jq-main--wide">
          <Routes>
            <Route path="/runs/:runId" element={<RunDetailPage />} />
          </Routes>
        </main>
      </div>
    );
  }

  const isDesk = DESK_PREFIXES.some(
    (p) => location.pathname === p || location.pathname.startsWith(p + "/"),
  );
  if (isDesk) {
    return (
      <Routes>
        <Route path="/overview" element={<OverviewDeskPage />} />
        <Route path="/strategy" element={<StrategyConsolePage />} />
        <Route path="/factors" element={<FactorDeskPage />} />
        <Route path="/models" element={<ModelDeskPage />} />
        <Route path="/paper" element={<PaperDeskPage />} />
        <Route path="/agent-workbench" element={<AgentWorkbenchPage />} />
      </Routes>
    );
  }

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/home" element={<Navigate to="/" replace />} />

        {/* 旧分散页 → 已搬进对应台，旧路由重定向到新落点 */}
        <Route path="/runs" element={<Navigate to="/overview" replace />} />
        <Route path="/compare" element={<CompareRedirect />} />
        <Route path="/data" element={<Navigate to="/overview?view=data" replace />} />
        <Route path="/strategies" element={<Navigate to="/overview?view=runs&mode=cards" replace />} />
        <Route path="/workshop" element={<Navigate to="/strategy" replace />} />
        <Route path="/ide" element={<Navigate to="/strategy" replace />} />
        <Route path="/templates" element={<Navigate to="/strategy" replace />} />
        <Route path="/chat" element={<Navigate to="/agent-workbench" replace />} />
        <Route path="/agent" element={<Navigate to="/agent-workbench" replace />} />
        <Route path="/trading" element={<Navigate to="/paper" replace />} />
        <Route path="/experiments" element={<Navigate to="/models" replace />} />
        <Route path="/training" element={<Navigate to="/models" replace />} />

        {/* 社区 + 私域带单 */}
        <Route path="/login" element={<LoginPage mode="login" />} />
        <Route path="/register" element={<LoginPage mode="register" />} />
        <Route path="/community" element={<CommunityFeedPage />} />
        <Route path="/square" element={<SharedStrategiesPage />} />
        <Route path="/copy-trade" element={<CopyTradePage />} />
        <Route path="/glossary" element={<GlossaryIndexPage />} />
        <Route path="/glossary/:slug" element={<GlossaryDetailPage />} />
        <Route path="/metrics/funnel" element={<FunnelDashboardPage />} />
        <Route path="/pricing" element={<PricingPage />} />
        <Route path="/settings/security" element={<SettingsSecurityPage />} />
        <Route path="/u/:username" element={<UserProfilePage />} />
      </Routes>
    </Shell>
  );
}
