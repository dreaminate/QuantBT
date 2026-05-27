import { Navigate, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { ComparePage } from "./pages/ComparePage";
import { DataPage } from "./pages/DataPage";
import { RunsPage } from "./pages/RunsPage";
import { RunDetailPage } from "./pages/RunDetailPage";
import { WorkbenchPage } from "./pages/WorkbenchPage";

/** `/runs/:runId` 回测详情页，主区域使用宽屏布局（见 `.jq-main--wide`） */
function useRunDetailWideLayout(): boolean {
  const { pathname } = useLocation();
  return /^\/runs\/[^/]+$/.test(pathname);
}

export default function App() {
  const location = useLocation();
  const runDetailWide = useRunDetailWideLayout();
  const secondaryItems = [
    { to: "/runs", label: "回测列表" },
    { to: "/compare", label: "对比分析" },
    { to: "/data", label: "数据中心" },
  ];
  const showSecondary =
    location.pathname.startsWith("/runs") || location.pathname.startsWith("/compare") || location.pathname.startsWith("/data");

  // 与 quant1 顶栏「回测研究」一致：/runs、/compare、/data 及其子路由视为同一研究区
  const researchActive = (pathname: string) =>
    pathname.startsWith("/runs") || pathname.startsWith("/compare") || pathname.startsWith("/data");

  return (
    <div className="jq-app">
      <header className="jq-topbar">
        <div className="jq-topbar-inner">
          <NavLink to="/runs" className="jq-logo">
            <span className="jq-logo-icon">QB</span>
            <span className="jq-logo-text">qb</span>
          </NavLink>
          <nav className="jq-nav">
            <NavLink to="/runs" className={researchActive(location.pathname) ? "jq-nav-item active" : "jq-nav-item"}>
              回测研究
            </NavLink>
            <NavLink to="/workbench" className={location.pathname.startsWith("/workbench") ? "jq-nav-item active" : "jq-nav-item"}>
              工坊
            </NavLink>
          </nav>
        </div>
      </header>
      {showSecondary ? (
        <nav className="jq-secondary-bar">
          <div className="jq-secondary-inner">
            {secondaryItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={location.pathname === item.to || location.pathname.startsWith(item.to) ? "jq-sub-item active" : "jq-sub-item"}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </nav>
      ) : null}
      <main className={`jq-main${runDetailWide ? " jq-main--wide" : ""}`}>
        <Routes>
          <Route path="/" element={<Navigate to="/runs" replace />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/data" element={<DataPage />} />
          <Route path="/workbench" element={<WorkbenchPage />} />
        </Routes>
      </main>
    </div>
  );
}
