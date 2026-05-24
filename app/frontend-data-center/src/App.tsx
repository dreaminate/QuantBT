import { DataPage } from "./pages/DataPage";

export default function App() {
  return (
    <div className="jq-app">
      <header className="jq-topbar">
        <div className="jq-topbar-inner">
          <a className="jq-logo" href="/">
            <span className="jq-logo-icon">Q1</span>
            <span className="jq-logo-text">1Backtest</span>
          </a>
          <nav className="jq-nav" aria-label="Primary">
            <a className="jq-nav-item active" href="/">
              数据中心
            </a>
          </nav>
        </div>
      </header>
      <nav className="jq-secondary-bar" aria-label="Secondary">
        <div className="jq-secondary-inner">
          <a className="jq-sub-item active" href="/">
            数据拉取与浏览
          </a>
        </div>
      </nav>
      <main className="jq-main">
        <DataPage />
      </main>
    </div>
  );
}
