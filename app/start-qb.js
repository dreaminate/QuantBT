#!/usr/bin/env node
// 跨平台一键启动分发器：npm run dev / npm start 都走这里。
// - Windows  → start-qb.ps1（PowerShell，保留原行为）
// - macOS / Linux → start.sh（POSIX bash）
// 子进程 stdio 直通当前终端，Ctrl+C 透传给子进程。
const { spawn } = require("node:child_process");
const path = require("node:path");

const here = __dirname;
const isWindows = process.platform === "win32";

let cmd;
let args;
if (isWindows) {
  cmd = "powershell";
  args = ["-ExecutionPolicy", "Bypass", "-File", path.join(here, "start-qb.ps1")];
} else {
  cmd = "bash";
  args = [path.join(here, "start.sh")];
}

const child = spawn(cmd, args, { stdio: "inherit" });

child.on("error", (err) => {
  console.error(`无法启动 ${cmd}: ${err.message}`);
  if (!isWindows) {
    console.error("请确认已安装 bash；或手动运行: bash app/start.sh");
  }
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.exit(1);
  }
  process.exit(code == null ? 0 : code);
});
