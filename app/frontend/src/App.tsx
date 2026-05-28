import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ComparePage } from "./pages/ComparePage";
import { DataPage } from "./pages/DataPage";
import { RunsPage } from "./pages/RunsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { WorkbenchPage } from "./pages/WorkbenchPage";
import { StrategyWorkshopPage } from "./pages/workshop/StrategyWorkshopPage";
import { AgentChatPage } from "./pages/workshop/AgentChatPage";
import { FactorMarketPage } from "./pages/workshop/FactorMarketPage";
import { BinanceTradingPage } from "./pages/workshop/BinanceTradingPage";
import { ExperimentTrackingPage } from "./pages/workshop/ExperimentTrackingPage";

/** `/runs/:runId` 回测详情页，主区域使用宽屏布局（见 `.jq-main--wide`） */
function useRunDetailWideLayout(): boolean {
  const { pathname } = useLocation();
  return /^\/runs\/[^/]+$/.test(pathname);
}

const RESEARCH_SECONDARY = [
  { to: "/runs", label: "回测列表" },
  { to: "/compare", label: "对比分析" },
  { to: "/data", label: "数据中心" },
];

const WORKSHOP_SECONDARY = [
  { to: "/workshop", label: "策略工坊" },
  { to: "/agent", label: "Agent 工作台" },
  { to: "/factors", label: "因子市场" },
  { to: "/trading", label: "Binance 交易台" },
  { to: "/experiments", label: "实验追踪" },
];

export default function App() {
  const location = useLocation();
  const runDetailWide = useRunDetailWideLayout();

  const isResearchArea =
    location.pathname.startsWith("/runs") ||
    location.pathname.startsWith("/compare") ||
    location.pathname.startsWith("/data");
  const isWorkshopArea =
    ["/workshop", "/agent", "/factors", "/trading", "/experiments", "/workbench"].some(
      (p) => location.pathname.startsWith(p),
    );

  return (
    <div className="jq-app">
      <header className="jq-topbar">
        <div className="jq-topbar-inner">
          <NavLink to="/runs" className="jq-logo">
            <span className="jq-logo-icon">QB</span>
            <span className="jq-logo-text">qb</span>
          </NavLink>
          <nav className="jq-nav">
            <NavLink to="/runs" className={isResearchArea ? "jq-nav-item active" : "jq-nav-item"}>
              回测研究
            </NavLink>
            <NavLink to="/workshop" className={isWorkshopArea ? "jq-nav-item active" : "jq-nav-item"}>
              工坊
            </NavLink>
          </nav>
        </div>
      </header>
      {(isResearchArea || isWorkshopArea) && (
        <nav className="jq-secondary-bar">
          <div className="jq-secondary-inner">
            {(isWorkshopArea ? WORKSHOP_SECONDARY : RESEARCH_SECONDARY).map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={
                  location.pathname === item.to || location.pathname.startsWith(item.to)
                    ? "jq-sub-item active"
                    : "jq-sub-item"
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>
      )}
      <main className={`jq-main${runDetailWide ? " jq-main--wide" : ""}`}>
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/data" element={<DataPage />} />
          {/* 5 个独立 SPA 页 */}
          <Route path="/workshop" element={<StrategyWorkshopPage />} />
          <Route path="/agent" element={<AgentChatPage />} />
          <Route path="/factors" element={<FactorMarketPage />} />
          <Route path="/trading" element={<BinanceTradingPage />} />
          <Route path="/experiments" element={<ExperimentTrackingPage />} />
          {/* 兼容旧入口 */}
          <Route path="/workbench" element={<WorkbenchPage />} />
        </Routes>
      </main>
    </div>
  );
}
