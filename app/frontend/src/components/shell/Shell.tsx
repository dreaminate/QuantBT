import { ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { clearSession, getStoredUser, logout, type AuthUser } from "../../lib/auth";

/**
 * Claude Code 风 shell：顶部 nav + 左侧 sidebar + 底部 status bar
 * RunDetailPage 走 wide layout 时由 App.tsx 跳过整个 shell（不动它）
 */

export type Theme = "dark" | "light";

interface SidebarItem {
  to: string;
  label: string;
  icon?: string;
}

const SIDEBAR_BY_AREA: Record<string, SidebarItem[]> = {
  research: [
    { to: "/runs", label: "回测列表", icon: "▦" },
    { to: "/strategies", label: "策略索引", icon: "◆" },
    { to: "/compare", label: "对比分析", icon: "⇄" },
    { to: "/data", label: "数据中心", icon: "⊞" },
  ],
  workshop: [
    { to: "/workshop", label: "策略工坊", icon: "✎" },
    { to: "/agent", label: "Agent 工作台", icon: "◉" },
    { to: "/factors", label: "因子市场", icon: "∑" },
    { to: "/trading", label: "Binance 交易台", icon: "$" },
    { to: "/experiments", label: "实验追踪", icon: "⌥" },
  ],
  community: [
    { to: "/community", label: "社区广场", icon: "#" },
    { to: "/square", label: "策略广场", icon: "★" },
  ],
};

export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem("cc-theme") : null;
    return (stored as Theme) || "dark";
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("cc-theme", theme);
    } catch {
      /* noop */
    }
  }, [theme]);

  const location = useLocation();
  const area = areaOf(location.pathname);
  const sidebar = SIDEBAR_BY_AREA[area];

  return (
    <div className="cc-app">
      <TopNav theme={theme} onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")} />
      <div className="cc-shell">
        {sidebar && <Sidebar items={sidebar} area={area} />}
        <main className={`cc-main${wide ? " cc-main--wide" : ""}`}>{children}</main>
      </div>
      <StatusBar />
    </div>
  );
}

function TopNav({ theme, onToggleTheme }: { theme: Theme; onToggleTheme: () => void }) {
  const location = useLocation();
  const area = areaOf(location.pathname);
  return (
    <header className="cc-topbar">
      <NavLink to="/" className="cc-topbar-logo">
        <b>qb</b>
        <span className="cc-logo-tag">// QuantBT</span>
      </NavLink>
      <nav className="cc-topbar-nav">
        <NavLink to="/" className={area === "home" ? "cc-nav-item active" : "cc-nav-item"} end>
          Home
        </NavLink>
        <NavLink
          to="/runs"
          className={area === "research" ? "cc-nav-item active" : "cc-nav-item"}
        >
          Research
        </NavLink>
        <NavLink
          to="/workshop"
          className={area === "workshop" ? "cc-nav-item active" : "cc-nav-item"}
        >
          Workshop
        </NavLink>
        <NavLink
          to="/community"
          className={area === "community" ? "cc-nav-item active" : "cc-nav-item"}
        >
          Community
        </NavLink>
      </nav>
      <div className="cc-topbar-right">
        <UserMenu />
        <button
          type="button"
          className="cc-btn cc-btn--ghost cc-btn--sm"
          onClick={onToggleTheme}
          title="切换深/浅"
        >
          {theme === "dark" ? "☾ dark" : "☀ light"}
        </button>
        <a
          className="cc-btn cc-btn--ghost cc-btn--sm"
          href="https://github.com"
          target="_blank"
          rel="noreferrer"
          title="docs"
        >
          ?
        </a>
      </div>
    </header>
  );
}

function Sidebar({ items, area }: { items: SidebarItem[]; area: string }) {
  return (
    <aside className="cc-sidebar">
      <div className="cc-sidebar-section">{area === "research" ? "回测研究" : "工坊"}</div>
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) => (isActive ? "active" : "")}
          end
        >
          {item.icon && <span className="cc-sidebar-icon">{item.icon}</span>}
          <span>{item.label}</span>
        </NavLink>
      ))}
    </aside>
  );
}

