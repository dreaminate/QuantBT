import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import "./styles.css";
import "./theme-cc.css";

// 桌面挂载入口门（T-042）：Tauri 窗口加载 index.html?view=agent-workbench，
// 在 React 挂载前把初始路由改写成 /agent-workbench，再交给 App.tsx 既有路由。
// Web 无 ?view= → 无操作；一套组件两处挂载、不重写、不绕治理门（同组件同 router 同 gate）。
const VIEW_ROUTES: Record<string, string> = {
  "agent-workbench": "/agent-workbench",
};
const desktopView = new URLSearchParams(window.location.search).get("view");
if (desktopView && VIEW_ROUTES[desktopView]) {
  window.history.replaceState(null, "", VIEW_ROUTES[desktopView]);
}

const queryClient = new QueryClient();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
