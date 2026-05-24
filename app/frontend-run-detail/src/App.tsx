import { Navigate, Route, Routes } from "react-router-dom";
import { RunDetailPage } from "./pages/RunDetailPage";

export default function App() {
  return (
    <div className="jq-app">
      <header className="jq-topbar">
        <div className="jq-topbar-inner">
          <a className="jq-logo" href="/runs/demo">
            <span className="jq-logo-icon">Q1</span>
            <span className="jq-logo-text">1Backtest</span>
          </a>
          <nav className="jq-nav" aria-label="Primary">
            <a className="jq-nav-item active" href="/runs/demo">
              回测详情
            </a>
          </nav>
        </div>
      </header>
      <nav className="jq-secondary-bar" aria-label="Secondary">
        <div className="jq-secondary-inner">
          <a className="jq-sub-item active" href="/runs/demo">
            结果查看
          </a>
        </div>
      </nav>
      <main className="jq-main jq-main--wide">
        <Routes>
          <Route path="/" element={<Navigate to="/runs/demo" replace />} />
          <Route path="/runs/:runId" element={<RunDetailPage />} />
        </Routes>
      </main>
    </div>
  );
}
