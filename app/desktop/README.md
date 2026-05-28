# QuantBT Desktop (Tauri 2)

桌面端套壳 React 前端 + 内置 Python backend 子进程。

**安全特性**：API key（含 Binance mainnet）**永远不离开用户本机** — 走 OS keyring。
即便 QuantBT 云服务被攻破，桌面用户资金不受影响。

## 一次性环境准备

### 1. 装 Rust toolchain

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source $HOME/.cargo/env
rustc --version    # 期望 ≥ 1.75
```

### 2. 装 Tauri CLI

```bash
cd app/desktop
npm install        # 装 @tauri-apps/cli
```

### 3. 平台特定依赖

**macOS**:
```bash
xcode-select --install   # Xcode CLT
```

**Windows**:
- 装 [Microsoft Visual Studio C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
- 装 [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/)

**Linux**:
```bash
sudo apt install libwebkit2gtk-4.1-dev build-essential curl wget file libxdo-dev libssl-dev libayatana-appindicator3-dev librsvg2-dev
```

## 开发期跑

```bash
cd app/desktop
npm run dev
```

- Tauri 启动会先跑 `cd ../../frontend && npm run dev`（启动 Vite dev server）
- 然后 Tauri webview 加载 http://localhost:5173
- 同时 spawn `python -m uvicorn ... --port 18234` 后端子进程
- backend 健康检查走 IPC: `invoke('backend_health')`

## 打包发布

### macOS

```bash
cd app/desktop
npm run build:mac
# 产物: src-tauri/target/release/bundle/dmg/QuantBT_1.0.0_universal.dmg
```

**签名要求**（避免 Gatekeeper 警告）：
- 准备 Apple Developer ID Application 证书（$99/年 Apple Developer Program）
- 在 `tauri.conf.json` → `bundle.macOS.signingIdentity` 填证书 hash
- 公证: `xcrun notarytool submit QuantBT.dmg --keychain-profile "AC_PASSWORD" --wait`

### Windows

```bash
npm run build:win
# 产物: src-tauri/target/release/bundle/nsis/QuantBT_1.0.0_x64-setup.exe
```

**Code Signing**（避免 SmartScreen 拦截）：
- 买 OV/EV Code Signing 证书（DigiCert 大约 $200-500/年）
- 在 `tauri.conf.json` → `bundle.windows.wix.certificateThumbprint` 填证书 thumbprint

### Linux

```bash
npm run build:linux
# 产物: src-tauri/target/release/bundle/deb/quantbt_1.0.0_amd64.deb
#       src-tauri/target/release/bundle/appimage/quantbt_1.0.0_amd64.AppImage
```

## Backend 打包（PyInstaller 单 binary）

桌面发布前先把 Python backend 打成单 binary，避免用户机器装 Python：

```bash
cd app/backend
pyinstaller deploy/quantbt-backend.spec --clean
# 产物: dist/quantbt-backend (macOS/Linux) 或 dist/quantbt-backend.exe (Windows)

# 把 binary 拷到 Tauri 资源目录
cp dist/quantbt-backend ../desktop/src-tauri/binaries/
```

然后 Tauri build 时通过 `tauri.bundle.resources` 把 binary 打进 .dmg/.exe，
运行时 `main.rs` 设 `QB_BACKEND_BIN` 环境变量指向解压后的 binary 路径。

## 已知限制

1. **首次启动慢**（5-10s）：backend uvicorn 启动 + 加载 secrets.yaml + 初始化所有 service
2. **macOS 不签名首启**：Finder 右键"打开"→"打开"绕过 Gatekeeper
3. **Windows 不签名**：SmartScreen "更多信息"→"仍要运行"
4. **Linux**：AppImage 需要 `chmod +x` 后才能跑

## 故障排查

- backend 子进程未启 → 检查 `~/Library/Logs/com.quantbt.desktop/` (macOS)
- webview 空白 → DevTools 看 console (Cmd+Opt+I)
- 健康检查 `backend_health` 失败 → 重启: `invoke('backend_restart')`
