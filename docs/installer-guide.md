# QuantBT 安装包指南

QuantBT 提供三种安装方式，按你的偏好选：

| 方式 | 适合谁 | 启动 |
|---|---|---|
| **docker compose**（推荐） | 任何想最快起步的人 | `docker compose up -d` |
| **PyInstaller 安装包** | 不想装 Python 环境的桌面用户 | 双击 `quantbt-backend.app` (macOS) / `.exe` (Windows) |
| **本地 Python** | 开发者 / 想改代码 | 见根 README |

---

## 1. docker compose

```bash
git clone <repo> quantbt && cd quantbt
cp deploy/secrets.yaml.example ~/.quantbt/secrets.yaml
# 编辑 ~/.quantbt/secrets.yaml 填字段
docker compose up -d
# 打开 http://127.0.0.1:5173
```

---

## 2. PyInstaller 安装包（macOS / Windows）

### 从 GitHub Release 下载（推荐）

GitHub Actions 在每个 `vX.Y.Z` tag 自动 build macOS + Windows 两份产物到 Release：
1. 去 <https://github.com/你的组织/QuantBT/releases/latest>
2. 下载对应平台 zip：`quantbt-backend-macos-latest.zip` / `quantbt-backend-windows-latest.zip`
3. 解压
4. 双击 `quantbt-backend`（macOS .app）/ `quantbt-backend.exe`（Windows）
5. 访问 http://127.0.0.1:8000/api/health 应回 `{"status": "ok"}`
6. 前端：另开一个 `app/frontend` 跑 `npm run dev`，或单独打前端 Docker

### 本机自己构建

```bash
# 安装 pyinstaller（额外依赖，没列进 requirements）
pip install pyinstaller

# 进仓库根
cd /path/to/QuantBT
pyinstaller --clean --noconfirm deploy/quantbt-backend.spec

# 产物
ls dist/quantbt-backend/
# 启动：
./dist/quantbt-backend/quantbt-backend
# Windows: dist\quantbt-backend\quantbt-backend.exe
```

**注意**：PyInstaller 只跨平台「兼容性」不跨平台「构建」——你在 macOS 上只能打 .app，
打 .exe 必须用 Windows 机器（或 GitHub Actions windows-latest runner）。

### 常见问题

| 症状 | 原因 | 解决 |
|---|---|---|
| 启动报 `ImportError: lightgbm` | lightgbm 二进制没被 collect-all 进 | spec 里已 `collect_all('lightgbm')`；如仍出，加 `--hidden-import=lightgbm` |
| 启动报 `cryptography.hazmat.bindings` | 同上 | 确保 spec 里 collect_all('cryptography') 没被注释 |
| macOS 启动弹「无法验证开发者」 | 没有签名 | `xattr -dr com.apple.quarantine dist/quantbt-backend/quantbt-backend`；正式签名见 Apple Developer 文档 |
| Windows 启动弹「Windows protected your PC」 | 同上 | 点「更多信息」→「仍要运行」；正式签名买 code signing cert |

---

## 3. 本地 Python（开发模式）

```bash
cd app/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cd ../frontend
npm install
cd ../..

npm run dev   # 仓库根 package.json 串起来
```

---

## 4. 三种方式对比

| | docker | PyInstaller | 本地 Python |
|---|---|---|---|
| 启动耗时 | 一键，约 30s 拉镜像 | 双击秒级 | 10s |
| 大小 | 镜像 ~600MB | macOS .app ~400MB / Win .exe 包 ~350MB | 仅源码 ~10MB + 你的 venv |
| 改代码 | 重新 `docker compose build` | 重新打包 | 改完即生效 |
| 跨平台 | linux container | 必须各平台单独 build | 你装啥就跑啥 |
| 后端推荐 | ✓ 生产 | ✓ 桌面用户 | ✓ 开发 |