interface StatusInfo {
  network: string;
  mode: string;
  factorsCount: number;
  llmProvider: string | null;
  loadedSecrets: string[];
}

function StatusBar() {
  const [info, setInfo] = useState<StatusInfo | null>(null);
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch("/api/security/network").then((r) => r.json()),
      fetch("/api/factors").then((r) => r.json()),
      fetch("/api/llm/status").then((r) => r.json()),
      fetch("/api/security/secrets").then((r) => r.json()),
    ])
      .then(([net, factors, llm, secrets]) => {
        if (cancelled) return;
        const active = llm.find((p: { configured: boolean; provider: string }) => p.configured);
        setInfo({
          network: net.binance_network,
          mode: net.mode,
          factorsCount: Array.isArray(factors) ? factors.length : 0,
          llmProvider: active?.provider ?? null,
          loadedSecrets: secrets.loaded || [],
        });
      })
      .catch(() => {
        /* status bar best-effort */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!info) {
    return (
      <footer className="cc-statusbar">
        <span className="cc-status-item">
          <span className="cc-status-dot" /> connecting...
        </span>
      </footer>
    );
  }

  return (
    <footer className="cc-statusbar">
      <span className="cc-status-item">
        <span
          className={`cc-status-dot ${
            info.network === "mainnet" ? "cc-status-dot--red" : "cc-status-dot--green"
          }`}
        />
        net: {info.network} · mode: {info.mode}
      </span>
      <span className="cc-status-item">
        <span
          className={`cc-status-dot ${info.llmProvider ? "cc-status-dot--orange" : ""}`}
        />
        LLM: {info.llmProvider || "dev_local (fallback)"}
      </span>
      <span className="cc-status-item">
        <span className="cc-status-dot cc-status-dot--blue" /> factors: {info.factorsCount}
      </span>
      <span className="cc-status-item">
        <span className="cc-status-dot" /> secrets: {info.loadedSecrets.length} loaded
      </span>
      <span className="cc-status-spacer" />
      <span className="cc-status-item">v0.6.2</span>
    </footer>
  );
}

function UserMenu() {
  const [user, setUser] = useState<AuthUser | null>(() => getStoredUser());
  useEffect(() => {
    const h = () => setUser(getStoredUser());
    window.addEventListener("qb-auth-change", h);
    window.addEventListener("storage", h);
    return () => {
      window.removeEventListener("qb-auth-change", h);
      window.removeEventListener("storage", h);
    };
  }, []);
  if (!user) {
    return (
      <NavLink to="/login" className="cc-btn cc-btn--ghost cc-btn--sm">登录</NavLink>
    );
  }
  return (
    <div className="cc-row" style={{ gap: 4 }}>
      <NavLink to={`/u/${user.username}`} className="cc-btn cc-btn--ghost cc-btn--sm" title="profile">
        @{user.username}
      </NavLink>
      <button
        type="button"
        className="cc-btn cc-btn--ghost cc-btn--sm"
        title="退出登录"
        onClick={() => {
          logout().catch(() => clearSession());
        }}
      >
        ↪
      </button>
    </div>
  );
}

function areaOf(pathname: string): string {
  if (pathname === "/" || pathname.startsWith("/home")) return "home";
  if (
    pathname.startsWith("/runs") ||
    pathname.startsWith("/compare") ||
    pathname.startsWith("/data") ||
    pathname.startsWith("/strategies")
  )
    return "research";
  if (
    pathname.startsWith("/workshop") ||
    pathname.startsWith("/agent") ||
    pathname.startsWith("/factors") ||
    pathname.startsWith("/trading") ||
    pathname.startsWith("/experiments")
  )
    return "workshop";
  if (
    pathname.startsWith("/community") ||
    pathname.startsWith("/square") ||
    pathname.startsWith("/u/") ||
    pathname === "/login" ||
    pathname === "/register"
  )
    return "community";
  return "research";
}

export default Shell;
