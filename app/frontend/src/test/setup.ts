import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// 每个测试后清理 DOM，避免跨用例污染
afterEach(() => cleanup());
