# QuantBT 阿里云轻量香港部署（v1.0 生产）

## 0. 准备清单

- [ ] 阿里云账号 + 实名 + ¥100+ 余额
- [ ] 域名（GoDaddy / Namecheap，避开 `.cn`；推荐 `.com / .io / .ai`）
- [ ] 香港 SMS 接收手机号（阿里云国际站登录可能要）

## 1. 买 VPS

### 推荐配置
- **产品**：阿里云**轻量应用服务器**（不是 ECS，便宜很多）
- **地域**：**香港**（接 Binance 无障碍，国内访问延迟 ~30ms，免备案）
- **规格**：2 核 2GB / 4Mbps 带宽 / 60GB SSD → ¥24/月（年付折后 ¥288/年）
- **系统镜像**：Ubuntu 22.04 LTS
- **流量包**：1TB/月（够 ~10k 月活够呛，初期足够）

### 创建后立刻做
1. 重置 root 密码（管理控制台 → 安全 → 重置密码）
2. 防火墙开放 **22 (SSH) / 80 (HTTP) / 443 (HTTPS)** 仅这三个
3. 用 ssh-copy-id 上传你的 public key，关 password auth

```bash
# 本地
ssh-keygen -t ed25519 -C "quantbt-vps"
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@<VPS_IP>

# 登录后关密码 auth
ssh root@<VPS_IP>
sudo nano /etc/ssh/sshd_config   # PasswordAuthentication no
sudo systemctl restart sshd
```

## 2. 域名 DNS 解析

GoDaddy / Namecheap 控制台:
- A 记录：`quantbt.example.com` → `<VPS_IP>`
- A 记录（可选 www）：`www.quantbt.example.com` → `<VPS_IP>`
- TTL: 300s

国内访问会被 Cloudflare 拖慢，推荐**不用** CF 代理，DNS 走域名注册商默认即可。

验证：
```bash
dig +short quantbt.example.com    # 应返回 VPS_IP
```

## 3. 服务器初始化

```bash
ssh root@<VPS_IP>

# 装 Docker + compose plugin
curl -fsSL https://get.docker.com | sh
apt install -y docker-compose-plugin git curl

# 克隆代码
mkdir -p /opt && cd /opt
git clone https://github.com/<你的 username>/QuantBT.git quantbt
cd quantbt
git checkout fullstack  # 或主分支

# 创建数据目录
mkdir -p data/secrets data/artifacts/experiments
chmod 700 data/secrets

# secrets.yaml
nano data/secrets/secrets.yaml
# 贴入完整 secrets schema (参 deploy/secrets.yaml.example)
chmod 600 data/secrets/secrets.yaml
```

## 4. 配 .env

```bash
cp deploy/cloud/.env.template .env
nano .env
```

必填项（参 .env.template 内说明）:
- `QUANTBT_DOMAIN=quantbt.example.com`
- `CADDY_EMAIL=admin@example.com`
- `QUANTBT_MASTER_KEY` （**生成**: `python3 -c "import secrets; print(secrets.token_urlsafe(64))"`）
- `POSTGRES_PASSWORD` （同上生成）
- `LLM_CUSTOM_*` 三件套

权限收紧:
```bash
chmod 600 .env
```

## 5. 启动

```bash
# 先构建 frontend dist (Caddy serve)
cd /opt/quantbt/app/frontend
docker run --rm -v "$PWD:/app" -w /app node:20-alpine sh -c "npm ci && npm run build"
cd /opt/quantbt

# 启动 stack
docker compose -f deploy/cloud/docker-compose.prod.yml up -d

# 看 Caddy 自动签 HTTPS（首次约 30s）
docker compose -f deploy/cloud/docker-compose.prod.yml logs -f caddy
# 看到 "certificate obtained successfully" 即 OK
```

访问 `https://quantbt.example.com` → 应该看到 QuantBT 首页 + 绿色锁。

## 6. 验证

```bash
curl -s https://quantbt.example.com/api/health
# {"status":"ok"}

# 真 LLM smoke
TOKEN=$(curl -s -X POST https://quantbt.example.com/api/auth/register \
  -H "content-type: application/json" \
  -d '{"username":"smoke_prod","password":"abc12345"}' | jq -r .token)

curl -s -X POST https://quantbt.example.com/api/llm/test \
  -H "content-type: application/json" \
  -H "authorization: Bearer $TOKEN" \
  -d '{"provider":"custom","message":"hi"}'
```

## 7. 备份策略

### 自动每日备份到本地

```bash
# /etc/cron.daily/quantbt-backup.sh
#!/bin/bash
DATE=$(date +%Y%m%d_%H%M%S)
mkdir -p /var/backups/quantbt
tar czf /var/backups/quantbt/data_${DATE}.tar.gz -C /opt/quantbt data
docker exec quantbt-postgres-1 pg_dump -U quantbt quantbt | gzip > /var/backups/quantbt/db_${DATE}.sql.gz

# 保留 30 天
find /var/backups/quantbt -type f -mtime +30 -delete
```

```bash
chmod +x /etc/cron.daily/quantbt-backup.sh
```

### 异地备份（推荐）

```bash
# 用 rclone 到 Backblaze B2 / AWS S3
rclone copy /var/backups/quantbt b2:quantbt-backups --max-age 7d
```

## 8. 监控

### 简易（自带）

```bash
# logs
docker compose -f deploy/cloud/docker-compose.prod.yml logs -f --tail 100

# Caddy 访问日志
tail -f /opt/quantbt/data/caddy/access.log | jq
```

### 进阶（v1.0.x）

- **Sentry**：错误上报已接入，填 `.env` 的 `SENTRY_DSN` 即用
- **UptimeRobot**：免费监控 https://quantbt.example.com 健康（5min 间隔）
- **PostHog self-host**：埋点 funnel 数据（v0.8.4 已埋 6 事件）

## 9. 升级流程

```bash
ssh root@<VPS_IP>
cd /opt/quantbt
git pull
# 重新 build frontend dist
cd app/frontend && docker run --rm -v "$PWD:/app" -w /app node:20-alpine sh -c "npm ci && npm run build"
cd /opt/quantbt
docker compose -f deploy/cloud/docker-compose.prod.yml up -d --build backend
docker compose -f deploy/cloud/docker-compose.prod.yml restart caddy
```

或者用 watchtower 自动 pull（已在 docker-compose 配置）。

## 10. 常见问题

- **Caddy 证书签发失败**：检查 DNS 是否正确解析；80 端口对外
- **backend 起不来**：`docker compose logs backend`，多半是 secrets.yaml 路径或权限问题
- **postgres 启动慢**：首次 init schema ~20s，等一下
- **CORS 错误**：`.env` 的 `QUANTBT_DOMAIN` 必须和访问域名完全一致
- **Binance API 调用 403**：阿里云轻量香港默认放行国际网络，但要确认 outbound 不限

## 11. 安全 checklist (上线前必过)

- [ ] root 关 password auth
- [ ] 防火墙只开 22/80/443
- [ ] fail2ban 安装：`apt install fail2ban`
- [ ] secrets.yaml + .env chmod 600
- [ ] QUANTBT_MASTER_KEY 已 ≥ 64 字符随机
- [ ] POSTGRES_PASSWORD 已 ≥ 32 字符随机
- [ ] HTTPS 已签发（绿色锁）
- [ ] HSTS preload 头已发出
- [ ] Caddy 日志已落盘
- [ ] 自动备份 cron 已开

完成后跑 ssllabs.com 测 SSL 评级，应 A+。
