import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // 单 bundle(2.5MB) → 按依赖切分,首屏只拉需要的 chunk、重型库可长缓存。
        // 铁律:react/react-dom/scheduler 必须同 chunk(拆开会造成多份 React 实例
        // → invalid hook call);echarts/recharts 是独立叶子库,隔离安全。
        // 用带斜杠的路径片段匹配,避免 "echarts-for-react" 被 /react/ 误吞。
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("echarts") || id.includes("zrender")) return "echarts";
          if (id.includes("recharts") || id.includes("d3-") || id.includes("/d3/") ||
              id.includes("victory")) return "recharts";
          if (id.includes("react-router")) return "router";
          if (id.includes("@tanstack")) return "query";
          if (id.includes("/react/") || id.includes("/react-dom/") ||
              id.includes("/scheduler/")) return "react-vendor";
          return "vendor";
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
