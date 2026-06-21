import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// G0 前端测试设施（e2de3d32）—— jsdom + RTL，复用 vite 的 plugin-react
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
