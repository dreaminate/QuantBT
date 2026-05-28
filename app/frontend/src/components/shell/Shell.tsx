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
    { to: "/ide", label: "IDE · 代码工坊", icon: "{}" },
    { to: "/chat", label: "Mode 2 · 量化教练", icon: "💬" },
    { to: "/agent", label: "Agent 工作台", icon: "◉" },
    { to: "/factors", label: "因子市场", icon: "∑" },
    { to: "/templates", label: "策略模板", icon: "≣" },
    { to: "/trading", label: "Binance 交易台", icon: "$" },
    { to: "/experiments", label: "实验追踪", icon: "⌥" },
  ],
  community: [
    { to: "/community", label: "社区广场", icon: "#" },
    { to: "/square", label: "策略广场", icon: "★" },
    { to: "/copy-trade", label: "带单大厅", icon: "⇆" },
    { to: "/glossary", label: "量化词典", icon: "📖" },
  ],
};

export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const [theme, setTheme] = useState<Theme>(() => {
    const stored = typeof window !== "undefined" ? localStorage.getItem("cc-theme") : null;
    return (stored as Theme) || "dark";
  });
  const [drawerOpen, setDrawerOpen] = useState(false);
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

  // 路由切换自动关 drawer
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  return (
    <div className="cc-app">
      <TopNav
        theme={theme}
        onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
        onHamburger={() => setDrawerOpen((v) => !v)}
      />
      <div className="cc-shell">
        {sidebar && <Sidebar items={sidebar} area={area} />}
        <main className={`cc-main${wide ? " cc-main--wide" : ""}`}>{children}</main>
      </div>
      <StatusBar />

      {/* v0.9.9 移动端 drawer (仅 < 768px 显示) */}
      {drawerOpen && <div className="cc-drawer-backdrop" onClick={() => setDrawerOpen(false)} />}
      <MobileDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)} currentArea={area} />
    </div>
  );
}

function MobileDrawer({ open, onClose, currentArea }: { open: boolean; onClose: () => void; currentArea: string }) {
  const allItems: { area: string; items: SidebarItem[] }[] = [
    { area: "research", items: SIDEBAR_BY_AREA.research },
    { area: "workshop", items: SIDEBAR_BY_AREA.workshop },
    { area: "community", items: SIDEBAR_BY_AREA.community },
  ];
  return (
    <aside className={`cc-sidebar-drawer${open ? " open" : ""}`} aria-hidden={!open}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <span style={{ fontWeight: 600, fontSize: 16 }}>qb · QuantBT</span>
        <button type="button" onClick={onClose} className="cc-btn cc-btn--ghost cc-btn--sm" aria-label="关闭菜单">×</button>
      </div>
      {allItems.map((group) => (
        <div key={group.area} style={{ marginBottom: 16 }}>
          <div className="cc-sidebar-section" style={{ fontSize: 11, opacity: 0.6, marginBottom: 4 }}>
            {group.area === "research" ? "回测研究" : group.area === "workshop" ? "工坊" : "社区"}
          </div>
          {group.items.map((item) => (
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
        </div>
      ))}
      <div style={{ marginTop: 24, paddingTop: 12, borderTop: "1px solid rgba(255,255,255,0.08)", opacity: 0.7, fontSize: 11 }}>
        当前: {currentArea}
      </div>
    </aside>
  );
}

function TopNav({ theme, onToggleTheme, onHamburger }: { theme: Theme; onToggleTheme: () => void; onHamburger: () => void }) {
  const location = useLocation();
  const area = areaOf(location.pathname);
  return (
    <header className="cc-topbar">
      <button type="button" className="cc-hamburger" onClick={onHamburger} aria-label="菜单">≡</button>
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

interface ProviderStatus {
  provider: string;
  configured: boolean;
  base_url?: string;
  model?: string;
}

interface StatusInfo {
  network: string;
  mode: string;
  factorsCount: number;
  providers: ProviderStatus[];
  activeProvider: string;       // "auto" | provider name
  loadedSecrets: string[];
}

function StatusBar() {
  const [info, setInfo] = useState<StatusInfo | null>(null);
  const [switching, setSwitching] = useState(false);

  const reload = () => {
    Promise.all([
      fetch("/api/security/network").then((r) => r.json()),
      fetch("/api/factors").then((r) => r.json()),
      fetch("/api/llm/status").then((r) => r.json()),
      fetch("/api/security/secrets").then((r) => r.json()),
    ])
      .then(([net, factors, llm, secrets]) => {
        // 兼容旧 schema (list) 和新 schema ({providers, active_provider})
        const providers: ProviderStatus[] = Array.isArray(llm)
          ? llm
          : (llm.providers || []);
        const activeProvider: string = (!Array.isArray(llm) && llm.active_provider) || "auto";
        setInfo({
          network: net.binance_network,
          mode: net.mode,
          factorsCount: Array.isArray(factors) ? factors.length : 0,
          providers,
          activeProvider,
          loadedSecrets: secrets.loaded || [],
        });
      })
      .catch(() => { /* best-effort */ });
  };

  useEffect(() => { reload(); }, []);

  const setActive = async (provider: string) => {
    setSwitching(true);
    try {
      await fetch("/api/llm/active", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ provider }),
      });
      reload();
    } finally {
      setSwitching(false);
    }
  };

  if (!info) {
    return (
      <footer className="cc-statusbar">
        <span className="cc-status-item">
          <span className="cc-status-dot" /> connecting...
        </span>
      </footer>
    );
  }

  const configuredProviders = info.providers.filter((p) => p.configured);
  const effectiveLabel = info.activeProvider === "auto"
    ? (configuredProviders[0]?.provider ?? "dev_local")
    : info.activeProvider;

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
        <span className={`cc-status-dot ${effectiveLabel !== "dev_local" ? "cc-status-dot--orange" : ""}`} />
        LLM:&nbsp;
        <select
          value={info.activeProvider}
          onChange={(e) => setActive(e.target.value)}
          disabled={switching}
          title="切换当前 active LLM provider（不持久化，重启回 auto）"
          style={{
            background: "transparent",
            color: "inherit",
            border: "1px solid var(--cc-border, rgba(255,255,255,0.2))",
            borderRadius: 3,
            padding: "0 4px",
            fontFamily: "inherit",
            fontSize: 11,
            cursor: "pointer",
          }}
        >
          <option value="auto">auto ({configuredProviders[0]?.provider ?? "dev_local"})</option>
          {info.providers.map((p) => (
            <option key={p.provider} value={p.provider} disabled={!p.configured}>
              {p.provider}{p.configured ? "" : " (未配置)"}
            </option>
          ))}
        </select>
      </span>
      <span className="cc-status-item">
        <span className="cc-status-dot cc-status-dot--blue" /> factors: {info.factorsCount}
      </span>
      <span className="cc-status-item">
        <span className="cc-status-dot" /> secrets: {info.loadedSecrets.length} loaded
      </span>
      <span className="cc-status-spacer" />
      <span className="cc-status-item">v0.9.9</span>
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
    pathname.startsWith("/templates") ||
    pathname.startsWith("/trading") ||
    pathname.startsWith("/experiments") ||
    pathname.startsWith("/ide") ||
    pathname.startsWith("/chat")
  )
    return "workshop";
  if (
    pathname.startsWith("/community") ||
    pathname.startsWith("/square") ||
    pathname.startsWith("/copy-trade") ||
    pathname.startsWith("/glossary") ||
    pathname.startsWith("/u/") ||
    pathname === "/login" ||
    pathname === "/register"
  )
    return "community";
  return "research";
}

export default Shell;
