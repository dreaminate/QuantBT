import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ComparePage } from "./pages/ComparePage";
import { DataPage } from "./pages/DataPage";
import { RunsPage } from "./pages/RunsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { StrategyWorkshopPage } from "./pages/workshop/StrategyWorkshopPage";
import { AgentChatPage } from "./pages/workshop/AgentChatPage";
import { FactorMarketPage } from "./pages/workshop/FactorMarketPage";
import { BinanceTradingPage } from "./pages/workshop/BinanceTradingPage";
import { ExperimentTrackingPage } from "./pages/workshop/ExperimentTrackingPage";
import { IDEPage } from "./pages/workshop/IDEPage";
import { Mode2ChatPage } from "./pages/workshop/Mode2ChatPage";
import { HomePage } from "./pages/HomePage";
import { StrategyIndexPage } from "./pages/StrategyIndexPage";
import { LoginPage } from "./pages/community/LoginPage";
import { CommunityFeedPage } from "./pages/community/CommunityFeedPage";
import { SharedStrategiesPage } from "./pages/community/SharedStrategiesPage";
import { UserProfilePage } from "./pages/community/UserProfilePage";
import { CopyTradePage } from "./pages/community/CopyTradePage";
import { GlossaryIndexPage } from "./pages/community/GlossaryIndexPage";
import { GlossaryDetailPage } from "./pages/community/GlossaryDetailPage";
import { FunnelDashboardPage } from "./pages/FunnelDashboardPage";
import { PricingPage } from "./pages/PricingPage";
import { StrategyTemplatesPage } from "./pages/StrategyTemplatesPage";
import { Shell } from "./components/shell/Shell";

/**
 * 路由策略：
 * - `/runs/:runId` RunDetailPage 是 GOAL §M15 冻结的 jq-* 旧 SPA：完全跳过 cc-* shell，
 *   保留它自身的 wide 布局；这是唯一例外。
 * - 其它路由统一用 Shell（Claude Code 风深色 + Codex 辅 + quantpedia 风组织）。
 */

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

  return (
    <Shell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/home" element={<Navigate to="/" replace />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/data" element={<DataPage />} />
        <Route path="/strategies" element={<StrategyIndexPage />} />
        {/* workshop 5 页 */}
        <Route path="/workshop" element={<StrategyWorkshopPage />} />
        <Route path="/agent" element={<AgentChatPage />} />
        <Route path="/factors" element={<FactorMarketPage />} />
        <Route path="/trading" element={<BinanceTradingPage />} />
        <Route path="/experiments" element={<ExperimentTrackingPage />} />
        <Route path="/ide" element={<IDEPage />} />
        <Route path="/chat" element={<Mode2ChatPage />} />
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
        <Route path="/templates" element={<StrategyTemplatesPage />} />
        <Route path="/u/:username" element={<UserProfilePage />} />
      </Routes>
    </Shell>
  );
}
